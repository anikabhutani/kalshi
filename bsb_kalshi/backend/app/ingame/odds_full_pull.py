"""Every in-game DraftKings and FanDuel moneyline snapshot for every NFL game, 2025 and 2026, as one CSV.

What it does
1. Game windows from nflverse play-by-play (downloaded, no key): first to last play wall-clock time of every
   game (regular season and playoffs).
2. Every 5-minute mark inside any window (one call returns every game live at that moment, so overlapping
   games share calls). Historical snapshots land ~37 s after each 5-minute mark, so each mark is requested
   at mark + 4 min, which returns the snapshot taken just after the mark.
3. One historical call per mark: sport americanfootball_nfl, markets=h2h, bookmakers=draftkings,fanduel,
   oddsFormat=american. Cost = 10 credits per call (2 bookmakers count as one region).
4. Every response is saved raw (data/odds_ingame/nfl/raw/<mark>.json) before anything else, so a stop or
   crash loses nothing: run the same command again and it continues where it stopped.
5. All responses are flattened to data/odds_ingame/nfl/nfl_ingame_odds_2025_2026.csv: one row per
   snapshot x game x bookmaker x team, with every timestamp the API gives (snapshot, bookmaker
   last_update, market last_update), the nflverse game_id, and whether the game was live at the snapshot.

Run on your own machine (needs internet; the key is read from ODDS_API_KEY in the environment or .env and
is never printed):

    cd ~/Downloads/BSB-Kalshi/backend
    .venv/bin/python -m app.ingame.odds_full_pull --dry-run        # counts calls and credits, no API calls
    .venv/bin/python -m app.ingame.odds_full_pull                  # asks for confirmation, then pulls
    .venv/bin/python -m app.ingame.odds_full_pull --csv-only       # rebuild the CSV from saved responses

Options: --seasons 2025 2026, --through 2026-11-09, --max-credits N (stops before spending more),
--keep-credits N (stops when the account would drop below N; default 0).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.task4.common import REPO_ROOT

BASE = "https://api.the-odds-api.com/v4/historical/sports/americanfootball_nfl/odds"
NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{y}.csv.gz"
OUT = REPO_ROOT / "data" / "odds_ingame" / "nfl"
CREDITS_PER_CALL = 10
SLOT = 300
REQUEST_OFFSET = 240          # request at mark + 4 min -> snapshot taken ~37 s after the mark

# Odds API full names -> nflverse codes
TEAMS = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LA", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}


def api_key() -> str:
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        for p in (REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"):
            if p.exists():
                for line in p.read_text().splitlines():
                    if line.strip().startswith("ODDS_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        raise SystemExit("ODDS_API_KEY is not set. Add a line ODDS_API_KEY=... to ~/Downloads/BSB-Kalshi/.env")
    return key


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def game_windows(seasons: list[int], through: str | None) -> pd.DataFrame:
    import httpx

    frames = []
    pbp_dir = OUT / "nflverse"
    pbp_dir.mkdir(parents=True, exist_ok=True)
    for y in seasons:
        path = pbp_dir / f"pbp_{y}.csv.gz"
        r = httpx.get(NFLVERSE.format(y=y), follow_redirects=True, timeout=180)
        r.raise_for_status()
        path.write_bytes(r.content)
        p = pd.read_csv(path, usecols=["game_id", "season", "season_type", "week", "home_team", "away_team",
                                       "game_date", "time_of_day", "start_time"], low_memory=False)
        p["wall"] = pd.to_datetime(p["time_of_day"], utc=True, errors="coerce", format="ISO8601")
        g = p.groupby("game_id").agg(season=("season", "first"), season_type=("season_type", "first"),
                                     week=("week", "first"), home=("home_team", "first"), away=("away_team", "first"),
                                     game_date=("game_date", "first"), first_play=("wall", "min"),
                                     last_play=("wall", "max")).reset_index()
        frames.append(g)
    g = pd.concat(frames, ignore_index=True)
    missing = g["first_play"].isna() | g["last_play"].isna()
    if missing.any():
        print(f"warning: {int(missing.sum())} games have no wall-clock play times and are skipped: "
              f"{', '.join(g.loc[missing, 'game_id'])}")
    g = g[~missing]
    if through:
        g = g[g["game_date"] <= through]
    return g.sort_values("first_play").reset_index(drop=True)


def marks(games: pd.DataFrame) -> list[int]:
    out: set[int] = set()
    for a, b in zip(games["first_play"], games["last_play"]):
        lo, hi = int(a.timestamp()) // SLOT * SLOT, int(b.timestamp()) // SLOT * SLOT
        out.update(range(lo, hi + SLOT, SLOT))
    return sorted(out)


def pull(todo: list[int], key: str, max_credits: int | None, keep_credits: int) -> None:
    import httpx

    raw = OUT / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    spent = 0
    with httpx.Client(timeout=60) as c:
        for i, m in enumerate(todo, 1):
            if max_credits is not None and spent + CREDITS_PER_CALL > max_credits:
                print(f"Stopped: --max-credits {max_credits} reached. Run again to continue.")
                return
            params = {"apiKey": key, "markets": "h2h", "bookmakers": "draftkings,fanduel", "oddsFormat": "american",
                      "dateFormat": "iso", "date": iso(m + REQUEST_OFFSET)}
            r = None
            for attempt in range(5):
                try:
                    r = c.get(BASE, params=params)
                except httpx.HTTPError as exc:
                    wait = 5 * (attempt + 1)
                    print(f"  network error ({type(exc).__name__}), retrying in {wait}s")
                    time.sleep(wait)
                    continue
                if r.status_code == 429:
                    time.sleep(5 * (attempt + 1))
                    continue
                break
            if r is None:
                raise SystemExit(f"No response at {iso(m)} after 5 tries (network). Saved responses are kept; run again.")
            if r.status_code == 401:
                raise SystemExit("The Odds API said 401: the ODDS_API_KEY is wrong or the plan has no historical access.")
            if r.status_code != 200:
                raise SystemExit(f"The Odds API said HTTP {r.status_code} at {iso(m)}: {r.text[:300]}. "
                                 f"Saved responses are kept; run again to continue.")
            body = r.json()
            body["_request"] = {"mark_utc": iso(m), "requested_date": params["date"],
                                "requests_last": r.headers.get("x-requests-last"),
                                "requests_remaining": r.headers.get("x-requests-remaining")}
            (raw / f"{iso(m).replace(':', '')}.json").write_text(json.dumps(body))
            spent += int(r.headers.get("x-requests-last") or CREDITS_PER_CALL)
            remaining = r.headers.get("x-requests-remaining")
            if i % 50 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} calls, {spent:,} credits this run, {remaining} left on the account", flush=True)
            if remaining is not None and float(remaining) - CREDITS_PER_CALL < keep_credits:
                print(f"Stopped: account down to {remaining} credits (--keep-credits {keep_credits}). "
                      f"{len(todo) - i} calls left; run again after topping up.")
                return
            time.sleep(0.25)
    print(f"Pull done: {spent:,} credits this run.")


def build_csv(games: pd.DataFrame) -> Path:
    rows = []
    for p in sorted((OUT / "raw").glob("*.json")):
        body = json.loads(p.read_text())
        req = body.get("_request", {})
        for ev in body.get("data") or []:
            for bk in ev.get("bookmakers") or []:
                for mk in bk.get("markets") or []:
                    for oc in mk.get("outcomes") or []:
                        rows.append({
                            "mark_utc": req.get("mark_utc"), "requested_date_utc": req.get("requested_date"),
                            "snapshot_utc": body.get("timestamp"), "previous_snapshot_utc": body.get("previous_timestamp"),
                            "next_snapshot_utc": body.get("next_timestamp"), "odds_api_event_id": ev.get("id"),
                            "commence_time_utc": ev.get("commence_time"), "home_team": ev.get("home_team"),
                            "away_team": ev.get("away_team"), "bookmaker": bk.get("key"),
                            "bookmaker_last_update_utc": bk.get("last_update"), "market": mk.get("key"),
                            "market_last_update_utc": mk.get("last_update"), "team": oc.get("name"),
                            "american_odds": oc.get("price")})
    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("No saved responses yet.")
    df["home"] = df["home_team"].map(TEAMS)
    df["away"] = df["away_team"].map(TEAMS)
    df["commence"] = pd.to_datetime(df["commence_time_utc"], utc=True)
    df["snap"] = pd.to_datetime(df["snapshot_utc"], utc=True)
    # attach the nflverse game: same teams, kickoff within a day
    g = games[["game_id", "season", "season_type", "week", "home", "away", "first_play", "last_play"]]
    df = df.merge(g, on=["home", "away"], how="left")
    df = df[df["game_id"].isna() | ((df["first_play"] - df["commence"]).abs() <= pd.Timedelta(hours=24))]
    df = df.sort_values("game_id").drop_duplicates(["snapshot_utc", "odds_api_event_id", "bookmaker", "team"])
    df["game_live"] = (df["snap"] >= df["first_play"]) & (df["snap"] <= df["last_play"])
    df["minutes_since_first_play"] = ((df["snap"] - df["first_play"]).dt.total_seconds() / 60).round(1)
    p_ = df["american_odds"].astype(float)
    df["implied_prob"] = (100 / (p_ + 100)).where(p_ > 0, -p_ / (-p_ + 100)).round(6)
    df["bookmaker_age_sec"] = (df["snap"] - pd.to_datetime(df["bookmaker_last_update_utc"], utc=True)).dt.total_seconds()
    df["first_play_utc"] = df["first_play"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    df["last_play_utc"] = df["last_play"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    cols = ["season", "season_type", "week", "game_id", "home", "away", "first_play_utc", "last_play_utc", "game_live",
            "minutes_since_first_play", "mark_utc", "requested_date_utc", "snapshot_utc", "previous_snapshot_utc",
            "next_snapshot_utc", "odds_api_event_id", "commence_time_utc", "home_team", "away_team", "bookmaker",
            "bookmaker_last_update_utc", "bookmaker_age_sec", "market", "market_last_update_utc", "team",
            "american_odds", "implied_prob"]
    df = df[cols].sort_values(["snapshot_utc", "game_id", "bookmaker", "team"])
    path = OUT / "nfl_ingame_odds_2025_2026.csv"
    df.to_csv(path, index=False)
    live = df[df["game_live"]]
    print(f"CSV: {path}\n  {len(df):,} rows ({len(live):,} while the game was live), "
          f"{df['snapshot_utc'].nunique():,} snapshots, {live['game_id'].nunique()} games with live odds, "
          f"{df['game_id'].isna().sum():,} rows for games not in nflverse (e.g. future games listed in a snapshot)")
    cov = live.groupby("bookmaker")["game_id"].nunique().to_dict()
    print(f"  games with live odds by bookmaker: {cov}")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Every in-game NFL moneyline snapshot (DraftKings, FanDuel) to CSV")
    ap.add_argument("--seasons", type=int, nargs="+", default=[2025, 2026])
    ap.add_argument("--through", help="last game date to include, YYYY-MM-DD (default: every game played so far)")
    ap.add_argument("--dry-run", action="store_true", help="count calls and credits only")
    ap.add_argument("--csv-only", action="store_true", help="rebuild the CSV from saved responses, no API calls")
    ap.add_argument("--max-credits", type=int, default=None, help="spend at most this many credits this run")
    ap.add_argument("--keep-credits", type=int, default=0, help="stop before the account drops below this")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    a = ap.parse_args(argv)

    games = game_windows(a.seasons, a.through)
    all_marks = marks(games)
    done = {p.stem for p in (OUT / "raw").glob("*.json")} if (OUT / "raw").exists() else set()
    todo = [m for m in all_marks if iso(m).replace(":", "") not in done]
    by_season = {int(s): len(marks(x)) for s, x in games.groupby("season")}
    print(f"{len(games)} games ({', '.join(f'{s}: {(games.season == s).sum()}' for s in sorted(by_season))}), "
          f"{games['game_date'].min()} to {games['game_date'].max()}")
    print(f"5-minute in-game marks: {len(all_marks):,} ({', '.join(f'{s}: {n:,}' for s, n in by_season.items())}; "
          f"shared marks counted once overall)")
    print(f"Already saved: {len(all_marks) - len(todo):,}. To pull: {len(todo):,} calls = "
          f"{len(todo) * CREDITS_PER_CALL:,} credits.")
    if a.csv_only:
        build_csv(games)
        return 0
    if a.dry_run or not todo:
        if not todo and not a.dry_run:
            build_csv(games)
        return 0
    key = api_key()
    if not a.yes:
        ans = input(f"Spend up to {len(todo) * CREDITS_PER_CALL:,} credits? [y/N] ").strip().lower()
        if ans != "y":
            print("Nothing pulled.")
            return 0
    pull(todo, key, a.max_credits, a.keep_credits)
    build_csv(games)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
