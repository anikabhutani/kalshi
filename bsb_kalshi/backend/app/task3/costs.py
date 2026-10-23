"""Trading costs from stored 1-minute candles, plus a quality check of the stored data.

Cost of a bet placed at a checkpoint before kickoff (taker order that crosses the spread):

    cost = contracts x half the bid-ask gap + Kalshi taker fee

The standing quote at a checkpoint is the close bid/ask of the latest candle ending at or before
it (Kalshi only emits a 1-minute candle when something changed). Each market can be bought on
the YES side (pay the ask) or the NO side (pay 1 - bid); both are counted. Cost per $10 bet
scales the cost to $10 staked: ``10 x cost / (contracts x price paid)``.

Taker fee (series ``fee_type`` quadratic*, Kalshi fee schedule and docs.kalshi.com fee
rounding): ``0.07 x multiplier x contracts x price x (1 - price)``, rounded up to the cent
(``fee_rounding="cent"``) or to $0.0001 (``"exact"``, direct-member balance precision).
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel

from app.analysis.timestamps import iso, to_epoch
from app.task3.store import PRICE_SCALE, NflStore

CHECKPOINTS: list[tuple[str, int]] = [("24h", 86_400), ("3h", 10_800), ("1h", 3_600), ("15m", 900)]
SIZES = [1, 10, 100]
STAKE = 10.0
TAKER_RATE = 0.07
WIDE_GAP = 300
PRICE_GROUPS = [f"{lo}–{lo + 9}¢" if lo else "1–9¢" for lo in range(0, 100, 10)]
QUADRATIC = frozenset({"quadratic", "quadratic_with_maker_fees", "quadratic_with_combo_maker_fees"})
LIST_LIMIT = 300


class AnalysisParams(BaseModel):
    """User choices for the cost calculation (no requests are sent)."""

    fee_rounding: Literal["cent", "exact"] = "cent"


def fee_dollars(contracts: int, price: float, multiplier: float, rounding: str = "cent") -> float:
    """Kalshi taker fee for ``contracts`` at ``price`` dollars, rounded up."""
    model = TAKER_RATE * multiplier * contracts * price * (1 - price)
    step = 0.01 if rounding == "cent" else 0.0001
    return math.ceil(model / step - 1e-7) * step


def price_group(price: float) -> str:
    return PRICE_GROUPS[min(9, max(0, int(round(price * 100)) // 10))]


def bet_costs(bid: int, ask: int, multiplier: float, rounding: str) -> list[dict[str, Any]]:
    """Cost rows for both sides and every size from one two-sided quote (prices in 1/10,000 $)."""
    half = (ask - bid) / 2 / PRICE_SCALE
    rows: list[dict[str, Any]] = []
    for side, paid in (("yes", ask / PRICE_SCALE), ("no", 1 - bid / PRICE_SCALE)):
        if not 0 < paid < 1:
            continue
        for size in SIZES:
            fee = fee_dollars(size, paid, multiplier, rounding)
            stake = size * paid
            rows.append(
                {
                    "side": side,
                    "size": size,
                    "price_paid": round(paid, 4),
                    "price_group": price_group(paid),
                    "half_gap": half,
                    "fee": round(fee, 6),
                    "cost": size * half + fee,
                    "cost_per_10": STAKE * (size * half + fee) / stake,
                    "gap_part_per_10": STAKE * size * half / stake,
                    "fee_part_per_10": STAKE * fee / stake,
                }
            )
    return rows


class FeeBook:
    """Fee type and multiplier in effect for a market at a moment (series value, scheduled
    series changes, then event overrides)."""

    def __init__(self, fees: dict[str, Any]) -> None:
        self.series = fees.get("series") or {}
        self.changes = sorted(
            (c for c in fees.get("series_changes") or [] if to_epoch(c.get("scheduled_ts")) is not None),
            key=lambda c: to_epoch(c["scheduled_ts"]) or 0,
        )
        self.overrides = sorted(
            (c for c in fees.get("event_overrides") or [] if to_epoch(c.get("scheduled_ts")) is not None),
            key=lambda c: to_epoch(c["scheduled_ts"]) or 0,
        )

    def at(self, series: str, event: str, ts: int) -> tuple[str | None, float]:
        current = self.series.get(series) or {}
        fee_type, mult = current.get("fee_type"), current.get("fee_multiplier")
        for c in self.changes:
            if c.get("series_ticker") == series and (to_epoch(c["scheduled_ts"]) or 0) <= ts:
                fee_type, mult = c.get("fee_type"), c.get("fee_multiplier")
        for o in self.overrides:
            if o.get("event_ticker") == event and (to_epoch(o["scheduled_ts"]) or 0) <= ts:
                if o.get("fee_type_override") is not None:
                    fee_type = o["fee_type_override"]
                if o.get("fee_multiplier_override") is not None:
                    mult = o["fee_multiplier_override"]
        return fee_type, float(mult if mult is not None else 1.0)


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Plain-Python records (numpy scalars would not survive ``json.dumps``)."""
    return json.loads(df.to_json(orient="records"))


def _summary(df: pd.DataFrame, keys: list[str]) -> list[dict[str, Any]]:
    if df.empty:
        return []
    out = (
        df.assign(cents_per_contract=df["cost"] / df["size"] * 100)
        .groupby(keys, sort=False)
        .agg(
            n=("cost_per_10", "size"),
            median=("cost_per_10", "median"),
            mean=("cost_per_10", "mean"),
            p25=("cost_per_10", lambda s: s.quantile(0.25)),
            p75=("cost_per_10", lambda s: s.quantile(0.75)),
            gap_part=("gap_part_per_10", "median"),
            fee_part=("fee_part_per_10", "median"),
            cents_per_contract=("cents_per_contract", "median"),
        )
        .reset_index()
        .round(4)
    )
    return _records(out)


def _with_all_types(df: pd.DataFrame) -> pd.DataFrame:
    return pd.concat([df, df.assign(market_type="All types")], ignore_index=True)


def run_analysis(store: NflStore, params: AnalysisParams, now: int | None = None) -> dict[str, Any]:
    """Compute costs, results and the quality check from stored data; saves and returns it."""
    now = int(time.time()) if now is None else now
    started = time.perf_counter()
    games = {g["game_key"]: g for g in store.games()}
    markets = store.markets()
    fees = FeeBook(store.get_meta("fees") or {})
    stats = store.candle_stats()

    quotes: list[dict[str, Any]] = []
    costs: list[dict[str, Any]] = []
    fee_types: Counter[str] = Counter()
    with store.connect() as conn:
        for m in markets:
            game = games.get(m["game_key"]) or {}
            kickoff = game.get("kickoff_ts")
            if kickoff is None:
                continue
            for label, offset in CHECKPOINTS:
                at = kickoff - offset
                base = {
                    "ticker": m["ticker"],
                    "event_ticker": m["event_ticker"],
                    "market_type": m["market_type"],
                    "week": game.get("week"),
                    "game": game.get("title"),
                    "kickoff_utc": iso(kickoff),
                    "checkpoint": label,
                    "checkpoint_utc": iso(at),
                }
                if at > now:
                    continue
                if m["open_ts"] is None or m["open_ts"] > at:
                    quotes.append({**base, "status": "not open yet"})
                    continue
                if m["close_ts"] is not None and m["close_ts"] < at:
                    quotes.append({**base, "status": "closed before checkpoint"})
                    continue
                q = store.quote_at(conn, m["id"], at)
                if q is None:
                    quotes.append({**base, "status": "no candle yet"})
                    continue
                bid, ask = q["bid"], q["ask"]
                row = {
                    **base,
                    "quote_ts_utc": iso(q["ts"]),
                    "quote_age_s": at - q["ts"],
                    "bid": None if bid is None else bid / PRICE_SCALE,
                    "ask": None if ask is None else ask / PRICE_SCALE,
                    "gap_cents": None if bid is None or ask is None else (ask - bid) / 100,
                }
                if bid is None or ask is None or bid <= 0 or ask >= PRICE_SCALE:
                    quotes.append({**row, "status": "one-sided book"})
                    continue
                if bid > ask:
                    quotes.append({**row, "status": "bid above ask"})
                    continue
                fee_type, mult = fees.at(m["series_ticker"], m["event_ticker"], at)
                fee_types[f"{fee_type} x{mult:g}"] += 1
                if fee_type not in QUADRATIC:
                    quotes.append({**row, "status": f"fee type {fee_type} not modelled"})
                    continue
                quotes.append({**row, "status": "ok", "wide": ask - bid >= WIDE_GAP})
                for c in bet_costs(bid, ask, mult, params.fee_rounding):
                    costs.append(
                        {
                            "ticker": m["ticker"],
                            "market_type": m["market_type"],
                            "week": game.get("week"),
                            "checkpoint": label,
                            **c,
                        }
                    )

    cost_df = pd.DataFrame(costs)
    quote_df = pd.DataFrame(quotes)
    results: dict[str, Any] = {"by_price_group": [], "by_market_type": [], "by_week": []}
    if not cost_df.empty:
        cost_df["week"] = cost_df["week"].astype("Int64")
        results["by_price_group"] = _summary(cost_df, ["checkpoint", "size", "price_group"])
        results["by_market_type"] = _summary(_with_all_types(cost_df), ["checkpoint", "size", "market_type"])
        results["by_week"] = _summary(_with_all_types(cost_df).dropna(subset=["week"]), ["checkpoint", "size", "market_type", "week"])
    gaps: list[dict[str, Any]] = []
    if not quote_df.empty and "gap_cents" in quote_df:
        ok = quote_df[quote_df["status"] == "ok"]
        if not ok.empty:
            ok = ok.assign(wide=ok["wide"].astype(bool), quote_age_s=ok["quote_age_s"].astype(float))
            g = _with_all_types(ok).groupby(["checkpoint", "market_type"], sort=False)
            gaps = _records(
                g.agg(
                    n=("gap_cents", "size"),
                    median_gap_cents=("gap_cents", "median"),
                    wide_share=("wide", "mean"),
                    median_quote_age_s=("quote_age_s", "median"),
                )
                .reset_index()
                .round(4)
            )

    export = store.root / "exports"
    export.mkdir(exist_ok=True)
    _write_csv(quote_df, export / "checkpoint_quotes.csv")
    _write_csv(cost_df, export / "checkpoint_costs.csv")

    result = {
        "generated_at": now,
        "params": params.model_dump(),
        "checkpoints": [c for c, _ in CHECKPOINTS],
        "sizes": SIZES,
        "price_groups": PRICE_GROUPS,
        "stake": STAKE,
        "fee_types_used": dict(fee_types),
        "counts": {
            "markets": len(markets),
            "quotes": len(quotes),
            "quotes_ok": int((quote_df["status"] == "ok").sum()) if not quote_df.empty else 0,
            "cost_rows": len(costs),
        },
        "results": results,
        "gaps": gaps,
        "quality": quality_check(markets, games, stats, quote_df, now),
        "seconds": round(time.perf_counter() - started, 2),
    }
    store.save_analysis(params.model_dump(), result)
    store.set_meta("analysis_params", params.model_dump())
    return result


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(path)


def quality_check(
    markets: list[dict[str, Any]],
    games: dict[str, dict[str, Any]],
    stats: dict[int, dict[str, int]],
    quote_df: pd.DataFrame,
    now: int,
) -> dict[str, Any]:
    """Missing candles, bid above ask, and gaps of 3¢ or more in our own stored data."""
    per_market: list[dict[str, Any]] = []
    by_type: dict[str, Counter[str]] = {}
    for m in markets:
        s = stats.get(m["id"], {})
        candles = s.get("candles", 0)
        game = games.get(m["game_key"]) or {}
        row = {
            "ticker": m["ticker"],
            "market_type": m["market_type"],
            "week": game.get("week"),
            "status": m["status"],
            "open_utc": iso(m["open_ts"]),
            "close_utc": iso(m["close_ts"]),
            "fetched_through_utc": iso(m["fetched_through"]),
            "complete": bool(m["complete"]),
            "candles": candles,
            "bid_above_ask": s.get("crossed", 0),
            "bid_equals_ask": s.get("locked", 0),
            "gap_3c_or_more": s.get("wide", 0),
            "one_sided": s.get("one_sided", 0),
            "last_error": m["last_error"],
        }
        two_sided = candles - s.get("one_sided", 0)
        row["gap_3c_share"] = round(s.get("wide", 0) / two_sided, 4) if two_sided > 0 else None
        per_market.append(row)
        c = by_type.setdefault(m["market_type"], Counter())
        c["markets"] += 1
        c["candles"] += candles
        c["missing_candles"] += 1 if m["fetched_through"] is not None and candles == 0 else 0
        c["not_fetched"] += 1 if m["fetched_through"] is None else 0
        c["incomplete"] += 0 if m["complete"] else 1
        c["bid_above_ask"] += s.get("crossed", 0)
        c["markets_bid_above_ask"] += 1 if s.get("crossed", 0) else 0
        c["bid_equals_ask"] += s.get("locked", 0)
        c["gap_3c_or_more"] += s.get("wide", 0)
        c["one_sided"] += s.get("one_sided", 0)
        c["fetch_errors"] += 1 if m["last_error"] else 0

    checkpoint_status: list[dict[str, Any]] = []
    if not quote_df.empty:
        checkpoint_status = _records(quote_df.groupby(["market_type", "checkpoint", "status"]).size().reset_index(name="n"))

    missing = [r for r in per_market if r["candles"] == 0]
    crossed = sorted((r for r in per_market if r["bid_above_ask"]), key=lambda r: -r["bid_above_ask"])
    wide = sorted((r for r in per_market if r["gap_3c_share"]), key=lambda r: -(r["gap_3c_share"] or 0))
    totals: Counter[str] = Counter()
    for counts in by_type.values():
        totals.update(counts)
    return {
        "checked_at": now,
        "totals": dict(totals),
        "by_market_type": [{"market_type": k, **dict(v)} for k, v in sorted(by_type.items())],
        "checkpoint_status": checkpoint_status,
        "missing_candles": missing[:LIST_LIMIT],
        "missing_candles_total": len(missing),
        "bid_above_ask": crossed[:LIST_LIMIT],
        "bid_above_ask_total": len(crossed),
        "wide_gap_markets": wide[:LIST_LIMIT],
        "wide_gap_markets_total": len(wide),
        "list_limit": LIST_LIMIT,
    }
