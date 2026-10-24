"""Step 4: cost per $10 for every venue, measured against every ruler.

A *ruler* is the fair chance a bet is measured against. There are four, one per venue:

- Ruler A = Kalshi: the two team markets' mid prices, scaled so the two teams add up to 100%.
- Ruler B = Pinnacle, FanDuel, DraftKings: that book's two moneyline prices with the margin taken
  out (Shin method; the simple proportional method is kept alongside for comparison with the
  team's matching work).

Every venue's price is measured against every ruler, so each game x team x checkpoint gives a
4 venues x 4 rulers grid. Measured against its own ruler a venue shows just its own margin;
against another venue's ruler it shows what you pay compared with what that venue thinks is fair.

    cost per $10 = 10 x (1 - fair chance / price paid)

Price paid:

- Sportsbook: the chance implied by the American odds (e.g. -110 = 52.38¢ per $1 of payout).
  The price does not depend on the bet size, so sportsbook rows have no n.
- Kalshi: the cheaper of the two ways to back a team (buy YES on its market at the ask, or buy
  NO on the opponent's market at 1 - the opponent's bid) plus the taker fee, for n contracts:
  ``0.07 x n x price x (1 - price)``, rounded up to the cent, per order. Rounding makes small
  orders pay more per contract, which is the only way n changes the cost here: the stored data
  are 1-minute candles (best bid/ask), not the order book, so a large order is assumed to fill
  at the best ask.

n values: the median, p75 and p90 Kalshi game-winner trade sizes (contracts per trade, block
trades excluded) from ``data/alignment/trade_sizes_<season>.json``; a season without its own file uses
the other season's sizes, and without either the team's placeholder sizes. Every row says which
(``n_source``).

Freshness (fixed rule): a sportsbook price is only used when it is at most ``MAX_AGE_MIN`` old at
the checkpoint (from the team's time windows). Kalshi candles are only written when the quote
changes, so an old Kalshi candle is still the live quote and has no age limit. Rows that break
the rule are kept with ``usable = False`` and a reason; summaries use usable rows only.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from app.task4.sportsbook_costs import shin_two_way

STAKE = 10.0
TAKER_RATE = 0.07
FEE_MULTIPLIER = 1.0  # KXNFLGAME: standard quadratic taker fee
PLACEHOLDER_N = (1, 5, 10, 25, 100)  # the team's compute_costs.py sizes
VENUES = ("Kalshi", "Pinnacle", "FanDuel", "DraftKings")
RULERS = {"A_Kalshi": "Kalshi", "B_Pinnacle": "Pinnacle", "B_FanDuel": "FanDuel", "B_DraftKings": "DraftKings"}
# Oldest sportsbook price allowed at each checkpoint, minutes (the team's windows; close = Task 4's rule).
MAX_AGE_MIN = {"24h": 360, "3h": 45, "1h": 15, "15m": 10, "close": 60}

COST_COLS = ["game_id", "season", "week", "team", "team_code", "side", "checkpoint", "checkpoint_utc",
             "kickoff_utc", "venue", "ruler", "n", "n_label", "n_source", "price_paid", "kalshi_route",
             "kalshi_price", "fee_per_contract", "fair", "fair_proportional", "cost_per_10",
             "cost_per_10_proportional", "fee_per_10", "price_age_min", "ruler_age_min", "usable",
             "unusable_reason"]


def fee_dollars(n: int, price: float) -> float:
    """Kalshi taker fee for one order of n contracts at ``price`` dollars, rounded up to the cent."""
    raw = TAKER_RATE * FEE_MULTIPLIER * n * price * (1 - price)
    return math.ceil(round(raw * 100, 9)) / 100


def n_values(season: int, folder: Path) -> tuple[list[tuple[str, int]], str]:
    """[(label, n), ...] and where they came from.

    The season's own trade sizes if they exist, otherwise another season's (the same sizes for
    both seasons keeps them comparable), otherwise the team's placeholder sizes.
    """
    for s in [season, *sorted({2025, 2026} - {season}, key=lambda x: abs(x - season))]:
        path = folder / f"trade_sizes_{s}.json"
        if not path.exists():
            continue
        allstats = json.loads(path.read_text())["stats"]
        # costs are for game-winner bets, so game-winner trade sizes when the file has them
        group = "KXNFLGAME" if allstats.get("KXNFLGAME", {}).get("excluding block trades", {}).get("trades") \
            else "all NFL markets"
        stats = allstats[group]["excluding block trades"]["per_trade"]
        if all(stats.get(k) for k in ("p50", "p75", "p90")):
            src = f"trade_sizes_{s}.json, {group}" + ("" if s == season else f" ({s} sizes used for {season})")
            return ([("median", max(1, math.ceil(stats["p50"]))), ("p75", max(1, math.ceil(stats["p75"]))),
                     ("p90", max(1, math.ceil(stats["p90"])))], src)
    return [(f"placeholder {n}", n) for n in PLACEHOLDER_N], "placeholder (run make trade-sizes)"


def _wide(snap: pd.DataFrame) -> pd.DataFrame:
    """One row per game x team x checkpoint, with every source's numbers and the opponent's Kalshi quote."""
    key = ["game_id", "side", "checkpoint"]
    base = snap.drop_duplicates(key)[["game_id", "season", "week", "team", "team_code", "side", "checkpoint",
                                      "checkpoint_utc", "kickoff_utc"]].set_index(key)
    k = snap[snap["source"] == "Kalshi"].set_index(key)[["kalshi_bid", "kalshi_ask"]]
    opp = k.reset_index()
    opp["side"] = opp["side"].map({"home": "away", "away": "home"})
    opp = opp.set_index(key).rename(columns={"kalshi_bid": "kalshi_bid_opp", "kalshi_ask": "kalshi_ask_opp"})
    out = base.join(k).join(opp)
    for book in RULERS.values():
        if book == "Kalshi":
            continue
        b = snap[snap["source"] == book].set_index(key)[["book_implied", "book_implied_other", "age_s"]]
        out = out.join(b.rename(columns={"book_implied": f"{book}_p", "book_implied_other": f"{book}_p_other",
                                         "age_s": f"{book}_age_s"}))
    return out.reset_index()


def _valid_quote(bid, ask):
    return (bid > 0) & (ask < 1) & (ask > bid)


def rulers(w: pd.DataFrame) -> pd.DataFrame:
    """Fair chance for the row's team under each ruler (Shin and proportional for the books)."""
    w = w.copy()
    ok = _valid_quote(w["kalshi_bid"], w["kalshi_ask"]) & _valid_quote(w["kalshi_bid_opp"], w["kalshi_ask_opp"])
    mid, mid_opp = (w["kalshi_bid"] + w["kalshi_ask"]) / 2, (w["kalshi_bid_opp"] + w["kalshi_ask_opp"]) / 2
    w["fair_Kalshi"] = np.where(ok, mid / (mid + mid_opp), np.nan)
    w["fairprop_Kalshi"] = w["fair_Kalshi"]
    w["Kalshi_age_s"] = np.nan
    for book in ("Pinnacle", "FanDuel", "DraftKings"):
        p, q = w[f"{book}_p"].astype(float), w[f"{book}_p_other"].astype(float)
        fa, _, _ = shin_two_way(p.fillna(0.5), q.fillna(0.5))
        w[f"fair_{book}"] = np.where(p.notna() & q.notna(), fa, np.nan)
        w[f"fairprop_{book}"] = p / (p + q)
    return w


def compute(snap: pd.DataFrame, season: int, n_list: list[tuple[str, int]], n_source: str) -> pd.DataFrame:
    if snap.empty:
        return pd.DataFrame(columns=COST_COLS)
    w = rulers(_wide(snap))
    rows = []
    for r in w.to_dict("records"):
        # price paid per venue: list of (n, n_label, price_paid, route, kalshi_price, fee_per_contract, age_min)
        paid: dict[str, list[tuple]] = {}
        yes, no = r["kalshi_ask"], 1 - r["kalshi_bid_opp"]
        if _valid_quote(r["kalshi_bid"], r["kalshi_ask"]) and _valid_quote(r["kalshi_bid_opp"], r["kalshi_ask_opp"]):
            route, kp = ("yes_own_market", yes) if yes <= no else ("no_opponent_market", no)
            paid["Kalshi"] = [(n, lab, kp + fee_dollars(n, kp) / n, route, kp, fee_dollars(n, kp) / n, np.nan)
                              for lab, n in n_list]
        else:
            paid["Kalshi"] = [(n, lab, np.nan, None, np.nan, np.nan, np.nan) for lab, n in n_list]
        for book in ("Pinnacle", "FanDuel", "DraftKings"):
            age = r[f"{book}_age_s"] / 60 if pd.notna(r[f"{book}_age_s"]) else np.nan
            paid[book] = [(None, None, r[f"{book}_p"], None, np.nan, np.nan, age)]
        for venue in VENUES:
            for n, lab, price, route, kp, fee, page in paid[venue]:
                for ruler, src in RULERS.items():
                    fair, fprop = r[f"fair_{src}"], r[f"fairprop_{src}"]
                    rage = r[f"{src}_age_s"] / 60 if pd.notna(r[f"{src}_age_s"]) else np.nan
                    reasons = []
                    if pd.isna(price):
                        reasons.append(f"no {venue} price")
                    if pd.isna(fair):
                        reasons.append(f"no {src} fair price")
                    lim = MAX_AGE_MIN[r["checkpoint"]]
                    if pd.notna(page) and page > lim:
                        reasons.append(f"{venue} price {page:.0f} min old (max {lim})")
                    if pd.notna(rage) and rage > lim and src != venue:
                        reasons.append(f"{src} ruler {rage:.0f} min old (max {lim})")
                    ok = price > 0 if pd.notna(price) else False
                    rows.append({
                        "game_id": r["game_id"], "season": r["season"], "week": r["week"], "team": r["team"],
                        "team_code": r["team_code"], "side": r["side"], "checkpoint": r["checkpoint"],
                        "checkpoint_utc": r["checkpoint_utc"], "kickoff_utc": r["kickoff_utc"],
                        "venue": venue, "ruler": ruler, "n": n, "n_label": lab,
                        "n_source": n_source if venue == "Kalshi" else None,
                        "price_paid": price, "kalshi_route": route, "kalshi_price": kp, "fee_per_contract": fee,
                        "fair": fair, "fair_proportional": fprop,
                        "cost_per_10": STAKE * (1 - fair / price) if ok and pd.notna(fair) else np.nan,
                        "cost_per_10_proportional": STAKE * (1 - fprop / price) if ok and pd.notna(fprop) else np.nan,
                        "fee_per_10": STAKE * fee / price if ok and pd.notna(fee) else np.nan,
                        "price_age_min": page, "ruler_age_min": rage,
                        "usable": not reasons, "unusable_reason": "; ".join(reasons) or None,
                    })
    out = pd.DataFrame(rows, columns=COST_COLS)
    out["n"] = out["n"].astype("Int64")
    return out


def table(costs: pd.DataFrame) -> pd.DataFrame:
    """Median cost per $10 (usable rows): venue (and Kalshi size) down, ruler across, per checkpoint."""
    u = costs[costs["usable"]].copy()
    if u.empty:
        return pd.DataFrame()
    u["venue_n"] = np.where(u["venue"] == "Kalshi", "Kalshi n=" + u["n"].astype(str), u["venue"])
    t = u.pivot_table(index=["checkpoint", "venue_n"], columns="ruler", values="cost_per_10", aggfunc="median")
    t = t.reindex(columns=[c for c in RULERS if c in t.columns]).round(3)
    cp = {c: i for i, c in enumerate(MAX_AGE_MIN)}
    vn = {v: (VENUES.index("Kalshi"), int(v.split("=")[1])) if v.startswith("Kalshi") else (VENUES.index(v), 0)
          for v in t.index.get_level_values(1)}
    return t.iloc[sorted(range(len(t)), key=lambda i: (cp[t.index[i][0]], vn[t.index[i][1]]))]
