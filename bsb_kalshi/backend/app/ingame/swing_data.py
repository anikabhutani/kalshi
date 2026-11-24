"""Inputs for the in-game swing study (Task 7 Part 1): Kalshi 1-minute candles and college play-by-play.

Everything lands in ``data/ingame/<league>/<season>/``:

- ``candles/<event_ticker>.csv.gz``: 1-minute candles for both team markets of one Kalshi game event,
  from 06:00 Eastern on the ticker date to 12:00 UTC the next day (covers every kickoff slot).
  Columns ``ticker, ts, bid, ask, volume, price, oi``; prices in cents, ``ts`` = end of the minute
  (Unix seconds). Kalshi only writes a candle when something changed, so a missing minute means the
  quote did not change.
- ``events.csv``: every Kalshi KXNCAAFGAME event of the season (ticker, date, both team markets).
- ``cfbd/games.json``, ``cfbd/plays_<seasonType>_<week>.json``, ``cfbd/wp/<game_id>.json``:
  CollegeFootballData responses, saved as returned.

Reuse first: ``extract-zip`` copies candles out of Theo's Task 5 raw pull
(``data/kalshi_raw_2026_college_ncaaf.zip``). ``pull`` then asks Kalshi only for events that have no
candle file yet, and CollegeFootballData for games, plays and win probability.

NFL::

    cd backend && .venv/bin/python -m app.ingame.swing_data export-task3   # from data/task3/nfl_costs.db
    cd backend && .venv/bin/python -m app.ingame.swing_data fill-nfl-zip   # 2025 games missing from Task 3

College, on your own machine (needs internet, your Kalshi key and ``CFBD_API_KEY`` in .env)::

    cd backend && .venv/bin/python -m app.ingame.swing_data pull --season 2026
    cd backend && .venv/bin/python -m app.ingame.swing_data extract-zip --season 2026   # container only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from app.task4.common import EASTERN, REPO_ROOT

DATA = REPO_ROOT / "data"
SERIES = "KXNCAAFGAME"
CANDLE_COLS = ["ticker", "ts", "bid", "ask", "volume", "price", "oi"]
TICKER_DATE = re.compile(r"^KX[A-Z]+-(\d{2})([A-Z]{3})(\d{2})")
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP",
                                       "OCT", "NOV", "DEC"], 1)}
CFBD = "https://api.collegefootballdata.com"
MAX_CANDLES = 10_000


def out_dir(season: int, league: str = "ncaaf") -> Path:
    return DATA / "ingame" / league / str(season)


def ticker_date(ticker: str) -> date | None:
    m = TICKER_DATE.match(ticker)
    if not m or m.group(2) not in MONTHS:
        return None
    return date(2000 + int(m.group(1)), MONTHS[m.group(2)], int(m.group(3)))


def window(d: date) -> tuple[int, int]:
    """06:00 Eastern on the ticker date to 12:00 UTC the next day, Unix seconds."""
    start = datetime(d.year, d.month, d.day, 6, tzinfo=EASTERN).astimezone(UTC)
    end = datetime(d.year, d.month, d.day, 12, tzinfo=UTC) + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())


def _cents(side: dict[str, Any] | None) -> float | None:
    if not side:
        return None
    v = side.get("close_dollars", side.get("close"))   # both are dollars ("0.7600")
    return None if v is None else round(float(v) * 100, 4)


def candle_rows(ticker: str, candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for c in candles:
        price = c.get("price") or {}
        p = price.get("close_dollars", price.get("close"))
        rows.append({"ticker": ticker, "ts": int(c["end_period_ts"]), "bid": _cents(c.get("yes_bid")),
                     "ask": _cents(c.get("yes_ask")),
                     "volume": float(c.get("volume_fp", c.get("volume", 0)) or 0),
                     "price": None if p is None else round(float(p) * 100, 4),
                     "oi": float(c.get("open_interest_fp", c.get("open_interest", 0)) or 0)})
    return rows


def save_event(path: Path, rows: list[dict[str, Any]]) -> int:
    df = pd.DataFrame(rows, columns=CANDLE_COLS)
    if not df.empty:
        df = df.drop_duplicates(["ticker", "ts"], keep="last").sort_values(["ticker", "ts"])
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, compression="gzip")
    return len(df)


# --------------------------------------------------------------------------------------
# Reuse: Theo's raw pull
# --------------------------------------------------------------------------------------

def events_from_discovery(z: zipfile.ZipFile) -> pd.DataFrame:
    rows = []
    for name in sorted(n for n in z.namelist() if re.search(rf"discovery/events_{SERIES}_p\d+\.json$", n)):
        body = json.loads(z.read(name))
        for ev in body.get("events") or []:
            rows.append(event_row(ev))
    return pd.DataFrame(rows).drop_duplicates("event_ticker") if rows else pd.DataFrame()


def event_row(ev: dict[str, Any]) -> dict[str, Any]:
    mk = ev.get("markets") or []
    d = ticker_date(ev.get("event_ticker", ""))
    return {"event_ticker": ev.get("event_ticker"), "ticker_date": d.isoformat() if d else None,
            "title": ev.get("title"), "sub_title": ev.get("sub_title"),
            "tickers": "|".join(m.get("ticker", "") for m in mk),
            "team_names": "|".join((m.get("yes_sub_title") or m.get("subtitle") or "") for m in mk),
            "result": "|".join((m.get("result") or "") for m in mk)}


def extract_zip(season: int, zpath: Path) -> int:
    out = out_dir(season)
    z = zipfile.ZipFile(zpath)
    events = events_from_discovery(z)
    if not events.empty:
        out.mkdir(parents=True, exist_ok=True)
        events.to_csv(out / "events_from_zip.csv", index=False)
    by_event: dict[str, list[str]] = {}
    for n in z.namelist():
        parts = n.split("/")
        if len(parts) == 4 and parts[1] == "candles" and parts[3].endswith(".json") and parts[2].startswith(SERIES):
            by_event.setdefault(parts[2], []).append(n)
    done = 0
    for ev, names in sorted(by_event.items()):
        d = ticker_date(ev)
        if d is None:
            continue
        lo, hi = window(d)
        rows: list[dict[str, Any]] = []
        for n in names:
            start = int(n.rsplit("__", 1)[1].split(".")[0])
            if start > hi or start + 300_000 < lo:   # chunk outside the window
                continue
            body = json.loads(z.read(n))
            for m in body.get("markets") or []:
                rows += [r for r in candle_rows(m.get("market_ticker") or m.get("ticker"), m.get("candlesticks") or [])
                         if lo <= r["ts"] <= hi]
        save_event(out / "candles" / f"{ev}.csv.gz", rows)
        done += 1
    print(f"Extracted in-game candles for {done} events into {out / 'candles'}")
    return 0


# --------------------------------------------------------------------------------------
# Kalshi: events list and missing candles (read-only GETs through the project's client)
# --------------------------------------------------------------------------------------

async def pull_kalshi(season: int, today: date, max_requests: int | None) -> int:
    from app.alignment.trade_sizes import Stopped, client_getter
    from app.config import get_settings
    from app.db import Database
    from app.evidence import EvidenceLog
    from app.kalshi_client import KalshiClient, TokenBucket
    from app.settings_store import SettingsStore
    from app.spec_loader import OpenApiSpec
    from app.task3.backfill import _NoJobs

    config = get_settings()
    db = Database(config.db_path)
    spec = OpenApiSpec.load(config.specs_dir / "openapi.yaml")
    settings = SettingsStore(db, config, spec)
    secrets = [config.kalshi_key_id.get_secret_value()] if config.kalshi_key_id else []
    evidence = EvidenceLog(db, config.raw_dir, secrets)
    cur = settings.get()
    client = KalshiClient(config, spec, settings, evidence, _NoJobs(), TokenBucket(min(cur.rate_limit_rps, 8.0),
                                                                                  cur.rate_limit_burst))
    get = client_getter(client)
    out = out_dir(season)
    requests = 0
    try:
        # 1. every game market of the series closed this season, grouped into events (two team markets
        #    each). Markets archived past Kalshi's historical cutoff drop out of /markets, so the events
        #    already listed in the raw pull's discovery files are kept too.
        season_start = int(datetime(season, 8, 1, tzinfo=UTC).timestamp())
        mk_rows, cursor = [], None
        while True:
            params: dict[str, Any] = {"series_ticker": SERIES, "limit": 1000, "min_close_ts": season_start}
            if cursor:
                params["cursor"] = cursor
            body = await get("/markets", params)
            requests += 1
            mk_rows += [m for m in (body or {}).get("markets") or []
                        if str(m.get("event_ticker", "")).startswith(SERIES)]
            cursor = (body or {}).get("cursor")
            if not cursor:
                break
        rows = []
        for et, ms in pd.DataFrame(mk_rows).groupby("event_ticker") if mk_rows else []:
            rows.append(event_row({"event_ticker": et, "title": ms["title"].iloc[0] if "title" in ms else None,
                                   "markets": ms.to_dict("records")}))
        events = pd.DataFrame(rows)
        zip_events = out / "events_from_zip.csv"
        if zip_events.exists():
            events = pd.concat([events, pd.read_csv(zip_events)]).drop_duplicates("event_ticker")
        events = events[events["ticker_date"].notna()]
        events = events[(pd.to_datetime(events["ticker_date"]).dt.year == season)
                        & (pd.to_datetime(events["ticker_date"]).dt.date < today)]
        out.mkdir(parents=True, exist_ok=True)
        events.sort_values("event_ticker").to_csv(out / "events.csv", index=False)
        print(f"{len(events)} {SERIES} events in {season} before {today}", flush=True)

        # 2. candles for events without a file yet, batched by date (same window per date)
        todo = events[[not (out / "candles" / f"{e}.csv.gz").exists() for e in events["event_ticker"]]]
        print(f"{len(todo)} events need candles ({len(events) - len(todo)} already have a file)", flush=True)
        for d, grp in todo.groupby("ticker_date"):
            lo, hi = window(date.fromisoformat(d))
            per_market = (hi - lo) // 60 + 1
            size = max(1, min(100, MAX_CANDLES // per_market))
            pairs = [(e, t) for e, ts in zip(grp["event_ticker"], grp["tickers"]) for t in str(ts).split("|") if t]
            got: dict[str, list[dict[str, Any]]] = {e: [] for e in grp["event_ticker"]}
            for i in range(0, len(pairs), size):
                chunk = pairs[i:i + size]
                if max_requests is not None and requests >= max_requests:
                    raise Stopped(f"stopped at --max-requests {max_requests}")
                body = await get("/markets/candlesticks", {"market_tickers": ",".join(t for _, t in chunk),
                                                           "start_ts": lo, "end_ts": hi, "period_interval": 1,
                                                           "include_latest_before_start": "true"})
                requests += 1
                ev_of = dict((t, e) for e, t in chunk)
                for m in (body or {}).get("markets") or []:
                    t = m.get("market_ticker") or m.get("ticker")
                    if t in ev_of:
                        got[ev_of[t]] += candle_rows(t, m.get("candlesticks") or [])
            have = {t for e, r in got.items() for t in {x["ticker"] for x in r}}
            for e, t in pairs:   # archived markets: the historical endpoint, one market per request
                if t in have:
                    continue
                body = await get(f"/historical/markets/{t}/candlesticks",
                                 {"start_ts": lo, "end_ts": hi, "period_interval": 1})
                requests += 1
                got[e] += candle_rows(t, (body or {}).get("candlesticks") or [])
            for e, rows_e in got.items():
                if rows_e:   # an empty answer is not saved, so the next run asks again
                    save_event(out / "candles" / f"{e}.csv.gz", rows_e)
            print(f"  {d}: {len(grp)} events, {sum(1 for r in got.values() if r)} with candles", flush=True)
    except Stopped as exc:
        print(f"Stopped: {exc}. Saved files are kept; run the same command again to continue.", file=sys.stderr)
        return 2
    finally:
        await client.aclose()
    print(f"Kalshi done: {requests} requests.")
    return 0


# --------------------------------------------------------------------------------------
# CollegeFootballData: games, plays (wall clock), win probability
# --------------------------------------------------------------------------------------

def _env_key() -> str | None:
    key = os.environ.get("CFBD_API_KEY")
    if key:
        return key.strip()
    for p in (REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"):
        if p.exists():
            for line in p.read_text().splitlines():
                if line.strip().startswith("CFBD_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


def pull_cfbd(season: int, today: date, wp: bool = True) -> int:
    import httpx

    key = _env_key()
    if not key:
        print("CFBD_API_KEY is not set. Get a free key at https://collegefootballdata.com/key and add "
              "CFBD_API_KEY=... to .env", file=sys.stderr)
        return 2
    out = out_dir(season) / "cfbd"
    (out / "wp").mkdir(parents=True, exist_ok=True)
    calls = 0
    with httpx.Client(base_url=CFBD, headers={"Authorization": f"Bearer {key}", "accept": "application/json"},
                      timeout=120) as c:
        def get(path: str, params: dict[str, Any]) -> Any:
            nonlocal calls
            for attempt in range(3):
                r = c.get(path, params=params)
                calls += 1
                if r.status_code == 429:
                    time.sleep(10 * (attempt + 1))
                    continue
                if r.status_code == 401:
                    raise SystemExit("CollegeFootballData said 401: the CFBD_API_KEY in .env is wrong.")
                r.raise_for_status()
                return r.json()
            r.raise_for_status()

        games = get("/games", {"year": season, "seasonType": "both"})
        (out / "games.json").write_text(json.dumps(games))
        g = pd.json_normalize(games)
        start_col = "startDate" if "startDate" in g.columns else "start_date"
        g["start"] = pd.to_datetime(g[start_col], utc=True)
        g = g[g["start"].dt.date < today]
        st_col = "seasonType" if "seasonType" in g.columns else "season_type"
        print(f"{len(g)} games played before {today}", flush=True)
        for (stype, week), _ in g.groupby([st_col, "week"]):
            path = out / f"plays_{stype}_{int(week)}.json"
            last_game = g[(g[st_col] == stype) & (g["week"] == week)]["start"].max()
            # a week is final once its last game started more than a day ago; re-pull otherwise
            if path.exists() and last_game < pd.Timestamp(datetime.now(UTC) - timedelta(days=1)):
                continue
            plays = []
            for cls in ("fbs", "fcs"):
                try:
                    plays += get("/plays", {"year": season, "week": int(week), "seasonType": stype,
                                            "classification": cls})
                except httpx.HTTPStatusError as exc:
                    print(f"  plays {stype} week {week} {cls}: HTTP {exc.response.status_code}", file=sys.stderr)
            path.write_text(json.dumps(plays))
            print(f"  plays {stype} week {int(week)}: {len(plays)}", flush=True)
        if wp:
            # games with at least one FBS team: the games the Odds API lists and the swing study uses
            hc = next((c for c in ("homeClassification", "home_classification") if c in g.columns), None)
            ac = next((c for c in ("awayClassification", "away_classification") if c in g.columns), None)
            fbs = g if hc is None or ac is None else g[(g[hc] == "fbs") | (g[ac] == "fbs")]
            ids = [int(i) for i in fbs["id"]]
            todo = [i for i in ids if not (out / "wp" / f"{i}.json").exists()]
            print(f"win probability: {len(todo)} games to pull", flush=True)
            for i in todo:
                try:
                    body = get("/metrics/wp", {"gameId": i})
                except httpx.HTTPStatusError:
                    body = []
                (out / "wp" / f"{i}.json").write_text(json.dumps(body))
    print(f"CollegeFootballData done: {calls} calls (free tier allows 1,000 a month).")
    return 0


# --------------------------------------------------------------------------------------
# NFL: export in-game candles from the Task 3 store; fill gaps from the 2025 raw pull
# --------------------------------------------------------------------------------------

TASK3_DB = DATA / "task3" / "nfl_costs.db"
NFL_ZIP = DATA / "kalshi_raw_2025_season_nfl_ncaaf.zip"


def nfl_season(game_key: str) -> int:
    """26JAN25LASEA -> 2025 (January-July games belong to the season that started the year before)."""
    y = 2000 + int(game_key[:2])
    return y - 1 if game_key[2:5] in ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL") else y


def export_task3(db: Path = TASK3_DB, force: bool = False) -> int:
    """KXNFLGAME candles from 1 h before to 6 h after kickoff, per game, plus the game list (Task 3 kickoff
    times). Task 3 prices are in 1/100 cent (0-10000); written here in cents."""
    import sqlite3

    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    g = pd.read_sql("SELECT * FROM games", c)
    m = pd.read_sql("SELECT id, ticker, event_ticker, game_key, yes_sub_title, result FROM markets "
                    "WHERE series_ticker = 'KXNFLGAME'", c)
    g["season"] = g["game_key"].map(nfl_season)
    rows = []
    for _, r in g.iterrows():
        mk = m[m["game_key"] == r["game_key"]]
        if len(mk) != 2 or not r["kickoff_ts"]:
            continue
        lo, hi = int(r["kickoff_ts"]) - 3600, int(r["kickoff_ts"]) + 6 * 3600
        ids = ",".join(str(i) for i in mk["id"])
        cd = pd.read_sql(f"SELECT market_id, ts, bid, ask, last, volume, open_interest FROM candles "
                         f"WHERE market_id IN ({ids}) AND ts BETWEEN {lo} AND {hi}", c)
        rows.append({"season": r["season"], "event_ticker": r["game_event_ticker"], "title": r["title"],
                     "week": r["week"], "season_type": r["season_type"], "kickoff_ts": int(r["kickoff_ts"]),
                     "kickoff_source": r["kickoff_source"], "tickers": "|".join(mk["ticker"]),
                     "team_names": "|".join(mk["yes_sub_title"].fillna("")), "result": "|".join(mk["result"].fillna("")),
                     "candles": len(cd)})
        dest = out_dir(int(r["season"]), "nfl") / "candles" / f"{r['game_event_ticker']}.csv.gz"
        if cd.empty or (dest.exists() and not force):   # existing files may be rebuilt from the raw pull: keep them
            continue
        tk = dict(zip(mk["id"], mk["ticker"]))
        out = pd.DataFrame({"ticker": cd["market_id"].map(tk), "ts": cd["ts"], "bid": cd["bid"] / 100,
                            "ask": cd["ask"] / 100, "volume": cd["volume"], "price": cd["last"] / 100,
                            "oi": cd["open_interest"]})
        save_event(dest, out.to_dict("records"))
    ev = pd.DataFrame(rows)
    for yr, x in ev.groupby("season"):
        out_dir(int(yr), "nfl").mkdir(parents=True, exist_ok=True)
        x.to_csv(out_dir(int(yr), "nfl") / "events_task3.csv", index=False)
    print(ev.groupby("season").agg(games=("event_ticker", "size"), with_candles=("candles", lambda v: int((v > 0).sum())))
          .to_string())
    return 0


def nflverse_times(season: int) -> pd.DataFrame:
    """First and last play wall-clock time per nflverse game (game_id, home_team, away_team, first, last)."""
    p = pd.read_csv(DATA / "ingame" / "nfl" / "pbp" / f"pbp_{season}.csv.gz",
                    usecols=["game_id", "home_team", "away_team", "time_of_day"], low_memory=False)
    p["wall"] = pd.to_datetime(p["time_of_day"], utc=True, errors="coerce", format="ISO8601")
    return p.dropna(subset=["wall"]).groupby(["game_id", "home_team", "away_team"])["wall"].agg(["min", "max"]) \
        .rename(columns={"min": "first", "max": "last"}).reset_index()


def fill_nfl_from_zip(season: int = 2025, zpath: Path = NFL_ZIP) -> int:
    """Games whose candle file is missing or does not cover the game (Task 3 kickoff estimated hours off,
    e.g. Week 18 Saturday games): rebuild from the 2025 raw pull (one file per market, whole market life),
    from 1 h before the first nflverse play to 1 h after the last."""
    from app.ingame.swings import NFL_CODE

    folder = out_dir(season, "nfl")
    if not zpath.exists():
        print(f"{zpath.name} not here: skipping the 2025 gap fill (the fixed files are kept if present).")
        return 0
    ev = pd.read_csv(folder / "events_task3.csv")
    times = nflverse_times(season)
    z = zipfile.ZipFile(zpath)
    names = set(z.namelist())
    filled, missing = 0, []
    for _, e in ev.iterrows():
        d = ticker_date(e["event_ticker"])
        codes = {NFL_CODE.get(t.rsplit("-", 1)[1], t.rsplit("-", 1)[1]) for t in str(e["tickers"]).split("|")}
        tm = times[times["home_team"].isin(codes) & times["away_team"].isin(codes)
                   & (times["first"].dt.tz_convert(EASTERN).dt.date.map(lambda x: abs((x - d).days) <= 1))]
        if len(tm) != 1:
            continue
        first, last = int(tm["first"].iloc[0].timestamp()), int(tm["last"].iloc[0].timestamp())
        path = folder / "candles" / f"{e['event_ticker']}.csv.gz"
        if path.exists():
            have = pd.read_csv(path, usecols=["ts"])["ts"]
            if len(have) and have.min() <= first - 1800 and have.max() >= last:
                continue
        lo, hi = first - 3600, last + 3600
        rows = []
        for t in str(e["tickers"]).split("|"):
            n = f"raw/candles/KXNFLGAME/{t}.json"
            if n not in names:
                continue
            body = json.loads(z.read(n))
            cs = body.get("candlesticks") or [c for mk in body.get("markets") or [] for c in mk.get("candlesticks") or []]
            rows += [r for r in candle_rows(t, cs) if lo <= r["ts"] <= hi]
        if rows:
            save_event(path, rows)
            filled += 1
            print(f"  rebuilt {e['event_ticker']} from the raw pull ({len(rows)} candles)")
        else:
            missing.append(e["event_ticker"])
    print(f"Rebuilt {filled} games from {zpath.name}; not in the raw pull either: {missing}")
    return 0


def pull_nflverse(seasons: tuple[int, ...] = (2025, 2026)) -> int:
    """nflverse play-by-play (GitHub release asset, no key). The current season is re-downloaded every time."""
    import httpx

    dest = DATA / "ingame" / "nfl" / "pbp"
    dest.mkdir(parents=True, exist_ok=True)
    for yr in seasons:
        url = f"https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{yr}.csv.gz"
        r = httpx.get(url, follow_redirects=True, timeout=120)
        r.raise_for_status()
        (dest / f"pbp_{yr}.csv.gz").write_bytes(r.content)
        print(f"nflverse {yr}: {len(r.content) / 1e6:.1f} MB")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="In-game swing study inputs (Kalshi candles, college play-by-play)")
    ap.add_argument("command", choices=["pull", "pull-kalshi", "pull-cfbd", "extract-zip", "export-task3", "fill-nfl-zip", "pull-nflverse"])
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--zip", type=Path, default=DATA / "kalshi_raw_2026_college_ncaaf.zip")
    ap.add_argument("--no-wp", action="store_true", help="skip CollegeFootballData win probability (1 call per game)")
    ap.add_argument("--max-requests", type=int, default=None)
    a = ap.parse_args(argv)
    today = datetime.now(EASTERN).date()
    if a.command == "extract-zip":
        return extract_zip(a.season, a.zip)
    if a.command == "export-task3":
        return export_task3()
    if a.command == "fill-nfl-zip":
        return fill_nfl_from_zip(2025)
    if a.command == "pull-nflverse":
        return pull_nflverse()
    code = 0
    if a.command in ("pull", "pull-cfbd"):
        code = pull_cfbd(a.season, today, wp=not a.no_wp) or code
    if a.command in ("pull", "pull-kalshi"):
        code = asyncio.run(pull_kalshi(a.season, today, a.max_requests)) or code
    return code


if __name__ == "__main__":
    raise SystemExit(main())
