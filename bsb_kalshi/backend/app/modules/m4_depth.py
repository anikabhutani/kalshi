"""M4: Depth and Archive Tester. How far back each endpoint reaches, and which endpoints still
serve settled or archived markets on each side of the historical cutoff.

Depth: targets come from ``app.analysis.depth`` (checked against specs/openapi.yaml). Targets
with an upper time-bound parameter are bisected with ``limit=1`` requests; ``/historical/markets``
has no time parameters in the spec, so it is paged with its cursor up to a page cap.

Archive matrix: sample markets (one from ``/historical/markets``, one from
``/markets?status=settled``, and optionally the user's market) are each requested from the live
and historical market, trades, and candlestick endpoints plus ``/events/{event_ticker}``. The
spec's ``GET /historical/cutoff`` timestamps say which side of the cutoff each sample is on.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.analysis.depth import (
    DEFAULT_TARGETS,
    Probe,
    ProbeBudgetExhausted,
    ResolvedTarget,
    bisect_oldest,
    bisect_request_estimate,
    resolve_targets,
)
from app.analysis.timestamps import iso, to_epoch
from app.errors import RequestBudgetExceeded
from app.jobs import JobContext
from app.kalshi_client import CallResult
from app.services import Services, get_services

router = APIRouter(prefix="/api/m4", tags=["M4 depth"])

MODULE = "M4"
RUN_KIND = "depth_archive"
RESOLUTION_S = {"hour": 3600, "day": 86_400}
MATRIX_CHECKS_PER_MARKET = 7
MATRIX_DISCOVERY = 2
CANDLE_WINDOW_S = 86_400
HIST_CANDLES = "/historical/markets/{ticker}/candlesticks"
LIVE_CANDLES = "/series/{series_ticker}/markets/{ticker}/candlesticks"


class DepthParams(BaseModel):
    """Depth and archive run configuration from the control panel."""

    targets: list[str] = Field(default_factory=lambda: list(DEFAULT_TARGETS), max_length=10)
    series_ticker: str | None = Field(default=None, max_length=128)
    market_ticker: str | None = Field(default=None, max_length=128)
    search_from: date = date(2020, 1, 1)
    resolution: Literal["hour", "day"] = "day"
    walk_page_cap: int = Field(default=3, ge=1, le=20)
    archive_matrix: bool = True
    request_cap: int = Field(default=80, ge=5, le=500)

    @field_validator("series_ticker", "market_ticker", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return value.strip() or None if isinstance(value, str) else value


def _lower_bound(params: DepthParams) -> int:
    return int(datetime(params.search_from.year, params.search_from.month, params.search_from.day, tzinfo=UTC).timestamp())


def _selected(params: DepthParams, targets: list[ResolvedTarget]) -> list[ResolvedTarget]:
    by_id = {t.definition.id: t for t in targets}
    unknown = [t for t in params.targets if t not in by_id]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown depth target(s): {', '.join(unknown)}.")
    unavailable = [t for t in params.targets if not by_id[t].available]
    if unavailable:
        raise HTTPException(
            status_code=422, detail=f"Target(s) not usable with this spec: {', '.join(unavailable)}."
        )
    return [by_id[t] for t in dict.fromkeys(params.targets)]


def estimate_requests(params: DepthParams, targets: list[ResolvedTarget], now: int) -> dict[str, int]:
    """Upper bound on requests per part, and the run's hard cap."""
    lower = _lower_bound(params)
    resolution = RESOLUTION_S[params.resolution]
    bisect = sum(
        bisect_request_estimate(lower, now, resolution) for t in targets if t.definition.mode == "bisect"
    )
    walk = params.walk_page_cap * sum(1 for t in targets if t.definition.mode == "walk")
    samples = 2 + (1 if params.market_ticker else 0)
    matrix = MATRIX_DISCOVERY + MATRIX_CHECKS_PER_MARKET * samples if params.archive_matrix else 0
    total = 1 + bisect + walk + matrix
    return {
        "cutoff": 1,
        "bisect": bisect,
        "walk": walk,
        "matrix": matrix,
        "total": total,
        "cap": params.request_cap,
    }


@router.get("/targets")
def list_targets(services: Services = Depends(get_services)) -> dict[str, Any]:
    """Depth targets from the spec, the cutoff endpoint's description, and run defaults."""
    cutoff = services.spec.find("GET", "/historical/cutoff")
    return {
        "targets": [t.to_dict() for t in resolve_targets(services.spec)],
        "cutoff_description": cutoff.description if cutoff is not None else None,
        "defaults": DepthParams().model_dump(mode="json"),
    }


@router.post("/plan")
def plan_run(params: DepthParams, services: Services = Depends(get_services)) -> dict[str, Any]:
    """Request estimate for the pre-run safety dialog (no requests are sent)."""
    targets = _selected(params, resolve_targets(services.spec))
    return {"estimate": estimate_requests(params, targets, int(time.time()))}


def _records(body: Any, key: str) -> list[dict[str, Any]]:
    items = body.get(key) if isinstance(body, dict) else None
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _filters(target: ResolvedTarget, params: DepthParams) -> dict[str, Any]:
    d = target.definition
    query: dict[str, Any] = dict(d.fixed)
    if d.series_param is not None and params.series_ticker:
        query[d.series_param] = params.series_ticker
    if d.ticker_param is not None and params.market_ticker:
        query[d.ticker_param] = params.market_ticker
    return query


def _cutoff_side(settled: float | None, boundary: float | None) -> str:
    if settled is None:
        return "no settlement time"
    if boundary is None:
        return "cutoff unknown"
    return "settled before market_settled_ts" if settled < boundary else "settled at/after market_settled_ts"


@router.post("/run")
async def run_depth(params: DepthParams, services: Services = Depends(get_services)) -> dict[str, str]:
    """Job: bisect/walk each selected target, then (optionally) build the archive matrix."""
    targets = _selected(params, resolve_targets(services.spec))
    client = services.client
    spec = services.spec

    async def runner(ctx: JobContext) -> dict[str, Any]:
        now = int(time.time())
        lower = _lower_bound(params)
        resolution = RESOLUTION_S[params.resolution]
        result: dict[str, Any] = {
            "params": params.model_dump(mode="json"),
            "estimate": estimate_requests(params, targets, now),
            "run_at": iso(now),
            "cutoff": {},
            "targets": [],
            "matrix": None,
            "notes": [],
        }
        ctx.save_partial(result)

        async def get(path: str, query: dict[str, Any] | None = None) -> CallResult:
            if ctx.remaining_requests <= 0:
                raise ProbeBudgetExhausted()
            try:
                return await client.call("GET", path, params=query, job_id=ctx.id, store_raw=True)
            except RequestBudgetExceeded:
                raise ProbeBudgetExhausted() from None

        steps = 1 + len(targets) + (1 if params.archive_matrix else 0)
        ctx.progress(0, steps, "Historical cutoff")
        cutoff_raw: dict[str, Any] = {}
        try:
            res = await get("/historical/cutoff")
            body = res.json() if res.ok else None
            cutoff_raw = body if isinstance(body, dict) else {}
        except ProbeBudgetExhausted:
            result["notes"].append("Request cap reached before the cutoff request.")
        result["cutoff"] = {
            key: {"raw": value, "epoch_s": to_epoch(value), "utc": iso(to_epoch(value))}
            for key, value in cutoff_raw.items()
        }
        market_cutoff = to_epoch(cutoff_raw.get("market_settled_ts"))

        cap_reached = False
        for index, target in enumerate(targets):
            d = target.definition
            ctx.progress(1 + index, steps, d.label)
            entry: dict[str, Any] = {
                **target.to_dict(),
                "filters_applied": _filters(target, params),
            }
            if cap_reached:
                entry["stop_reason"] = "skipped: request cap reached"
                result["targets"].append(entry)
                continue
            path = d.path
            base_query = _filters(target, params)
            if d.mode == "bisect":
                async def probe(bound: int | None, _d: Any = d, _q: dict[str, Any] = base_query) -> Probe:
                    query = {**_q, "limit": 1}
                    if bound is not None and _d.bound_param is not None:
                        query[_d.bound_param] = bound
                    res = await get(_d.path, query)
                    items = _records(res.json() if res.ok else None, _d.list_key)
                    stamps = [t for t in (to_epoch(i.get(_d.ts_field)) for i in items) if t is not None]
                    return Probe(bound, res.status_code, len(items), stamps, res.request_id, res.error)

                outcome = await bisect_oldest(probe, lower, now, resolution)
                entry.update(outcome.to_dict())
                cap_reached = outcome.stop_reason == "request cap reached"
                ctx.log(
                    f"{d.label}: {len(outcome.probes)} probes; oldest observed {iso(outcome.oldest_ts) or '–'}"
                    + (f" ({outcome.stop_reason})" if outcome.stop_reason else "")
                )
            else:
                pages: list[dict[str, Any]] = []
                cursor: str | None = None
                stop_reason: str | None = None
                try:
                    for page in range(params.walk_page_cap):
                        query = {**base_query, "limit": target.page_limit, "cursor": cursor}
                        res = await get(path, query)
                        body = res.json() if res.ok else None
                        items = _records(body, d.list_key)
                        stamps = [t for t in (to_epoch(i.get(d.ts_field)) for i in items) if t is not None]
                        cursor = (body.get("cursor") or None) if isinstance(body, dict) else None
                        pages.append(
                            {
                                "index": page,
                                "status": res.status_code,
                                "records": len(items),
                                "min_ts": min(stamps) if stamps else None,
                                "max_ts": max(stamps) if stamps else None,
                                "cursor_returned": cursor is not None,
                                "request_id": res.request_id,
                            }
                        )
                        if not res.ok:
                            stop_reason = f"HTTP {res.status_code} on page {page + 1}"
                            break
                        if cursor is None:
                            break
                except ProbeBudgetExhausted:
                    stop_reason, cap_reached = "request cap reached", True
                mins = [p["min_ts"] for p in pages if p["min_ts"] is not None]
                maxs = [p["max_ts"] for p in pages if p["max_ts"] is not None]
                end_reached = bool(pages) and pages[-1]["status"] == 200 and not pages[-1]["cursor_returned"]
                entry.update(
                    {
                        "pages": pages,
                        "records_seen": sum(p["records"] for p in pages),
                        "oldest_ts": min(mins) if mins else None,
                        "newest_ts": max(maxs) if maxs else None,
                        "end_reached": end_reached,
                        "stop_reason": stop_reason
                        or (None if end_reached else f"page cap of {params.walk_page_cap} reached"),
                    }
                )
                ctx.log(f"{d.label}: {len(pages)} page(s), {entry['records_seen']} records, end reached: {end_reached}")
            entry["oldest_utc"] = iso(entry.get("oldest_ts"))
            entry["newest_utc"] = iso(entry.get("newest_ts"))
            result["targets"].append(entry)

        if params.archive_matrix:
            ctx.progress(steps - 1, steps, "Archive matrix")
            if cap_reached:
                result["notes"].append("Archive matrix skipped: request cap reached.")
            else:
                result["matrix"] = await _archive_matrix(get, spec, params, market_cutoff, ctx)
        ctx.progress(steps, steps, "Done")
        return result

    estimate = estimate_requests(params, targets, int(time.time()))
    job_id = services.jobs.start(
        MODULE, RUN_KIND, params.model_dump(mode="json"), runner, max_requests=estimate["cap"]
    )
    return {"job_id": job_id}


async def _archive_matrix(
    get: Any, spec: Any, params: DepthParams, market_cutoff: float | None, ctx: JobContext
) -> dict[str, Any]:
    """Request each sample market from every live/historical endpoint and record what returns."""
    samples: list[tuple[str, str]] = []
    discovery: list[dict[str, Any]] = []
    series_filter = {"series_ticker": params.series_ticker} if params.series_ticker else {}
    if params.market_ticker:
        samples.append(("Your market", params.market_ticker))
    try:
        for label, path, query in (
            ("Archived sample (first from /historical/markets)", "/historical/markets", {"limit": 1, **series_filter}),
            ("Settled sample (first from /markets?status=settled)", "/markets", {"limit": 1, "status": "settled", **series_filter}),
        ):
            res = await get(path, query)
            items = _records(res.json() if res.ok else None, "markets")
            ticker = str(items[0].get("ticker")) if items and items[0].get("ticker") else None
            discovery.append({"label": label, "path": path, "status": res.status_code, "ticker": ticker, "request_id": res.request_id})
            if ticker is not None and ticker not in {t for _, t in samples}:
                samples.append((label, ticker))
    except ProbeBudgetExhausted:
        return {"discovery": discovery, "samples": [], "stop_reason": "request cap reached"}

    interval_param = spec.find("GET", HIST_CANDLES)
    enum = interval_param.param("period_interval").enum if interval_param and interval_param.param("period_interval") else None
    interval = 60 if enum and 60 in enum else (enum[0] if enum else 60)

    rows: list[dict[str, Any]] = []
    stop_reason: str | None = None
    for label, ticker in samples:
        row: dict[str, Any] = {"label": label, "ticker": ticker, "cells": []}
        rows.append(row)

        def cell(check: str, endpoint: str, res: CallResult | None, records: int | None, note: str | None = None) -> None:
            row["cells"].append(
                {
                    "check": check,
                    "endpoint": endpoint,
                    "status": res.status_code if res is not None else None,
                    "records": records,
                    "request_id": res.request_id if res is not None else None,
                    "note": note,
                }
            )

        try:
            live = await get(f"/markets/{ticker}")
            live_body = live.json() if live.ok else None
            live_market = live_body.get("market") if isinstance(live_body, dict) else None
            cell("Market (live)", "/markets/{ticker}", live, 1 if isinstance(live_market, dict) else 0)
            hist = await get(f"/historical/markets/{ticker}")
            hist_body = hist.json() if hist.ok else None
            hist_market = hist_body.get("market") if isinstance(hist_body, dict) else None
            cell("Market (historical)", "/historical/markets/{ticker}", hist, 1 if isinstance(hist_market, dict) else 0)
            market = live_market if isinstance(live_market, dict) else hist_market if isinstance(hist_market, dict) else {}
            event_ticker = market.get("event_ticker")
            settled = to_epoch(market.get("settlement_ts"))
            close = to_epoch(market.get("close_time"))
            row.update(
                {
                    "event_ticker": event_ticker,
                    "status": market.get("status"),
                    "close_time": market.get("close_time"),
                    "settlement_ts": market.get("settlement_ts"),
                    "cutoff_side": _cutoff_side(settled, market_cutoff),
                }
            )

            series_ticker: str | None = None
            if event_ticker:
                ev = await get(f"/events/{event_ticker}")
                ev_body = ev.json() if ev.ok else None
                event = ev_body.get("event") if isinstance(ev_body, dict) else None
                series_ticker = str(event["series_ticker"]) if isinstance(event, dict) and event.get("series_ticker") else None
                cell("Event", "/events/{event_ticker}", ev, 1 if isinstance(event, dict) else 0)
            else:
                cell("Event", "/events/{event_ticker}", None, None, "no event ticker on the market record")
            row["series_ticker"] = series_ticker

            for check, path in (("Trades (live)", "/markets/trades"), ("Trades (historical)", "/historical/trades")):
                res = await get(path, {"ticker": ticker, "limit": 1})
                cell(check, path, res, len(_records(res.json() if res.ok else None, "trades")))

            end = int(close or settled or time.time())
            window = {"start_ts": end - CANDLE_WINDOW_S, "end_ts": end, "period_interval": interval}
            if series_ticker:
                res = await get(f"/series/{series_ticker}/markets/{ticker}/candlesticks", window)
                cell("Candlesticks (live)", LIVE_CANDLES, res, len(_records(res.json() if res.ok else None, "candlesticks")))
            else:
                cell("Candlesticks (live)", LIVE_CANDLES, None, None, "series ticker unknown")
            res = await get(f"/historical/markets/{ticker}/candlesticks", window)
            cell("Candlesticks (historical)", HIST_CANDLES, res, len(_records(res.json() if res.ok else None, "candlesticks")))
            row["candle_window"] = {**window, "start_utc": iso(window["start_ts"]), "end_utc": iso(window["end_ts"])}
        except ProbeBudgetExhausted:
            stop_reason = "request cap reached"
            break
        ctx.log(f"Archive matrix: {ticker} checked on {len(row['cells'])} endpoints.")
    return {"discovery": discovery, "samples": rows, "stop_reason": stop_reason}
