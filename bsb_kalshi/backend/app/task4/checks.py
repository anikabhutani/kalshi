"""Self-checks for Task 4, run on every report for every season.

Each check recomputes something a second way, independently of the pipeline that produced it,
and says which earlier mistake it guards against. A check returns one of:

- ``pass``: the result holds.
- ``warn``: the result is usable but something is incomplete (e.g. Kalshi covers fewer games).
- ``fail``: a number in the results or charts cannot be trusted; the report exits with code 1.
- ``skip``: nothing to check (e.g. no Kalshi data for this season).
"""

from __future__ import annotations

from fractions import Fraction
from math import sqrt
from typing import Any

import numpy as np
import pandas as pd

from app.task4.common import BOOKS, MARKETS, REGULAR_SEASON_WEEKS, season_start, week_label
from app.task4.sportsbook_costs import CLOSING_MAX_MINUTES

PLAYOFF_GAMES = {"Wild Card": 6, "Divisional": 4, "Conference": 2, "Super Bowl": 1}
TOL = 1e-6


def _check(cid: str, title: str, status: str, detail: str, guards: str) -> dict[str, Any]:
    return {"id": cid, "title": title, "status": status, "detail": detail, "guards": guards}


def _prob(american: float) -> Fraction:
    """Implied probability as an exact fraction (independent of the pipeline's float code)."""
    a = Fraction(int(round(american)))
    return Fraction(100) / (a + 100) if a > 0 else -a / (-a + 100)


def run_checks(season: int, t: dict[str, pd.DataFrame], rs: dict[str, pd.DataFrame], facts: dict,
               games: pd.DataFrame, manifest: dict, r_all: dict[str, pd.DataFrame]) -> list[dict]:
    out: list[dict] = []
    snaps = t["costs_all_snapshots"]
    pre = snaps[snaps["pre_kickoff"] & ~snaps["has_bad_odds"]]
    full = rs["markets"]  # unrounded (the published CSV is rounded to 6 decimals)
    pre_full = full[full["pre_kickoff"] & ~full["has_bad_odds"]]
    sides_raw = rs["sides_raw"]

    # 1. Odds -> implied probability, exactly, from the raw American odds
    priced = sides_raw.dropna(subset=["price_american"])
    exact = np.array([float(_prob(a)) for a in priced["price_american"]])
    diff = float(np.max(np.abs(exact - priced["p_implied"].to_numpy()))) if len(priced) else 0.0
    out.append(_check(
        "odds_conversion", "Odds converted to probabilities correctly",
        "pass" if diff < 1e-12 else "fail",
        f"{len(priced):,} prices recomputed with exact fractions; largest difference {diff:.1e}.",
        "Any slip in turning American odds into chances."))

    # 2. Shin fair prices: sum to 1, and inverting Shin's formula gives back the book's prices
    allm = rs["markets"]
    allm = allm[allm["p_implied_a"].notna() & allm["p_implied_b"].notna()]
    unsolved = allm[allm["fair_a"].isna()]
    unsolved_used = int((unsolved["pre_kickoff"] & ~unsolved["has_bad_odds"]).sum())
    m = allm[allm["fair_a"].notna()]
    s = m["p_implied_a"] + m["p_implied_b"]
    z = m["shin_z"]
    rec_a = np.sqrt(s * (z * m["fair_a"] + (1 - z) * m["fair_a"] ** 2))
    rec_b = np.sqrt(s * (z * m["fair_b"] + (1 - z) * m["fair_b"] ** 2))
    sum_err = float((m["fair_a"] + m["fair_b"] - 1).abs().max()) if len(m) else 0.0
    inv_err = float(max((rec_a - m["p_implied_a"]).abs().max(), (rec_b - m["p_implied_b"]).abs().max())) \
        if len(m) else 0.0
    z_bad = int(((z < 0) | (z >= 0.25)).sum())
    ok = sum_err < 1e-9 and inv_err < 1e-9 and z_bad == 0 and unsolved_used == 0
    out.append(_check(
        "shin_valid", "Fair prices are valid (Shin's method)", "pass" if ok else "fail",
        f"{len(m):,} market snapshots: fair chances sum to 1 (worst {sum_err:.1e}); rebuilding the book's "
        f"prices from them matches (worst {inv_err:.1e}); {z_bad} with an out-of-range Shin z. "
        f"{len(unsolved)} could not be solved (e.g. suspended in-game lines), {unsolved_used} of them "
        f"pre-game.",
        "A wrong de-vig formula, which would skew every cost."))

    # 3. Cost per $10 recomputed from the raw odds and the fair price
    def cost(f, a):
        return 10 * (1 - f / float(_prob(a)))
    rec = [(cost(r.fair_a, r.price_american_a) + cost(r.fair_b, r.price_american_b)) / 2
           for r in pre_full.itertuples()]
    cdiff = float(np.max(np.abs(np.array(rec) - pre_full["cost_per_10"].to_numpy()))) if len(pre_full) else 0.0
    pub = float((pre_full.set_index(["event_id", "snapshot_ts", "bookmaker", "market"])["cost_per_10"].round(6)
                 .sort_index().to_numpy() - pre.assign(snapshot_ts=pd.to_datetime(pre["snapshot_ts"], utc=True))
                 .set_index(["event_id", "snapshot_ts", "bookmaker", "market"])["cost_per_10"].sort_index()
                 .to_numpy()).__abs__().max()) if len(pre) else 0.0
    out.append(_check(
        "cost_recompute", "Cost per $10 recomputed independently",
        "pass" if cdiff < 1e-9 and pub < 1e-9 else "fail",
        f"{len(pre_full):,} pre-kickoff market snapshots recomputed from the raw odds; largest difference "
        f"${cdiff:.1e}; published table matches to 6 decimals (worst ${pub:.1e}).", "Errors in the cost formula or in averaging a bet's two sides."))

    # 4. In every lopsided market the longshot side costs more than the favorite side
    lop = pre_full[(pre_full["fair_a"] - pre_full["fair_b"]).abs() > 0.02]
    long_is_a = lop["fair_a"] < lop["fair_b"]
    long_cost = np.where(long_is_a, lop["cost_a_per_10"], lop["cost_b_per_10"])
    fav_cost = np.where(long_is_a, lop["cost_b_per_10"], lop["cost_a_per_10"])
    # strictly more: under the old proportional method both sides cost exactly the same
    bad = int((long_cost <= fav_cost + 1e-6).sum())
    out.append(_check(
        "longshot_costs_more", "Longshot side costs more than the favorite side",
        "pass" if bad == 0 and len(lop) else ("fail" if bad else "skip"),
        f"{len(lop):,} lopsided market snapshots; {bad} where the longshot side did not cost more.",
        "The earlier mistake: the proportional method charged both sides the same, hiding the "
        "favorite/longshot difference."))

    # 5. Price groups are not mirror images of each other (the visible symptom of that mistake)
    pg = t["by_price_group"]
    pg = pg[(pg["market"] == "h2h") & pg["bookmaker"].isin(BOOKS)].set_index(["bookmaker", "price_group"])["mean"]
    mirrored = []
    for book in BOOKS:
        for lo, hi in (("<25%", ">75%"), ("25-40%", "60-75%")):
            if (book, lo) in pg.index and (book, hi) in pg.index and abs(pg[(book, lo)] - pg[(book, hi)]) < 0.005:
                mirrored.append(f"{book} {lo} = {hi}")
    out.append(_check(
        "groups_not_mirrored", "Price groups are not mirror images", "fail" if mirrored else "pass",
        ("Identical: " + ", ".join(mirrored)) if mirrored else
        "Opposite price groups (<25% vs >75%, 25-40% vs 60-75%) differ at every sportsbook.",
        "Your partner's catch: <25% and >75% bars showing the same cost."))

    # 6. Headline table recomputed with an independent closing-line selection
    idx = pre.groupby(["event_id", "bookmaker", "market"])["snapshot_ts"].idxmax()
    close2 = pre.loc[idx]
    close2 = close2[close2["minutes_to_kickoff"] <= CLOSING_MAX_MINUTES]
    rec_bm = close2.groupby(["bookmaker", "market"])["cost_per_10"].agg(["mean", "count"])
    bm = t["by_book_market"]
    bm = bm[bm["bookmaker"].isin(BOOKS)].set_index(["bookmaker", "market"])
    joined = bm.join(rec_bm, rsuffix="_rec", how="outer")
    worst = float((joined["mean"] - joined["mean_rec"]).abs().max()) if len(joined) else 0.0
    n_bad = int((joined["n"] != joined["count"]).sum())
    out.append(_check(
        "headline_recompute", "Headline table recomputed", "pass" if worst < 1e-4 and n_bad == 0 else "fail",
        f"{len(joined)} book/bet averages rebuilt from every snapshot; largest difference ${worst:.1e}, "
        f"{n_bad} with a different game count.", "Wrong closing-line picks or averaging."))

    # 7. Every game of the season is in the results, and in the games list and manifest
    close = t["_close"]
    qc = rs["qc"]
    stale = qc[qc["check"] == "stale_closing_line"]
    stale_keys: dict = {}
    for e, b, mk in zip(stale["event_id"], stale["bookmaker"], stale["market"]):
        stale_keys.setdefault((b, mk), set()).add(e)
    in_results = set(close["event_id"])
    in_games = set(games["event_id"])
    in_manifest = {e for e, g in manifest.get("games", {}).items() if g.get("season") == season}
    posted = []
    for book in BOOKS:
        for mk in MARKETS:
            col = f"{book} {mk}"
            if col in games:
                want = set(games.loc[games[col] == "yes", "event_id"])
                have = set(close.loc[(close["bookmaker"] == book) & (close["market"] == mk), "event_id"])
                missing = want - have - stale_keys.get((book, mk), set())
                if missing:
                    posted.append(f"{col}: {len(missing)}")
    # A game with no price in its last hour at any book is correctly left out (it shows up in the
    # quality check as stale); anything else missing is an error.
    stale_games = set(stale["event_id"]) - in_results
    unexplained = ((in_games | in_manifest) - in_results - stale_games) | (in_results - in_games) \
        | (in_results - in_manifest) | (in_games ^ in_manifest)
    ok = not unexplained and not posted
    out.append(_check(
        "all_games_included", "Every game is in the results", "pass" if ok else "fail",
        f"{len(in_results)} in results, {len(in_games)} in the games list, {len(in_manifest)} saved by the "
        f"backfill" + (f"; {len(stale_games)} left out because no book priced them in the last hour"
                       if stale_games else "")
        + (f"; missing closing lines: {', '.join(posted)}" if posted else "")
        + (f"; {len(unexplained)} games unaccounted for" if unexplained else ""),
        "Games silently dropped (like the Kalshi game lost to a too-tight time window)."))

    # 7b. Closing lines are from the last hour before kickoff
    too_old = int((close["minutes_to_kickoff"] > CLOSING_MAX_MINUTES).sum())
    out.append(_check(
        "closing_fresh", f"Closing lines are from the last {CLOSING_MAX_MINUTES} minutes",
        "fail" if too_old else ("warn" if len(stale) else "pass"),
        f"Closing lines used are {facts['closing_minutes_min']:g}-{facts['closing_minutes_max']:g} min before "
        f"kickoff; {too_old} older than {CLOSING_MAX_MINUTES} min. "
        + (f"{len(stale)} book/bet lines whose last price was older were left out "
           f"({stale['event_id'].nunique()} games; listed in the quality check)." if len(stale) else
           "No lines had to be left out."),
        "A day-old price being counted as a closing line."))

    # 8. No live (after kickoff) prices
    live_close = int((close["minutes_to_kickoff"] < 0).sum())
    live_rows = int((~rs["markets"]["pre_kickoff"]).sum())
    out.append(_check(
        "no_live_prices", "No in-game prices in the results", "pass" if live_close == 0 else "fail",
        f"{live_rows} snapshots taken after kickoff were excluded; {live_close} reached a closing line.",
        "Live in-game odds mixed into pre-game costs."))

    # 9. Season isolation
    start = pd.Timestamp(season_start(season)).tz_localize("America/New_York")
    end = pd.Timestamp(season_start(season + 1)).tz_localize("America/New_York")
    kick = rs["markets"]["commence_time"]
    outside = int(((kick < start) | (kick >= end)).sum())
    other = r_all["markets"]
    shared = set(other.loc[other["season"] != season, "event_id"]) & in_results
    multi = int((rs["markets"].groupby("event_id")["season"].nunique() > 1).sum())
    ok = outside == 0 and not shared and multi == 0
    out.append(_check(
        "season_isolation", "Only this season's games", "pass" if ok else "fail",
        f"{outside} snapshots dated outside {start:%b %d, %Y} - {end:%b %d, %Y}; {len(shared)} games also in "
        f"another season; {multi} games with two seasons.", "One season's games leaking into the other's charts."))

    # 10. Week labels match the NFL calendar
    wk = games.groupby("week").size()
    issues = []
    if len(wk) and int(wk.index.min()) < 1:
        issues.append("a week before week 1")
    if len(wk) and int(wk.index.max()) > REGULAR_SEASON_WEEKS + 5:
        issues.append("a week past the Super Bowl")
    reg = wk[wk.index <= REGULAR_SEASON_WEEKS]
    if (reg > 16).any():
        issues.append("a regular-season week with more than 16 games")
    first_game_week = int(games.sort_values("commence_time")["week"].iloc[0]) if len(games) else 1
    if first_game_week != 1:
        issues.append(f"the opener is in week {first_game_week}")
    rounds = games[games["week"] > REGULAR_SEASON_WEEKS]["week"].map(week_label).value_counts()
    status = "fail" if issues else "pass"
    round_note = ""
    if len(rounds):
        wrong = {r: int(rounds.get(r, 0)) for r, n in PLAYOFF_GAMES.items() if rounds.get(r, 0) != n}
        if wrong:
            status = "warn" if status == "pass" else status
            round_note = f" Playoff rounds not complete: {wrong} (expected {PLAYOFF_GAMES})."
        else:
            round_note = " Playoff rounds complete: 6, 4, 2, 1 games."
    out.append(_check(
        "weeks", "Weeks match the NFL calendar", status,
        (("; ".join(issues) + ".") if issues else
         f"{len(reg)} regular-season weeks, at most {int(reg.max()) if len(reg) else 0} games each; the opener "
         f"is in week 1.") + round_note,
        "Games put in the wrong week (or playoffs mixed into week numbers)."))

    # 11. Every count a chart note quotes matches the tables
    mism = []
    if facts["games"] != len(in_results):
        mism.append("game count")
    tk = t["by_time_to_kickoff"]
    for book, buckets in facts["time_bucket_games"].items():
        tab = tk[(tk["bookmaker"] == book) & (tk["market"] == "h2h")].set_index("time_bucket")["games"]
        if {str(k): int(v) for k, v in tab.items()} != buckets:
            mism.append(f"{book} time buckets")
    pgt = t["by_price_group"]
    for book, groups in facts["price_group_sides"].items():
        tab = pgt[(pgt["bookmaker"] == book) & (pgt["market"] == "h2h")].set_index("price_group")["n"]
        if {str(k): int(v) for k, v in tab.items()} != groups:
            mism.append(f"{book} price groups")
    if sum(w["games"] for w in facts["weeks"]) != len(games):
        mism.append("weekly game counts")
    mins = close["minutes_to_kickoff"]
    if len(mins) and (round(float(mins.min()), 1) != facts["closing_minutes_min"]
                      or round(float(mins.max()), 1) != facts["closing_minutes_max"]):
        mism.append("closing-line window")
    out.append(_check(
        "notes_match_data", "Chart notes match the data", "fail" if mism else "pass",
        ("Mismatch: " + ", ".join(mism)) if mism else
        f"Game counts, time-bucket coverage, price-group sizes, weekly counts and the closing window "
        f"({facts['closing_minutes_min']:g}-{facts['closing_minutes_max']:g} min) all match the tables.",
        "Typed-in notes going stale (the wrong FanDuel coverage note, '80 games' on another season)."))

    # 11b. One kickoff per game: the provider's final start time
    raw = rs["sides_raw"]
    per_game = raw.groupby("event_id")["commence_time"].nunique()
    last_listed = raw.sort_values("snapshot_ts").groupby("event_id")["commence_time_listed"].last()
    used = raw.groupby("event_id")["commence_time"].first()
    wrong = int((per_game > 1).sum() + (used != last_listed.reindex(used.index)).sum())
    moved = (raw.groupby("event_id")["commence_time_listed"].agg(lambda x: (x.max() - x.min()).total_seconds() / 60))
    out.append(_check(
        "kickoff_final", "Times measured from each game's final start time", "fail" if wrong else "pass",
        f"{wrong} games with more than one kickoff time in use. The provider moved the start time of "
        f"{int((moved > 0).sum())} games (by more than an hour: {int((moved > 60).sum())}).",
        "Early snapshots of rescheduled games landing in the wrong time bucket (up to a day off)."))

    # 12. Bad odds kept out of the results
    bad_in_close = int(close["has_bad_odds"].sum()) if "has_bad_odds" in close else 0
    n_bad_odds = int(rs["qc"]["check"].str.startswith("bad_odds").sum())
    out.append(_check(
        "bad_odds_excluded", "Broken odds kept out", "pass" if bad_in_close == 0 else "fail",
        f"{n_bad_odds} broken prices found by the quality check; {bad_in_close} reached the results.",
        "Impossible prices feeding into averages."))

    # 13. Kalshi coverage (from Task 3)
    k = facts["kalshi"]
    if not k.get("available"):
        out.append(_check("kalshi_coverage", "Kalshi covers this season's games", "skip",
                          k.get("note", "No Kalshi data."), "Kalshi bars built from only part of the season."))
    else:
        cov = k.get("games_by_market", {})
        short = {mk: n for mk, n in cov.items() if n < facts["games"]}
        out.append(_check(
            "kalshi_coverage", "Kalshi covers this season's games", "warn" if short else "pass",
            f"Kalshi games per bet type: {cov} of {facts['games']}."
            + (" Kalshi bars average fewer games than the sportsbook bars." if short else ""),
            "Kalshi bars built from only part of the season."))
    return out
