"""Kalshi vs sportsbooks, same games and same moments. One script, run once per season.

Steps (the team's alignment brief):

1. Game list from the sportsbook data: game_id, season, week, home, away, kickoff (provider start
   time, UTC). The provider updates a game's start time as kickoff approaches (usually by a few
   minutes, sometimes by hours when a game is moved), so the kickoff used is the provider's
   *final* start time; the first one listed and how far it moved are kept too.
2. Crosswalk: parse the date and teams from each Kalshi game-winner event ticker, e.g.
   ``KXNFLGAME-26SEP20INDKC`` = IND at KC on Sept 20 (Eastern-time date), with one market per team
   (``...-IND``, ``...-KC``). Codes are mapped with ``teams.py`` and joined on teams and date.
   Every game ends ``matched`` or with a reason code (``REASONS``).
3. Snapshots at 24 h, 3 h, 1 h, 15 min before kickoff and at kickoff ("close"): for each team, the
   last Kalshi candle at or before that moment (bid, ask) and each book's moneyline for the same
   team, both with ``pandas.merge_asof(direction="backward")``. Each price's age is recorded.
4. Costs (``costs.py``): every venue's price measured against ruler A (Kalshi's fair price) and
   the three ruler Bs (Pinnacle's, FanDuel's and DraftKings' fair prices), Kalshi at each n
   (median, p75, p90 trade size) with the taker fee rounded up to the cent.
5. Every check (``checks.py``), then the three files per season, in ``data/alignment/<season>/``:
   ``crosswalk.csv`` (the game list plus the match), ``snapshots.csv`` and ``costs.csv``, plus
   ``checks.json`` and ``summary.md``.

Inputs: sportsbook snapshots from Task 4 (``data/task4/snapshots.csv.gz``) and Kalshi markets and
candles from Task 3 (``data/task3/nfl_costs.db``).

Command line (exit code 1 if a check fails; the files are still written)::

    cd backend && .venv/bin/python -m app.alignment.pipeline --season 2026
    cd backend && .venv/bin/python -m app.alignment.pipeline --season 2025
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from app.alignment import teams
from app.task4.common import EASTERN, REPO_ROOT, SNAPSHOTS, nfl_season, nfl_week, parse_times, week_label

OUT_DIR = REPO_ROOT / "data" / "alignment"
TASK3_DB = REPO_ROOT / "data" / "task3" / "nfl_costs.db"
GAME_SERIES = "KXNFLGAME"
PRICE_SCALE = 10_000  # Task 3 stores prices in 1/10,000 of a dollar
BOOKS = ("DraftKings", "FanDuel", "Pinnacle")
SOURCES = ("Kalshi", *BOOKS)
CHECKPOINTS: dict[str, int] = {"24h": 24 * 60, "3h": 180, "1h": 60, "15m": 15, "close": 0}
MOVED_WARN_MIN = 60
DATE_TOLERANCE_DAYS = 1

REASONS = {
    "matched": "Matched to one Kalshi event with one market per team.",
    "no_kalshi_data": "No Kalshi game markets in the Task 3 data for this season.",
    "no_kalshi_event": "No Kalshi event for these two teams within a day of kickoff.",
    "kalshi_date_mismatch": "A Kalshi event for these teams exists, but more than a day from kickoff.",
    "multiple_kalshi_events": "More than one Kalshi event fits; not matched to avoid a wrong pick.",
    "unknown_team_code": "The Kalshi event uses a team code not in teams.py.",
    "not_two_markets": "The Kalshi event does not have exactly one market per team.",
    "ticker_unparsed": "The Kalshi event ticker does not have the expected form.",
}
TICKER_RE = re.compile(r"^KXNFLGAME-(\d{2})([A-Z]{3})(\d{2})([A-Z]+)$")
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP",
                                       "OCT", "NOV", "DEC"], 1)}


# --------------------------------------------------------------------------------------
# Step 1: game list
# --------------------------------------------------------------------------------------


def load_sportsbook(path: Path = SNAPSHOTS) -> pd.DataFrame:
    snaps = parse_times(pd.read_csv(path, dtype=str, keep_default_na=False))
    snaps["price_american"] = pd.to_numeric(snaps["price_american"], errors="coerce")
    return snaps


def game_list(snaps: pd.DataFrame, season: int) -> pd.DataFrame:
    """One row per game of the season, kickoff = the provider's final start time."""
    s = snaps.sort_values("snapshot_ts")
    first = s.groupby("event_id").first()
    last = s.groupby("event_id").last()
    g = pd.DataFrame({
        "game_id": last.index,
        "home": last["home_team"].to_numpy(),
        "away": last["away_team"].to_numpy(),
        "kickoff_utc": last["commence_time"].to_numpy(),
        "kickoff_first_listed_utc": first["commence_time"].to_numpy(),
    })
    g["kickoff_utc"] = pd.to_datetime(g["kickoff_utc"], utc=True)
    g["kickoff_first_listed_utc"] = pd.to_datetime(g["kickoff_first_listed_utc"], utc=True)
    g["kickoff_moved_min"] = ((g["kickoff_utc"] - g["kickoff_first_listed_utc"]).dt.total_seconds() / 60).round(1)
    g["season"] = nfl_season(g["kickoff_utc"])
    g["week"] = nfl_week(g["kickoff_utc"])
    g["week_label"] = g["week"].map(week_label)
    g = g[g["season"] == season].sort_values(["kickoff_utc", "game_id"]).reset_index(drop=True)
    cols = ["game_id", "season", "week", "week_label", "home", "away", "kickoff_utc",
            "kickoff_first_listed_utc", "kickoff_moved_min"]
    return g[cols]


# --------------------------------------------------------------------------------------
# Step 2: crosswalk
# --------------------------------------------------------------------------------------


def load_kalshi_markets(db: Path = TASK3_DB) -> pd.DataFrame:
    """Kalshi game-winner markets from the Task 3 store (empty frame if there is none)."""
    cols = ["id", "ticker", "event_ticker", "series_ticker", "yes_sub_title"]
    if not db.exists():
        return pd.DataFrame(columns=cols)
    with sqlite3.connect(db) as conn:
        return pd.read_sql_query(
            "SELECT id, ticker, event_ticker, series_ticker, yes_sub_title FROM markets "
            "WHERE series_ticker = ? OR event_ticker LIKE ?", conn, params=(GAME_SERIES, f"{GAME_SERIES}-%"))


def parse_event(event_ticker: str, suffixes: list[str]) -> dict:
    """Date and teams of one Kalshi event. Teams are split using the market suffixes."""
    out = {"event_ticker": event_ticker, "ticker_date": None, "away_code": None, "home_code": None,
           "parse_reason": None}
    m = TICKER_RE.match(event_ticker)
    if not m or m.group(2) not in MONTHS:
        out["parse_reason"] = "ticker_unparsed"
        return out
    yy, mon, dd, block = m.groups()
    try:
        out["ticker_date"] = date(2000 + int(yy), MONTHS[mon], int(dd))
    except ValueError:
        out["parse_reason"] = "ticker_unparsed"
        return out
    if len(set(suffixes)) != 2 or len(suffixes) != 2:
        out["parse_reason"] = "not_two_markets"
        return out
    a, b = suffixes
    if block == a + b:
        out["away_code"], out["home_code"] = a, b
    elif block == b + a:
        out["away_code"], out["home_code"] = b, a
    else:
        out["parse_reason"] = "ticker_unparsed"
        return out
    if teams.team_name(a) is None or teams.team_name(b) is None:
        out["parse_reason"] = "unknown_team_code"
    return out


def kalshi_events(markets: pd.DataFrame) -> pd.DataFrame:
    """One row per Kalshi game event: date, away/home codes and names, the two markets."""
    rows = []
    for ev, grp in markets.groupby("event_ticker"):
        suffixes = [t[len(ev) + 1:] for t in grp["ticker"] if t.startswith(ev + "-")]
        info = parse_event(ev, suffixes)
        by_code = {t[len(ev) + 1:]: (t, mid) for t, mid in zip(grp["ticker"], grp["id"])}
        for side in ("away", "home"):
            code = info[f"{side}_code"]
            info[f"{side}_name"] = teams.team_name(code) if code else None
            info[f"{side}_ticker"], info[f"{side}_market_id"] = by_code.get(code, (None, None)) if code else (None, None)
        info["codes"] = ",".join(sorted(suffixes))
        rows.append(info)
    cols = ["event_ticker", "ticker_date", "away_code", "home_code", "parse_reason", "away_name", "home_name",
            "away_ticker", "away_market_id", "home_ticker", "home_market_id", "codes"]
    return pd.DataFrame(rows, columns=cols)


def crosswalk(games: pd.DataFrame, events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Match every game to at most one Kalshi event. Returns (crosswalk, Kalshi events not used)."""
    ok = events[events["parse_reason"].isna()].copy()
    bad = events[events["parse_reason"].notna()].copy()
    ok["teamset"] = [frozenset((a, h)) for a, h in zip(ok["away_name"], ok["home_name"])]
    out = []
    used: dict[str, int] = {}
    for g in games.itertuples():
        et_date = g.kickoff_utc.tz_convert(EASTERN).date()
        pair = frozenset((g.home, g.away))
        rec = {"game_id": g.game_id, "status": "unmatched", "reason_code": None, "kalshi_event_ticker": None,
               "ticker_date": None, "date_diff_days": None, "ticker_home_away_matches": None,
               "kalshi_ticker_home": None, "kalshi_ticker_away": None, "kalshi_market_id_home": None,
               "kalshi_market_id_away": None}
        same = ok[ok["teamset"] == pair]
        diffs = [abs((d - et_date).days) for d in same["ticker_date"]]
        near = same[[x <= DATE_TOLERANCE_DAYS for x in diffs]]
        if len(near) == 1:
            e = near.iloc[0]
            rec.update(status="matched", reason_code="matched", kalshi_event_ticker=e.event_ticker,
                       ticker_date=e.ticker_date, date_diff_days=(e.ticker_date - et_date).days,
                       ticker_home_away_matches=bool(e.home_name == g.home and e.away_name == g.away))
            # each Kalshi market goes to the team it is for, whatever the ticker's order
            for side, team in (("home", g.home), ("away", g.away)):
                k_side = "home" if e.home_name == team else "away"
                rec[f"kalshi_ticker_{side}"] = e[f"{k_side}_ticker"]
                rec[f"kalshi_market_id_{side}"] = e[f"{k_side}_market_id"]
            used[e.event_ticker] = used.get(e.event_ticker, 0) + 1
        elif len(near) > 1:
            rec["reason_code"] = "multiple_kalshi_events"
        elif len(same):
            rec["reason_code"] = "kalshi_date_mismatch"
        else:
            codes = {teams.NAME_TO_CODE.get(g.home), teams.NAME_TO_CODE.get(g.away)}
            near_bad = bad[[(d is not None and abs((d - et_date).days) <= DATE_TOLERANCE_DAYS
                             and bool(codes & set(c.split(",")))) for d, c in zip(bad["ticker_date"], bad["codes"])]]
            if len(near_bad):
                rec["reason_code"] = near_bad["parse_reason"].iloc[0]
                rec["kalshi_event_ticker"] = near_bad["event_ticker"].iloc[0]
            else:
                rec["reason_code"] = "no_kalshi_data" if events.empty else "no_kalshi_event"
        out.append(rec)
    cw = games.merge(pd.DataFrame(out), on="game_id", how="left")
    leftover = events[~events["event_ticker"].isin(used) & ~events["event_ticker"].isin(cw["kalshi_event_ticker"])]
    return cw, leftover


# --------------------------------------------------------------------------------------
# Step 3: snapshots
# --------------------------------------------------------------------------------------


def load_candles(market_ids: list[int], db: Path = TASK3_DB) -> pd.DataFrame:
    cols = ["market_id", "ts", "bid", "ask"]
    if not market_ids or not db.exists():
        return pd.DataFrame(columns=cols)
    with sqlite3.connect(db) as conn:
        marks = ",".join("?" * len(market_ids))
        return pd.read_sql_query(f"SELECT market_id, ts, bid, ask FROM candles WHERE market_id IN ({marks})",
                                 conn, params=[int(i) for i in market_ids])


EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def epoch_seconds(ts: pd.Series) -> pd.Series:
    """Unix seconds, whatever unit pandas stores the timestamps in (pandas 3 uses microseconds,
    so ``astype("int64") // 10**9`` would silently give dates in 1970)."""
    return ((ts - EPOCH) // pd.Timedelta(seconds=1)).astype("int64")


def _queries(cw: pd.DataFrame) -> pd.DataFrame:
    """One row per matched game x team x checkpoint."""
    rows = []
    for g in cw[cw["status"] == "matched"].itertuples():
        for side in ("home", "away"):
            team = getattr(g, side)
            for name, minutes in CHECKPOINTS.items():
                at = g.kickoff_utc - pd.Timedelta(minutes=minutes)
                rows.append({"game_id": g.game_id, "season": g.season, "week": g.week, "side": side, "team": team,
                             "team_code": teams.NAME_TO_CODE.get(team), "checkpoint": name,
                             "checkpoint_utc": at, "kickoff_utc": g.kickoff_utc,
                             "kalshi_ticker": getattr(g, f"kalshi_ticker_{side}"),
                             "market_id": getattr(g, f"kalshi_market_id_{side}")})
    q = pd.DataFrame(rows)
    if not q.empty:
        q["checkpoint_ts"] = epoch_seconds(q["checkpoint_utc"])
    return q


def kalshi_snapshots(q: pd.DataFrame, candles: pd.DataFrame) -> pd.DataFrame:
    """Last candle at or before each checkpoint, per market (merge_asof, backward)."""
    if q.empty:
        return pd.DataFrame()
    left = q.assign(market_id=q["market_id"].astype("int64")).sort_values("checkpoint_ts")
    right = candles.assign(market_id=candles["market_id"].astype("int64"), ts=candles["ts"].astype("int64"))
    right = right.sort_values("ts")
    m = pd.merge_asof(left, right, left_on="checkpoint_ts", right_on="ts", by="market_id",
                      direction="backward", allow_exact_matches=True)
    out = m.assign(
        source="Kalshi",
        price_ts_utc=pd.to_datetime(m["ts"], unit="s", utc=True),
        age_s=(m["checkpoint_ts"] - m["ts"]),
        kalshi_bid=m["bid"] / PRICE_SCALE,
        kalshi_ask=m["ask"] / PRICE_SCALE,
    )
    out["missing_reason"] = np.where(out["ts"].isna(), "no_candle_before_checkpoint", None)
    return out.drop(columns=["ts", "bid", "ask"])


def book_lines(snaps: pd.DataFrame, game_ids: set[str]) -> pd.DataFrame:
    """Moneyline per game, book and snapshot, with both teams' prices on one row."""
    h = snaps[(snaps["market"] == "h2h") & snaps["event_id"].isin(game_ids) & snaps["bookmaker"].isin(BOOKS)]
    keep = ["event_id", "bookmaker", "snapshot_ts", "outcome", "price_american", "market_last_update"]
    return h[keep].rename(columns={"event_id": "game_id", "bookmaker": "source"})


def book_snapshots(q: pd.DataFrame, lines: pd.DataFrame) -> pd.DataFrame:
    """Each book's line for the same team, last snapshot at or before the checkpoint."""
    if q.empty:
        return pd.DataFrame()
    other = lines.rename(columns={"outcome": "other_team", "price_american": "price_american_other"})[
        ["game_id", "source", "snapshot_ts", "other_team", "price_american_other"]]
    both = lines.merge(other, on=["game_id", "source", "snapshot_ts"])
    both = both[both["other_team"] != both["outcome"]]
    both = both.rename(columns={"outcome": "team"})
    both["snap_ts"] = epoch_seconds(both["snapshot_ts"])
    frames = []
    for book in BOOKS:
        left = q.assign(source=book).sort_values("checkpoint_ts")
        right = both[both["source"] == book].sort_values("snap_ts")
        m = pd.merge_asof(left, right.drop(columns=["source"]), left_on="checkpoint_ts", right_on="snap_ts",
                          by=["game_id", "team"], direction="backward", allow_exact_matches=True)
        frames.append(m)
    m = pd.concat(frames, ignore_index=True)
    m["price_ts_utc"] = m["snapshot_ts"]
    m["age_s"] = m["checkpoint_ts"] - m["snap_ts"]
    m["book_implied"] = _implied(m["price_american"])
    m["book_implied_other"] = _implied(m["price_american_other"])
    m["missing_reason"] = np.where(m["snap_ts"].isna(), "no_line_before_checkpoint", None)
    return m.drop(columns=["snapshot_ts", "snap_ts", "other_team"]).rename(
        columns={"price_american": "book_price_american", "price_american_other": "book_price_american_other",
                 "market_last_update": "book_last_update_utc"})


def _implied(a: pd.Series) -> pd.Series:
    a = a.astype(float)
    return pd.Series(np.where(a >= 100, 100 / (a + 100), np.where(a <= -100, -a / (-a + 100), np.nan)),
                     index=a.index)


SNAPSHOT_COLS = ["game_id", "season", "week", "side", "team", "team_code", "checkpoint", "checkpoint_utc",
                 "kickoff_utc", "source", "price_ts_utc", "age_s", "missing_reason", "kalshi_ticker",
                 "kalshi_bid", "kalshi_ask", "book_price_american", "book_price_american_other",
                 "book_implied", "book_implied_other", "book_last_update_utc"]


def snapshots(cw: pd.DataFrame, snaps: pd.DataFrame, candles: pd.DataFrame) -> pd.DataFrame:
    q = _queries(cw)
    if q.empty:
        return pd.DataFrame(columns=SNAPSHOT_COLS)
    k = kalshi_snapshots(q, candles)
    b = book_snapshots(q, book_lines(snaps, set(q["game_id"])))
    out = pd.concat([k, b], ignore_index=True)
    for c in SNAPSHOT_COLS:
        if c not in out:
            out[c] = None
    order = {c: i for i, c in enumerate(CHECKPOINTS)}
    src = {s: i for i, s in enumerate(SOURCES)}
    out = out.assign(_c=out["checkpoint"].map(order), _s=out["source"].map(src))
    out = out.sort_values(["kickoff_utc", "game_id", "side", "_c", "_s"]).drop(columns=["_c", "_s"])
    return out[SNAPSHOT_COLS].reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Step 4: costs (rulers and rules in costs.py)
# --------------------------------------------------------------------------------------


def compute_costs(snap: pd.DataFrame, season: int, n_folder: Path = OUT_DIR) -> pd.DataFrame:
    """Cost per $10 for every venue under ruler A (Kalshi) and the three ruler Bs (the books)."""
    from app.alignment import costs as costs_mod

    n_list, source = costs_mod.n_values(season, n_folder)
    return costs_mod.compute(snap, season, n_list, source)


# --------------------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------------------


def run(season: int, sportsbook: Path = SNAPSHOTS, db: Path = TASK3_DB, out_dir: Path = OUT_DIR) -> int:
    from app.alignment import checks as checks_mod

    snaps = load_sportsbook(sportsbook)
    games = game_list(snaps, season)
    markets = load_kalshi_markets(db)
    events = kalshi_events(markets)
    in_season = np.array([d is not None and _season_of(d) == season for d in events["ticker_date"]], dtype=bool)
    events_s = events.loc[in_season]  # a boolean array, so an empty frame keeps its columns
    cw, leftover = crosswalk(games, events_s)
    ids = pd.concat([cw["kalshi_market_id_home"], cw["kalshi_market_id_away"]]).dropna().astype(int).unique().tolist()
    candles = load_candles(ids, db)
    snap = snapshots(cw, snaps, candles)
    costs = compute_costs(snap, season, out_dir)
    results = checks_mod.run_checks(season, games, events_s, cw, leftover, snap, candles, snaps, costs,
                                    kalshi_present=not markets.empty)

    folder = out_dir / str(season)
    folder.mkdir(parents=True, exist_ok=True)
    cw.to_csv(folder / "crosswalk.csv", index=False)
    leftover.to_csv(folder / "kalshi_events_unmatched.csv", index=False)
    snap.to_csv(folder / "snapshots.csv", index=False)
    costs.to_csv(folder / "costs.csv", index=False)
    (folder / "checks.json").write_text(json.dumps(results, indent=2, default=str))
    (folder / "summary.md").write_text(summary(season, cw, leftover, snap, results, costs))

    tally = {s: sum(c["status"] == s for c in results) for s in ("pass", "warn", "skip", "fail")}
    print(f"{season}: {len(games)} games, {int((cw['status'] == 'matched').sum())} matched, "
          f"{len(snap)} snapshot rows; checks " + ", ".join(f"{n} {s}" for s, n in tally.items() if n))
    for c in results:
        if c["status"] in ("fail", "warn"):
            print(f"  {c['status'].upper()} {c['title']}: {c['detail']}")
    print(f"files: {folder}")
    return 1 if tally["fail"] else 0


def _season_of(d: date) -> int:
    return d.year if d.month >= 8 else d.year - 1


def summary(season: int, cw: pd.DataFrame, leftover: pd.DataFrame, snap: pd.DataFrame, results: list[dict],
            costs: pd.DataFrame | None = None) -> str:
    reasons = cw["reason_code"].value_counts()
    lines = [f"# Alignment, {season} season", "",
             f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC. Games: {len(cw)}; matched: "
             f"{int((cw['status'] == 'matched').sum())}; Kalshi events left unmatched: {len(leftover)}.", "",
             "## Match status", ""]
    lines += [f"- {k}: {int(v)} ({REASONS.get(k, '')})" for k, v in reasons.items()]
    lines += ["", "## Checks", ""]
    lines += [f"- [{c['status']}] {c['title']}: {c['detail']}" for c in results]
    if not snap.empty:
        ages = snap.dropna(subset=["age_s"]).groupby(["checkpoint", "source"])["age_s"].median() / 60
        lines += ["", "## Median price age (minutes) at each checkpoint", "",
                  ages.unstack().reindex(list(CHECKPOINTS)).round(1).to_string()]
    if costs is not None and not costs.empty:
        from app.alignment import costs as costs_mod

        t = costs_mod.table(costs)
        src = costs["n_source"].dropna()
        lines += ["", "## Median cost per $10 (usable rows only)", "",
                  "Rows: the venue you bet at (Kalshi at each order size n). Columns: the ruler (whose fair "
                  "price the cost is measured against). Own ruler = that venue's margin only.",
                  f"n values from: {src.iloc[0] if len(src) else 'n/a'}. Usable rows: "
                  f"{int(costs['usable'].sum())} of {len(costs)}.", "",
                  t.to_string() if not t.empty else "(no usable rows)"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Align Kalshi and sportsbook prices for one NFL season.")
    parser.add_argument("--season", type=int, required=True, help="2025 or 2026")
    args = parser.parse_args(argv)
    return run(args.season)


if __name__ == "__main__":
    raise SystemExit(main())
