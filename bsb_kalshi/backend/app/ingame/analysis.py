"""In-game Kalshi NFL analysis: what happens once the game starts.

Two kinds of data, both already in this repo's data folder:

- **Trades** (``data/alignment/trades/<season>/<ticker>.csv.gz``, from ``make trade-sizes``): every
  game-winner trade with its size, price, time and the side the taker bought. Used for where the
  money and fees happen, trade sizes, fee rounding and whether takers win or lose.
- **1-minute candles and results** (Task 3, ``data/task3/nfl_costs.db``): the standing bid/ask
  through the game and how each market settled. Used for in-game spreads and costs and for
  whether in-game prices predict the result (both seasons; trades exist for 2026 only so far).

Kickoff per game: Kalshi's milestone start time when it has one; otherwise the sportsbook feed's
final start time (``data/alignment/<season>/crosswalk.csv``); otherwise Task 3's estimate from
the market's expected expiration. Preseason games are left out (``trade_sizes.season_of``).

Conventions:

- The taker's price ``p`` is the price of the side the taker bought (YES price, or 1 - YES price
  for NO). Price groups: longshot < 40¢ <= middle < 60¢ <= favorite (as in the team's deck).
- Taker fee per trade: ``0.07 x contracts x p x (1 - p)`` rounded up to the cent (Kalshi fee
  schedule); ``fee_exact`` keeps the unrounded amount. Applied per fill, so totals are estimates.
- Taker result per $10 = ``10 x (contracts won - dollars paid [- fees]) / dollars paid``; only
  markets settled yes/no count (ties settle "scalar" and are left out).
- Confidence intervals resample whole games (both teams' markets move together), 1,000 times.

Command line (writes ``data/ingame/<season>/results.json`` and ``checks.json``)::

    cd backend && .venv/bin/python -m app.ingame.analysis --season 2026
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
import sqlite3
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.alignment.trade_sizes import market_date, season_of
from app.task4.common import EASTERN, REPO_ROOT

OUT_DIR = REPO_ROOT / "data" / "ingame"
TRADES_DIR = REPO_ROOT / "data" / "alignment" / "trades"
ALIGN_DIR = REPO_ROOT / "data" / "alignment"
TASK3_DB = REPO_ROOT / "data" / "task3" / "nfl_costs.db"
SERIES = "KXNFLGAME"
PRICE_SCALE = 10_000
TAKER_RATE = 0.07
DEFAULT_N = 24
BOOT = 1000
SEED = 20261025
CACHE_VERSION = 4

INF = float("inf")
TIME_BINS: list[tuple[str, float, float]] = [
    ("24h+ before", -INF, -1440), ("24h–3h before", -1440, -180), ("3h–1h before", -180, -60),
    ("Last hour", -60, 0), ("0–30 min", 0, 30), ("30–60 min", 30, 60), ("60–90 min", 60, 90),
    ("90–120 min", 90, 120), ("120–150 min", 120, 150), ("150–180 min", 150, 180),
    ("180–210 min", 180, 210), ("210+ min", 210, INF),
]
BIN_LABELS = [b[0] for b in TIME_BINS]
PRICE_BUCKETS = [f"{10 * i}–{10 * i + 10}¢" for i in range(10)]
GROUPS = ["Longshot (<40¢)", "Middle (40–60¢)", "Favorite (60¢+)"]
SIZE_BUCKETS = ["1 or less", "1–10", "10–100", "100+"]
CAL_CHECKPOINTS = [-60, 0, 30, 60, 90, 120, 150, 180]
GRID = list(range(-180, 245, 5))


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------


def fee_dollars(contracts: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Kalshi taker fee per fill, rounded up to the cent, in exact integer arithmetic.

    Prices come in 1/10,000 of a dollar and sizes in 1/100 of a contract, so with P = 10,000 p and
    C = 100 x contracts the fee in cents is exactly 7 C P (10,000 - P) / 10^10. Floating point would
    turn e.g. 28,000 contracts at 70c (exactly $411.60) into 41160.00000000001 cents and round it
    up to $411.61."""
    P = np.rint(np.asarray(p, dtype=float) * 10_000).astype(np.int64)
    C = np.rint(np.asarray(contracts, dtype=float) * 100).astype(np.int64)
    num = 7 * C * P * (10_000 - P)
    return (-(-num // 10**10)).astype(float) / 100


def time_bin(minutes: np.ndarray) -> np.ndarray:
    out = np.full(len(minutes), -1, dtype=np.int16)
    for i, (_, lo, hi) in enumerate(TIME_BINS):
        out[(minutes >= lo) & (minutes < hi)] = i
    return out


def price_bucket(p: np.ndarray) -> np.ndarray:
    return np.clip((p * 10).astype(int), 0, 9).astype(np.int8)


def price_group(p: np.ndarray) -> np.ndarray:
    return np.where(p < 0.4, 0, np.where(p < 0.6, 1, 2)).astype(np.int8)


def size_bucket(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 1, 0, np.where(c <= 10, 1, np.where(c <= 100, 2, 3))).astype(np.int8)


def _pct(values: np.ndarray, q: float) -> float | None:
    return float(np.percentile(values, q, method="inverted_cdf")) if len(values) else None


def _r(x: Any, nd: int = 6) -> Any:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), nd)


def _records(df: pd.DataFrame, nd: int = 6) -> list[dict[str, Any]]:
    out = []
    for row in df.to_dict("records"):
        out.append({k: (_r(v, nd) if isinstance(v, (float, np.floating)) else
                        (int(v) if isinstance(v, (np.integer,)) else v)) for k, v in row.items()})
    return out


def kickoff_slot(kick_ts: float) -> str:
    t = datetime.fromtimestamp(kick_ts, UTC).astimezone(EASTERN)
    wd, h = t.weekday(), t.hour + t.minute / 60
    if wd == 3:
        return "Thursday night"
    if wd == 0:
        return "Monday night"
    if wd == 6:
        return "Sunday early" if h < 15.5 else ("Sunday late" if h < 19 else "Sunday night")
    if wd == 5:
        return "Saturday"
    return "Other day"


# --------------------------------------------------------------------------------------
# markets, kickoffs, results
# --------------------------------------------------------------------------------------


def load_markets(season: int, db: Path = TASK3_DB, align_dir: Path = ALIGN_DIR) -> pd.DataFrame:
    """Game-winner markets of the season (no preseason) with kickoff, result and settle time."""
    cols = ["id", "ticker", "event_ticker", "result", "settle_ts", "kickoff_ts", "kickoff_source",
            "kickoff_milestone", "kickoff_sportsbook", "is_away", "team"]
    if not db.exists():
        return pd.DataFrame(columns=cols)
    with sqlite3.connect(db) as conn:
        m = pd.read_sql_query(
            "SELECT m.id, m.ticker, m.event_ticker, m.result, m.settle_ts, g.kickoff_ts AS kick_t3, "
            "g.kickoff_source AS src_t3 FROM markets m LEFT JOIN games g ON g.game_event_ticker = m.event_ticker "
            "WHERE m.series_ticker = ? OR m.event_ticker LIKE ?", conn, params=(SERIES, f"{SERIES}-%"))
    keep = []
    for t in m["ticker"]:
        d = market_date(t)
        keep.append(d is not None and d[0] == SERIES and season_of(d[1]) == season)
    m = m.loc[np.array(keep, dtype=bool)].copy()
    cw_path = align_dir / str(season) / "crosswalk.csv"
    book = {}
    if cw_path.exists():
        cw = pd.read_csv(cw_path)
        cw = cw[cw["status"] == "matched"]
        book = {e: pd.Timestamp(k).timestamp() for e, k in zip(cw["kalshi_event_ticker"], cw["kickoff_utc"])}
    m["kickoff_milestone"] = np.where(m["src_t3"] == "milestone", m["kick_t3"], np.nan)
    m["kickoff_sportsbook"] = m["event_ticker"].map(book)
    m["kickoff_ts"] = m["kickoff_milestone"].fillna(m["kickoff_sportsbook"]).fillna(m["kick_t3"])
    m["kickoff_source"] = np.where(m["kickoff_milestone"].notna(), "Kalshi milestone",
                                   np.where(m["kickoff_sportsbook"].notna(), "sportsbook feed",
                                            np.where(m["kick_t3"].notna(), "estimated", "none")))
    suffix = [t[len(e) + 1:] if isinstance(e, str) else "" for t, e in zip(m["ticker"], m["event_ticker"])]
    block = [e.split("-", 1)[1][7:] if isinstance(e, str) and "-" in e else "" for e in m["event_ticker"]]
    m["team"] = suffix
    m["is_away"] = [bool(s) and b.startswith(s) for s, b in zip(suffix, block)]
    m["result"] = m["result"].fillna("")
    return m[cols].reset_index(drop=True)


# --------------------------------------------------------------------------------------
# trades: one pass per market, cached
# --------------------------------------------------------------------------------------

AGG_KEYS = ["bin", "pbucket", "group", "sizeb"]
AGG_SUMS = ["trades", "contracts", "dollars", "fee", "fee_exact", "res_contracts", "res_dollars",
            "res_fee", "won"]


def process_market(trades: pd.DataFrame, kickoff_ts: float, result: str, settle_ts: float | None) -> dict[str, Any]:
    """Per-trade work for one market, reduced to small arrays/tables."""
    side = trades["taker_outcome_side"].astype(str).str.lower().to_numpy()
    yes = trades["yes_price"].to_numpy(dtype=float)
    c = trades["count"].to_numpy(dtype=float)
    p = np.where(side == "yes", yes, 1 - yes)
    ts = pd.to_datetime(trades["created_time"], utc=True, format="ISO8601")
    secs = ((ts - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1)).to_numpy(dtype=float)
    minutes = (secs - kickoff_ts) / 60
    fee = fee_dollars(c, p)
    fee_exact = TAKER_RATE * c * p * (1 - p)
    resolved = result in ("yes", "no")
    won = (side == result).astype(float) * c if resolved else np.zeros_like(c)
    df = pd.DataFrame({
        "bin": time_bin(minutes), "pbucket": price_bucket(p), "group": price_group(p), "sizeb": size_bucket(c),
        "trades": 1, "contracts": c, "dollars": c * p, "fee": fee, "fee_exact": fee_exact,
        "res_contracts": c if resolved else 0.0, "res_dollars": c * p if resolved else 0.0,
        "res_fee": fee if resolved else 0.0, "won": won,
    })
    agg = df.groupby(AGG_KEYS, as_index=False)[AGG_SUMS].sum()
    rng = np.random.default_rng(len(c))
    pick = rng.choice(len(c), size=min(20, len(c)), replace=False) if len(c) else np.array([], dtype=int)
    after = int((secs > settle_ts).sum()) if settle_ts and not math.isnan(settle_ts) else 0
    return {"agg": agg, "contracts": c.astype(np.float32), "dollars": (c * p).astype(np.float32),
            "inplay": (minutes >= 0), "sample": [(float(c[i]), float(p[i]), float(fee[i])) for i in pick],
            "n": int(len(c)), "after_settle": after, "unbinned": int((df["bin"] < 0).sum())}


def market_trades(season: int, mk: pd.Series, trades_dir: Path, cache_dir: Path) -> dict[str, Any] | None:
    path = trades_dir / str(season) / f"{mk['ticker']}.csv.gz"
    if not path.exists():
        return None
    key = (CACHE_VERSION, path.stat().st_mtime_ns, path.stat().st_size, float(mk["kickoff_ts"]), mk["result"],
           None if pd.isna(mk["settle_ts"]) else float(mk["settle_ts"]))
    cache = cache_dir / f"{mk['ticker']}.pkl"
    if cache.exists():
        try:
            saved = pickle.loads(cache.read_bytes())
            if saved.get("key") == key:
                return saved["data"]
        except Exception:  # noqa: BLE001 - a broken cache file is just rebuilt
            pass
    t = pd.read_csv(path, usecols=["count", "yes_price", "created_time", "taker_outcome_side"])
    data = process_market(t, float(mk["kickoff_ts"]), mk["result"],
                          None if pd.isna(mk["settle_ts"]) else float(mk["settle_ts"]))
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(pickle.dumps({"key": key, "data": data}))
    return data


# --------------------------------------------------------------------------------------
# candles: bid/ask sampled on a minute grid around kickoff
# --------------------------------------------------------------------------------------


def candle_grid(markets: pd.DataFrame, db: Path = TASK3_DB) -> pd.DataFrame:
    """Latest candle at or before each grid minute (and calibration checkpoint), per market.
    A quote is only used before the market settled."""
    minutes = sorted(set(GRID) | set(CAL_CHECKPOINTS))
    rows = []
    if not db.exists() or markets.empty:
        return pd.DataFrame(columns=["ticker", "minute", "bid", "ask", "age_min"])
    with sqlite3.connect(db) as conn:
        for mk in markets.itertuples():
            if pd.isna(mk.kickoff_ts):
                continue
            k = float(mk.kickoff_ts)
            c = pd.read_sql_query("SELECT ts, bid, ask FROM candles WHERE market_id = ? AND ts BETWEEN ? AND ? "
                                  "ORDER BY ts", conn, params=(int(mk.id), int(k - 86_400), int(k + 6 * 3600)))
            if c.empty:
                continue
            ts = c["ts"].to_numpy(dtype=float)
            for m in minutes:
                t = k + m * 60
                if not pd.isna(mk.settle_ts) and t >= float(mk.settle_ts):
                    continue
                i = int(np.searchsorted(ts, t, side="right")) - 1
                if i < 0:
                    continue
                rows.append((mk.ticker, m, c["bid"].iat[i], c["ask"].iat[i], (t - ts[i]) / 60))
    g = pd.DataFrame(rows, columns=["ticker", "minute", "bid", "ask", "age_min"])
    g["bid"] = g["bid"] / PRICE_SCALE
    g["ask"] = g["ask"] / PRICE_SCALE
    return g


def spread_cost(grid: pd.DataFrame, n: int) -> pd.DataFrame:
    """Two-sided quotes only: spread (cents) and cost per $10 of buying n contracts at the ask,
    split into the spread part (ask above mid) and the fee part; fair price = mid."""
    q = grid[(grid["bid"] > 0) & (grid["ask"] < 1) & (grid["ask"] > grid["bid"])].copy()
    q["mid"] = (q["bid"] + q["ask"]) / 2
    fee_pc = fee_dollars(np.full(len(q), float(n)), q["ask"].to_numpy()) / n
    paid = q["ask"] + fee_pc
    q["spread_c"] = (q["ask"] - q["bid"]) * 100
    q["spread_part"] = 10 * (q["ask"] - q["mid"]) / paid
    q["fee_part"] = 10 * fee_pc / paid
    q["cost"] = q["spread_part"] + q["fee_part"]
    q["group"] = price_group(q["mid"].to_numpy())
    return q


# --------------------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------------------


def boot_weights(n_games: int, b: int = BOOT, seed: int = SEED) -> np.ndarray:
    """b x n_games matrix of how many times each game is drawn in each resample."""
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n_games, size=(b, n_games))
    w = np.zeros((b, n_games))
    for r in range(b):
        w[r] = np.bincount(idx[r], minlength=n_games)
    return w


def logistic_fit(x: np.ndarray, y: np.ndarray, iters: int = 50) -> tuple[float, float]:
    """Intercept and slope of P(y=1) = 1 / (1 + exp(-(a + b x))) by Newton's method."""
    a, b = 0.0, 1.0
    for _ in range(iters):
        z = np.clip(a + b * x, -30, 30)
        p = 1 / (1 + np.exp(-z))
        w = p * (1 - p) + 1e-12
        g = np.array([np.sum(y - p), np.sum((y - p) * x)])
        h = np.array([[np.sum(w), np.sum(w * x)], [np.sum(w * x), np.sum(w * x * x)]])
        step = np.linalg.solve(h, g)
        a, b = a + step[0], b + step[1]
        if np.max(np.abs(step)) < 1e-10:
            break
    return float(a), float(b)


def calibration(grid: pd.DataFrame, markets: pd.DataFrame) -> dict[str, Any]:
    """One market per game (the away team's), mid price at each checkpoint vs how it settled."""
    m = markets[markets["is_away"] & markets["result"].isin(["yes", "no"])][["ticker", "event_ticker", "result"]]
    g = grid[grid["minute"].isin(CAL_CHECKPOINTS)].merge(m, on="ticker")
    g = g[(g["bid"] > 0) & (g["ask"] < 1) & (g["ask"] >= g["bid"])].copy()
    g["mid"] = (g["bid"] + g["ask"]) / 2
    g["y"] = (g["result"] == "yes").astype(float)
    by_cp, rel = [], []
    w_cache: dict[int, np.ndarray] = {}
    for cp in CAL_CHECKPOINTS:
        d = g[g["minute"] == cp]
        if len(d) < 5:
            continue
        sq = (d["mid"] - d["y"]) ** 2
        n = len(d)
        w = w_cache.setdefault(n, boot_weights(n))
        boots = (w @ sq.to_numpy()) / n
        x = np.log(np.clip(d["mid"], 0.01, 0.99) / (1 - np.clip(d["mid"], 0.01, 0.99)))
        a, b = logistic_fit(x.to_numpy(), d["y"].to_numpy())
        by_cp.append({"minute": cp, "games": n, "brier": float(sq.mean()),
                      "brier_lo": float(np.percentile(boots, 2.5)), "brier_hi": float(np.percentile(boots, 97.5)),
                      "brier_coinflip": 0.25, "slope": b, "intercept": a,
                      "mean_abs_from_50": float((d["mid"] - 0.5).abs().mean())})
    for cp in (-60, 60, 120):
        d = g[g["minute"] == cp].copy()
        if d.empty:
            continue
        d["bucket"] = np.clip((d["mid"] * 10).astype(int), 0, 9)
        r = d.groupby("bucket").agg(games=("y", "size"), mean_price=("mid", "mean"), won=("y", "mean")).reset_index()
        r["minute"] = cp
        r["bucket_label"] = r["bucket"].map(lambda i: PRICE_BUCKETS[i])
        rel += r.to_dict("records")
    return {"by_checkpoint": by_cp, "reliability": rel, "n_obs": int(len(g)),
            "games_by_checkpoint": {int(k): int(v) for k, v in g.groupby("minute").size().items()},
            "max_age_negative": float(g["age_min"].min()) if len(g) else 0.0}


def trade_analyses(season: int, markets: pd.DataFrame, per_market: dict[str, dict[str, Any]]) -> dict[str, Any]:
    games = {t: e for t, e in zip(markets["ticker"], markets["event_ticker"])}
    kick = {e: k for e, k in zip(markets["event_ticker"], markets["kickoff_ts"])}
    frames = []
    for t, d in per_market.items():
        a = d["agg"].copy()
        a["game"] = games[t]
        frames.append(a)
    agg = pd.concat(frames, ignore_index=True)
    agg["inplay"] = agg["bin"] >= BIN_LABELS.index("0–30 min")
    tot = agg[AGG_SUMS].sum()

    by_bin = agg.groupby("bin")[["trades", "dollars", "fee"]].sum().reindex(range(len(TIME_BINS)), fill_value=0)
    by_bin.insert(0, "bin_label", BIN_LABELS)
    by_bin["dollar_share"] = by_bin["dollars"] / tot["dollars"]
    by_bin["fee_share"] = by_bin["fee"] / tot["fee"]
    by_bin["fee_per_10"] = 10 * by_bin["fee"] / by_bin["dollars"].where(by_bin["dollars"] > 0)

    pg = agg.groupby(["inplay", "group"])[["dollars", "fee", "trades"]].sum().reset_index()
    pg["phase"] = np.where(pg["inplay"], "In-game", "Pre-game")
    pg["group_label"] = pg["group"].map(lambda i: GROUPS[i])
    pg["fee_share"] = pg["fee"] / tot["fee"]
    pg["dollar_share"] = pg["dollars"] / tot["dollars"]
    pg["fee_per_10"] = 10 * pg["fee"] / pg["dollars"]

    # trade sizes
    sizes = []
    for phase, flag in (("Pre-game", False), ("In-game", True)):
        c = np.concatenate([d["contracts"][d["inplay"] == flag] for d in per_market.values()])
        usd = np.concatenate([d["dollars"][d["inplay"] == flag] for d in per_market.values()])
        sizes.append({"phase": phase, "trades": int(len(c)), "median": _pct(c, 50), "p75": _pct(c, 75),
                      "p90": _pct(c, 90), "median_dollars": _pct(usd, 50), "p90_dollars": _pct(usd, 90),
                      "share_1_or_less": float((c <= 1).mean()) if len(c) else None})

    rnd = agg.groupby(["inplay", "sizeb"])[["fee", "fee_exact", "trades"]].sum().reset_index()
    rnd["phase"] = np.where(rnd["inplay"], "In-game", "Pre-game")
    rnd["size_label"] = rnd["sizeb"].map(lambda i: SIZE_BUCKETS[i])
    rnd["rounding_extra"] = rnd["fee"] / rnd["fee_exact"] - 1

    # taker results with game bootstrap
    ret = taker_returns(agg)

    # concentration
    ig = agg[agg["inplay"]].groupby("game")["dollars"].sum().sort_values(ascending=False)
    slots = pd.DataFrame({"game": list(kick), "slot": [kickoff_slot(k) for k in kick.values()]})
    gd = agg.groupby(["game", "inplay"])["dollars"].sum().unstack(fill_value=0).rename(columns={False: "pre", True: "inplay"})
    gd = gd.reset_index().merge(slots, on="game", how="left")
    slot = gd.groupby("slot").agg(games=("game", "nunique"), pre=("pre", "sum"), inplay=("inplay", "sum")).reset_index()
    slot["inplay_per_game"] = slot["inplay"] / slot["games"]
    slot["pre_per_game"] = slot["pre"] / slot["games"]
    slot["inplay_share"] = slot["inplay"] / (slot["inplay"] + slot["pre"])

    near = agg[agg["inplay"]]
    near_certain = {
        "dollar_share_90_plus": float(near.loc[near["pbucket"] == 9, "dollars"].sum() / near["dollars"].sum()),
        "trade_share_90_plus": float(near.loc[near["pbucket"] == 9, "trades"].sum() / near["trades"].sum()),
        "fee_share_90_plus": float(near.loc[near["pbucket"] == 9, "fee"].sum() / near["fee"].sum()),
        "dollar_share_10_minus": float(near.loc[near["pbucket"] == 0, "dollars"].sum() / near["dollars"].sum()),
    }
    return {"totals": {k: float(v) for k, v in tot.items()}, "by_bin": by_bin, "by_phase_group": pg, "sizes": sizes,
            "rounding": rnd, "returns": ret, "top10_inplay_share": float(ig.head(10).sum() / ig.sum()) if len(ig) else None,
            "games_with_trades": int(agg["game"].nunique()), "by_slot": slot, "near_certain": near_certain, "agg": agg}


def taker_returns(agg: pd.DataFrame) -> dict[str, Any]:
    """Taker result per $10, before and after fees, by phase x price group and phase x price decile,
    with 95% intervals from resampling games."""
    res = agg[agg["res_dollars"] > 0]
    games = sorted(res["game"].unique())
    gi = {g: i for i, g in enumerate(games)}
    w = boot_weights(len(games))
    out = {}
    for name, keys in (("by_group", ["inplay", "group"]), ("by_decile", ["inplay", "pbucket"]), ("by_phase", ["inplay"])):
        rows = []
        for key, d in res.groupby(keys):
            key = key if isinstance(key, tuple) else (key,)
            per_game = d.groupby("game")[["res_dollars", "won", "res_fee", "res_contracts"]].sum()
            M = np.zeros((len(games), 4))
            M[[gi[g] for g in per_game.index]] = per_game.to_numpy()
            s = M.sum(axis=0)
            bs = w @ M
            with np.errstate(invalid="ignore", divide="ignore"):  # resamples that miss every game of a cell
                before = 10 * (bs[:, 1] - bs[:, 0]) / bs[:, 0]
                after = 10 * (bs[:, 1] - bs[:, 0] - bs[:, 2]) / bs[:, 0]
            row = {"phase": "In-game" if key[0] else "Pre-game", "dollars": s[0], "games": int(len(per_game)),
                   "avg_price": s[0] / s[3], "win_rate": s[1] / s[3],
                   "before_fees": 10 * (s[1] - s[0]) / s[0], "after_fees": 10 * (s[1] - s[0] - s[2]) / s[0],
                   "before_lo": np.nanpercentile(before, 2.5), "before_hi": np.nanpercentile(before, 97.5),
                   "after_lo": np.nanpercentile(after, 2.5), "after_hi": np.nanpercentile(after, 97.5)}
            if len(key) > 1:
                row["group_label" if name == "by_group" else "bucket_label"] = (
                    GROUPS[key[1]] if name == "by_group" else PRICE_BUCKETS[key[1]])
            rows.append(row)
        out[name] = pd.DataFrame(rows)
    out["games"] = len(games)
    return out


# --------------------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------------------


def _c(cid: str, title: str, status: str, detail: str, guards: str) -> dict[str, str]:
    return {"id": cid, "title": title, "status": status, "detail": detail, "guards_against": guards}


def run_checks(season: int, markets: pd.DataFrame, per_market: dict[str, dict[str, Any]], ta: dict[str, Any] | None,
               grid: pd.DataFrame, cal: dict[str, Any], align_dir: Path = ALIGN_DIR) -> list[dict[str, str]]:
    out = []
    # 1. trades reconcile with the trade-size run
    if ta is not None:
        n_rows = sum(d["n"] for d in per_market.values())
        ts_path = align_dir / f"trade_sizes_{season}.json"
        ref = None
        if ts_path.exists():
            st = json.loads(ts_path.read_text())["stats"]
            ref = st.get(SERIES, st.get("all NFL markets", {})).get("including block trades", {}).get("trades")
        status = "pass" if ref is None or ref == n_rows else "fail"
        out.append(_c("trades_reconcile", "Every saved trade is read exactly once", status,
                      f"{n_rows:,} trades read from {len(per_market)} market files"
                      + (f"; the trade-size report counted {ref:,}." if ref is not None else "; no trade-size report to compare."),
                      "Files skipped or read twice, which would scale every total."))
        unb = sum(d["unbinned"] for d in per_market.values())
        tot = ta["totals"]
        bin_sum = float(ta["by_bin"]["trades"].sum())
        out.append(_c("bins_complete", "Every trade lands in exactly one time bin", "pass" if unb == 0 and
                      abs(bin_sum - tot["trades"]) < 0.5 else "fail",
                      f"{unb} trades outside the bins; bins hold {bin_sum:,.0f} of {tot['trades']:,.0f} trades.",
                      "Trades lost between bins, so shares would not add to 100%."))
        # fee recompute, exact arithmetic
        bad = 0
        n_s = 0
        for d in per_market.values():
            for c, p, f in d["sample"]:
                n_s += 1
                cents = Fraction(7, 100) * Fraction(str(c)) * Fraction(str(p)) * (1 - Fraction(str(p))) * 100
                exact = Fraction(-(-cents.numerator // cents.denominator), 100)
                bad += abs(float(exact) - f) > 1e-9
        out.append(_c("fee_recompute", "Fees recomputed with exact fractions", "fail" if bad else "pass",
                      f"{n_s} sampled trades: fee = 0.07 x contracts x p x (1 - p) rounded up to the cent; {bad} differ.",
                      "Fee rounded down, or computed on the wrong side's price."))
        after = sum(d["after_settle"] for d in per_market.values())
        out.append(_c("no_trades_after_settle", "No trades after a market settled", "warn" if after else "pass",
                      f"{after} trades time-stamped after their market's settlement.",
                      "Wrong settlement or kickoff times shifting trades into the wrong phase."))
        # returns: two independent paths to the same total
        r = ta["returns"]["by_phase"]
        a = ta["agg"]
        res = a[a["res_dollars"] > 0]
        direct = 10 * (res["won"].sum() - res["res_dollars"].sum() - res["res_fee"].sum()) / res["res_dollars"].sum()
        via = 10 * ((r["after_fees"] * r["dollars"]).sum() / 10) / r["dollars"].sum()
        out.append(_c("returns_identity", "Taker results add up across phases", "pass" if abs(direct - via) < 1e-9 else "fail",
                      f"All settled trades: {direct:+.4f} per $10 directly, {via:+.4f} from the phase rows.",
                      "Rows double counted or dropped in the taker-result tables."))
    # 2. kickoff sources
    src = markets["kickoff_source"].value_counts().to_dict()
    both = markets.dropna(subset=["kickoff_milestone", "kickoff_sportsbook"])
    diff = (both["kickoff_milestone"] - both["kickoff_sportsbook"]).abs() / 60
    status = "fail" if src.get("none") else ("warn" if len(diff) and diff.max() > 15 else "pass")
    out.append(_c("kickoff_sources", "Kickoff times known and consistent", status,
                  "Sources: " + ", ".join(f"{k} {v}" for k, v in src.items()) + (
                      f". Where Kalshi and the sportsbook feed both have a start time ({len(diff)} markets), "
                      f"median gap {diff.median():.1f} min, largest {diff.max():.1f} min." if len(diff) else "."),
                  "Trades put in the wrong phase because kickoff is off."))
    # 3. results consistent per game
    r = markets[markets["result"].isin(["yes", "no"])].groupby("event_ticker")["result"].agg(lambda s: sorted(s))
    bad_games = [e for e, v in r.items() if v != ["no", "yes"]]
    ties = sorted(markets.loc[markets["result"] == "scalar", "event_ticker"].unique())
    unsettled = int((~markets["result"].isin(["yes", "no", "scalar"])).sum())
    out.append(_c("results_consistent", "Exactly one team wins each settled game", "fail" if bad_games else "pass",
                  f"{len(r)} settled games; {len(bad_games)} without one yes and one no"
                  + (f" ({', '.join(bad_games[:3])})" if bad_games else "")
                  + f". Ties left out: {', '.join(ties) or 'none'}. Markets not settled yet: {unsettled}.",
                  "A result read for the wrong team, which flips taker results."))
    # 4. candles: no look-ahead, sample size
    if len(grid):
        neg = int((grid["age_min"] < -1e-9).sum())
        out.append(_c("no_lookahead", "Prices come from at or before each moment", "fail" if neg else "pass",
                      f"{len(grid):,} sampled quotes; {neg} from after their moment.",
                      "Using a later price, which makes prices look more accurate than they were."))
        crossed = int(((grid["bid"] > grid["ask"]) & (grid["bid"] > 0) & (grid["ask"] > 0)).sum())
        one_sided = float(((grid["bid"] <= 0) | (grid["ask"] >= 1)).mean())
        out.append(_c("quotes_valid", "Quotes are two-sided and not crossed", "fail" if crossed else "pass",
                      f"{crossed} crossed quotes; {one_sided:.1%} of sampled moments have only one side (left out of costs).",
                      "Negative spreads or one-sided books entering the cost numbers."))
        nmin = min(cal["games_by_checkpoint"].values()) if cal["games_by_checkpoint"] else 0
        out.append(_c("calibration_sample", "Enough games at every checkpoint", "warn" if nmin < 30 else "pass",
                      f"Games per checkpoint: " + ", ".join(f"{k:+d} min {v}" for k, v in cal["games_by_checkpoint"].items()) + ".",
                      "Reading accuracy differences into a handful of games."))
    else:
        out.append(_c("no_lookahead", "Prices come from at or before each moment", "skip", "No candles for this season.", ""))
    return out


# --------------------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------------------


def n_median(season: int, align_dir: Path = ALIGN_DIR) -> tuple[int, str]:
    from app.alignment import costs as cm

    n, src = cm.n_values(season, align_dir)
    return (n[0][1], src) if n and n[0][0] == "median" else (DEFAULT_N, "default 24 contracts")


def analyze(season: int, db: Path = TASK3_DB, trades_dir: Path = TRADES_DIR, align_dir: Path = ALIGN_DIR,
            out_dir: Path = OUT_DIR) -> dict[str, Any]:
    markets = load_markets(season, db, align_dir)
    cache_dir = out_dir / "cache" / str(season)
    per_market = {}
    for mk in markets.itertuples(index=False):
        if pd.isna(mk.kickoff_ts):
            continue
        d = market_trades(season, pd.Series(mk._asdict()), trades_dir, cache_dir)
        if d is not None and d["n"]:
            per_market[mk.ticker] = d
    ta = trade_analyses(season, markets, per_market) if per_market else None
    grid = candle_grid(markets, db)
    n, n_src = n_median(season, align_dir)
    sc = spread_cost(grid, n) if len(grid) else pd.DataFrame()
    cal = calibration(grid, markets) if len(grid) else {"by_checkpoint": [], "reliability": [], "games_by_checkpoint": {}}
    checks = run_checks(season, markets, per_market, ta, grid, cal, align_dir)

    result: dict[str, Any] = {"season": season, "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                              "markets": int(len(markets)), "games": int(markets["event_ticker"].nunique()),
                              "settled_games": int(markets.loc[markets["result"].isin(["yes", "no"]), "event_ticker"].nunique()),
                              "n_contracts": n, "n_source": n_src, "has_trades": ta is not None}
    if len(sc):
        by_min = sc.groupby("minute").agg(markets=("ticker", "nunique"), spread_c=("spread_c", "median"),
                                          cost=("cost", "median"), spread_part=("spread_part", "median"),
                                          fee_part=("fee_part", "median")).reset_index()
        by_min = by_min[by_min["minute"].isin(GRID)]
        sc["phase"] = np.where(sc["minute"] >= 0, "In-game", "Pre-game")
        sc_win = sc[sc["minute"].between(-60, 180)]
        by_pg = sc_win.groupby(["phase", "group"]).agg(quotes=("cost", "size"), spread_c=("spread_c", "median"),
                                                       cost=("cost", "median"), fee_part=("fee_part", "median"),
                                                       spread_part=("spread_part", "median")).reset_index()
        by_pg["group_label"] = by_pg["group"].map(lambda i: GROUPS[i])
        one_sided = grid.assign(two=(grid["bid"] > 0) & (grid["ask"] < 1) & (grid["ask"] > grid["bid"]))
        one_sided = one_sided[one_sided["minute"].isin(GRID)].groupby("minute")["two"].mean().reset_index()
        one_sided.columns = ["minute", "two_sided_share"]
        result["spread_by_minute"] = _records(by_min.merge(one_sided, on="minute", how="left"))
        result["cost_by_phase_group"] = _records(by_pg)
    result["calibration"] = {"by_checkpoint": _records(pd.DataFrame(cal["by_checkpoint"])),
                             "reliability": _records(pd.DataFrame(cal["reliability"]))}
    if ta is not None:
        result["trades"] = {
            "totals": {k: _r(v, 2) for k, v in ta["totals"].items()},
            "by_bin": _records(ta["by_bin"].reset_index(drop=True)),
            "by_phase_group": _records(ta["by_phase_group"][["phase", "group_label", "trades", "dollars", "fee",
                                                             "dollar_share", "fee_share", "fee_per_10"]]),
            "sizes": [{k: _r(v) if isinstance(v, float) else v for k, v in s.items()} for s in ta["sizes"]],
            "rounding": _records(ta["rounding"][["phase", "size_label", "trades", "fee", "fee_exact", "rounding_extra"]]),
            "returns_by_group": _records(ta["returns"]["by_group"]),
            "returns_by_decile": _records(ta["returns"]["by_decile"]),
            "returns_by_phase": _records(ta["returns"]["by_phase"]),
            "returns_games": ta["returns"]["games"],
            "by_slot": _records(ta["by_slot"]),
            "top10_inplay_share": _r(ta["top10_inplay_share"]),
            "games_with_trades": ta["games_with_trades"],
            "near_certain": {k: _r(v) for k, v in ta["near_certain"].items()},
        }
    result["facts"] = facts(result)
    result["checks"] = checks
    folder = out_dir / str(season)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "results.json").write_text(json.dumps(result, indent=1, default=str))
    (folder / "checks.json").write_text(json.dumps(checks, indent=2))
    index = {"generated_at": result["generated_at"],
             "seasons": sorted({*json.loads((out_dir / "index.json").read_text()).get("seasons", []), season})
             if (out_dir / "index.json").exists() else [season]}
    (out_dir / "index.json").write_text(json.dumps(index, indent=2))
    return result


def facts(r: dict[str, Any]) -> dict[str, Any]:
    """Headline numbers the page text is built from (nothing hard-coded on the page)."""
    f: dict[str, Any] = {"season": r["season"], "games": r["games"], "settled_games": r["settled_games"],
                         "has_trades": r["has_trades"], "n_contracts": r["n_contracts"]}
    t = r.get("trades")
    if t:
        tot = t["totals"]
        pg = t["by_phase_group"]
        inplay = [x for x in pg if x["phase"] == "In-game"]
        f["dollars"] = tot["dollars"]
        f["fees"] = tot["fee"]
        f["trades"] = tot["trades"]
        f["inplay_dollar_share"] = sum(x["dollar_share"] for x in inplay)
        f["inplay_fee_share"] = sum(x["fee_share"] for x in inplay)
        f["fee_per_10"] = 10 * tot["fee"] / tot["dollars"]
        rp = {x["phase"]: x for x in t["returns_by_phase"]}
        f["taker_after_fees"] = {k: v["after_fees"] for k, v in rp.items()}
        f["taker_before_fees"] = {k: v["before_fees"] for k, v in rp.items()}
        f["taker_after_ci"] = {k: [v["after_lo"], v["after_hi"]] for k, v in rp.items()}
        f["sizes"] = {s["phase"]: s for s in t["sizes"]}
        f["near_certain"] = t["near_certain"]
        f["top10_inplay_share"] = t["top10_inplay_share"]
        rnd = [x for x in t["rounding"] if x["size_label"] == "1 or less"]
        f["rounding_small"] = {x["phase"]: x["rounding_extra"] for x in rnd}
        f["rounding_total"] = sum(x["fee"] for x in t["rounding"]) / sum(x["fee_exact"] for x in t["rounding"]) - 1
        f["games_with_trades"] = t["games_with_trades"]
        f["returns_games"] = t["returns_games"]
        for phase in ("Pre-game", "In-game"):
            rows = [x for x in pg if x["phase"] == phase]
            f[f"fee_per_10_{'pre' if phase == 'Pre-game' else 'in'}"] = (
                10 * sum(x["fee"] for x in rows) / sum(x["dollars"] for x in rows) if rows else None)
        bins = {x["bin_label"]: x for x in t["by_bin"]}
        f["peak_bin"] = max(t["by_bin"], key=lambda x: x["dollars"])["bin_label"]
        f["peak_bin_share"] = max(x["dollar_share"] for x in t["by_bin"])
        f["late_fee_per_10"] = bins["150–180 min"]["fee_per_10"]
        slots = {x["slot"]: x for x in t["by_slot"]}
        prime = [slots[s] for s in ("Thursday night", "Sunday night", "Monday night") if s in slots]
        day = [slots[s] for s in ("Sunday early", "Sunday late") if s in slots]
        if prime and day:
            f["prime_inplay_per_game"] = sum(x["inplay"] for x in prime) / sum(x["games"] for x in prime)
            f["day_inplay_per_game"] = sum(x["inplay"] for x in day) / sum(x["games"] for x in day)
        grp = {(x["phase"], x["group_label"]): x for x in pg}
        il = grp.get(("In-game", GROUPS[0]))
        if il:
            f["inplay_longshot_dollar_share"] = il["dollar_share"]
            f["inplay_longshot_fee_share"] = il["fee_share"]
    cal = r["calibration"]["by_checkpoint"]
    if cal:
        f["brier"] = {x["minute"]: x["brier"] for x in cal}
        f["slope"] = {x["minute"]: x["slope"] for x in cal}
    s = r.get("cost_by_phase_group")
    if s:
        f["cost_phase_group"] = {f"{x['phase']}|{x['group_label']}": x["cost"] for x in s}
        f["spread_phase_group"] = {f"{x['phase']}|{x['group_label']}": x["spread_c"] for x in s}
    return f


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="In-game Kalshi NFL analysis for one season.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args(argv)
    r = analyze(args.season)
    tally = {s: sum(c["status"] == s for c in r["checks"]) for s in ("pass", "warn", "skip", "fail")}
    print(f"{args.season}: {r['games']} games, trades: {'yes' if r['has_trades'] else 'no'}; checks "
          + ", ".join(f"{n} {s}" for s, n in tally.items() if n))
    for c in r["checks"]:
        if c["status"] in ("warn", "fail"):
            print(f"  {c['status'].upper()} {c['title']}: {c['detail']}")
    print(f"files: {OUT_DIR / str(args.season)}")
    return 1 if tally["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
