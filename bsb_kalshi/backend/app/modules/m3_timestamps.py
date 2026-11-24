"""M3: Timestamp Lab. Pull every price-history source for one market and measure it.

Sources (all from specs/openapi.yaml): candlesticks at every ``period_interval`` the chosen
candlestick endpoint allows, trades (live and, before the trades cutoff, historical), an
orderbook snapshot, and market metadata timestamps. Live vs historical endpoints are chosen
using ``GET /historical/cutoff`` as the spec describes.

Client-side choice (not from the spec): candlestick requests are split into windows of at
most ``CANDLES_PER_REQUEST`` periods. TODO(spec): the spec does not state a maximum number
of candlesticks per response, so this is a conservative assumption.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from app.analysis.timeseries import (
    PricePoint,
    aligned_origin,
    compute_gaps,
    inter_arrival,
    price_at,
)
from app.analysis.timestamps import detect_timestamp_format, iso, parse_timestamp, to_epoch
from app.errors import RateLimited, ReconError
from app.jobs import JobContext
from app.kalshi_client import CallResult, KalshiClient
from app.services import Services, get_services
from app.spec_loader import TIMESTAMP_NAME_RE, OpenApiSpec

router = APIRouter(prefix="/api/m3", tags=["M3 timestamps"])

MODULE = "M3"
RUN_KIND = "price_sources"
CANDLES_PER_REQUEST = 1440
RETRY_HEADROOM = 10
LIVE_CANDLES = "/series/{series_ticker}/markets/{ticker}/candlesticks"
HIST_CANDLES = "/historical/markets/{ticker}/candlesticks"
LIVE_TRADES = "/markets/trades"
HIST_TRADES = "/historical/trades"

_last_cutoff: dict[str, float | None] = {}


class RunParams(BaseModel):
    """Timestamp Lab run configuration from the control panel."""

    market_ticker: str = Field(min_length=1, max_length=128)
    series_ticker: str | None = Field(default=None, max_length=128)
    start_ts: int = Field(ge=0)
    end_ts: int = Field(ge=0)
    trade_page_cap: int = Field(default=10, ge=1, le=100)
    trade_bucket_s: int = Field(default=60, ge=1, le=86_400)
    archived: bool = False

    @model_validator(mode="after")
    def _check_window(self) -> RunParams:
        if self.end_ts <= self.start_ts:
            raise ValueError("end must be after start")
        return self


@contextmanager
def _http_errors() -> Iterator[None]:
    """Turn client errors in non-job routes into readable HTTP errors."""
    try:
        yield
    except RateLimited as exc:
        raise HTTPException(status_code=429, detail=exc.user_message) from None
    except ReconError as exc:
        raise HTTPException(status_code=400, detail=exc.user_message) from None


def _num(value: Any) -> float | None:
    """Fixed-point dollar/count strings (and numbers) to float; anything else to None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick(container: Any, base: str) -> float | None:
    """Live schema uses ``<base>_dollars``; the historical schema uses ``<base>``."""
    if not isinstance(container, dict):
        return None
    return _num(container.get(f"{base}_dollars", container.get(base)))


def normalize_candle(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Flatten one live or historical candlestick into numeric columns."""
    ts = raw.get("end_period_ts")
    if not isinstance(ts, int | float) or isinstance(ts, bool):
        return None
    price = raw.get("price")
    return {
        "ts": int(ts),
        "open": _pick(price, "open"),
        "high": _pick(price, "high"),
        "low": _pick(price, "low"),
        "close": _pick(price, "close"),
        "mean": _pick(price, "mean"),
        "bid_close": _pick(raw.get("yes_bid"), "close"),
        "ask_close": _pick(raw.get("yes_ask"), "close"),
        "volume": _num(raw.get("volume_fp", raw.get("volume"))),
        "open_interest": _num(raw.get("open_interest_fp", raw.get("open_interest"))),
    }


def normalize_trade(raw: dict[str, Any], source: str) -> dict[str, Any] | None:
    """Flatten one trade; ``ts`` is unix seconds parsed from ``created_time``."""
    ts = to_epoch(raw.get("created_time"))
    if ts is None:
        return None
    return {
        "ts": ts,
        "price": _num(raw.get("yes_price_dollars")),
        "count": _num(raw.get("count_fp")),
        "side": raw.get("taker_outcome_side"),
        "block": bool(raw.get("is_block_trade")),
        "source": source,
    }


def candle_chunks(start_ts: int, end_ts: int, interval_min: int) -> list[tuple[int, int]]:
    """Split a window into request windows of at most CANDLES_PER_REQUEST periods."""
    span = interval_min * 60 * CANDLES_PER_REQUEST
    chunks: list[tuple[int, int]] = []
    cursor = start_ts
    while cursor < end_ts:
        chunks.append((cursor, min(end_ts, cursor + span)))
        cursor += span
    return chunks


def _intervals(spec: OpenApiSpec, path: str) -> list[int]:
    endpoint = spec.find("GET", path)
    param = endpoint.param("period_interval") if endpoint is not None else None
    if param is None or not param.enum:
        raise ReconError(f"The spec lists no period_interval values for GET {path}.")
    return sorted(int(v) for v in param.enum if isinstance(v, int) and v > 0)


def _page_limit(spec: OpenApiSpec, path: str) -> int | None:
    endpoint = spec.find("GET", path)
    param = endpoint.param("limit") if endpoint is not None else None
    return int(param.maximum) if param is not None and param.maximum is not None else None


def trade_plan(
    start_ts: int, end_ts: int, trades_cutoff: float | None
) -> list[tuple[str, int, int]]:
    """(endpoint, min_ts, max_ts) per trades endpoint, split at the trades cutoff.

    Spec: trades filled before ``trades_created_ts`` are served by /historical/trades.
    """
    if trades_cutoff is None:
        return [(LIVE_TRADES, start_ts, end_ts)]
    cutoff = int(trades_cutoff)
    plan: list[tuple[str, int, int]] = []
    if start_ts < cutoff:
        plan.append((HIST_TRADES, start_ts, min(end_ts, cutoff)))
    if end_ts > cutoff:
        plan.append((LIVE_TRADES, max(start_ts, cutoff), end_ts))
    return plan


def estimate_requests(spec: OpenApiSpec, params: RunParams) -> dict[str, int]:
    """Upper bound on requests for a run (exact for candles, capped for trade pages)."""
    candle_path = HIST_CANDLES if params.archived else LIVE_CANDLES
    candles = sum(
        len(candle_chunks(params.start_ts, params.end_ts, i)) for i in _intervals(spec, candle_path)
    )
    endpoints = trade_plan(params.start_ts, params.end_ts, _last_cutoff.get("trades_created_ts"))
    fixed = 1 + 2 + (0 if params.series_ticker else 1) + 1
    trades = len(endpoints) * params.trade_page_cap
    total = fixed + candles + trades
    return {
        "fixed": fixed,
        "candles": candles,
        "trades_max": trades,
        "total": total,
        "cap": total + RETRY_HEADROOM,
    }


async def _cutoff(client: KalshiClient, job_id: str | None) -> tuple[dict[str, Any], CallResult]:
    result = await client.call("GET", "/historical/cutoff", job_id=job_id, module=MODULE)
    body = result.json() if result.ok else None
    cutoff = body if isinstance(body, dict) else {}
    for key in ("market_settled_ts", "trades_created_ts"):
        _last_cutoff[key] = to_epoch(cutoff.get(key))
    return cutoff, result


async def _market(
    client: KalshiClient, ticker: str, job_id: str | None
) -> tuple[dict[str, Any] | None, str, list[CallResult]]:
    calls: list[CallResult] = []
    live = await client.call("GET", f"/markets/{ticker}", job_id=job_id, module=MODULE)
    calls.append(live)
    body = live.json() if live.ok else None
    if isinstance(body, dict) and isinstance(body.get("market"), dict):
        return body["market"], "live", calls
    hist = await client.call("GET", f"/historical/markets/{ticker}", job_id=job_id, module=MODULE)
    calls.append(hist)
    body = hist.json() if hist.ok else None
    if isinstance(body, dict) and isinstance(body.get("market"), dict):
        return body["market"], "historical", calls
    return None, "not found", calls


async def _series_ticker(
    client: KalshiClient, event_ticker: str | None, job_id: str | None
) -> tuple[str | None, CallResult | None]:
    if not event_ticker:
        return None, None
    result = await client.call("GET", f"/events/{event_ticker}", job_id=job_id, module=MODULE)
    body = result.json() if result.ok else None
    event = body.get("event") if isinstance(body, dict) else None
    value = event.get("series_ticker") if isinstance(event, dict) else None
    return (str(value) if value else None), result


def _is_archived(market: dict[str, Any], source: str, cutoff: dict[str, Any]) -> bool:
    """Spec rule: markets settled before ``market_settled_ts`` are served by /historical."""
    if source == "historical":
        return True
    settled = to_epoch(market.get("settlement_ts"))
    boundary = to_epoch(cutoff.get("market_settled_ts"))
    return settled is not None and boundary is not None and settled < boundary


_SUMMARY_KEYS = (
    "ticker",
    "event_ticker",
    "title",
    "yes_sub_title",
    "status",
    "open_time",
    "close_time",
    "expected_expiration_time",
    "occurrence_datetime",
    "settlement_ts",
)


@router.get("/market")
async def load_market(
    ticker: str = Query(min_length=1, max_length=128),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    """Market metadata, its series, archive status, and a suggested window (3-4 requests)."""
    client = services.client
    with _http_errors():
        cutoff, _ = await _cutoff(client, None)
        market, source, _ = await _market(client, ticker, None)
        if market is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Market {ticker} not found (live or historical). If this is an event ticker, "
                    "use one of its market tickers (event ticker plus an outcome suffix; the Schema "
                    "page lists them)."
                ),
            )
        series_ticker, _ = await _series_ticker(client, market.get("event_ticker"), None)
    open_ts = to_epoch(market.get("open_time"))
    close_ts = to_epoch(market.get("close_time"))
    now = time.time()
    end = min(close_ts, now) if close_ts is not None else now
    return {
        "market": {k: market.get(k) for k in _SUMMARY_KEYS},
        "series_ticker": series_ticker,
        "source": source,
        "archived": _is_archived(market, source, cutoff),
        "cutoff": cutoff,
        "suggested_window": {
            "start_ts": int(open_ts) if open_ts is not None else int(end - 86_400),
            "end_ts": int(end),
        },
    }


@router.post("/plan")
def plan_run(params: RunParams, services: Services = Depends(get_services)) -> dict[str, Any]:
    """Request estimate for the pre-run safety dialog (no requests are sent)."""
    with _http_errors():
        return {"estimate": estimate_requests(services.spec, params)}


def _clock_row(result: CallResult) -> dict[str, Any]:
    offset = result.clock_offset_s
    return {
        "request_id": result.request_id,
        "path": result.path_template,
        "sent_at": result.sent_at.isoformat(),
        "server_date": result.server_date.isoformat() if result.server_date else None,
        "offset_s": round(offset, 3) if offset is not None else None,
        "latency_ms": result.latency_ms,
        "status": result.status_code,
    }


def clock_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Median/min/max of server-minus-local offsets and of latency."""
    offsets = [r["offset_s"] for r in rows if r["offset_s"] is not None]
    latencies = sorted(r["latency_ms"] for r in rows if r["latency_ms"] is not None)
    return {
        "requests": len(rows),
        "offset_median_s": statistics.median(offsets) if offsets else None,
        "offset_min_s": min(offsets) if offsets else None,
        "offset_max_s": max(offsets) if offsets else None,
        "latency_median_ms": statistics.median(latencies) if latencies else None,
        "latency_p95_ms": latencies[int(0.95 * (len(latencies) - 1))] if latencies else None,
        "latency_max_ms": latencies[-1] if latencies else None,
        "date_header_resolution_s": 1,
    }


def candle_metrics(
    rows: list[dict[str, Any]], interval_s: int, start_ts: int, end_ts: int, raw_example: Any
) -> dict[str, Any]:
    """Coverage of one candlestick series: missing periods and periods without a trade."""
    ts = [r["ts"] for r in rows]
    priced = [r["ts"] for r in rows if r["close"] is not None]
    origin = aligned_origin(ts[0], start_ts, interval_s) if ts else None
    spacing = inter_arrival(ts)
    record_gaps = compute_gaps(ts, interval_s, origin, end_ts if ts else None)
    trade_gaps = compute_gaps(priced, interval_s, origin, end_ts if ts else None)
    fmt = detect_timestamp_format(raw_example)
    return {
        "records": len(rows),
        "first_ts": iso(ts[0]) if ts else None,
        "last_ts": iso(ts[-1]) if ts else None,
        "covered_s": (ts[-1] - ts[0]) if ts else 0,
        "finest_granularity_s": spacing.min_positive_delta_s,
        "median_delta_s": spacing.median_delta_s,
        "max_delta_s": spacing.max_delta_s,
        "alignment_offset_s": (ts[0] % interval_s) if ts else None,
        "candles_without_trade": len(rows) - len(priced),
        "missing_periods": record_gaps.to_dict(),
        "periods_without_trade": trade_gaps.to_dict(),
        "timestamp_field": "end_period_ts (period end, inclusive)",
        "timestamp_format": fmt,
    }


def trade_metrics(
    rows: list[dict[str, Any]],
    bucket_s: int,
    start_ts: int,
    end_ts: int,
    truncated: bool,
    raw_times: list[Any],
) -> dict[str, Any]:
    """Coverage of the trade series over fixed buckets (window shrinks if truncated)."""
    ts = sorted(r["ts"] for r in rows)
    origin: float | None = float(start_ts)
    end: float | None = float(end_ts)
    if truncated:
        origin, end = (ts[0], ts[-1]) if ts else (None, None)
    spacing = inter_arrival(ts)
    gaps = compute_gaps(ts, bucket_s, origin, end)
    formats = sorted({f for f in (detect_timestamp_format(v) for v in raw_times) if f})
    return {
        "records": len(rows),
        "first_ts": iso(ts[0]) if ts else None,
        "last_ts": iso(ts[-1]) if ts else None,
        "covered_s": (ts[-1] - ts[0]) if ts else 0,
        "truncated_by_page_cap": truncated,
        "finest_granularity_s": spacing.min_positive_delta_s,
        "median_delta_s": spacing.median_delta_s,
        "max_delta_s": spacing.max_delta_s,
        "bucket_s": bucket_s,
        "empty_buckets": gaps.to_dict(),
        "timestamp_field": "created_time",
        "timestamp_formats": formats,
    }


def orderbook_summary(body: Any, result: CallResult) -> dict[str, Any]:
    """Best levels of a snapshot. Its time is the local receive time (see has_timestamp_field)."""
    book = body.get("orderbook_fp") if isinstance(body, dict) else None
    yes = (book or {}).get("yes_dollars") or []
    no = (book or {}).get("no_dollars") or []
    yes_prices = [p for p in (_num(level[0]) for level in yes if level) if p is not None]
    no_prices = [p for p in (_num(level[0]) for level in no if level) if p is not None]
    best_yes_bid = max(yes_prices) if yes_prices else None
    best_no_bid = max(no_prices) if no_prices else None
    implied_yes_ask = round(1.0 - best_no_bid, 6) if best_no_bid is not None else None
    mid = (
        round((best_yes_bid + implied_yes_ask) / 2, 6)
        if best_yes_bid is not None and implied_yes_ask is not None
        else None
    )
    keys = list(body.keys()) + list((book or {}).keys()) if isinstance(body, dict) else []
    return {
        "status": result.status_code,
        "yes_levels": len(yes),
        "no_levels": len(no),
        "best_yes_bid": best_yes_bid,
        "best_no_bid": best_no_bid,
        "implied_yes_ask": implied_yes_ask,
        "mid": mid,
        "snapshot_ts": result.received_at.timestamp(),
        "server_date": result.server_date.isoformat() if result.server_date else None,
        "has_timestamp_field": any(TIMESTAMP_NAME_RE.search(k) for k in keys),
        "request_id": result.request_id,
    }


def metadata_timestamps(spec: OpenApiSpec, market: dict[str, Any], spec_path: str) -> list[dict[str, Any]]:
    """Market fields that are timestamps by value, by spec format, or by name."""
    props = spec.response_object_properties(spec_path, "market")
    rows: list[dict[str, Any]] = []
    for name in sorted(set(market) | {k for k, p in props.items() if p.format in ("date-time", "date")}):
        value = market.get(name)
        prop = props.get(name)
        detected = detect_timestamp_format(value)
        spec_fmt = prop.format if prop else None
        if detected is None and spec_fmt not in ("date-time", "date") and not TIMESTAMP_NAME_RE.search(name):
            continue
        parsed = parse_timestamp(value)
        rows.append(
            {
                "field": name,
                "value": value,
                "detected_format": detected,
                "spec_format": spec_fmt,
                "spec_description": prop.description if prop else None,
                "utc": parsed.isoformat() if parsed else None,
                "epoch_s": parsed.timestamp() if parsed else None,
            }
        )
    return rows


@router.post("/run")
async def run_lab(params: RunParams, services: Services = Depends(get_services)) -> dict[str, str]:
    """Job: pull candles (every allowed interval), trades, orderbook, metadata; compute metrics."""
    with _http_errors():
        estimate = estimate_requests(services.spec, params)
    client = services.client
    spec = services.spec

    async def runner(ctx: JobContext) -> dict[str, Any]:
        clock: list[dict[str, Any]] = []
        result: dict[str, Any] = {
            "params": params.model_dump(),
            "sources": {},
            "errors": [],
            "clock": {"rows": clock},
        }
        ctx.save_partial(result)

        async def get(path: str, query: dict[str, Any] | None = None, raw: bool = False) -> CallResult:
            res = await client.call("GET", path, params=query, job_id=ctx.id, store_raw=raw)
            clock.append(_clock_row(res))
            result["clock"]["summary"] = clock_summary(clock)
            return res

        ctx.progress(0, 5, "Historical cutoff and market metadata")
        cutoff_res = await get("/historical/cutoff")
        cutoff_body = cutoff_res.json() if cutoff_res.ok else None
        cutoff = cutoff_body if isinstance(cutoff_body, dict) else {}
        result["cutoff"] = cutoff
        trades_cutoff = to_epoch(cutoff.get("trades_created_ts"))

        live = await get(f"/markets/{params.market_ticker}")
        market_body = live.json() if live.ok else None
        source, market_spec_path = "live", "/markets/{ticker}"
        if not (isinstance(market_body, dict) and isinstance(market_body.get("market"), dict)):
            hist = await get(f"/historical/markets/{params.market_ticker}")
            market_body = hist.json() if hist.ok else None
            source, market_spec_path = "historical", "/historical/markets/{ticker}"
        market = (market_body or {}).get("market") if isinstance(market_body, dict) else None
        if not isinstance(market, dict):
            raise ReconError(f"Market {params.market_ticker} was not found (live or historical).")
        archived = _is_archived(market, source, cutoff)
        result["market"] = {k: market.get(k) for k in _SUMMARY_KEYS}
        result["market_source"] = source
        result["archived"] = archived
        result["metadata_timestamps"] = metadata_timestamps(spec, market, market_spec_path)

        series_ticker = params.series_ticker
        if not series_ticker and not archived:
            event_res = await get(f"/events/{market.get('event_ticker')}")
            event = (event_res.json() or {}).get("event") if event_res.ok else None
            series_ticker = event.get("series_ticker") if isinstance(event, dict) else None
        candle_path = HIST_CANDLES if archived else LIVE_CANDLES
        result["candle_endpoint"] = candle_path
        if not archived and not series_ticker:
            raise ReconError("Could not determine the series ticker needed for live candlesticks.")

        ctx.progress(1, 5, "Candlesticks")
        for interval in _intervals(spec, candle_path):
            key = f"candles_{interval}m"
            path = candle_path.replace("{ticker}", params.market_ticker).replace(
                "{series_ticker}", series_ticker or ""
            )
            by_ts: dict[int, dict[str, Any]] = {}
            raw_example: Any = None
            requests: list[int] = []
            for chunk_start, chunk_end in candle_chunks(params.start_ts, params.end_ts, interval):
                res = await get(
                    path,
                    {"start_ts": chunk_start, "end_ts": chunk_end, "period_interval": interval},
                    raw=True,
                )
                requests.append(res.request_id)
                body = res.json() if res.ok else None
                if not isinstance(body, dict):
                    result["errors"].append(
                        {"source": key, "message": res.error or f"HTTP {res.status_code}", "request_id": res.request_id}
                    )
                    ctx.log(f"{key}: HTTP {res.status_code}; skipping the rest of this interval.", "warn")
                    break
                for raw in body.get("candlesticks") or []:
                    if isinstance(raw, dict) and (row := normalize_candle(raw)) is not None:
                        raw_example = raw_example if raw_example is not None else raw.get("end_period_ts")
                        by_ts[row["ts"]] = row
            rows = [by_ts[t] for t in sorted(by_ts)]
            result["sources"][key] = {
                "kind": "candles",
                "interval_min": interval,
                "endpoint": candle_path,
                "request_ids": requests,
                "rows": rows,
                "metrics": candle_metrics(rows, interval * 60, params.start_ts, params.end_ts, raw_example),
            }
            ctx.log(f"{key}: {len(rows)} candles from {len(requests)} request(s).")

        ctx.progress(2, 5, "Trades")
        trades: list[dict[str, Any]] = []
        raw_times: list[Any] = []
        seen_trade_ids: set[str] = set()
        truncated = False
        trade_requests: list[int] = []
        trade_endpoints: list[str] = []
        for endpoint, min_ts, max_ts in trade_plan(params.start_ts, params.end_ts, trades_cutoff):
            trade_endpoints.append(endpoint)
            cursor: str | None = None
            for page in range(params.trade_page_cap):
                query: dict[str, Any] = {
                    "ticker": params.market_ticker,
                    "min_ts": min_ts,
                    "max_ts": max_ts,
                    "limit": _page_limit(spec, endpoint),
                    "cursor": cursor,
                }
                res = await get(endpoint, query, raw=True)
                trade_requests.append(res.request_id)
                body = res.json() if res.ok else None
                if not isinstance(body, dict):
                    result["errors"].append(
                        {"source": "trades", "message": res.error or f"HTTP {res.status_code}", "request_id": res.request_id}
                    )
                    break
                label = "historical" if endpoint == HIST_TRADES else "live"
                for raw in body.get("trades") or []:
                    if not isinstance(raw, dict):
                        continue
                    trade_id = str(raw.get("trade_id") or "")
                    if trade_id and trade_id in seen_trade_ids:
                        continue
                    if (row := normalize_trade(raw, label)) is not None:
                        seen_trade_ids.add(trade_id)
                        trades.append(row)
                        raw_times.append(raw.get("created_time"))
                cursor = body.get("cursor") or None
                ctx.log(f"Trades {endpoint} page {page + 1}: {len(body.get('trades') or [])} rows.")
                if cursor is None:
                    break
            else:
                truncated = truncated or cursor is not None
        trades.sort(key=lambda r: r["ts"])
        result["sources"]["trades"] = {
            "kind": "trades",
            "endpoints": trade_endpoints,
            "request_ids": trade_requests,
            "rows": trades,
            "metrics": trade_metrics(
                trades, params.trade_bucket_s, params.start_ts, params.end_ts, truncated, raw_times
            ),
        }

        ctx.progress(3, 5, "Orderbook snapshot")
        book_res = await get(f"/markets/{params.market_ticker}/orderbook")
        result["sources"]["orderbook"] = {
            "kind": "orderbook",
            "endpoint": "/markets/{ticker}/orderbook",
            **orderbook_summary(book_res.json() if book_res.ok else None, book_res),
        }

        ctx.progress(5, 5, "Done")
        return result

    job_id = services.jobs.start(MODULE, RUN_KIND, params.model_dump(), runner, max_requests=estimate["cap"])
    return {"job_id": job_id}


def _points(source: dict[str, Any], field: str) -> list[PricePoint]:
    return [PricePoint(ts=float(r["ts"]), price=r.get(field)) for r in source.get("rows", [])]


_CANDLE_FIELDS = (
    ("price.close (last trade in period)", "close"),
    ("yes_bid.close", "bid_close"),
    ("yes_ask.close", "ask_close"),
)


def price_series(sources: dict[str, Any]) -> list[tuple[str, str, str, str, list[PricePoint]]]:
    """Every price series of a stored run as (source key, field id, label, note, points)."""
    out: list[tuple[str, str, str, str, list[PricePoint]]] = []
    for key, source in sources.items():
        if source.get("kind") == "candles":
            note = "Timestamp is the candle's end_period_ts (period end)."
            out += [(key, field, label, note, _points(source, field)) for label, field in _CANDLE_FIELDS]
        elif source.get("kind") == "trades":
            out.append((key, "price", "yes_price (trade)", "Timestamp is the trade's created_time.", _points(source, "price")))
        else:
            snapshot = PricePoint(ts=float(source.get("snapshot_ts") or 0), price=source.get("mid"))
            note = "Single snapshot; its time is the local receive time (no timestamp field in response)."
            out.append((key, "mid", "mid of best YES bid and implied YES ask", note, [snapshot]))
    return out


@router.get("/price_at")
def price_at_route(
    job_id: str,
    at: str = Query(description="ISO 8601 timestamp with timezone, e.g. 2026-10-01T00:05:00Z"),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    """``price_at(market, timestamp, source)`` for every source of a stored run."""
    parsed = parse_timestamp(at)
    if parsed is None:
        raise HTTPException(status_code=422, detail="Could not parse the timestamp.")
    job = services.jobs.get_job(job_id)
    if job is None or not isinstance(job.get("result"), dict):
        raise HTTPException(status_code=404, detail="No stored Timestamp Lab result for that job.")
    query_ts = parsed.timestamp()
    rows: list[dict[str, Any]] = []
    for key, _field, label, note, points in price_series(job["result"].get("sources") or {}):
        answer = price_at(points, query_ts)
        rows.append(
            {
                "source": key,
                "field": label,
                "price": answer.price,
                "price_ts": iso(answer.price_ts),
                "staleness_s": answer.staleness_s,
                "before_first_record": answer.before_first_record,
                "after_last_record": answer.after_last_record,
                "records": answer.records_considered,
                "note": note,
            }
        )
    return {"query_ts": parsed.isoformat(), "rows": rows}
