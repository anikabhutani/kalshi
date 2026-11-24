"""College football (NCAAF) alignment: the same five steps as ``pipeline.py``, for one season.

Inputs, read straight from the two zip files (nothing needs unzipping):

- Sportsbook odds: ``odds_data.zip`` -> ``history_americanfootball_ncaaf.csv`` (DraftKings, FanDuel,
  Pinnacle; daily and pre-kickoff snapshots).
- Kalshi: Theo's raw pull ``kalshi_raw_2025_season_nfl_ncaaf.zip`` -> ``raw/discovery/
  hist_KXNCAAFGAME_p*.json`` (markets, titles, results) and ``raw/candles/KXNCAAFGAME/<ticker>.json``
  (1-minute candles, parsed exactly like Task 3's: ``end_period_ts``, yes bid/ask close).

Steps:

1. Game list from the sportsbook data (kickoff = the provider's final start time, as for the NFL).
   College week: week 0 is the opening weekend (late August); weeks run Tuesday to Monday,
   Eastern; postseason = after the second Saturday of December (bowls and playoff).
2. Crosswalk. There is no fixed team table for ~250 schools, so games are matched on the date
   (ticker date, Eastern, +-1 day) and *both* team names: Kalshi's short school name (``Ohio
   St.``) against the feed's full name (``Ohio State Buckeyes``). A name scores 1 when it is the
   start of the feed name and the next word is not one that makes it a different school
   ("State", "Tech", "A&M", ...); otherwise by the share of its words found. A game is matched
   when both teams together score at least ``MIN_SCORE`` and clearly beat the next candidate
   (``MIN_MARGIN``), and the match is mutual. The team table (Kalshi code -> feed name) is then
   *learned* from the matches and checked: one school per code and one code per school.
3. Snapshots: ``pipeline.snapshots`` unchanged (merge_asof backward, price ages).
4. Costs: ``costs.compute`` unchanged (ruler A = Kalshi, rulers B = the three books, fixed
   rules). n values: Kalshi trade sizes for college are not pulled, so the NFL game-winner sizes
   are used and every row says so; fee schedule: the standard 0.07 taker fee.
5. Checks (the NFL snapshot and cost checks plus the college crosswalk checks), then the files in
   ``data/alignment/ncaaf/<season>/``: crosswalk.csv, snapshots.csv, costs.csv.gz (the three files),
   plus team_table.csv, kalshi_events_unmatched.csv, checks.json and summary.md.

Command line::

    cd backend && .venv/bin/python -m app.alignment.college --season 2025
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.alignment import checks as nfl_checks
from app.alignment import costs as costs_mod
from app.alignment import pipeline as pl
from app.task3.backfill import parse_candle
from app.task4.common import EASTERN, REPO_ROOT, parse_times

OUT_DIR = REPO_ROOT / "data" / "alignment" / "ncaaf"
ODDS_ZIP = REPO_ROOT / "data" / "odds_data.zip"
KALSHI_ZIP = REPO_ROOT / "data" / "kalshi_raw_2025_season_nfl_ncaaf.zip"
# Theo's 2025 pull and the 2026 pull use different layouts; both are read (see load_kalshi_markets / load_candles).
KALSHI_ZIPS = {2025: KALSHI_ZIP, 2026: REPO_ROOT / "data" / "kalshi_raw_2026_college_ncaaf.zip"}
ODDS_MEMBER = "history_americanfootball_ncaaf.csv"
SERIES = "KXNCAAFGAME"
MIN_SCORE = 1.5
MIN_MARGIN = 0.5
DATE_TOLERANCE_DAYS = 1
# Week 1 starts on this Tuesday; the weekend before it is week 0.
WEEK1_TUESDAY = {2025: date(2025, 8, 26), 2026: date(2026, 9, 1)}
# A word right after a matched school name that makes it a different school ("Oregon" vs "Oregon State").
QUALIFIERS = {"state", "tech", "a", "am", "christian", "international", "baptist", "methodist", "atlantic",
              "southern", "northern", "eastern", "western", "central", "poly", "pacific", "st", "oh", "fl"}
# Spellings that differ between Kalshi and the odds feed (normalised words). Kept short and explicit;
# every match is also checked against prices (team_alignment) and the learned table.
ALIASES = {
    "north carolina state": "nc state",
    "louisiana monroe": "ul monroe",
    "tennessee martin": "ut martin",
    "miami fl": "miami",
    "university at albany": "albany",
    "the citadel": "citadel",
    "houston christian": "houston baptist",
}
REASONS = {
    "matched": "Matched to one Kalshi event on the same date with both team names agreeing.",
    "no_kalshi_event": "No Kalshi game market for these two teams within a day of kickoff.",
    "ambiguous_match": "More than one Kalshi event fits about equally well; not matched to avoid a wrong pick.",
    "weak_name_match": "The closest Kalshi event's team names agree only partly; not matched.",
    "no_kalshi_data": "No Kalshi college game markets in the raw files for this season.",
}
TITLE_RE = re.compile(r"^(?P<a>.+?) (?:at|vs\.?) (?P<h>.+?) Winner\?$")
# Team codes can contain a hyphen (Miami (OH) is "M-OH"), so the block after the date allows it.
TICKER_RE = re.compile(r"^KXNCAAFGAME-(\d{2})([A-Z]{3})(\d{2})([A-Z0-9-]+)$")


# --------------------------------------------------------------------------------------
# names
# --------------------------------------------------------------------------------------


def norm(name: str) -> list[str]:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    for a, b in (("&", " and "), ("'", ""), ("-", " "), (".", ""), ("(", " "), (")", " ")):
        s = s.replace(a, b)
    joined = " ".join("state" if w == "st" else w for w in s.split())
    for a, b in ALIASES.items():
        if joined == a or joined.startswith(a + " "):
            joined = b + joined[len(a):]
    return joined.split()


def name_score(kalshi: str, feed: str) -> float:
    """1.0 when Kalshi's school name starts the feed name and the next word doesn't make it another
    school; otherwise the share of Kalshi's words found in the feed name (prefixes of 3+ letters count)."""
    k, f = norm(kalshi), norm(feed)
    if f[: len(k)] == k:
        nxt = f[len(k)] if len(f) > len(k) else None
        return 0.5 if nxt in QUALIFIERS else 1.0
    hit = sum(1 for w in k if w in f or (len(w) >= 3 and any(x.startswith(w) for x in f)))
    return hit / len(k)


# --------------------------------------------------------------------------------------
# step 1: game list
# --------------------------------------------------------------------------------------


def season_of(d: date) -> int | None:
    if d.month >= 8:
        return d.year
    return d.year - 1 if d.month <= 1 else None


def college_week(d: date, season: int) -> int:
    start = WEEK1_TUESDAY.get(season, date(season, 8, 26))
    return max(0, (d - start).days // 7 + 1)


def postseason_start(season: int) -> date:
    """Day after the second Saturday of December (Army-Navy weekend ends the regular season)."""
    d = date(season, 12, 1)
    first_sat = d + timedelta(days=(5 - d.weekday()) % 7)
    return first_sat + timedelta(days=8)


def load_odds(path: Path = ODDS_ZIP) -> pd.DataFrame:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            member = next(n for n in z.namelist() if n.endswith(ODDS_MEMBER))
            with z.open(member) as fh:
                snaps = pd.read_csv(fh, dtype=str, keep_default_na=False)
    else:
        snaps = pd.read_csv(path, dtype=str, keep_default_na=False)
    snaps = parse_times(snaps)
    snaps["price_american"] = pd.to_numeric(snaps["price_american"], errors="coerce")
    return snaps


def drop_feed_duplicates(snaps: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """The odds feed sometimes lists one game twice (same teams, kickoffs a day apart, usually after a
    reschedule). Keep the listing the feed kept updating (latest snapshot); return the dropped ids."""
    last = snaps.groupby("event_id").agg(home=("home_team", "last"), away=("away_team", "last"),
                                         kick=("commence_time", "last"), seen=("snapshot_ts", "max"))
    dropped = []
    for _, g in last.groupby(["home", "away"]):
        g = g.sort_values("kick")
        while len(g) > 1:
            close = g[(g["kick"] - g["kick"].iloc[0]).abs() <= pd.Timedelta(days=2)]
            if len(close) > 1:
                keep = close["seen"].idxmax()
                dropped += [i for i in close.index if i != keep]
            g = g.drop(close.index)
    return snaps[~snaps["event_id"].isin(dropped)], dropped


def game_list(snaps: pd.DataFrame, season: int) -> pd.DataFrame:
    s = snaps.sort_values("snapshot_ts")
    first = s.groupby("event_id").first()
    last = s.groupby("event_id").last()
    g = pd.DataFrame({"game_id": last.index, "home": last["home_team"].to_numpy(), "away": last["away_team"].to_numpy(),
                      "kickoff_utc": pd.to_datetime(last["commence_time"].to_numpy(), utc=True),
                      "kickoff_first_listed_utc": pd.to_datetime(first["commence_time"].to_numpy(), utc=True)})
    as_of = snaps["snapshot_ts"].max()
    g["kickoff_moved_min"] = ((g["kickoff_utc"] - g["kickoff_first_listed_utc"]).dt.total_seconds() / 60).round(1)
    et = g["kickoff_utc"].dt.tz_convert(EASTERN).dt.date
    g["season"] = [season_of(d) for d in et]
    g = g[(g["season"] == season) & (g["kickoff_utc"] < as_of)].copy()
    et = g["kickoff_utc"].dt.tz_convert(EASTERN).dt.date
    g["week"] = [college_week(d, season) for d in et]
    g["postseason"] = [d >= postseason_start(season) for d in et]
    g["week_label"] = np.where(g["postseason"], "Postseason", "Week " + g["week"].astype(str))
    g["season"] = g["season"].astype(int)
    cols = ["game_id", "season", "week", "week_label", "postseason", "home", "away", "kickoff_utc",
            "kickoff_first_listed_utc", "kickoff_moved_min"]
    return g.sort_values(["kickoff_utc", "game_id"])[cols].reset_index(drop=True)


# --------------------------------------------------------------------------------------
# step 2: Kalshi markets and crosswalk
# --------------------------------------------------------------------------------------


def load_kalshi_markets(path: Path = KALSHI_ZIP) -> pd.DataFrame:
    """Game-winner markets from either layout:
    2025 (historical pull): ``raw/discovery/hist_KXNCAAFGAME_p*.json`` = {"markets": [...]}, candles in
    ``raw/candles/KXNCAAFGAME/<ticker>.json``.
    2026 (live pull): ``raw/discovery/events_KXNCAAFGAME_p*.json`` = {"events": [{..., "markets": [...]}]}
    (the game's title is on the event), candles in ``raw/candles/<event>/<event>__g*.json`` chunks."""
    cols = ["id", "ticker", "event_ticker", "code", "kalshi_name", "title", "result", "volume", "has_candles"]
    if not path.exists():
        return pd.DataFrame(columns=cols)
    rows = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        for n in sorted(names):
            if re.search(rf"discovery/hist_{SERIES}_p\d+\.json$", n):
                rows += json.loads(z.read(n))["markets"]
            elif re.search(rf"discovery/events_{SERIES}_p\d+\.json$", n):
                for ev in json.loads(z.read(n)).get("events", []):
                    for mk in ev.get("markets", []):
                        rows.append({**mk, "title": ev.get("title", mk.get("title"))})
    per_ticker = {n.rsplit("/", 1)[-1][:-5] for n in names if f"/candles/{SERIES}/" in n and n.endswith(".json")}
    per_event = {n.split("/")[-2] for n in names if re.search(rf"/candles/{SERIES}-[^/]+/[^/]+__g\d+__\d+\.json$", n)}
    m = pd.DataFrame(rows).drop_duplicates("ticker").sort_values("ticker").reset_index(drop=True)
    if m.empty:
        return pd.DataFrame(columns=cols)
    m["id"] = np.arange(1, len(m) + 1)
    m["code"] = [t[len(e) + 1:] for t, e in zip(m["ticker"], m["event_ticker"])]
    m["kalshi_name"] = m["yes_sub_title"]
    m["volume"] = pd.to_numeric(m.get("volume_fp"), errors="coerce").fillna(0)
    m["has_candles"] = m["ticker"].isin(per_ticker) | m["event_ticker"].isin(per_event)
    return m[cols]


def split_title(title: str, names: set[str]) -> tuple[str, str] | None:
    """"Away at Home Winner?" or "Away vs Home" -> (away, home), trying every " at " / " vs " so a name that itself
    contains "at" ("University at Albany at Iowa") still splits on the right one."""
    body = re.sub(r" Winner\?$", "", title.strip())
    for sep in (" at ", " vs. ", " vs "):
        start = 0
        while (i := body.find(sep, start)) != -1:
            a, h = body[:i], body[i + len(sep):]
            if a in names and h in names:
                return a, h
            start = i + 1
    return None


def kalshi_events(markets: pd.DataFrame, season: int) -> pd.DataFrame:
    rows = []
    for ev, g in markets.groupby("event_ticker"):
        r = TICKER_RE.match(ev)
        t = split_title(str(g["title"].iat[0]), set(g["kalshi_name"]))
        info: dict[str, Any] = {"event_ticker": ev, "ticker_date": None, "parse_reason": None}
        if not r or not t or len(g) != 2:
            info["parse_reason"] = "ticker_unparsed" if not r else ("title_unparsed" if not t else "not_two_markets")
            rows.append(info)
            continue
        d = date(2000 + int(r[1]), pl.MONTHS[r[2]], int(r[3]))
        names = dict(zip(g["kalshi_name"], zip(g["ticker"], g["id"], g["code"])))
        a, h = t
        info.update(ticker_date=d, away_name=a, home_name=h, neutral=" vs" in str(g["title"].iat[0]),
                    away_ticker=names[a][0], away_market_id=names[a][1], away_code=names[a][2],
                    home_ticker=names[h][0], home_market_id=names[h][1], home_code=names[h][2])
        rows.append(info)
    ev = pd.DataFrame(rows)
    # Kalshi sometimes lists the same game twice (e.g. Ball St. at Miami (OH), Nov 29 2025, as both
    # ...BALLM-OH and ...BALLMOH). Keep the listing with candles, then the larger volume.
    if "away_name" in ev:
        vol = markets.groupby("event_ticker").agg(volume=("volume", "sum"), candles=("has_candles", "all"))
        ev = ev.join(vol, on="event_ticker")
        ok = ev["parse_reason"].isna()
        key = ["ticker_date", "away_name", "home_name"]
        order = ev[ok].sort_values(["candles", "volume"], ascending=False)
        dup = order[order.duplicated(key, keep="first")]["event_ticker"]
        ev.loc[ev["event_ticker"].isin(dup), "parse_reason"] = "duplicate_listing"
    in_season = np.array([d is not None and not pd.isna(d) and season_of(d) == season for d in ev["ticker_date"]], dtype=bool)
    ev = ev[in_season | ev["parse_reason"].notna().to_numpy()]
    return ev.reset_index(drop=True)


def _pair_scores(games: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    g_et = games["kickoff_utc"].dt.tz_convert(EASTERN).dt.date
    out = []
    ok = events[events["parse_reason"].isna()]
    for e in ok.itertuples():
        near = games[[abs((d - e.ticker_date).days) <= DATE_TOLERANCE_DAYS for d in g_et]]
        for g in near.itertuples():
            same = (name_score(e.away_name, g.away), name_score(e.home_name, g.home))
            flip = (name_score(e.away_name, g.home), name_score(e.home_name, g.away))
            best, order = (same, True) if sum(same) >= sum(flip) else (flip, False)
            if sum(best) > 0:
                out.append({"event_ticker": e.event_ticker, "game_id": g.game_id, "score": sum(best),
                            "away_score": best[0], "home_score": best[1], "same_order": order})
    return pd.DataFrame(out, columns=["event_ticker", "game_id", "score", "away_score", "home_score", "same_order"])


def crosswalk(games: pd.DataFrame, events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(crosswalk, Kalshi events not used, all candidate pairs)."""
    pairs = _pair_scores(games, events)
    ev = events.set_index("event_ticker")
    best_e = pairs.sort_values("score", ascending=False).groupby("event_ticker")
    best_g = pairs.sort_values("score", ascending=False).groupby("game_id")
    rows, used = [], set()
    for g in games.itertuples():
        rec = {"game_id": g.game_id, "status": "unmatched", "reason_code": "no_kalshi_event", "kalshi_event_ticker": None,
               "ticker_date": None, "date_diff_days": None, "ticker_home_away_matches": None, "match_score": None,
               "runner_up_score": None, "kalshi_name_home": None, "kalshi_name_away": None, "kalshi_code_home": None,
               "kalshi_code_away": None, "kalshi_ticker_home": None, "kalshi_ticker_away": None,
               "kalshi_market_id_home": None, "kalshi_market_id_away": None}
        if g.game_id in best_g.groups:
            cand = best_g.get_group(g.game_id)
            top = cand.iloc[0]
            second_g = cand["score"].iloc[1] if len(cand) > 1 else 0.0
            ecand = best_e.get_group(top.event_ticker)
            second_e = ecand["score"].iloc[1] if len(ecand) > 1 else 0.0
            mutual = ecand.iloc[0]["game_id"] == g.game_id
            rec.update(kalshi_event_ticker=top.event_ticker, match_score=top.score,
                       runner_up_score=max(second_g, second_e))
            if top.score < MIN_SCORE:
                rec["reason_code"] = "weak_name_match"
            elif not mutual or top.score - max(second_g, second_e) < MIN_MARGIN:
                rec["reason_code"] = "ambiguous_match"
            else:
                e = ev.loc[top.event_ticker]
                et_date = g.kickoff_utc.tz_convert(EASTERN).date()
                rec.update(status="matched", reason_code="matched", ticker_date=e.ticker_date,
                           date_diff_days=(e.ticker_date - et_date).days, ticker_home_away_matches=bool(top.same_order))
                sides = (("home", "home"), ("away", "away")) if top.same_order else (("home", "away"), ("away", "home"))
                for ours, theirs in sides:
                    rec[f"kalshi_name_{ours}"] = e[f"{theirs}_name"]
                    rec[f"kalshi_code_{ours}"] = e[f"{theirs}_code"]
                    rec[f"kalshi_ticker_{ours}"] = e[f"{theirs}_ticker"]
                    rec[f"kalshi_market_id_{ours}"] = e[f"{theirs}_market_id"]
                used.add(top.event_ticker)
        rows.append(rec)
    out = pd.DataFrame(rows)
    taken = out["reason_code"].isin(["weak_name_match", "ambiguous_match"]) & out["kalshi_event_ticker"].isin(used)
    out.loc[taken, "reason_code"] = "no_kalshi_event"  # its closest Kalshi event is another game's
    cw = games.merge(out, on="game_id", how="left")
    leftover = events[~events["event_ticker"].isin(used)].copy()
    best_any = pairs.sort_values("score", ascending=False).drop_duplicates("event_ticker").set_index("event_ticker")
    leftover["best_game_id"] = leftover["event_ticker"].map(best_any["game_id"])
    leftover["best_score"] = leftover["event_ticker"].map(best_any["score"])
    leftover["reason"] = np.where(leftover["parse_reason"].notna(), leftover["parse_reason"],
                                  np.where(leftover["best_score"].isna() | (leftover["best_score"] < MIN_SCORE),
                                           "no_odds_game", "not_matched_see_crosswalk"))
    return cw, leftover, pairs


def team_table(cw: pd.DataFrame) -> pd.DataFrame:
    """Kalshi code -> Kalshi name -> odds-feed name, learned from the matched games."""
    m = cw[cw["status"] == "matched"]
    rows = pd.concat([
        pd.DataFrame({"kalshi_code": m[f"kalshi_code_{s}"], "kalshi_name": m[f"kalshi_name_{s}"], "feed_name": m[s]})
        for s in ("home", "away")])
    return (rows.groupby(["kalshi_code", "kalshi_name", "feed_name"]).size().rename("games").reset_index()
            .sort_values(["kalshi_code", "games"], ascending=[True, False]))


# --------------------------------------------------------------------------------------
# step 3: candles for the matched markets
# --------------------------------------------------------------------------------------


def load_candles(tickers: dict[str, int], path: Path = KALSHI_ZIP) -> tuple[pd.DataFrame, list[str]]:
    """Candles for these market tickers, from per-market files (2025 layout) or per-event chunk files
    (2026 layout, several time windows per game, both teams' markets in each file)."""
    rows: list[tuple[int, int, Any, Any]] = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        name_set = set(names)
        chunks: dict[str, list[str]] = {}
        for n in names:
            if re.search(r"__g\d+__\d+\.json$", n):
                chunks.setdefault(n.split("/")[-2], []).append(n)

        def add(mid: int, candles: list[dict[str, Any]]) -> None:
            for c in candles:
                r = parse_candle(c)
                if r is not None:
                    rows.append((mid, r[0], r[1], r[2]))

        by_event: dict[str, list[str]] = {}
        for ticker, mid in tickers.items():
            member = next((n for n in (f"raw/candles/{SERIES}/{ticker}.json", f"candles/{SERIES}/{ticker}.json")
                           if n in name_set), None)
            if member is not None:
                add(mid, json.loads(z.read(member)).get("candlesticks", []))
            else:
                ev = next((e for e in chunks if ticker.startswith(e + "-")), None)
                if ev is not None:
                    by_event.setdefault(ev, []).append(ticker)
        for ev, wanted in by_event.items():
            for n in sorted(chunks[ev]):
                for mk in json.loads(z.read(n)).get("markets", []):
                    if mk.get("market_ticker") in wanted:
                        add(tickers[mk["market_ticker"]], mk.get("candlesticks", []))
    have = {r[0] for r in rows}
    missing = [t for t, mid in tickers.items() if mid not in have]
    df = pd.DataFrame(rows, columns=["market_id", "ts", "bid", "ask"])
    return df.drop_duplicates(["market_id", "ts"]).sort_values(["market_id", "ts"]).reset_index(drop=True), missing


# --------------------------------------------------------------------------------------
# step 5: checks specific to the college crosswalk
# --------------------------------------------------------------------------------------


def crosswalk_checks(games: pd.DataFrame, events: pd.DataFrame, cw: pd.DataFrame, leftover: pd.DataFrame,
                     table: pd.DataFrame, snaps: pd.DataFrame, missing_candles: list[str],
                     feed_dups: list[str] | None = None) -> list[dict[str, Any]]:
    c = nfl_checks._c
    out = []
    matched = cw[cw["status"] == "matched"]
    # game list
    dup = int(games["game_id"].duplicated().sum())
    last_kick = snaps.sort_values("snapshot_ts").groupby("event_id")["commence_time"].last()
    kick_bad = int((games.set_index("game_id")["kickoff_utc"] != last_kick.reindex(games["game_id"])).sum())
    out.append(c("game_list", "Game list: each played game once, final kickoff time", "fail" if dup or kick_bad else "pass",
                 f"{len(games)} games ({int(games['postseason'].sum())} postseason); {dup} duplicates; {kick_bad} not using "
                 f"the provider's final start time; {len(feed_dups or [])} duplicate listings in the odds feed dropped "
                 "(the listing the feed kept updating is kept).", "Checkpoints measured from a stale scheduled time."))
    # every game accounted
    counts = cw["reason_code"].value_counts().to_dict()
    bad = sorted(set(cw["reason_code"].dropna()) - set(REASONS))
    out.append(c("every_game_accounted", "Every game is matched or has a reason code",
                 "fail" if bad or cw["reason_code"].isna().any() else ("warn" if len(matched) < len(cw) else "pass"),
                 f"{counts}", "Games silently dropped from the comparison."))
    # one-to-one and markets
    reused = matched["kalshi_event_ticker"].value_counts()
    reused = int((reused > 1).sum())
    two = int((matched["kalshi_market_id_home"].isna() | (matched["kalshi_market_id_home"] == matched["kalshi_market_id_away"])).sum())
    out.append(c("one_to_one", "Each game has its own two Kalshi markets, one per team", "fail" if reused or two else "pass",
                 f"{len(matched)} matched games; {reused} Kalshi events used twice; {two} without two distinct markets.",
                 "Two games sharing one Kalshi event."))
    # learned team table. A wrong pairing (Oregon vs Oregon State) shows up as one school under two
    # different codes *and* names -> fail. Same code, two names = Kalshi renamed it (NC St. / North
    # Carolina St.); same name, two codes = Kalshi's code variants (M-OH / MOH) -> warning only.
    per_code = table.groupby("kalshi_code")["feed_name"].nunique()
    bad_code = per_code[per_code > 1].index.tolist()
    g = table.groupby("feed_name").agg(codes=("kalshi_code", "unique"), names=("kalshi_name", "unique"))
    wrong = g[(g["codes"].str.len() > 1) & (g["names"].str.len() > 1)].index.tolist()
    variants = {k: sorted(set(r.codes) | set(r.names)) for k, r in g.iterrows()
                if (len(r.codes) > 1) != (len(r.names) > 1)}
    out.append(c("team_table", "Learned team table: one school per Kalshi code, no school under two teams",
                 "fail" if bad_code or wrong else ("warn" if variants else "pass"),
                 f"{len(per_code)} Kalshi codes mapped to {len(g)} feed names; {len(bad_code)} codes with two schools "
                 f"{bad_code[:5]}; {len(wrong)} schools under two different Kalshi teams {wrong[:5]}."
                 + (f" Kalshi spelling/code variants of one team: {variants}." if variants else ""),
                 "A name match that paired a team with the wrong school (e.g. Oregon vs Oregon State)."))
    # match quality
    partial = matched[matched["match_score"] < 2]
    margin = (matched["match_score"] - matched["runner_up_score"]).min() if len(matched) else None
    out.append(c("name_match_quality", "Name matches are clear", "warn" if len(partial) else "pass",
                 f"{len(matched) - len(partial)} games with both names agreeing exactly, {len(partial)} partly "
                 f"(spelling differences, listed with match_score in crosswalk.csv); smallest lead over the runner-up "
                 f"{margin if margin is None else round(float(margin), 2)}.",
                 "Accepting a pairing that only half agrees."))
    # ticker dates
    off = matched[matched["date_diff_days"] != 0]
    out.append(c("ticker_dates", "Ticker dates match kickoff dates (Eastern)", "warn" if len(off) else "pass",
                 f"{len(off)} of {len(matched)} ticker dates differ by a day.", "Joining on UTC dates."))
    # leftovers
    lo = games["kickoff_utc"].min().tz_convert(EASTERN).date()
    hi = games["kickoff_utc"].max().tz_convert(EASTERN).date()
    inside = leftover[[d is not None and not pd.isna(d) and lo <= d <= hi for d in leftover["ticker_date"]]]
    out.append(c("kalshi_leftover", "Kalshi events not matched to a game", "warn" if len(inside) else "pass",
                 f"{len(leftover)} Kalshi events unmatched ({leftover['reason'].value_counts().to_dict()}); "
                 "listed in kalshi_events_unmatched.csv.", "Real games missing from the comparison."))
    out.append(c("candles_present", "Every matched market has candles", "warn" if missing_candles else "pass",
                 f"{len(missing_candles)} matched markets without a candle file" + (f": {missing_candles[:4]}" if missing_candles else "."),
                 "Kalshi prices silently missing for a matched game."))
    return out


# --------------------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------------------


def run(season: int, odds: Path = ODDS_ZIP, kalshi: Path | None = None, out_dir: Path = OUT_DIR,
        n_folder: Path = pl.OUT_DIR) -> int:
    kalshi = kalshi or KALSHI_ZIPS.get(season, KALSHI_ZIP)
    for path, what in ((kalshi, "Kalshi raw zip"), (odds, "odds zip")):
        if not Path(path).exists():
            print(f"Missing {what}: {path}. Put it there (exact name) and run again; nothing was written.",
                  file=sys.stderr)
            return 2
    snaps, feed_dups = drop_feed_duplicates(load_odds(odds))
    games = game_list(snaps, season)
    markets = load_kalshi_markets(kalshi)
    events = kalshi_events(markets, season) if len(markets) else pd.DataFrame(columns=["event_ticker", "ticker_date", "parse_reason"])
    if events.empty:
        cw = games.assign(status="unmatched", reason_code="no_kalshi_data")
        leftover, table = events, pd.DataFrame(columns=["kalshi_code", "kalshi_name", "feed_name", "games"])
    else:
        cw, leftover, _ = crosswalk(games, events)
        table = team_table(cw)
    m = cw[cw["status"] == "matched"]
    tickers = {**dict(zip(m["kalshi_ticker_home"], m["kalshi_market_id_home"].astype(int))),
               **dict(zip(m["kalshi_ticker_away"], m["kalshi_market_id_away"].astype(int)))}
    candles, missing = load_candles(tickers, kalshi) if tickers else (pd.DataFrame(columns=["market_id", "ts", "bid", "ask"]), [])
    snap = pl.snapshots(cw, snaps[snaps["event_id"].isin(set(m["game_id"]))], candles)
    codes = {**dict(zip(zip(m["game_id"], m["home"]), m["kalshi_code_home"])),
             **dict(zip(zip(m["game_id"], m["away"]), m["kalshi_code_away"]))}
    snap["team_code"] = [codes.get((g, t)) for g, t in zip(snap["game_id"], snap["team"])]
    # college trade sizes (make trade-sizes LEAGUE=ncaaf) when pulled, otherwise the NFL sizes, labelled
    n_list, n_src = costs_mod.n_values(season, out_dir, groups=("KXNCAAFGAME", "all college markets"))
    if "placeholder" in n_src:
        n_list, n_src = costs_mod.n_values(season, n_folder)
        if "placeholder" not in n_src:
            n_src = f"NFL {n_src} (no college trade sizes pulled)"
    else:
        n_src = f"college {n_src}"
    costs = costs_mod.compute(snap, season, n_list, n_src)

    results = crosswalk_checks(games, events, cw, leftover, table, snaps, missing, feed_dups)
    if not snap.empty:
        results += nfl_checks._snapshot_checks(snap, candles, snaps, m)
    results += nfl_checks.cost_checks(costs, snap, m)

    folder = out_dir / str(season)
    folder.mkdir(parents=True, exist_ok=True)
    cw.to_csv(folder / "crosswalk.csv", index=False)
    snap.to_csv(folder / "snapshots.csv", index=False)
    # college costs are ~80 MB as plain CSV; gzip keeps it pushable (pandas reads .csv.gz directly)
    (folder / "costs.csv").unlink(missing_ok=True)
    costs.to_csv(folder / "costs.csv.gz", index=False, compression="gzip")
    table.to_csv(folder / "team_table.csv", index=False)
    leftover.to_csv(folder / "kalshi_events_unmatched.csv", index=False)
    (folder / "checks.json").write_text(json.dumps(results, indent=2, default=str))
    summary = pl.summary(season, cw, leftover, snap, results, costs).replace(
        f"# Alignment, {season} season", f"# College football (NCAAF) alignment, {season} season")
    (folder / "summary.md").write_text(summary)

    tally = {s: sum(c["status"] == s for c in results) for s in ("pass", "warn", "skip", "fail")}
    print(f"NCAAF {season}: {len(games)} games, {len(m)} matched, {len(snap)} snapshot rows, {len(costs)} cost rows; "
          "checks " + ", ".join(f"{n} {s}" for s, n in tally.items() if n))
    for c in results:
        if c["status"] in ("warn", "fail"):
            print(f"  {c['status'].upper()} {c['title']}: {c['detail'][:400]}")
    print(f"files: {folder}")
    return 1 if tally["fail"] else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="College football Kalshi vs sportsbook alignment for one season.")
    p.add_argument("--season", type=int, required=True)
    p.add_argument("--odds", type=Path, default=ODDS_ZIP, help="odds_data.zip (or the ncaaf history CSV)")
    p.add_argument("--kalshi", type=Path, default=None,
                   help="raw Kalshi zip (default: data/kalshi_raw_2025_season_nfl_ncaaf.zip for 2025, "
                        "data/kalshi_raw_2026_college_ncaaf.zip for 2026)")
    a = p.parse_args(argv)
    return run(a.season, a.odds, a.kalshi)


if __name__ == "__main__":
    raise SystemExit(main())
