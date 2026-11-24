"""In-game analysis page: results per season, and a button to recompute them locally.

No Kalshi requests: it reads the saved trades (``make trade-sizes``) and the Task 3 candles.

- ``GET /api/ingame/results``: every season's results and checks (None before the first run).
- ``POST /api/ingame/run``: recompute for 2025 and 2026 (cached per market, so reruns are quick).
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException

from app.ingame import analysis
from app.task4.common import SEASONS

router = APIRouter(prefix="/api/ingame", tags=["In-game analysis"])
OUT_DIR = analysis.OUT_DIR
_lock = threading.Lock()


@router.get("/results")
def results() -> dict[str, Any] | None:
    seasons = []
    for season in SEASONS:
        path = OUT_DIR / str(season) / "results.json"
        if path.exists():
            seasons.append(json.loads(path.read_text()))
    if not seasons:
        return None
    return {"generated_at": max(s["generated_at"] for s in seasons), "seasons": seasons}


def _run() -> dict[str, Any]:
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, "An in-game run is already in progress.")
    try:
        started = time.monotonic()
        out = []
        for season in SEASONS:
            r = analysis.analyze(season, out_dir=OUT_DIR)
            out.append({"season": season, "games": r["games"], "has_trades": r["has_trades"],
                        "checks_failed": sum(c["status"] == "fail" for c in r["checks"])})
        return {"seasons": out, "seconds": round(time.monotonic() - started, 1)}
    finally:
        _lock.release()


@router.post("/run")
async def run() -> dict[str, Any]:
    return await asyncio.to_thread(_run)
