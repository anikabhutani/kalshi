"""Vig and cost per $10 for every game, book, market and snapshot, plus a data quality check.

Definitions
-----------
Implied probability of American odds A: 100/(A+100) if A >= +100, else -A/(-A+100).
For a two-sided market with implied probabilities p_a and p_b (they sum to more than 1):

- overround (vig) = p_a + p_b - 1
- fair (no-vig) probability: Shin's method (Shin 1993), the standard de-vig in betting research.
  It lets the margin fall unevenly, more of it on the longshot, which is what the
  favorite-longshot bias says bookmakers do:
      fair_i = (sqrt(z^2 + 4 (1 - z) p_i^2 / (p_a + p_b)) - z) / (2 (1 - z)),
  with z (0 <= z < 1) solved so the two fair probabilities sum to 1.
- cost per $10 on side i = expected loss on a $10 bet at the fair probability
                         = 10 * (1 - fair_i * decimal_i) = 10 * (1 - fair_i / p_i)
- cost per $10 of a market = the average of its two sides (a bettor taking either side).

Why not the simpler proportional method (fair_i = p_i / (p_a + p_b))? It charges both sides of
every bet exactly the same, 10 * (1 - 1 / (p_a + p_b)), so a "<25%" side and the ">75%" side of
the same game always show the same cost: the method hides any favorite/longshot difference by
construction. Proportional results are kept in ``*_proportional`` columns as a check.

The data has no game results, so which de-vig method is right cannot be tested here; Shin's is
an assumption backed by the research, and the Pinnacle comparison below is the outside check.
Each DraftKings and FanDuel side is also priced against Pinnacle's Shin fair probability for the
same side, at the same snapshot and the same line (``cost_vs_pinnacle_per_10``). Pinnacle as
the sharp reference is itself an assumption.

Snapshot buckets use minutes from the snapshot to kickoff. Snapshots taken after kickoff are
live in-game lines; they are excluded from costs and reported by the quality check.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.task4.common import nfl_season, nfl_week, parse_times

STAKE = 10.0
PRICE_GROUPS = [0.0, 0.25, 0.40, 0.60, 0.75, 1.0]
PRICE_GROUP_LABELS = ["<25%", "25-40%", "40-60%", "60-75%", ">75%"]
TIME_BUCKETS = [0, 60, 1440, 3 * 1440, 7 * 1440, np.inf]
TIME_BUCKET_LABELS = ["under 1 h", "1-24 h", "1-3 days", "3-7 days", "7+ days"]

# Quality check thresholds
STALE_MINUTES = 60
CLOSING_MAX_MINUTES = 60  # a closing line must be from the last hour before kickoff
MAX_OVERROUND = 0.12
OFF_MARKET_PROB = 0.05  # moneyline: Pinnacle fair prob vs DK/FD average
OFF_MARKET_POINTS = 1.5  # spreads/totals: Pinnacle line vs both DK and FD


def american_to_prob(a: pd.Series) -> pd.Series:
    a = a.astype(float)
    out = pd.Series(np.nan, index=a.index)
    pos = a >= 100
    neg = a <= -100
    out[pos] = 100.0 / (a[pos] + 100.0)
    out[neg] = -a[neg] / (-a[neg] + 100.0)
    return out


def american_to_decimal(a: pd.Series) -> pd.Series:
    a = a.astype(float)
    out = pd.Series(np.nan, index=a.index)
    pos = a >= 100
    neg = a <= -100
    out[pos] = 1.0 + a[pos] / 100.0
    out[neg] = 1.0 + 100.0 / -a[neg]
    return out


def prepare(snapshots: pd.DataFrame) -> pd.DataFrame:
    """Typed side-level rows with the side label (home/away/over/under) and timing."""
    s = parse_times(snapshots)
    # The provider updates a game's start time as kickoff nears (usually by minutes; for flexed
    # late-season games by up to a day). Every row uses the game's final start time, so "time
    # before kickoff" means the same thing for an early snapshot as for a late one.
    s["commence_time_listed"] = s["commence_time"]
    final = s.sort_values("snapshot_ts").groupby("event_id")["commence_time"].last()
    s["commence_time"] = s["event_id"].map(final)
    for col in ("point", "price_american", "price_decimal", "implied_prob"):
        s[col] = pd.to_numeric(s[col].replace("", np.nan), errors="coerce")
    s["side"] = np.select(
        [
            s["market"] == "totals",
            s["outcome"] == s["home_team"],
            s["outcome"] == s["away_team"],
        ],
        [s["outcome"].str.lower(), "home", "away"],
        default="unknown",
    )
    s["p_implied"] = american_to_prob(s["price_american"])
    s["decimal_calc"] = american_to_decimal(s["price_american"])
    s["minutes_to_kickoff"] = (s["commence_time"] - s["snapshot_ts"]).dt.total_seconds() / 60
    s["season"] = nfl_season(s["commence_time"])
    s["week"] = nfl_week(s["commence_time"])
    return s


MARKET_KEY = ["event_id", "snapshot_ts", "bookmaker", "market"]


def shin_two_way(p_a, p_b, iterations: int = 80):
    """Shin fair probabilities for two-way markets (arrays in, arrays out) and Shin's z.

    Bisection on z in [0, 0.5]: the fair probabilities fall as z rises, and z is the value at
    which they sum to 1. A market with no overround gets z = 0 and fair = implied.
    """
    p_a = np.asarray(p_a, dtype=float)
    p_b = np.asarray(p_b, dtype=float)
    total = p_a + p_b

    def fair(z, p):
        return (np.sqrt(z ** 2 + 4 * (1 - z) * p ** 2 / total) - z) / (2 * (1 - z))

    lo = np.zeros_like(total)
    hi = np.full_like(total, 0.5)
    for _ in range(iterations):
        z = (lo + hi) / 2
        too_low = fair(z, p_a) + fair(z, p_b) < 1
        hi = np.where(too_low, z, hi)
        lo = np.where(too_low, lo, z)
    z = (lo + hi) / 2
    fa, fb = fair(z, p_a), fair(z, p_b)
    # Markets Shin cannot solve (e.g. a suspended in-play line priced -100000/-100000) get no fair
    # price rather than a wrong one.
    unsolved = ~(np.abs(fa + fb - 1) < 1e-9)
    fa, fb, z = (np.where(unsolved, np.nan, x) for x in (fa, fb, z))
    return fa, fb, z


def market_snapshots(sides: pd.DataFrame) -> pd.DataFrame:
    """One row per game/book/market/snapshot with both sides, vig and cost per $10."""
    first = {"h2h": "home", "spreads": "home", "totals": "over"}
    s = sides.copy()
    s["slot"] = np.where(s["side"] == s["market"].map(first), "a", "b")
    keep = ["price_american", "point", "p_implied", "decimal_calc", "outcome"]
    wide = s.pivot_table(index=MARKET_KEY, columns="slot", values=keep, aggfunc="first")
    wide.columns = [f"{v}_{slot}" for v, slot in wide.columns]
    wide = wide.reset_index()
    meta = s.drop_duplicates(MARKET_KEY)[
        MARKET_KEY + ["snapshot_type", "commence_time", "home_team", "away_team",
                      "minutes_to_kickoff", "season", "week", "market_last_update"]
    ]
    m = wide.merge(meta, on=MARKET_KEY, how="left")
    total = m["p_implied_a"] + m["p_implied_b"]
    m["overround"] = total - 1
    m["fair_a"], m["fair_b"], m["shin_z"] = shin_two_way(m["p_implied_a"], m["p_implied_b"])
    m["cost_a_per_10"] = STAKE * (1 - m["fair_a"] / m["p_implied_a"])
    m["cost_b_per_10"] = STAKE * (1 - m["fair_b"] / m["p_implied_b"])
    m["cost_per_10"] = (m["cost_a_per_10"] + m["cost_b_per_10"]) / 2
    m["fair_a_proportional"] = m["p_implied_a"] / total
    m["fair_b_proportional"] = m["p_implied_b"] / total
    m["cost_per_10_proportional"] = STAKE * (1 - 1 / total)
    m["pre_kickoff"] = m["minutes_to_kickoff"] >= 0
    m["time_bucket"] = pd.cut(
        m["minutes_to_kickoff"], TIME_BUCKETS, labels=TIME_BUCKET_LABELS, right=True,
        include_lowest=True,
    )
    return m


def closing_lines(markets: pd.DataFrame) -> pd.DataFrame:
    """Last pre-kickoff snapshot per game, book and market, if it is within the last hour.

    A book whose last price before kickoff is older than ``CLOSING_MAX_MINUTES`` has no closing
    line for that game (the quality check lists it as ``stale_closing_line``): a price from the
    day before is not a closing line.
    """
    pre = markets[markets["pre_kickoff"]].sort_values("snapshot_ts")
    last = pre.groupby(["event_id", "bookmaker", "market"], as_index=False).tail(1)
    return last[last["minutes_to_kickoff"] <= CLOSING_MAX_MINUTES]


def stale_closing(markets: pd.DataFrame) -> pd.DataFrame:
    """Game/book/market whose last pre-kickoff price is older than ``CLOSING_MAX_MINUTES``."""
    pre = markets[markets["pre_kickoff"]].sort_values("snapshot_ts")
    last = pre.groupby(["event_id", "bookmaker", "market"], as_index=False).tail(1)
    return last[last["minutes_to_kickoff"] > CLOSING_MAX_MINUTES]


def side_rows(markets: pd.DataFrame) -> pd.DataFrame:
    """Each market snapshot split into its two sides, with the Pinnacle-referenced cost."""
    rows = []
    for slot, other in (("a", "b"), ("b", "a")):
        part = markets[MARKET_KEY + ["market_snapshot_id", "season", "week", "minutes_to_kickoff",
                                     "time_bucket", "pre_kickoff", "overround",
                                     "cost_per_10_proportional"]].copy()
        part["side_slot"] = slot
        part["outcome"] = markets[f"outcome_{slot}"]
        part["point"] = markets[f"point_{slot}"]
        part["price_american"] = markets[f"price_american_{slot}"]
        part["decimal"] = markets[f"decimal_calc_{slot}"]
        part["fair_prob"] = markets[f"fair_{slot}"]
        part["fair_prob_proportional"] = markets[f"fair_{slot}_proportional"]
        part["cost_per_10"] = markets[f"cost_{slot}_per_10"]
        rows.append(part)
    sides = pd.concat(rows, ignore_index=True)

    pin = sides[sides["bookmaker"] == "Pinnacle"][
        ["event_id", "snapshot_ts", "market", "side_slot", "point", "fair_prob", "fair_prob_proportional"]
    ].rename(columns={"point": "pin_point", "fair_prob": "pin_fair_prob",
                      "fair_prob_proportional": "pin_fair_prob_proportional"})
    sides = sides.merge(pin, on=["event_id", "snapshot_ts", "market", "side_slot"], how="left")
    same_line = (sides["market"] == "h2h") | (sides["point"] == sides["pin_point"])
    sides["cost_vs_pinnacle_per_10"] = np.where(
        same_line & sides["pin_fair_prob"].notna(),
        STAKE * (1 - sides["pin_fair_prob"] * sides["decimal"]),
        np.nan,
    )
    sides["cost_vs_pinnacle_proportional"] = np.where(
        same_line & sides["pin_fair_prob_proportional"].notna(),
        STAKE * (1 - sides["pin_fair_prob_proportional"] * sides["decimal"]),
        np.nan,
    )
    sides["price_group"] = pd.cut(
        sides["fair_prob"], PRICE_GROUPS, labels=PRICE_GROUP_LABELS, include_lowest=True
    )
    sides["role"] = np.where(
        sides["market"] != "h2h", "n/a",
        np.where(sides["fair_prob"] > 0.5, "favorite", "underdog"),
    )
    return sides


# --------------------------------------------------------------------------------------
# Quality check
# --------------------------------------------------------------------------------------


def quality_check(sides: pd.DataFrame, markets: pd.DataFrame) -> pd.DataFrame:
    """One row per issue found. Checks are listed in ``QC_CHECKS``."""
    issues: list[pd.DataFrame] = []

    def add(check: str, df: pd.DataFrame, detail: pd.Series | str) -> None:
        if df.empty:
            return
        out = df[["event_id", "bookmaker", "market", "snapshot_ts"]].copy()
        out.insert(0, "check", check)
        out["detail"] = detail if isinstance(detail, str) else detail.loc[df.index].values
        issues.append(out)

    # Bad odds
    bad = sides[sides["p_implied"].isna()]
    add("bad_odds_invalid_american", bad, "American odds missing or between -100 and +100")
    dec_gap = (sides["decimal_calc"] - sides["price_decimal"]).abs()
    mism = sides[dec_gap > 0.01]
    add("bad_odds_decimal_mismatch", mism,
        "decimal " + mism["price_decimal"].astype(str) + " vs American " +
        mism["price_american"].astype(str))
    prob_gap = (sides["p_implied"] - sides["implied_prob"]).abs()
    pm = sides[prob_gap > 0.001]
    add("bad_odds_implied_prob_mismatch", pm,
        "file " + pm["implied_prob"].astype(str) + " vs computed " + pm["p_implied"].round(4).astype(str))
    unk = sides[sides["side"] == "unknown"]
    add("bad_odds_unknown_outcome", unk, "outcome name matches neither team")

    pre = markets[markets["pre_kickoff"]]
    neg = pre[pre["overround"] < 0]
    add("bad_odds_negative_vig", neg, "overround " + neg["overround"].round(4).astype(str))
    high = pre[pre["overround"] > MAX_OVERROUND]
    add("bad_odds_vig_above_12pct", high, "overround " + high["overround"].round(4).astype(str))
    sp = pre[(pre["market"] == "spreads") & (pre["point_a"] != -pre["point_b"])]
    add("bad_odds_spread_points_not_opposite", sp,
        sp["point_a"].astype(str) + " / " + sp["point_b"].astype(str))
    tt = pre[(pre["market"] == "totals") & (pre["point_a"] != pre["point_b"])]
    add("bad_odds_total_points_differ", tt,
        tt["point_a"].astype(str) + " / " + tt["point_b"].astype(str))

    # Post-kickoff snapshots
    live = markets[~markets["pre_kickoff"]]
    add("post_kickoff_snapshot_excluded", live,
        (-live["minutes_to_kickoff"]).round(0).astype(int).astype(str) + " min after kickoff")

    # Missing Pinnacle: a snapshot where DK or FD posted the market and Pinnacle did not
    posted = pre.groupby(["event_id", "snapshot_ts", "market"])["bookmaker"].agg(set)
    no_pin = posted[posted.map(lambda b: "Pinnacle" not in b and bool(b & {"DraftKings", "FanDuel"}))]
    if len(no_pin):
        df = no_pin.reset_index()
        df["bookmaker"] = "Pinnacle"
        add("missing_pinnacle_line", df, "DK/FD posted, Pinnacle did not")
    closing = closing_lines(markets)
    have = set(zip(closing["event_id"], closing["market"], closing["bookmaker"]))
    games = closing[["event_id", "market"]].drop_duplicates()
    miss_close = games[[(e, m, "Pinnacle") not in have for e, m in zip(games["event_id"], games["market"])]]
    if len(miss_close):
        df = miss_close.assign(bookmaker="Pinnacle", snapshot_ts=pd.NaT)
        add("missing_pinnacle_closing_line", df,
            f"no Pinnacle line in the last {CLOSING_MAX_MINUTES} min before kickoff")
    stale = stale_closing(markets)
    add("stale_closing_line", stale,
        "last price before kickoff was " + (stale["minutes_to_kickoff"] / 60).round(1).astype(str)
        + " h old; left out of closing-line results")

    # Stale lines
    lag = (pre["snapshot_ts"] - pre["market_last_update"]).dt.total_seconds() / 60
    stale = pre[lag > STALE_MINUTES]
    add("stale_line_last_update", stale,
        "book last updated this line " + lag.loc[stale.index].round(0).astype(int).astype(str) +
        " min before the snapshot")

    pin = pre[pre["bookmaker"] == "Pinnacle"].set_index(["event_id", "snapshot_ts", "market"])
    us = pre[pre["bookmaker"].isin(["DraftKings", "FanDuel"])]
    us_ml = us[us["market"] == "h2h"].groupby(["event_id", "snapshot_ts", "market"])["fair_a"].mean()
    ml = pin[pin.index.get_level_values("market") == "h2h"].join(us_ml.rename("us_fair_a"), how="inner")
    off_ml = ml[(ml["fair_a"] - ml["us_fair_a"]).abs() > OFF_MARKET_PROB].reset_index()
    if len(off_ml):
        add("stale_line_pinnacle_off_market", off_ml,
            "Pinnacle home fair " + off_ml["fair_a"].round(3).astype(str) + " vs DK/FD avg " +
            off_ml["us_fair_a"].round(3).astype(str))
    pts = us[us["market"] != "h2h"].pivot_table(
        index=["event_id", "snapshot_ts", "market"], columns="bookmaker", values="point_a")
    pts = pin[pin.index.get_level_values("market") != "h2h"][["point_a", "bookmaker"]].join(pts, how="inner")
    if {"DraftKings", "FanDuel"} <= set(pts.columns):
        far = ((pts["point_a"] - pts["DraftKings"]).abs() >= OFF_MARKET_POINTS) & (
            (pts["point_a"] - pts["FanDuel"]).abs() >= OFF_MARKET_POINTS)
        off_pts = pts[far].reset_index()
        if len(off_pts):
            add("stale_line_pinnacle_off_market", off_pts,
                "Pinnacle line " + off_pts["point_a"].astype(str) + " vs DK " +
                off_pts["DraftKings"].astype(str) + ", FD " + off_pts["FanDuel"].astype(str))

    if not issues:
        return pd.DataFrame(columns=["check", "event_id", "bookmaker", "market", "snapshot_ts", "detail"])
    return pd.concat(issues, ignore_index=True)


QC_CHECKS = [
    "bad_odds_invalid_american",
    "bad_odds_decimal_mismatch",
    "bad_odds_implied_prob_mismatch",
    "bad_odds_unknown_outcome",
    "bad_odds_negative_vig",
    "bad_odds_vig_above_12pct",
    "bad_odds_spread_points_not_opposite",
    "bad_odds_total_points_differ",
    "post_kickoff_snapshot_excluded",
    "missing_pinnacle_line",
    "missing_pinnacle_closing_line",
    "stale_closing_line",
    "stale_line_last_update",
    "stale_line_pinnacle_off_market",
]


def compute(snapshots: pd.DataFrame) -> dict[str, pd.DataFrame]:
    sides_raw = prepare(snapshots)
    markets = market_snapshots(sides_raw)
    markets["market_snapshot_id"] = np.arange(len(markets))
    sides = side_rows(markets)
    qc = quality_check(sides_raw, markets)
    # Exclude market snapshots with bad odds from the results (they stay in the QC file)
    bad = qc[qc["check"].str.startswith("bad_odds")][["event_id", "bookmaker", "market", "snapshot_ts"]]
    bad_keys = set(map(tuple, bad.astype(str).values))
    key = markets[["event_id", "bookmaker", "market", "snapshot_ts"]].astype(str)
    markets["has_bad_odds"] = [tuple(r) in bad_keys for r in key.values]
    return {"sides_raw": sides_raw, "markets": markets, "sides": sides, "qc": qc}
