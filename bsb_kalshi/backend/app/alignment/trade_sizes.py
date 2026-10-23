"""Median, 75th and 90th percentile Kalshi trade sizes (contracts) for NFL markets, one season.

Task 3 stores 1-minute candles, which only hold the total volume per minute, so trade sizes need
the individual trades. For every NFL game, spread and total market in the Task 3 store whose game
date is in the season and before today, this pulls every trade from ``GET /markets/trades`` and
``GET /historical/trades`` (older trades move to the historical endpoint after Kalshi's cutoff),
merges the two by ``trade_id``, and saves them to ``data/alignment/trades/<season>/<ticker>.csv.gz``.

Pages are followed until the cursor is empty; there is no silent page cap (Task 3's listing pager
stops at 50 pages). A market that hits the safety limit is marked truncated and fails the checks.
Each market is saved as soon as it is done, so the first HTTP 429 (the project's rule is to stop)
loses nothing: run the same command again to continue.

Two ways to read "trade size", both reported:
- per trade: the size of a typical trade (each trade counts once);
- per contract: the trade size a typical contract was traded in (big trades count more).
Each with and without block trades (large trades matched off the order book). Percentiles use
``method="inverted_cdf"``, so every reported size is a size that actually occurred.

Command line (needs your Kalshi key in .env; read-only GETs)::

    cd backend && .venv/bin/python -m app.alignment.trade_sizes --season 2026
    cd backend && .venv/bin/python -m app.alignment.trade_sizes --season 2026 --from-saved   # no requests
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.task4.common import EASTERN, REPO_ROOT

TASK3_DB = REPO_ROOT / "data" / "task3" / "nfl_costs.db"
OUT_DIR = REPO_ROOT / "data" / "alignment"
SERIES = ("KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL")
PAGE = 1000
SAFETY_PAGES = 5000  # 5 million trades in one market: far beyond any NFL market, so hitting it is an error
TICKER_DATE = re.compile(r"^(KXNFL[A-Z]+)-(\d{2})([A-Z]{3})(\d{2})")
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP",
                                       "OCT", "NOV", "DEC"], 1)}
TRADE_COLS = ["trade_id", "ticker", "count", "yes_price", "created_time", "is_block_trade", "taker_outcome_side"]
PERCENTILES = (50, 75, 90)

Getter = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | None]]


class Stopped(Exception):
    """The run stopped early (rate limit or error); progress is saved."""


def market_date(ticker: str) -> tuple[str, date] | None:
    m = TICKER_DATE.match(ticker)
    if not m or m.group(3) not in MONTHS:
        return None
    try:
        return m.group(1), date(2000 + int(m.group(2)), MONTHS[m.group(3)], int(m.group(4)))
    except ValueError:
        return None


def season_of(d: date) -> int:
    return d.year if d.month >= 8 else d.year - 1


def season_markets(season: int, db: Path = TASK3_DB, series: tuple[str, ...] = SERIES,
                   today: date | None = None) -> pd.DataFrame:
    """NFL markets in the Task 3 store for games of ``season`` dated before today (Eastern)."""
    today = today or datetime.now(EASTERN).date()
    if not db.exists():
        return pd.DataFrame(columns=["ticker", "series", "game_date", "status"])
    with sqlite3.connect(db) as conn:
        m = pd.read_sql_query("SELECT ticker, event_ticker, status FROM markets", conn)
    parsed = [market_date(e or t) for t, e in zip(m["ticker"], m["event_ticker"])]
    m["series"] = [p[0] if p else None for p in parsed]
    m["game_date"] = [p[1] if p else None for p in parsed]
    keep = [p is not None and p[0] in series and season_of(p[1]) == season and p[1] < today for p in parsed]
    return m.loc[np.array(keep, dtype=bool), ["ticker", "series", "game_date", "status"]].reset_index(drop=True)


def _count(t: dict[str, Any]) -> float | None:
    raw = t.get("count_fp", t.get("count"))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _rows(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "trade_id": t.get("trade_id"), "ticker": t.get("ticker"), "count": _count(t),
        "yes_price": t.get("yes_price_dollars"), "created_time": t.get("created_time"),
        "is_block_trade": bool(t.get("is_block_trade", False)),
        "taker_outcome_side": t.get("taker_outcome_side", t.get("taker_side")),
    } for t in trades]


async def pull_market(get: Getter, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Every trade of one market from the live and historical endpoints, merged by trade_id."""
    info: dict[str, Any] = {"ticker": ticker, "pages": 0, "truncated": False, "live": 0, "historical": 0}
    rows: list[dict[str, Any]] = []
    for path, key in (("/markets/trades", "live"), ("/historical/trades", "historical")):
        cursor: str | None = None
        for _ in range(SAFETY_PAGES):
            body = await get(path, {"ticker": ticker, "limit": PAGE, **({"cursor": cursor} if cursor else {})})
            info["pages"] += 1
            if body is None:  # e.g. 404 from the historical endpoint for a market not archived yet
                break
            page = [t for t in body.get("trades") or [] if isinstance(t, dict)]
            info[key] += len(page)
            rows += _rows(page)
            cursor = body.get("cursor") or None
            if not cursor:
                break
        else:
            info["truncated"] = True
    df = pd.DataFrame(rows, columns=TRADE_COLS)
    info["duplicates_merged"] = int(df["trade_id"].duplicated().sum())
    df = df.drop_duplicates("trade_id").reset_index(drop=True)
    return df, info


def _progress_path(season: int, out: Path) -> Path:
    return out / "trades" / str(season) / "_progress.json"


async def pull_season(get: Getter, markets: pd.DataFrame, season: int, out: Path = OUT_DIR,
                      max_requests: int | None = None) -> dict[str, Any]:
    """Pull every market not already saved. Saves each market as soon as it is done."""
    folder = out / "trades" / str(season)
    folder.mkdir(parents=True, exist_ok=True)
    prog_path = _progress_path(season, out)
    progress = json.loads(prog_path.read_text()) if prog_path.exists() else {"markets": {}}
    sent = 0

    async def counted(path: str, params: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal sent
        if max_requests is not None and sent >= max_requests:
            raise Stopped(f"Stopped at the request cap ({max_requests}). Run again to continue.")
        sent += 1
        return await get(path, params)

    todo = [t for t in markets["ticker"] if not progress["markets"].get(t, {}).get("done")]
    for i, ticker in enumerate(todo, 1):
        df, info = await pull_market(counted, ticker)
        df.to_csv(folder / f"{ticker}.csv.gz", index=False, compression="gzip")
        progress["markets"][ticker] = {**info, "trades": len(df), "done": not info["truncated"],
                                       "saved_at": datetime.now(UTC).isoformat(timespec="seconds")}
        prog_path.write_text(json.dumps(progress, indent=2))
        if i % 25 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)} markets, {sent} requests", flush=True)
    return {"requests": sent, "markets_pulled": len(todo)}


# --------------------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------------------


def _pct(values: np.ndarray, weights: np.ndarray | None = None) -> dict[str, float | None]:
    if len(values) == 0:
        return {f"p{p}": None for p in PERCENTILES}
    if weights is None:
        return {f"p{p}": float(np.percentile(values, p, method="inverted_cdf")) for p in PERCENTILES}
    order = np.argsort(values, kind="stable")
    v, w = values[order], weights[order]
    cum = np.cumsum(w) / w.sum()
    return {f"p{p}": float(v[np.searchsorted(cum, p / 100)]) for p in PERCENTILES}


def summarize(trades: pd.DataFrame, markets: pd.DataFrame) -> dict[str, Any]:
    t = trades.merge(markets[["ticker", "series"]], on="ticker", how="left")
    out: dict[str, Any] = {}
    for label, sub in (("all NFL markets", t), *((s, t[t["series"] == s]) for s in SERIES)):
        group: dict[str, Any] = {}
        for blocks, d in (("including block trades", sub), ("excluding block trades", sub[~sub["is_block_trade"]])):
            c = d["count"].to_numpy(dtype=float)
            group[blocks] = {"trades": int(len(c)), "contracts": float(c.sum()) if len(c) else 0.0,
                             "per_trade": _pct(c), "per_contract": _pct(c, c)}
        out[label] = group
    return out


def load_saved(season: int, markets: pd.DataFrame, out: Path = OUT_DIR) -> pd.DataFrame:
    folder = out / "trades" / str(season)
    frames = [pd.read_csv(folder / f"{t}.csv.gz") for t in markets["ticker"] if (folder / f"{t}.csv.gz").exists()]
    if not frames:
        return pd.DataFrame(columns=TRADE_COLS)
    df = pd.concat(frames, ignore_index=True)
    df["is_block_trade"] = df["is_block_trade"].astype(str).str.lower().isin(["true", "1"])
    return df


def checks(trades: pd.DataFrame, markets: pd.DataFrame, progress: dict[str, Any], stats: dict[str, Any]) -> list[dict]:
    out = []
    p = progress.get("markets", {})
    missing = [t for t in markets["ticker"] if not p.get(t, {}).get("done")]
    truncated = [t for t, v in p.items() if v.get("truncated")]
    out.append({"id": "all_markets_pulled", "status": "fail" if missing or truncated else "pass",
                "detail": f"{len(markets)} markets; {len(missing)} not finished; {len(truncated)} hit the page "
                          f"safety limit." + (f" Not finished: {missing[:5]}" if missing else "")})
    dup = int(trades["trade_id"].duplicated().sum())
    out.append({"id": "no_duplicate_trades", "status": "fail" if dup else "pass",
                "detail": f"{len(trades):,} trades; {dup} trade ids appear twice after merging live and historical."})
    bad = int((trades["count"].isna() | (trades["count"] <= 0)).sum())
    out.append({"id": "sizes_valid", "status": "fail" if bad else "pass",
                "detail": f"{bad} trades with a missing or non-positive size."})
    foreign = int((~trades["ticker"].isin(markets["ticker"])).sum())
    out.append({"id": "trades_belong_to_markets", "status": "fail" if foreign else "pass",
                "detail": f"{foreign} trades whose ticker is not one of the season's markets."})
    # Independent recompute of the headline percentiles with plain sorted-list arithmetic
    c = sorted(float(x) for x in trades["count"].dropna())
    worst = 0.0
    if c:
        for q in PERCENTILES:
            k = max(0, int(np.ceil(q / 100 * len(c))) - 1)  # inverted CDF: smallest x with share >= q
            got = stats["all NFL markets"]["including block trades"]["per_trade"][f"p{q}"]
            worst = max(worst, abs(c[k] - got))
    out.append({"id": "percentiles_recomputed", "status": "fail" if worst > 1e-9 else ("pass" if c else "skip"),
                "detail": f"Median, p75 and p90 recomputed from the sorted sizes; largest difference {worst:g}."})
    empty = [t for t in markets["ticker"] if p.get(t, {}).get("done") and p[t].get("trades", 0) == 0]
    out.append({"id": "markets_without_trades", "status": "warn" if empty else "pass",
                "detail": f"{len(empty)} markets had no trades at all (normal for far-off strikes)."})
    share = float(trades["is_block_trade"].mean()) if len(trades) else 0.0
    out.append({"id": "block_trades", "status": "pass",
                "detail": f"{share:.2%} of trades are block trades; both versions are reported."})
    return out


def report(season: int, markets: pd.DataFrame, out: Path = OUT_DIR) -> int:
    trades = load_saved(season, markets, out)
    prog_path = _progress_path(season, out)
    progress = json.loads(prog_path.read_text()) if prog_path.exists() else {"markets": {}}
    stats = summarize(trades, markets)
    chk = checks(trades, markets, progress, stats)
    result = {"season": season, "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
              "markets": int(len(markets)), "percentile_method": "inverted_cdf (each value is a real trade size)",
              "stats": stats, "checks": chk}
    out.mkdir(parents=True, exist_ok=True)
    (out / f"trade_sizes_{season}.json").write_text(json.dumps(result, indent=2))
    (out / f"trade_sizes_{season}.md").write_text(_markdown(result))
    print(_markdown(result))
    return 1 if any(c["status"] == "fail" for c in chk) else 0


def _markdown(r: dict[str, Any]) -> str:
    def fmt(x: float | None) -> str:
        return "-" if x is None else f"{x:g}"
    lines = [f"# Kalshi NFL trade sizes, {r['season']} season (contracts)", "",
             f"{r['markets']} markets; percentiles use {r['percentile_method']}.", "",
             "| Markets | Block trades | Trades | Median | p75 | p90 | Median (per contract) | p75 (pc) | p90 (pc) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for label, g in r["stats"].items():
        for blocks, s in g.items():
            a, b = s["per_trade"], s["per_contract"]
            lines.append(f"| {label} | {blocks.split()[0]} | {s['trades']:,} | {fmt(a['p50'])} | {fmt(a['p75'])} | "
                         f"{fmt(a['p90'])} | {fmt(b['p50'])} | {fmt(b['p75'])} | {fmt(b['p90'])} |")
    lines += ["", "## Checks", ""] + [f"- [{c['status']}] {c['id']}: {c['detail']}" for c in r["checks"]]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------


def client_getter(client: Any) -> Getter:
    """GET through the project's Kalshi client (signing, rate limit, request log). 404 = no data."""
    async def get(path: str, params: dict[str, Any]) -> dict[str, Any] | None:
        res = await client.call("GET", path, params=params, module="ALIGN")
        if res.status_code == 404:
            return None
        if not res.ok:
            raise Stopped(f"GET {path} returned HTTP {res.status_code} (request {res.request_id}).")
        body = res.json()
        if not isinstance(body, dict):
            raise Stopped(f"GET {path} returned no JSON (request {res.request_id}).")
        return body
    return get


async def _live(season: int, markets: pd.DataFrame, max_requests: int | None) -> int:
    from app.config import get_settings
    from app.db import Database
    from app.errors import RateLimited, ReconError
    from app.evidence import EvidenceLog
    from app.jobs import JobManager
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
    current = settings.get()
    client = KalshiClient(config, spec, settings, evidence, _NoJobs(),  # type: ignore[arg-type]
                          TokenBucket(current.rate_limit_rps, current.rate_limit_burst))

    started = time.time()
    try:
        done = await pull_season(client_getter(client), markets, season, max_requests=max_requests)
        print(f"Pulled {done['markets_pulled']} markets with {done['requests']} requests in "
              f"{time.time() - started:.0f} s.")
    except (Stopped, RateLimited, ReconError) as exc:
        print(f"Stopped: {exc}. Progress is saved; run the same command again to continue.", file=sys.stderr)
        return 2
    finally:
        await client.aclose()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kalshi NFL trade sizes (median, p75, p90) for one season.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--series", nargs="+", default=list(SERIES), choices=list(SERIES))
    parser.add_argument("--max-requests", type=int, default=None, help="stop after this many requests")
    parser.add_argument("--from-saved", action="store_true", help="only recompute from saved trades")
    args = parser.parse_args(argv)
    markets = season_markets(args.season, series=tuple(args.series))
    if markets.empty:
        print(f"No {args.season} NFL markets in the Task 3 data ({TASK3_DB}). Run Task 3 first.", file=sys.stderr)
        return 2
    print(f"{len(markets)} markets: " + ", ".join(f"{s} {n}" for s, n in markets["series"].value_counts().items()))
    if not args.from_saved:
        code = asyncio.run(_live(args.season, markets, args.max_requests))
        if code:
            return code
    return report(args.season, markets)


if __name__ == "__main__":
    raise SystemExit(main())
