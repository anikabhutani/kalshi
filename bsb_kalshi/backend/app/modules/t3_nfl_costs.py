"""Task 3: Kalshi costs for every NFL game this season.

Two jobs and one local calculation:
- ``inventory``: list every NFL game, spread and total event and market since the start date
  (settled ones included), fee settings, kickoff times, and the historical cutoff check.
- ``backfill``: 1-minute candles for every listed market that is not fully stored yet (batch
  endpoint), then the cost calculation.
- ``analyze``: recompute costs, results and the quality check from stored candles (no requests).

The same steps run from the command line once a day: ``python -m app.task3.backfill``.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter, defaultdict
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.analysis.timestamps import iso
from app.config import ROOT_DIR
from app.errors import ReconError
from app.jobs import JobContext
from app.services import Services, get_services
from app.task3.backfill import (
    DEFAULT_START,
    SERIES,
    BackfillBusy,
    BudgetExhausted,
    Fetcher,
    Hooks,
    backfill_candles,
    cutoff_check,
    estimate_candle_requests,
    refresh_inventory,
    run_lock,
)
from app.task3.costs import CHECKPOINTS, SIZES, AnalysisParams, run_analysis
from app.task3.store import NflStore

router = APIRouter(prefix="/api/t3", tags=["Task 3 NFL costs"])

MODULE = "T3"
LISTING_ESTIMATE = 12
CUTOFF_CHECK_ESTIMATE = 13
EXPORT_FILES = frozenset({"checkpoint_quotes.csv", "checkpoint_costs.csv"})


@lru_cache(maxsize=4)
def _store_at(root: Path) -> NflStore:
    return NflStore(root)


def get_store(services: Services) -> NflStore:
    return _store_at(services.config.data_dir / "task3")


class InventoryParams(BaseModel):
    """Which games to list."""

    start_date: date = DEFAULT_START
    series: list[str] = Field(default_factory=lambda: list(SERIES), min_length=1)
    request_cap: int = Field(default=80, ge=20, le=500)

    @field_validator("series")
    @classmethod
    def _known(cls, value: list[str]) -> list[str]:
        unknown = [s for s in value if s not in SERIES]
        if unknown:
            raise ValueError(f"Unknown series: {', '.join(unknown)}")
        return list(dict.fromkeys(value))


class BackfillParams(BaseModel):
    """Candle fetch limits and the fee rounding used for the cost calculation afterwards."""

    request_cap: int = Field(default=6000, ge=10, le=20_000)
    fee_rounding: Literal["cent", "exact"] = "cent"


def _listing_estimate(params: InventoryParams) -> dict[str, int]:
    listing = LISTING_ESTIMATE + 2 * len(params.series)
    total = listing + CUTOFF_CHECK_ESTIMATE
    return {"listing": listing, "cutoff_check": CUTOFF_CHECK_ESTIMATE, "total": total, "cap": params.request_cap}


def _games_table(store: NflStore) -> list[dict[str, Any]]:
    by_game: dict[str, dict[str, Any]] = defaultdict(lambda: {"types": Counter(), "markets": 0, "settled": 0, "complete": 0, "candles": 0, "errors": 0})
    for m in store.markets():
        g = by_game[m["game_key"]]
        g["types"][m["market_type"]] += 1
        g["markets"] += 1
        g["settled"] += 1 if m["status"] in ("settled", "finalized") else 0
        g["complete"] += m["complete"]
        g["candles"] += m["candle_count"]
        g["errors"] += 1 if m["last_error"] else 0
    rows = []
    for game in store.games():
        agg = by_game.get(game["game_key"], {"types": Counter(), "markets": 0, "settled": 0, "complete": 0, "candles": 0, "errors": 0})
        rows.append(
            {
                "game_key": game["game_key"],
                "title": game["title"],
                "week": game["week"],
                "kickoff_utc": iso(game["kickoff_ts"]),
                "kickoff_source": game["kickoff_source"],
                "game_markets": agg["types"].get("Game winner", 0),
                "spread_markets": agg["types"].get("Spread", 0),
                "total_markets": agg["types"].get("Total points", 0),
                "markets": agg["markets"],
                "settled": agg["settled"],
                "complete": agg["complete"],
                "candles": agg["candles"],
                "errors": agg["errors"],
            }
        )
    return rows


@router.get("/state")
def get_state(services: Services = Depends(get_services)) -> dict[str, Any]:
    """Everything stored so far (no requests are sent)."""
    store = get_store(services)
    backend = ROOT_DIR / "backend"
    command = f"cd {backend} && .venv/bin/python -m app.task3.backfill"
    return {
        "defaults": {
            "inventory": InventoryParams().model_dump(mode="json"),
            "backfill": BackfillParams().model_dump(mode="json"),
        },
        "series": SERIES,
        "checkpoints": [c for c, _ in CHECKPOINTS],
        "sizes": SIZES,
        "totals": store.totals(),
        "inventory": store.get_meta("inventory"),
        "cutoff": store.get_meta("cutoff"),
        "cutoff_check": store.get_meta("cutoff_check"),
        "fees": store.get_meta("fees"),
        "last_run": store.get_meta("last_run"),
        "next_backfill_requests": estimate_candle_requests(store),
        "games": _games_table(store),
        "storage": {"folder": str(store.root), "database": str(store.path), "raw": str(store.raw_dir)},
        "daily": {
            "command": command,
            "cron": f"15 9 * * * {command} >> {store.root / 'backfill.log'} 2>&1",
        },
    }


@router.post("/inventory/plan")
def plan_inventory(params: InventoryParams) -> dict[str, Any]:
    """Request estimate for the listing job (no requests are sent)."""
    return {"estimate": _listing_estimate(params)}


def _hooks(ctx: JobContext) -> Hooks:
    return Hooks(log=lambda m, level="info": ctx.log(m, level), progress=ctx.progress, check_cancelled=ctx.check_cancelled)


@router.post("/inventory/run")
async def run_inventory(params: InventoryParams, services: Services = Depends(get_services)) -> dict[str, str]:
    """Job: list games, events and markets, fee settings, then the cutoff check."""
    store = get_store(services)

    async def runner(ctx: JobContext) -> dict[str, Any]:
        fetcher = Fetcher(services.client, store, job_id=ctx.id)
        hooks = _hooks(ctx)
        try:
            with run_lock(store):
                inventory = await refresh_inventory(fetcher, store, params.start_date, params.series, hooks)
                ctx.save_partial({"inventory": inventory})
                check = await cutoff_check(fetcher, store, hooks)
        except BackfillBusy as exc:
            raise ReconError(str(exc)) from None
        except BudgetExhausted:
            raise ReconError("Reached the request cap before the listing finished. Raise the cap and run again.") from None
        return {"inventory": inventory, "cutoff_check": check, "requests": fetcher.sent}

    job_id = services.jobs.start(MODULE, "inventory", params.model_dump(mode="json"), runner, max_requests=params.request_cap)
    return {"job_id": job_id}


@router.post("/backfill/plan")
def plan_backfill(params: BackfillParams, services: Services = Depends(get_services)) -> dict[str, Any]:
    """Exact number of candle requests for the markets not fully stored yet (no requests are sent)."""
    store = get_store(services)
    if store.totals()["markets"] == 0:
        raise HTTPException(status_code=409, detail="List the games first: no markets are stored yet.")
    candles = estimate_candle_requests(store)
    return {"estimate": {"candles": candles, "total": candles, "cap": max(params.request_cap, 1)}}


@router.post("/backfill/run")
async def run_backfill(params: BackfillParams, services: Services = Depends(get_services)) -> dict[str, str]:
    """Job: fetch missing 1-minute candles, then recompute costs and the quality check."""
    store = get_store(services)
    if store.totals()["markets"] == 0:
        raise HTTPException(status_code=409, detail="List the games first: no markets are stored yet.")

    async def runner(ctx: JobContext) -> dict[str, Any]:
        fetcher = Fetcher(services.client, store, job_id=ctx.id, cap=params.request_cap)
        started = int(time.time())
        try:
            with run_lock(store):
                candles = await backfill_candles(fetcher, store, _hooks(ctx))
                ctx.save_partial({"candles": candles})
                ctx.progress(1, 1, "Computing costs and the quality check")
                analysis = await asyncio.to_thread(run_analysis, store, AnalysisParams(fee_rounding=params.fee_rounding))
        except BackfillBusy as exc:
            raise ReconError(str(exc)) from None
        store.set_meta(
            "last_run",
            {"source": "app", "started_at": started, "finished_at": int(time.time()), "requests": fetcher.sent, "candles": candles},
        )
        ctx.log(f"Costs computed from {analysis['counts']['quotes_ok']:,} quotes in {analysis['seconds']} s.")
        return {"candles": candles, "requests": fetcher.sent, "analysis_counts": analysis["counts"]}

    job_id = services.jobs.start(MODULE, "backfill", params.model_dump(mode="json"), runner, max_requests=params.request_cap + 20)
    return {"job_id": job_id}


@router.post("/analyze")
def analyze(params: AnalysisParams, services: Services = Depends(get_services)) -> dict[str, Any]:
    """Recompute costs, results and the quality check from stored candles (no requests)."""
    return run_analysis(get_store(services), params)


@router.get("/results")
def latest_results(services: Services = Depends(get_services)) -> dict[str, Any] | None:
    """Latest stored cost calculation."""
    latest = get_store(services).latest_analysis()
    return latest["result"] if latest is not None else None


@router.get("/exports/{name}")
def export_file(name: str, services: Services = Depends(get_services)) -> FileResponse:
    """Per-quote and per-bet CSV files written by the latest calculation."""
    path = get_store(services).root / "exports" / name
    if name not in EXPORT_FILES or not path.is_file():
        raise HTTPException(status_code=404, detail="No such export yet. Run the backfill or recompute first.")
    return FileResponse(path, media_type="text/csv", filename=name)
