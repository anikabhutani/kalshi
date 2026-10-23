"""M6: REST vs WebSocket recorder for one market.

For N minutes (1-30) the job keeps one authenticated WebSocket subscribed to market-data
channels for the chosen market and, in parallel, polls REST at a fixed interval through the
global rate limiter:

- WebSocket (specs/asyncapi.yaml): ``subscribe`` to ``ticker``/``trade`` (optionally
  ``orderbook_delta``) with ``market_ticker``. Every message is kept with its local receive
  time; the raw text is appended to ``data/raw/ws-<job id>.jsonl``.
- REST (specs/openapi.yaml): ``GET /markets/{ticker}`` each cycle, plus optionally
  ``GET /markets/trades?ticker=...&min_ts=...`` with an overlap so no trade falls between polls.

Metrics are defined in ``app.analysis.ws_compare``. The WebSocket URL is the one
specs/auth_notes.md pairs with the configured REST host. The connection is dropped at the end;
no command other than ``subscribe`` is ever sent (``app.ws_client``).
"""

from __future__ import annotations

import asyncio
import json
import math
import statistics
import time
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from websockets.exceptions import ConnectionClosed

from app.analysis.limits import describe, parse_rate_doc
from app.analysis.spec_compare import comparison_rows, spec_summary
from app.analysis.timestamps import to_epoch
from app.analysis.ws_compare import (
    Observation,
    TradeSeen,
    change_times,
    latency_summary,
    match_trades,
    message_counts,
    parse_ws_message,
    rest_market_state,
    rest_miss_analysis,
    sequence_gaps,
    ws_ticker_state,
)
from app.errors import JobCancelled, RateLimited, ReconError
from app.jobs import JobContext
from app.services import Services, get_services
from app.ws_client import (
    RECORDABLE_CHANNELS,
    Connector,
    MarketDataSocket,
    default_connector,
    ws_url_for,
    ws_url_table,
)

router = APIRouter(prefix="/api/m6", tags=["M6 REST vs WebSocket"])

MODULE = "M6"
RUN_KIND = "recorder"
MAX_HANDSHAKES = 6
RETRY_HEADROOM = 5
TRADE_OVERLAP_S = 5
MAX_STORED_EVENTS = 20_000
MAX_MEMORY_EVENTS = 200_000
MAX_STORED_INTERVALS = 5_000
RECEIVE_SLICE_S = 1.0
PROGRESS_EVERY_S = 2.0
LOG_EVERY_S = 30.0
MARKET_PATH = "/markets/{ticker}"
TRADES_PATH = "/markets/trades"
FIELD_PAIRING = [
    {"state": "yes bid", "rest": "market.yes_bid_dollars", "websocket": "ticker msg.yes_bid_dollars"},
    {"state": "yes ask", "rest": "market.yes_ask_dollars", "websocket": "ticker msg.yes_ask_dollars"},
    {"state": "last trade price", "rest": "market.last_price_dollars", "websocket": "ticker msg.price_dollars"},
]

connector: Connector = default_connector
seconds_per_minute = 60.0
backoff_base_s = 1.0

Channel = Literal["ticker", "trade", "orderbook_delta"]


class RecorderParams(BaseModel):
    """Recorder configuration from the control panel."""

    market_ticker: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    duration_min: int = Field(default=5, ge=1, le=30)
    poll_interval_s: float = Field(default=5.0, ge=0.5, le=60.0)
    channels: list[Channel] = Field(default_factory=lambda: ["ticker", "trade"], min_length=1, max_length=3)
    poll_trades: bool = True

    @field_validator("channels")
    @classmethod
    def _unique(cls, value: list[Channel]) -> list[Channel]:
        return list(dict.fromkeys(value))


def _auth_notes(services: Services) -> str:
    return (services.config.specs_dir / "auth_notes.md").read_text(encoding="utf-8")


def _ws_url(services: Services) -> str | None:
    return ws_url_for(services.settings.get().base_url, ws_url_table(_auth_notes(services)))


def estimate_requests(params: RecorderParams) -> dict[str, int]:
    """Upper bound: REST polls plus every allowed handshake and subscribe."""
    cycles = math.ceil(params.duration_min * 60 / params.poll_interval_s)
    per_cycle = 2 if params.poll_trades else 1
    rest = cycles * per_cycle
    ws = 2 * MAX_HANDSHAKES
    return {
        "rest_cycles": cycles,
        "rest_requests": rest,
        "ws_requests_max": ws,
        "total": rest + ws,
        "cap": rest + ws + RETRY_HEADROOM,
    }


def _check(params: RecorderParams, services: Services) -> str:
    if not services.config.credentials_configured:
        raise HTTPException(
            status_code=422,
            detail="The WebSocket requires an authenticated connection (specs/asyncapi.yaml) and no API key is configured in .env.",
        )
    url = _ws_url(services)
    if url is None:
        raise HTTPException(
            status_code=422,
            detail=f"specs/auth_notes.md pairs no WebSocket URL with the configured base URL {services.settings.get().base_url}.",
        )
    missing = [c for c in params.channels if c not in services.asyncspec.subscribe_channels()]
    if missing:
        raise HTTPException(status_code=422, detail=f"Not in the spec's subscribe channels: {', '.join(missing)}.")
    rps = services.settings.get().rate_limit_rps
    needed = (2 if params.poll_trades else 1) / params.poll_interval_s
    if needed > rps:
        raise HTTPException(
            status_code=422,
            detail=(
                f"REST polling would need {needed:.2f} req/s, above the global rate limit of {rps} req/s in "
                "Settings. Increase the poll interval or turn off trade polling."
            ),
        )
    return url


def spec_comparison(services: Services) -> list[dict[str, str]]:
    """REST vs WebSocket rows filled only from the spec files."""
    rate_text = (services.config.specs_dir / "rate_limits.md").read_text(encoding="utf-8")
    return comparison_rows(
        services.spec,
        services.asyncspec,
        _auth_notes(services),
        parse_rate_doc(rate_text)["sections"],
        services.settings.get().base_url,
        _ws_url(services),
    )


@router.get("/spec")
def spec_view(services: Services = Depends(get_services)) -> dict[str, Any]:
    """Spec-only comparison table and recorder settings (no requests are sent)."""
    current = services.settings.get()
    return {
        "ws_url": _ws_url(services),
        "rows": spec_comparison(services),
        **spec_summary(services.asyncspec),
        "recordable_channels": [c for c in RECORDABLE_CHANNELS if c in services.asyncspec.subscribe_channels()],
        "field_pairing": FIELD_PAIRING,
        "credentials_configured": services.config.credentials_configured,
        "rate_limit_rps": current.rate_limit_rps,
    }


@router.post("/plan")
def plan(params: RecorderParams, services: Services = Depends(get_services)) -> dict[str, Any]:
    """Request estimate for the safety dialog (validates, sends nothing)."""
    _check(params, services)
    return {"estimate": estimate_requests(params)}


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    if seconds <= 0:
        return
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


def _now_ms() -> float:
    return time.time() * 1000.0


@router.post("/run")
async def run(params: RecorderParams, services: Services = Depends(get_services)) -> dict[str, str]:
    """Job: record the WebSocket feed and REST polls side by side, then compute metrics."""
    url = _check(params, services)
    estimate = estimate_requests(params)
    client = services.client
    spec_channels = services.asyncspec.subscribe_channels()
    trades_endpoint = services.spec.find("GET", TRADES_PATH)
    limit_param = trades_endpoint.param("limit") if trades_endpoint else None
    trade_page_limit = int(limit_param.maximum) if limit_param and limit_param.maximum else None
    raw_dir = services.config.raw_dir
    duration_s = params.duration_min * seconds_per_minute
    progress_total = math.ceil(duration_s)

    async def runner(ctx: JobContext) -> dict[str, Any]:
        stop = asyncio.Event()
        start_ms = _now_ms()
        started_at = datetime.now(UTC).isoformat()
        deadline = time.monotonic() + duration_s
        events: list[dict[str, Any]] = []
        counters = {"ws_messages": 0}
        polls: list[dict[str, Any]] = []
        trade_polls: list[dict[str, Any]] = []
        ws_trades: dict[str, TradeSeen] = {}
        rest_trades: dict[str, TradeSeen] = {}
        connections: list[dict[str, Any]] = []
        disconnects: list[dict[str, Any]] = []
        acks: list[dict[str, Any]] = []
        state: dict[str, Any] = {
            "stopped_reason": None,
            "trades_ok_sent_ms": None,
            "trade_pages_full": 0,
            "subscribed_ms": None,
        }
        raw_path = raw_dir / f"ws-{ctx.id}.jsonl"

        def handle(fh: Any, recv_ms: float, text: str) -> None:
            fh.write(json.dumps({"recv_ms": recv_ms, "text": text}) + "\n")
            counters["ws_messages"] += 1
            row = parse_ws_message(text, recv_ms)
            if len(events) < MAX_MEMORY_EVENTS:
                events.append(row)
            trade_id = row.get("trade_id")
            if row["type"] == "trade" and isinstance(trade_id, str) and trade_id not in ws_trades:
                ws_trades[trade_id] = TradeSeen(trade_id, row.get("ts_ms"), recv_ms)

        def stop_with(reason: str) -> None:
            if state["stopped_reason"] is None:
                state["stopped_reason"] = reason
            stop.set()

        async def ws_loop() -> None:
            with raw_path.open("a", encoding="utf-8") as fh:
                attempt = 0
                last_error: str | None = None
                while not stop.is_set() and time.monotonic() < deadline:
                    if attempt >= MAX_HANDSHAKES:
                        stop_with(f"WebSocket gave up after {MAX_HANDSHAKES} connection attempts. Last error: {last_error}")
                        return
                    if attempt > 0:
                        await _sleep_or_stop(stop, min(30.0, backoff_base_s * 2.0 ** (attempt - 1)))
                        if stop.is_set() or time.monotonic() >= deadline:
                            return
                    attempt += 1
                    ctx.consume_request()
                    await client.acquire_token()
                    sock = MarketDataSocket(url, client.websocket_headers, services.evidence, ctx.id, MODULE, connector)
                    hs = await sock.open()
                    connections.append(
                        {
                            "attempt": attempt,
                            "at_ms": _now_ms(),
                            "status": hs.status_code,
                            "latency_ms": hs.latency_ms,
                            "error": hs.error,
                            "request_id": hs.request_id,
                        }
                    )
                    if hs.connection is None:
                        last_error = hs.error
                        ctx.log(f"WebSocket handshake failed: {hs.error}", "warn")
                        if hs.status_code in (401, 403):
                            stop_with(f"WebSocket handshake rejected with HTTP {hs.status_code}.")
                            return
                        continue
                    ctx.log(f"WebSocket connected (attempt {attempt}, HTTP {hs.status_code}).")
                    try:
                        ctx.consume_request()
                        await client.acquire_token()
                        got, early = await sock.subscribe(params.channels, [params.market_ticker], spec_channels)
                        acks.extend({**a, "attempt": attempt} for a in got)
                        subscribed = [a for a in got if a.get("type") == "subscribed"]
                        if not subscribed:
                            stop_with("No channel subscription was confirmed; see the acknowledgements table.")
                            return
                        if state["subscribed_ms"] is None:
                            ack_ts = [a["sending_ts_ms"] for a in subscribed if isinstance(a.get("sending_ts_ms"), int | float)]
                            state["subscribed_ms"] = float(min(ack_ts)) if ack_ts else _now_ms()
                        for recv_ms, text in early:
                            handle(fh, recv_ms, text)
                        while not stop.is_set():
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                return
                            message = await sock.receive(min(remaining, RECEIVE_SLICE_S))
                            if message is not None:
                                handle(fh, *message)
                    except ConnectionClosed as exc:
                        last_error = f"closed by server (code {exc.rcvd.code if exc.rcvd else 'unknown'})"
                        disconnects.append(
                            {"attempt": attempt, "at_ms": _now_ms(), "code": exc.rcvd.code if exc.rcvd else None, "reason": exc.rcvd.reason if exc.rcvd else str(exc)}
                        )
                        ctx.log("WebSocket closed by the server; reconnecting with backoff.", "warn")
                    finally:
                        await sock.close()

        async def rest_loop() -> None:
            t0 = time.monotonic()
            cycle = 0
            prev_trades_sent_s: float | None = None
            while not stop.is_set():
                due = t0 + cycle * params.poll_interval_s
                if due >= deadline:
                    return
                await _sleep_or_stop(stop, due - time.monotonic())
                if stop.is_set():
                    return
                res = await client.call("GET", f"/markets/{params.market_ticker}", job_id=ctx.id)
                if cycle == 0 and res.status_code == 404:
                    stop_with(f"GET /markets/{params.market_ticker} returned HTTP 404; check the market ticker.")
                body = res.json() if res.ok else None
                market = body.get("market") if isinstance(body, dict) else None
                bid, ask, last = rest_market_state(market) if isinstance(market, dict) else (None, None, None)
                polls.append(
                    {
                        "cycle": cycle,
                        "sent_ms": res.sent_at.timestamp() * 1000,
                        "recv_ms": res.received_at.timestamp() * 1000,
                        "status": res.status_code,
                        "latency_ms": res.latency_ms,
                        "request_id": res.request_id,
                        "yes_bid": bid,
                        "yes_ask": ask,
                        "last_price": last,
                        "market_status": market.get("status") if isinstance(market, dict) else None,
                        "clock_offset_s": res.clock_offset_s,
                        "error": res.error,
                    }
                )
                if params.poll_trades:
                    sent_s = time.time()
                    min_ts = int(prev_trades_sent_s if prev_trades_sent_s is not None else start_ms / 1000) - TRADE_OVERLAP_S
                    tres = await client.call(
                        "GET",
                        TRADES_PATH,
                        params={"ticker": params.market_ticker, "min_ts": min_ts, "limit": trade_page_limit},
                        job_id=ctx.id,
                    )
                    tbody = tres.json() if tres.ok else None
                    items = tbody.get("trades") if isinstance(tbody, dict) else None
                    new = 0
                    if isinstance(items, list):
                        seen_ms = tres.received_at.timestamp() * 1000
                        for raw in items:
                            trade_id = raw.get("trade_id") if isinstance(raw, dict) else None
                            if isinstance(trade_id, str) and trade_id not in rest_trades:
                                created = to_epoch(raw.get("created_time"))
                                rest_trades[trade_id] = TradeSeen(trade_id, created * 1000 if created is not None else None, seen_ms)
                                new += 1
                        if trade_page_limit is not None and len(items) >= trade_page_limit:
                            state["trade_pages_full"] += 1
                        state["trades_ok_sent_ms"] = sent_s * 1000
                        prev_trades_sent_s = sent_s
                    trade_polls.append(
                        {
                            "cycle": cycle,
                            "sent_ms": tres.sent_at.timestamp() * 1000,
                            "status": tres.status_code,
                            "min_ts": min_ts,
                            "items": len(items) if isinstance(items, list) else None,
                            "new_trades": new,
                            "latency_ms": tres.latency_ms,
                            "request_id": tres.request_id,
                        }
                    )
                cycle += 1

        async def progress_loop() -> None:
            last_log = time.monotonic()
            while not stop.is_set():
                elapsed = duration_s - max(0.0, deadline - time.monotonic())
                ctx.progress(
                    int(elapsed),
                    progress_total,
                    f"{counters['ws_messages']} WS messages · {len(polls)} REST polls · {len(connections)} connection(s)",
                )
                if time.monotonic() - last_log >= LOG_EVERY_S:
                    last_log = time.monotonic()
                    ctx.log(f"{int(elapsed)}s: {counters['ws_messages']} WS messages, {len(polls)} REST polls.")
                await _sleep_or_stop(stop, PROGRESS_EVERY_S)

        async def guarded(name: str, body: Any) -> None:
            try:
                await body
            except RateLimited as exc:
                stop_with(exc.user_message)
            except JobCancelled:
                stop.set()
                raise
            except ReconError as exc:
                stop_with(f"{name}: {exc.user_message}")

        def build() -> dict[str, Any]:
            end_ms = _now_ms()
            ticker_obs = [Observation(e["recv_ms"], ws_ticker_state(e)) for e in events if e["type"] == "ticker"]
            ws_changes = change_times(ticker_obs)
            ok_polls = [
                p
                for p in polls
                if p["status"] == 200 and any(p[k] is not None for k in ("yes_bid", "yes_ask", "last_price"))
            ]
            poll_obs = [Observation(p["recv_ms"], (p["yes_bid"], p["yes_ask"], p["last_price"])) for p in ok_polls]
            misses = rest_miss_analysis(ws_changes, poll_obs)
            offsets = [p["clock_offset_s"] for p in polls if p["clock_offset_s"] is not None]
            stored = events[:MAX_STORED_EVENTS]
            first_status = next((p["market_status"] for p in polls if p["market_status"]), None)
            return {
                "params": params.model_dump(),
                "ws_url": url,
                "started_at": started_at,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "planned_duration_s": duration_s,
                "recorded_s": round((end_ms - start_ms) / 1000, 1),
                "stopped_reason": state["stopped_reason"],
                "market_status": first_status,
                "field_pairing": FIELD_PAIRING,
                "connections": connections,
                "disconnects": disconnects,
                "reconnects": max(0, len([c for c in connections if c["status"] == 101]) - 1),
                "acks": acks,
                "ws": {
                    "messages": counters["ws_messages"],
                    "message_counts": message_counts(events),
                    "ticker_messages": len(ticker_obs),
                    "price_changes": len(ws_changes),
                    "errors": [e for e in events if e["type"] == "error"],
                    "latency": latency_summary(events),
                    "sequence": sequence_gaps(events),
                    "raw_file": f"data/raw/{raw_path.name}",
                    "events_stored": len(stored),
                    "events_truncated": counters["ws_messages"] > len(stored),
                    "metrics_capped_at": MAX_MEMORY_EVENTS if counters["ws_messages"] > len(events) else None,
                },
                "rest": {
                    "polls": len(polls),
                    "ok_polls": len(ok_polls),
                    "price_changes": len(change_times(poll_obs)),
                    "latency_ms": describe(p["latency_ms"] for p in polls if p["latency_ms"] is not None),
                    "clock_offset_median_s": statistics.median(offsets) if offsets else None,
                    "trade_polls": len(trade_polls),
                    "trade_pages_full": state["trade_pages_full"],
                },
                "comparison": {
                    **{k: v for k, v in misses.items() if k != "per_interval"},
                    "per_interval": misses["per_interval"][:MAX_STORED_INTERVALS],
                },
                "trades": match_trades(ws_trades, rest_trades, state["subscribed_ms"], state["trades_ok_sent_ms"]),
                "ws_change_times": ws_changes[:MAX_STORED_EVENTS],
                "events": stored,
                "polls": polls,
                "trade_polls": trade_polls,
            }

        ctx.progress(0, progress_total, "Connecting")
        tasks = [
            asyncio.create_task(guarded("WebSocket", ws_loop())),
            asyncio.create_task(guarded("REST polling", rest_loop())),
        ]
        progress = asyncio.create_task(progress_loop())
        try:
            await asyncio.gather(*tasks)
        except (asyncio.CancelledError, JobCancelled):
            stop.set()
            ctx.save_partial(build())
            raise
        finally:
            stop.set()
            for task in [*tasks, progress]:
                task.cancel()
            await asyncio.gather(*tasks, progress, return_exceptions=True)
        ctx.progress(progress_total, progress_total, "Done")
        return build()

    job_id = services.jobs.start(MODULE, RUN_KIND, params.model_dump(), runner, max_requests=estimate["cap"])
    return {"job_id": job_id}
