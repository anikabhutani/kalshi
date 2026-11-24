"""Backfill sportsbook odds snapshots for every NFL game this season.

Sources
-------
``file`` (default, the only one that works today): an export from ``odds_history_pull.py``,
either the ``odds_data.zip`` it produces or the ``history_americanfootball_nfl.csv`` inside it.
Books: DraftKings, FanDuel, Pinnacle. Markets: moneyline (h2h), spreads, totals.

``api`` (placeholder): The Odds API historical endpoint. Not implemented. It needs an
``ODDS_API_KEY`` in ``.env`` and a paid plan; see :func:`fetch_from_api`.

What a run does (safe to repeat; this is the daily update)
----------------------------------------------------------
1. Reads every snapshot from the source and keeps NFL games kicking off on or after the start
   of the first season in ``common.SEASONS`` (2025) and before the newest snapshot in the source
   (games that have been played). Each game is tagged with its season.
2. Skips games already marked complete in ``data/task4/manifest.json``. A game is complete once
   it has kicked off and the source has a snapshot from the last 60 minutes before kickoff.
   Anything else is saved but stays "partial" and is fetched again on the next run.
3. Saves each new game's raw rows, unchanged, to ``data/task4/raw/<event_id>.csv.gz``.
4. Rebuilds ``data/task4/snapshots.csv.gz`` (all saved games) and ``data/task4/games.csv``
   (one row per game: week, kickoff, teams, and which books posted each market).

Command line::

    cd backend && .venv/bin/python -m app.task4.sportsbook_backfill --path ~/Downloads/odds_data.zip
    cd backend && .venv/bin/python -m app.task4.sportsbook_backfill           # reuse last --path
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.task4.common import (
    BOOKS,
    DATA_DIR,
    GAMES,
    MANIFEST,
    MARKETS,
    RAW_DIR,
    SNAPSHOTS,
    SPORT,
    nfl_season,
    nfl_week,
    week_label,
    parse_times,
    season_start_utc,
)

HISTORY_NAME = f"history_{SPORT}.csv"
COMPLETE_WINDOW_MIN = 60
EXPECTED_COLUMNS = {
    "snapshot_ts", "snapshot_type", "sport", "event_id", "commence_time", "home_team",
    "away_team", "bookmaker", "book_last_update", "market", "market_last_update", "outcome",
    "point", "price_american", "price_decimal", "implied_prob",
}


class ApiNotConfigured(RuntimeError):
    pass


# --------------------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------------------


def read_source_file(path: Path) -> pd.DataFrame:
    """Read the NFL history CSV from a zip export or a bare CSV. Values are kept as text."""
    if not path.exists():
        raise FileNotFoundError(f"source file not found: {path}")
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist()
                     if n.endswith(HISTORY_NAME) and not n.startswith("__MACOSX")]
            if not names:
                raise ValueError(f"{path} has no {HISTORY_NAME}")
            text = zf.read(names[0]).decode("utf-8")
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    else:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = EXPECTED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"source is missing columns: {sorted(missing)}")
    return df


def fetch_from_api(since: datetime, until: datetime) -> pd.DataFrame:  # pragma: no cover
    """PLACEHOLDER for The Odds API historical endpoint.

    To implement when a key is available:
    - read ``ODDS_API_KEY`` from the environment (``.env``), never from code or chat;
    - list events per day with the historical events endpoint for ``americanfootball_nfl``;
    - for each event and snapshot time, request historical event odds with
      ``bookmakers=draftkings,fanduel,pinnacle`` and ``markets=h2h,spreads,totals``,
      ``oddsFormat=american``;
    - return rows with exactly the columns in ``EXPECTED_COLUMNS`` so the rest of this
      pipeline is unchanged;
    - check the plan's credit cost per request before running a full season.
    """
    if not os.environ.get("ODDS_API_KEY"):
        raise ApiNotConfigured(
            "ODDS_API_KEY is not set. Use --source file --path <odds_data.zip> for now."
        )
    raise NotImplementedError("The Odds API source is a placeholder; use --source file.")


# --------------------------------------------------------------------------------------
# Manifest and raw storage
# --------------------------------------------------------------------------------------


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {"source_path": None, "games": {}}


def save_manifest(manifest: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    tmp.replace(MANIFEST)


@dataclass
class RunSummary:
    in_source: int = 0
    played: int = 0
    skipped_complete: int = 0
    saved_complete: int = 0
    saved_partial: int = 0
    not_played_yet: int = 0


def select_played_games(raw: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
    """NFL rows for games kicking off between the season start and ``as_of``."""
    df = raw[raw["sport"] == SPORT]
    kick = pd.to_datetime(df["commence_time"], utc=True, format="mixed")
    keep = (kick >= pd.Timestamp(season_start_utc())) & (kick <= pd.Timestamp(as_of))
    return df[keep]


def _add_missing_seasons(manifest: dict) -> None:
    """Manifests written before seasons existed have no ``season``; derive it from the kickoff."""
    for entry in manifest.get("games", {}).values():
        if entry.get("season") is None and entry.get("kickoff"):
            kick = pd.to_datetime(pd.Series([entry["kickoff"]]), utc=True, format="mixed")
            entry["season"] = int(nfl_season(kick).iloc[0])


def game_is_complete(rows: pd.DataFrame) -> bool:
    t = parse_times(rows[["snapshot_ts", "commence_time"]])
    mins = (t["commence_time"] - t["snapshot_ts"]).dt.total_seconds() / 60
    return bool(((mins >= 0) & (mins <= COMPLETE_WINDOW_MIN)).any())


def backfill(raw: pd.DataFrame, source: str, as_of: datetime | None = None) -> RunSummary:
    """Save new or still-partial games. Returns counts for the run log."""
    if as_of is None:
        as_of = pd.to_datetime(raw["snapshot_ts"], utc=True, format="mixed").max().to_pydatetime()
    manifest = load_manifest()
    _add_missing_seasons(manifest)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    summary = RunSummary(in_source=raw.loc[raw["sport"] == SPORT, "event_id"].nunique())
    played = select_played_games(raw, as_of)
    summary.played = played["event_id"].nunique()
    upcoming = raw[(raw["sport"] == SPORT) & ~raw["event_id"].isin(played["event_id"])]
    summary.not_played_yet = upcoming["event_id"].nunique()

    for event_id, rows in played.groupby("event_id", sort=False):
        entry = manifest["games"].get(event_id)
        if entry and entry.get("status") == "complete":
            summary.skipped_complete += 1
            continue
        rows = rows.sort_values(["snapshot_ts", "bookmaker", "market", "outcome"])
        rows.to_csv(RAW_DIR / f"{event_id}.csv.gz", index=False, compression="gzip")
        complete = game_is_complete(rows)
        kick = pd.to_datetime(rows["commence_time"].iloc[:1], utc=True, format="mixed")
        manifest["games"][event_id] = {
            "season": int(nfl_season(kick).iloc[0]),
            "kickoff": rows["commence_time"].iloc[0],
            "home_team": rows["home_team"].iloc[0],
            "away_team": rows["away_team"].iloc[0],
            "rows": int(len(rows)),
            "status": "complete" if complete else "partial",
            "source": source,
            "saved_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        if complete:
            summary.saved_complete += 1
        else:
            summary.saved_partial += 1

    manifest["last_run"] = datetime.now(UTC).isoformat(timespec="seconds")
    manifest["source_as_of"] = pd.Timestamp(as_of).isoformat()
    save_manifest(manifest)
    rebuild_outputs(manifest)
    return summary


# --------------------------------------------------------------------------------------
# Combined outputs
# --------------------------------------------------------------------------------------


def load_saved_snapshots(manifest: dict | None = None) -> pd.DataFrame:
    manifest = manifest or load_manifest()
    frames = [
        pd.read_csv(RAW_DIR / f"{eid}.csv.gz", dtype=str, keep_default_na=False)
        for eid in manifest["games"]
        if (RAW_DIR / f"{eid}.csv.gz").exists()
    ]
    if not frames:
        return pd.DataFrame(columns=sorted(EXPECTED_COLUMNS))
    return pd.concat(frames, ignore_index=True)


def build_games_table(snapshots: pd.DataFrame) -> pd.DataFrame:
    """One row per game with week, kickoff and whether each book posted each market pre-game."""
    s = parse_times(snapshots)
    pre = s[s["snapshot_ts"] <= s["commence_time"]]
    games = (
        # the provider's final start time: the last snapshot's (see sportsbook_costs.prepare)
        s.sort_values("snapshot_ts").drop_duplicates("event_id", keep="last")[
            ["event_id", "commence_time", "home_team", "away_team"]]
        .sort_values("commence_time")
        .reset_index(drop=True)
    )
    games.insert(1, "season", nfl_season(games["commence_time"]))
    games.insert(2, "week", nfl_week(games["commence_time"]))
    games.insert(3, "week_label", games["week"].map(week_label))
    games["kickoff_et"] = (
        games["commence_time"].dt.tz_convert("America/New_York").dt.strftime("%a %b %d, %Y %I:%M %p")
    )
    posted = pre.groupby(["event_id", "bookmaker", "market"]).size()
    for book in BOOKS:
        for market in MARKETS:
            col = f"{book} {market}"
            games[col] = [
                "yes" if (eid, book, market) in posted.index else "no" for eid in games["event_id"]
            ]
    games["books_posting_all_3_markets"] = [
        sum(all(row[f"{b} {m}"] == "yes" for m in MARKETS) for b in BOOKS)
        for _, row in games.iterrows()
    ]
    games["commence_time"] = games["commence_time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return games


def rebuild_outputs(manifest: dict) -> None:
    snaps = load_saved_snapshots(manifest)
    snaps.to_csv(SNAPSHOTS, index=False, compression="gzip")
    build_games_table(snaps).to_csv(GAMES, index=False)


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill NFL sportsbook odds snapshots.")
    parser.add_argument("--source", choices=["file", "api"], default="file")
    parser.add_argument("--path", type=Path, help="odds_data.zip or history_americanfootball_nfl.csv")
    args = parser.parse_args(argv)

    manifest = load_manifest()
    if args.source == "api":
        try:
            raw = fetch_from_api(season_start_utc(), datetime.now(UTC))
        except (ApiNotConfigured, NotImplementedError) as exc:
            print(f"api source unavailable: {exc}", file=sys.stderr)
            return 2
        source = "the-odds-api"
    else:
        path = args.path or (Path(manifest["source_path"]) if manifest.get("source_path") else None)
        if path is None:
            print("no --path given and no previous source recorded", file=sys.stderr)
            return 2
        path = path.expanduser().resolve()
        raw = read_source_file(path)
        manifest["source_path"] = str(path)
        save_manifest(manifest)
        source = f"file:{path.name}"

    s = backfill(raw, source)
    print(
        f"games in source: {s.in_source} | played: {s.played} | not played yet: {s.not_played_yet}\n"
        f"already complete (skipped): {s.skipped_complete} | saved complete: {s.saved_complete} "
        f"| saved partial: {s.saved_partial}\n"
        f"raw: {RAW_DIR}\ngames list: {GAMES}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
