"""Checks for the alignment pipeline. Each recomputes or cross-checks a result independently.

Statuses: ``pass``, ``warn`` (usable, but something needs a decision or is incomplete), ``fail``
(a number cannot be trusted; the script exits with code 1), ``skip`` (nothing to check yet).
"""

from __future__ import annotations

import math

from fractions import Fraction
from typing import Any

import pandas as pd

from app.alignment import teams
from app.alignment.pipeline import BOOKS, CHECKPOINTS, MOVED_WARN_MIN, REASONS, SOURCES

COMPLEMENT_LO, COMPLEMENT_HI = 0.85, 1.15  # Kalshi team A mid + team B mid should be near 1
SWAP_MARGIN = 0.25  # how much better a swapped assignment must fit before a game is flagged


def _c(cid: str, title: str, status: str, detail: str, guards: str) -> dict[str, Any]:
    return {"id": cid, "title": title, "status": status, "detail": detail, "guards": guards}


def _prob(a: float) -> float:
    a = Fraction(int(round(a)))
    return float(Fraction(100) / (a + 100) if a > 0 else -a / (-a + 100))


def run_checks(season: int, games: pd.DataFrame, events: pd.DataFrame, cw: pd.DataFrame,
               leftover: pd.DataFrame, snap: pd.DataFrame, candles: pd.DataFrame, snaps: pd.DataFrame,
               costs: pd.DataFrame | None, kalshi_present: bool) -> list[dict]:
    out: list[dict] = []
    matched = cw[cw["status"] == "matched"]

    # 1. Team table itself
    probs = teams.table_problems()
    out.append(_c("team_table", "32-team table is valid", "fail" if probs else "pass",
                  "; ".join(probs) if probs else "32 teams, no code used for two teams.",
                  "A code mapped to two teams, which would match the wrong game."))

    # 2. Game list: every sportsbook game of the season once, final kickoff, moved games flagged
    src_ids = set(snaps["event_id"])
    dup = int(games["game_id"].duplicated().sum())
    wrong_season = int((games["season"] != season).sum())
    last_kick = snaps.sort_values("snapshot_ts").groupby("event_id")["commence_time"].last()
    kick_bad = int((games.set_index("game_id")["kickoff_utc"] != last_kick.reindex(games["game_id"])).sum())
    moved = games[games["kickoff_moved_min"].abs() > MOVED_WARN_MIN]
    missing = len(set(games["game_id"]) - src_ids)
    status = "fail" if (dup or wrong_season or kick_bad or missing) else ("warn" if len(moved) else "pass")
    out.append(_c(
        "game_list", "Game list: each game once, final kickoff time", status,
        f"{len(games)} games; {dup} duplicates; {wrong_season} from another season; {kick_bad} not using the "
        f"provider's final start time. Kickoff moved by more than {MOVED_WARN_MIN} min after first listing: "
        + (", ".join(f"{r.away} at {r.home} ({r.kickoff_moved_min:+.0f} min)" for r in moved.itertuples())
           if len(moved) else "none") + ".",
        "Checkpoints measured from a stale scheduled time (most kickoffs shift a few minutes; some by hours)."))

    # 3. Every game matched or with a known reason code
    no_reason = int(cw["reason_code"].isna().sum())
    unknown_reason = sorted(set(cw["reason_code"].dropna()) - set(REASONS))
    counts = cw["reason_code"].value_counts().to_dict()
    unmatched = len(cw) - len(matched)
    status = "fail" if (no_reason or unknown_reason) else ("pass" if not unmatched else "warn")
    if not kalshi_present:
        status = "skip"
    out.append(_c("every_game_accounted", "Every game is matched or has a reason code", status,
                  f"{counts}" + (f"; {no_reason} games without a reason" if no_reason else "")
                  + (f"; unknown reasons {unknown_reason}" if unknown_reason else "")
                  + ("" if kalshi_present else " (no Kalshi data from Task 3 yet)"),
                  "Games silently dropped from the comparison."))

    # 4. One-to-one: no Kalshi event used twice; each matched game has its two teams' markets
    reused = matched["kalshi_event_ticker"].value_counts()
    reused = reused[reused > 1]
    two = matched[matched["kalshi_market_id_home"].isna() | matched["kalshi_market_id_away"].isna()
                  | (matched["kalshi_market_id_home"] == matched["kalshi_market_id_away"])]
    team_bad = []
    for r in matched.itertuples():
        for side in ("home", "away"):
            t = getattr(r, f"kalshi_ticker_{side}")
            code = t.rsplit("-", 1)[-1] if isinstance(t, str) else None
            if teams.team_name(code or "") != getattr(r, side):
                team_bad.append(f"{r.game_id} {side}")
    status = "fail" if (len(reused) or len(two) or team_bad) else ("pass" if len(matched) else "skip")
    out.append(_c("one_to_one", "Each game has its own two Kalshi markets, one per team", status,
                  f"{len(matched)} matched games; {len(reused)} Kalshi events used twice; {len(two)} without two "
                  f"distinct markets; {len(team_bad)} markets whose ticker team is not the team they are filed under.",
                  "Two games sharing one Kalshi event, or a market filed under the wrong team."))

    # 5. Ticker date vs kickoff (Eastern) date
    if len(matched):
        off = matched[matched["date_diff_days"] != 0]
        status = "warn" if len(off) else "pass"
        detail = (f"All {len(matched)} ticker dates equal the Eastern kickoff date." if not len(off) else
                  f"{len(off)} ticker dates differ by a day: "
                  + ", ".join(f"{r.kalshi_event_ticker} vs {r.kickoff_utc.tz_convert('America/New_York'):%b %d}"
                              for r in off.head(5).itertuples()))
    else:
        status, detail = "skip", "No matched games."
    out.append(_c("ticker_dates", "Ticker dates match kickoff dates (Eastern)", status, detail,
                  "Joining on UTC dates, which puts night games on the wrong day."))

    # 6. Team codes Kalshi uses that the table does not know
    unknown = sorted({c for codes in events["codes"] for c in str(codes).split(",") if c and teams.team_name(c) is None}) \
        if len(events) else []
    out.append(_c("unknown_codes", "Every Kalshi team code is in the table",
                  "warn" if unknown else ("pass" if len(events) else "skip"),
                  (f"Not in teams.py: {', '.join(unknown)} (add them to TEAMS)." if unknown
                   else f"All codes in {len(events)} Kalshi events are known.") if len(events) else "No Kalshi events.",
                  "Games left unmatched because of a code spelled differently."))

    # 7. Unmatched Kalshi events are explained (preseason etc.), not lost regular-season games
    lo = games["kickoff_utc"].min()
    hi = games["kickoff_utc"].max()
    inside = leftover[[d is not None and lo is not pd.NaT and lo.tz_convert("America/New_York").date() <= d
                       <= hi.tz_convert("America/New_York").date() for d in leftover["ticker_date"]]] if len(games) else leftover
    out.append(_c("kalshi_leftover", "Kalshi events not matched to a game",
                  "warn" if len(inside) else ("pass" if len(events) else "skip"),
                  f"{len(leftover)} Kalshi events unmatched; {len(inside)} of them dated inside the season's game "
                  f"dates (listed in kalshi_events_unmatched.csv)." if len(events) else "No Kalshi events.",
                  "Real games missing from the sportsbook side or mis-parsed tickers."))

    if snap.empty:
        for cid, title in (("no_lookahead", "No price from after its checkpoint"),
                           ("asof_recompute", "Snapshot prices recomputed independently"),
                           ("complete_grid", "Every game x team x checkpoint x source present"),
                           ("kalshi_complement", "Kalshi prices for the two teams add up to about $1"),
                           ("team_alignment", "Kalshi and sportsbooks agree on which team is which"),
                           ("book_prices", "Sportsbook prices are the team's own line")):
            out.append(_c(cid, title, "skip", "No matched games, so no snapshots yet.", ""))
    else:
        out += _snapshot_checks(snap, candles, snaps, matched)

    # Price ages: a decision the team has to make
    if not snap.empty:
        ages = snap.dropna(subset=["age_s"])
        med = (ages.groupby(["source", "checkpoint"])["age_s"].median() / 60).round(1)
        old = ages[(ages["source"] != "Kalshi") & (ages["age_s"] > 3600)]
        share = (len(old) / max(1, len(ages[ages["source"] != "Kalshi"]))) * 100
        parts = [f"{s} {c}: {med.get((s, c), float('nan')):g} min" for c in ("3h", "1h", "15m")
                 for s in ("Kalshi", "Pinnacle")]
        out.append(_c("price_ages", "Price ages recorded", "warn" if share else "pass",
                      f"{share:.0f}% of sportsbook prices are more than an hour old at their checkpoint. Median ages: "
                      + "; ".join(parts) + ". Costs only use prices within the maximum age (costs.MAX_AGE_MIN); "
                      "older ones are marked not usable, so checkpoints with few fresh snapshots have few costs.",
                      "Comparing a Kalshi price from one minute ago with a sportsbook price from this morning."))

    # Costs
    out += cost_checks(costs, snap, matched)
    return out


def _snapshot_checks(snap: pd.DataFrame, candles: pd.DataFrame, snaps: pd.DataFrame,
                     matched: pd.DataFrame) -> list[dict]:
    out = []
    s = snap.copy()
    # Seconds via Python's own Timestamp.timestamp(), deliberately not the pipeline's conversion,
    # so a unit mistake there cannot hide here.
    s["checkpoint_ts"] = [int(pd.Timestamp(x).timestamp()) for x in s["checkpoint_utc"]]
    have = s.dropna(subset=["price_ts_utc"])
    price_ts = pd.Series([int(pd.Timestamp(x).timestamp()) for x in have["price_ts_utc"]], index=have.index)
    late = int((price_ts > have["checkpoint_ts"]).sum())
    neg = int((have["age_s"] < 0).sum())
    kick = [int(pd.Timestamp(x).timestamp()) for x in s["kickoff_utc"]]
    ages_ok = all(0 <= k - c <= 24 * 3600 for k, c in zip(kick, s["checkpoint_ts"]))
    out.append(_c("no_lookahead", "No price from after its checkpoint",
                  "fail" if late or neg or not ages_ok else "pass",
                  f"{len(have):,} prices; {late} timestamped after their checkpoint; {neg} negative ages; "
                  f"checkpoints {'all' if ages_ok else 'NOT all'} 0-24 h before their kickoff.",
                  "Look-ahead: using a price that did not exist yet at that moment."))

    # Independent recompute: brute force 'latest at or before' for every row
    c = candles.assign(ts=candles["ts"].astype("int64"))
    by_market = {int(k): g.sort_values("ts") for k, g in c.groupby("market_id")}
    ml = snaps[(snaps["market"] == "h2h") & snaps["bookmaker"].isin(BOOKS)]
    by_line = {k: g for k, g in ml.groupby(["event_id", "bookmaker", "outcome"])}
    tickers = {}
    for r in matched.itertuples():
        tickers[(r.game_id, "home")] = r.kalshi_market_id_home
        tickers[(r.game_id, "away")] = r.kalshi_market_id_away
    mism = 0
    for r in s.itertuples():
        if r.source == "Kalshi":
            g = by_market.get(int(tickers.get((r.game_id, r.side), -1) or -1))
            hit = g[g["ts"] <= r.checkpoint_ts].tail(1) if g is not None else None
            want_ts = int(hit["ts"].iloc[0]) if hit is not None and len(hit) else None
            want_bid = float(hit["bid"].iloc[0]) / 10_000 if want_ts is not None else None
            got_ts = None if pd.isna(r.price_ts_utc) else int(pd.Timestamp(r.price_ts_utc).timestamp())
            ok = (want_ts == got_ts) and (want_ts is None or abs(want_bid - r.kalshi_bid) < 1e-12)
        else:
            g = by_line.get((r.game_id, r.source, r.team))
            hit = g[g["snapshot_ts"] <= pd.Timestamp(r.checkpoint_utc)].sort_values("snapshot_ts").tail(1) \
                if g is not None else None
            want = hit["snapshot_ts"].iloc[0] if hit is not None and len(hit) else None
            got = None if pd.isna(r.price_ts_utc) else pd.Timestamp(r.price_ts_utc)
            ok = (want is None and got is None) or (want is not None and got is not None and want == got
                                                    and float(hit["price_american"].iloc[0]) == float(r.book_price_american))
        mism += 0 if ok else 1
    out.append(_c("asof_recompute", "Snapshot prices recomputed independently", "fail" if mism else "pass",
                  f"All {len(s):,} rows re-found by scanning every candle and line (no merge_asof); "
                  f"{mism} differ.", "Errors in the merge_asof join (wrong key, wrong direction, unsorted input)."))

    # Grid completeness
    want = len(matched) * 2 * len(CHECKPOINTS) * len(SOURCES)
    dupes = int(s.duplicated(["game_id", "side", "checkpoint", "source"]).sum())
    no_reason = int((s["price_ts_utc"].isna() & s["missing_reason"].isna()).sum())
    missing = s["price_ts_utc"].isna().groupby(s["source"]).sum().to_dict()
    rows_per = s.groupby("source").size().to_dict()
    # a source with no price in a whole checkpoint means a broken join, not quiet markets
    by_cp = s.assign(m=s["price_ts_utc"].isna()).groupby(["source", "checkpoint"])["m"].mean()
    dead = [f"{src} {cp}" for (src, cp), share in by_cp.items() if share == 1.0]
    out.append(_c("complete_grid", "Every game x team x checkpoint x source present",
                  "fail" if (len(s) != want or dupes or no_reason or dead)
                  else ("warn" if sum(missing.values()) else "pass"),
                  f"{len(s):,} rows, expected {want:,}; {dupes} duplicates; rows without a price: "
                  + ", ".join(f"{k} {int(v)} of {rows_per[k]}" for k, v in missing.items())
                  + (f"; {no_reason} without a reason" if no_reason else "")
                  + (f"; NO prices at all for: {', '.join(dead)}" if dead else ""),
                  "Rows silently missing or doubled."))

    # Kalshi complement: the two teams' mids should add to about $1
    k = s[(s["source"] == "Kalshi") & s["kalshi_bid"].notna()].assign(mid=lambda d: (d["kalshi_bid"] + d["kalshi_ask"]) / 2)
    pair = k.pivot_table(index=["game_id", "checkpoint"], columns="side", values="mid").dropna()
    total = pair.sum(axis=1)
    off = total[(total < COMPLEMENT_LO) | (total > COMPLEMENT_HI)]
    share = len(off) / max(1, len(total))
    out.append(_c("kalshi_complement", "Kalshi prices for the two teams add up to about $1",
                  "fail" if share > 0.10 else ("warn" if len(off) else "pass"),
                  f"{len(total):,} game checkpoints; {len(off)} where home mid + away mid is outside "
                  f"{COMPLEMENT_LO}-{COMPLEMENT_HI} (median sum {total.median():.3f}).",
                  "Two markets from different games filed as one game."))

    # Team alignment: Kalshi's price for a team should track the books' price for the same team
    close = s[s["checkpoint"] == "close"]
    km = close[close["source"] == "Kalshi"].assign(mid=lambda d: (d["kalshi_bid"] + d["kalshi_ask"]) / 2)
    bk = close[close["source"].isin(BOOKS)].assign(
        fair=lambda d: d["book_implied"] / (d["book_implied"] + d["book_implied_other"]))
    bmean = bk.groupby(["game_id", "side"])["fair"].mean()
    kmid = km.set_index(["game_id", "side"])["mid"]
    j = pd.concat([kmid.rename("k"), bmean.rename("b")], axis=1).dropna().reset_index()
    flagged = []
    for gid, g in j.groupby("game_id"):
        if len(g) != 2:
            continue
        straight = (g["k"] - g["b"]).abs().sum()
        swapped = (g["k"].to_numpy() - g["b"].to_numpy()[::-1]).__abs__().sum()
        if swapped + SWAP_MARGIN < straight:
            flagged.append(gid)
    out.append(_c("team_alignment", "Kalshi and sportsbooks agree on which team is which",
                  "fail" if flagged else ("pass" if len(j) else "skip"),
                  f"{j['game_id'].nunique()} games compared at kickoff; {len(flagged)} fit better with the teams "
                  f"swapped" + (f": {', '.join(flagged[:5])}" if flagged else "") + ".",
                  "A Kalshi market attached to the opposing team (prices would look wildly off)."))

    # Sportsbook price on a row really is that team's line, and implied probability is right
    b = s[s["source"].isin(BOOKS) & s["book_price_american"].notna()]
    imp = b["book_price_american"].map(_prob)
    imp_err = float((imp - b["book_implied"]).abs().max()) if len(b) else 0.0
    out.append(_c("book_prices", "Sportsbook prices are the team's own line", "fail" if imp_err > 1e-12 else "pass",
                  f"{len(b):,} sportsbook prices; implied probability recomputed exactly (worst {imp_err:.1e}); "
                  f"each was looked up by the team's own name.", "Using the opponent's price or a wrong conversion."))
    return out


def cost_checks(costs: pd.DataFrame | None, snap: pd.DataFrame, matched: pd.DataFrame) -> list[dict]:
    """Step 4, recomputed independently from snapshots.csv (exact fractions, own fee and de-vig code)."""
    from app.alignment import costs as cm

    if costs is None:
        return [_c("costs", "Costs computed", "fail", "No cost table.", "Step 4 silently skipped.")]
    out: list[dict] = []
    if matched.empty or costs.empty:
        return [_c("costs", "Costs computed", "skip", "No matched games, so no costs.", "")]

    # 1. Grid: every matched game x team x checkpoint x venue x ruler (x n for Kalshi) exactly once
    n_k = costs.loc[costs["venue"] == "Kalshi", "n"].nunique()
    per_slot = len(cm.RULERS) * (n_k + 3)
    expect = len(matched) * 2 * len(CHECKPOINTS) * per_slot
    key = ["game_id", "side", "checkpoint", "venue", "ruler", "n"]
    dup = int(costs.duplicated(key).sum())
    out.append(_c("cost_grid", "Every game x team x checkpoint x venue x ruler (x n) once",
                  "pass" if (len(costs) == expect and not dup) else "fail",
                  f"{len(costs)} rows, expected {expect} ({len(matched)} games x 2 teams x {len(CHECKPOINTS)} "
                  f"checkpoints x 4 rulers x ({n_k} Kalshi sizes + 3 books)); {dup} duplicates.",
                  "A combination dropped or counted twice."))

    # 2. Each ruler's fair chances for the two teams add up to 1
    f = costs.drop_duplicates(["game_id", "side", "checkpoint", "ruler"]).pivot_table(
        index=["game_id", "checkpoint", "ruler"], columns="side", values="fair")
    f = f.dropna()
    worst = float((f["home"] + f["away"] - 1).abs().max()) if len(f) else 0.0
    out.append(_c("ruler_sums", "Each ruler's two fair chances add up to 100%",
                  "pass" if worst < 1e-9 else "fail", f"Largest gap {worst:.2e} over {len(f)} game-checkpoint-rulers.",
                  "Margin not fully removed, or the two teams swapped between rulers."))

    # 3. Recompute fair chances, prices and costs from snapshots.csv with separate code
    s = snap.set_index(["game_id", "side", "checkpoint", "source"])
    bad: list[str] = []
    checked = 0
    for r in costs.itertuples():
        if not r.usable:
            continue
        checked += 1
        opp = "away" if r.side == "home" else "home"
        src = cm.RULERS[r.ruler]
        if src == "Kalshi":
            own, oth = s.loc[(r.game_id, r.side, r.checkpoint, "Kalshi")], s.loc[(r.game_id, opp, r.checkpoint, "Kalshi")]
            m1 = (Fraction(str(own.kalshi_bid)) + Fraction(str(own.kalshi_ask))) / 2
            m2 = (Fraction(str(oth.kalshi_bid)) + Fraction(str(oth.kalshi_ask))) / 2
            fair = float(m1 / (m1 + m2))
        else:
            b = s.loc[(r.game_id, r.side, r.checkpoint, src)]
            fair = _shin_closed_form(_prob(b.book_price_american), _prob(b.book_price_american_other))
        if r.venue == "Kalshi":
            own, oth = s.loc[(r.game_id, r.side, r.checkpoint, "Kalshi")], s.loc[(r.game_id, opp, r.checkpoint, "Kalshi")]
            kp = min(Fraction(str(own.kalshi_ask)), 1 - Fraction(str(oth.kalshi_bid)))
            cents = Fraction(7, 100) * int(r.n) * kp * (1 - kp) * 100
            fee = Fraction(-(-cents.numerator // cents.denominator), 100)  # round up to the cent
            price = float(kp + fee / int(r.n))
        else:
            price = _prob(s.loc[(r.game_id, r.side, r.checkpoint, r.venue)].book_price_american)
        cost = 10 * (1 - fair / price)
        if abs(cost - r.cost_per_10) > 1e-6 or abs(fair - r.fair) > 1e-6:
            bad.append(f"{r.game_id} {r.team} {r.checkpoint} {r.venue} {r.ruler} n={r.n}: "
                       f"{r.cost_per_10:.6f} vs {cost:.6f}")
    out.append(_c("cost_recompute", "Cost per $10 recomputed independently from the snapshots",
                  "fail" if bad else ("pass" if checked else "skip"),
                  f"{checked} usable rows recomputed with exact fractions, a closed-form Shin and the fee rounded "
                  f"up to the cent; {len(bad)} differ." + (" e.g. " + "; ".join(bad[:3]) if bad else ""),
                  "Wrong fee, wrong de-vig, wrong team's price, or the price/fair the wrong way round."))

    # 4. Against its own ruler a sportsbook can only show a positive margin
    own = costs[costs["usable"] & (costs["venue"] != "Kalshi") & (costs["venue"] == costs["ruler"].map(cm.RULERS))]
    neg = own[own["cost_per_10"] < 0]
    out.append(_c("own_margin_positive", "Each sportsbook costs more than its own fair price",
                  "fail" if len(neg) else "pass",
                  f"{len(neg)} of {len(own)} own-ruler sportsbook rows are negative.",
                  "De-vig adding margin instead of removing it."))

    # 5. Kalshi: smaller orders pay at least as much per contract (fee rounding), never less
    k = costs[(costs["venue"] == "Kalshi") & costs["usable"]].sort_values("n")
    wrong = 0
    for _, g in k.groupby(["game_id", "side", "checkpoint", "ruler"]):
        fees = (g["fee_per_contract"] * g["n"].astype(float)).to_numpy()
        raw = 0.07 * g["n"].astype(float).to_numpy() * g["kalshi_price"].to_numpy() * (1 - g["kalshi_price"].to_numpy())
        wrong += int(((fees + 1e-9 < raw) | (fees > raw + 0.01 + 1e-9)).sum())
    out.append(_c("fee_rounding", "Kalshi fee per order is the exact fee rounded up by less than 1 cent",
                  "fail" if wrong else "pass", f"{wrong} Kalshi rows outside [exact fee, exact fee + 1 cent).",
                  "Fee rounded down, charged per contract instead of per order, or left out."))

    # 6. Sportsbook rows must not depend on n; Kalshi rows must have one
    nb = int(costs.loc[costs["venue"] != "Kalshi", "n"].notna().sum())
    nk = int(costs.loc[costs["venue"] == "Kalshi", "n"].isna().sum())
    out.append(_c("n_assignment", "n applies to Kalshi only", "fail" if (nb or nk) else "pass",
                  f"{nb} sportsbook rows with an n, {nk} Kalshi rows without one.",
                  "Sportsbook rows repeated per order size, inflating counts."))

    # 7. Freshness rule applied, and the n values' source stated
    lim = costs["checkpoint"].map(cm.MAX_AGE_MIN)
    leak = costs[costs["usable"] & (costs["price_age_min"] > lim)]
    out.append(_c("freshness_rule", "No sportsbook price older than the maximum age is used",
                  "fail" if len(leak) else "pass",
                  f"{len(leak)} usable rows break it. Usable: {int(costs['usable'].sum())} of {len(costs)}; "
                  "max ages (min): " + ", ".join(f"{c} {m}" for c, m in cm.MAX_AGE_MIN.items()) + ".",
                  "A morning sportsbook price compared with a Kalshi price from a minute before kickoff."))
    src = costs["n_source"].dropna().unique().tolist()
    placeholder = any("placeholder" in x for x in src)
    out.append(_c("n_values", "n values are real trade sizes", "warn" if placeholder else "pass",
                  ("Using the team's placeholder sizes " + ", ".join(map(str, cm.PLACEHOLDER_N))
                   + ": run make trade-sizes for this season, then re-run.") if placeholder else f"From {src[0]}.",
                  "Costs for order sizes nobody trades."))
    return out


def _shin_closed_form(pa: float, pb: float) -> float:
    """Shin for two outcomes has a closed form (Jullien & Salanie): solved here without bisection."""
    total = pa + pb
    # z solves fair_a + fair_b = 1; for two outcomes z = ((total-1)*(d^2 - total)) / (total*(d^2 - 1)), d = pa - pb
    d = pa - pb
    z = ((total - 1) * (d * d - total)) / (total * (d * d - 1))
    return (math.sqrt(z * z + 4 * (1 - z) * pa * pa / total) - z) / (2 * (1 - z))
