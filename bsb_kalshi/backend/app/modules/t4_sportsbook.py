"""Task 4: sportsbook (DraftKings, FanDuel, Pinnacle) vig and cost per $10 for every NFL game.

No Kalshi requests. Everything runs locally on an odds export file:
- ``GET /state``: where the source file is, how many games are saved, last run.
- ``POST /run``: backfill new games from the file (raw saved per game), then recompute the
  costs, quality check, results tables and charts.
- ``GET /results``: per season (2025, 2026): the result tables, the facts the page text is built
  from, and the self-checks.
- ``GET /exports/{season}/{name}``: any result CSV of a season.

The same steps run from the command line once a day: ``scripts/task4_daily.sh``.
"""

from __future__ import annotations

import asyncio
import json
import math
import threading
import time
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.task4 import sportsbook_backfill as bf
from app.task4 import sportsbook_report as report
from app.task4.common import BOOKS, GAMES, MANIFEST, RAW_DIR, RESULTS_DIR, SEASONS

router = APIRouter(prefix="/api/t4", tags=["Task 4 sportsbook costs"])

RESULT_TABLES = (
    "by_book_market", "by_price_group", "by_week", "by_time_to_kickoff",
    "favorites_longshots", "qc_summary",
)
EXPORTS = frozenset({
    *(f"{t}.csv" for t in RESULT_TABLES),
    "qc_issues.csv", "costs_all_snapshots.csv", "costs_all_sides.csv", "summary.md",
    "kalshi_all_strikes.csv", "checks.json", "facts.json",
})


def _index() -> Path:
    return RESULTS_DIR / "index.json"
_lock = threading.Lock()


class RunParams(BaseModel):
    """Path to odds_data.zip or history_americanfootball_nfl.csv. Empty = reuse the last one."""

    path: str | None = None


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    out = json.loads(df.to_json(orient="records", date_format="iso"))
    return [{k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r.items()} for r in out]


@router.get("/state")
def get_state() -> dict[str, Any]:
    manifest = bf.load_manifest()
    games = manifest.get("games", {})
    statuses = [g.get("status") for g in games.values()]
    index = json.loads(_index().read_text()) if _index().exists() else {}
    return {
        "source_path": manifest.get("source_path"),
        "source_as_of": manifest.get("source_as_of"),
        "last_run": manifest.get("last_run"),
        "games_saved": len(games),
        "games_complete": statuses.count("complete"),
        "games_partial": statuses.count("partial"),
        "games_by_season": {str(s): sum(g.get("season") == s for g in games.values()) for s in SEASONS},
        "raw_dir": str(RAW_DIR),
        "results_at": index.get("generated_at"),
        "api_source": "placeholder (The Odds API not implemented; no key)",
        "books": list(BOOKS),
    }


def _run(path: str | None) -> dict[str, Any]:
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, "A Task 4 run is already in progress.")
    try:
        started = time.monotonic()
        manifest = bf.load_manifest()
        src = Path(path).expanduser() if path else (
            Path(manifest["source_path"]) if manifest.get("source_path") else None)
        if src is None:
            raise HTTPException(400, "Give the path to odds_data.zip on this computer.")
        src = src.resolve()
        try:
            raw = bf.read_source_file(src)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        manifest["source_path"] = str(src)
        bf.save_manifest(manifest)
        summary = bf.backfill(raw, f"file:{src.name}")
        report.main()
        index = json.loads(_index().read_text()) if _index().exists() else {}
        return {"backfill": summary.__dict__, "seasons": index.get("seasons", []),
                "seconds": round(time.monotonic() - started, 1)}
    finally:
        _lock.release()


@router.post("/run")
async def run(params: RunParams) -> dict[str, Any]:
    return await asyncio.to_thread(_run, params.path)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    try:
        return _records(pd.read_csv(path)) if path.exists() else []
    except pd.errors.EmptyDataError:
        return []


def _season(season: int, games: pd.DataFrame) -> dict[str, Any] | None:
    folder = RESULTS_DIR / str(season)
    if not (folder / "facts.json").exists():
        return None
    out: dict[str, Any] = {name: _read_csv(folder / f"{name}.csv") for name in RESULT_TABLES}
    out["season"] = season
    out["facts"] = json.loads((folder / "facts.json").read_text())
    out["checks"] = json.loads((folder / "checks.json").read_text()) if (folder / "checks.json").exists() else []
    out["kalshi_info"] = out["facts"].get("kalshi", {"available": False})
    out["kalshi_all_strikes"] = _read_csv(folder / "kalshi_all_strikes.csv")
    out["games"] = _records(games[games["season"] == season]) if "season" in games else []
    qc = folder / "qc_issues.csv"
    out["qc_examples"] = _records(pd.read_csv(qc).groupby("check").head(5)) if qc.exists() else []
    return out


@router.get("/results")
def results() -> dict[str, Any] | None:
    if not _index().exists() or not MANIFEST.exists():
        return None
    games = pd.read_csv(GAMES) if GAMES.exists() else pd.DataFrame()
    seasons = [s for s in (_season(season, games) for season in SEASONS) if s is not None]
    if not seasons:
        return None
    return {"generated_at": json.loads(_index().read_text()).get("generated_at"), "seasons": seasons}


@router.get("/exports/{season}/{name}")
def export_file(season: int, name: str) -> FileResponse:
    if name not in EXPORTS or season not in SEASONS:
        raise HTTPException(404, "Unknown export")
    path = RESULTS_DIR / str(season) / name
    if not path.exists():
        raise HTTPException(404, "Run Task 4 first")
    media = "text/markdown" if name.endswith(".md") else (
        "application/json" if name.endswith(".json") else "text/csv")
    return FileResponse(path, media_type=media, filename=f"task4_{season}_{name}")
