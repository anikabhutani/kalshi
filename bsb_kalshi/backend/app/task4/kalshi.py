"""Kalshi costs for Task 4, taken from Task 3's API data (no requests are sent from here).

Task 3 downloads Kalshi candles from the API and writes, for every NFL game, spread and total
market, the quote and the cost of a bet at 24 h, 3 h, 1 h and 15 min before kickoff:

    data/task3/exports/checkpoint_quotes.csv   bid/ask per market and checkpoint
    data/task3/exports/checkpoint_costs.csv    cost per $10 per side (Yes/No) and order size

Task 4 lines Kalshi up with the sportsbook numbers like this:

- Bet types: Game winner -> moneyline, Spread -> spread, Total points -> total.
- Main line: sportsbooks quote one spread and one total per game, near 50/50, while Kalshi lists
  a ladder of strikes. For spreads and totals only the strike whose mid price is nearest 50 cents
  (per game and checkpoint) is kept. Both game-winner markets are kept.
- Order size: 10 contracts (closest to a $10 bet at mid prices).
- Closing line: the 15-minute checkpoint (sportsbook closing snapshots are 9-15 minutes out).
- Fair price: Kalshi's own mid price ((bid + ask) / 2), the counterpart of a sportsbook's no-vig
  price. Kalshi cost per $10 = half the bid-ask gap + the taker fee, per $10 staked (Task 3).
- Games: only Kalshi games kicking off inside the sportsbook games' date range (6 h either side).

Kalshi has no price checks against Pinnacle here (that needs team-by-team matching), so it
appears only in the "own fair price" views.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from app.task4.common import REPO_ROOT, nfl_week

KALSHI = "Kalshi"
KALSHI_EXPORTS = REPO_ROOT / "data" / "task3" / "exports"
MARKET_MAP = {"Game winner": "h2h", "Spread": "spreads", "Total points": "totals"}
CHECKPOINT_MINUTES = {"24h": 1440, "3h": 180, "1h": 60, "15m": 15}
CLOSING_CHECKPOINT = "15m"
SIZE = 10
KICKOFF_PAD = pd.Timedelta(hours=6)


def load(exports: Path | None = None, kickoff_range: tuple[pd.Timestamp, pd.Timestamp] | None = None,
         ) -> pd.DataFrame | None:
    """Side-level Kalshi rows lined up with Task 4, or None if Task 3 has no exports yet."""
    exports = KALSHI_EXPORTS if exports is None else exports
    qpath, cpath = exports / "checkpoint_quotes.csv", exports / "checkpoint_costs.csv"
    if not qpath.exists() or not cpath.exists():
        return None
    quotes = pd.read_csv(qpath)
    costs = pd.read_csv(cpath)
    if quotes.empty or costs.empty or "status" not in quotes:
        return None
    q = quotes[quotes["status"] == "ok"][
        ["ticker", "event_ticker", "market_type", "kickoff_utc", "checkpoint", "bid", "ask"]
    ].copy()
    q["market"] = q["market_type"].map(MARKET_MAP)
    q = q.dropna(subset=["market"])
    q["kickoff"] = pd.to_datetime(q["kickoff_utc"], utc=True, format="mixed")
    if kickoff_range is not None:
        # Padded: kickoff times can differ by minutes between sources (and move between snapshots)
        lo, hi = kickoff_range
        q = q[(q["kickoff"] >= lo - KICKOFF_PAD) & (q["kickoff"] <= hi + KICKOFF_PAD)]
    q["mid"] = (q["bid"] + q["ask"]) / 2

    # Main line for spreads and totals: the strike nearest 50 cents per game and checkpoint
    q["dist"] = (q["mid"] - 0.5).abs()
    ladder = q["market"] != "h2h"
    best = q[ladder].sort_values("dist").groupby(["event_ticker", "checkpoint"]).head(1)
    q["main_line"] = ~ladder
    q.loc[best.index, "main_line"] = True

    c = costs[costs["size"] == SIZE][["ticker", "checkpoint", "side", "price_paid", "cost_per_10"]]
    rows = c.merge(q, on=["ticker", "checkpoint"], how="inner")
    if rows.empty:
        return None
    rows["fair_prob"] = np.where(rows["side"] == "yes", rows["mid"], 1 - rows["mid"])
    rows["minutes_to_kickoff"] = rows["checkpoint"].map(CHECKPOINT_MINUTES)
    rows["week"] = nfl_week(rows["kickoff"])
    rows["bookmaker"] = KALSHI
    rows["event_id"] = rows["event_ticker"]
    return rows[[
        "bookmaker", "event_id", "ticker", "market", "checkpoint", "minutes_to_kickoff", "week",
        "side", "price_paid", "mid", "fair_prob", "cost_per_10", "main_line", "kickoff",
    ]].reset_index(drop=True)
