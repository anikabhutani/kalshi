"""Backfill 1-minute candlesticks for every NFL game, spread and total market this season.

Three steps, each safe to repeat:

1. ``refresh_inventory``: the historical cutoff, series fee settings, NFL game milestones (kickoff
   time and week), and every event with its markets in the game, spread and total series whose
   kickoff is on or after the start date. Archived events (no nested markets) are listed from
   ``/historical/markets``.
2. ``cutoff_check``: requests archived and live sample markets from the live, batch and
   historical endpoints so the page can show how the cutoff treats older settled markets.
3. ``backfill_candles``: 1-minute candles from market open to settlement using the batch
   endpoint ``GET /markets/candlesticks``. Each market remembers how far it has been fetched,
   so a later run only asks for new minutes, and settled markets that are fully fetched are
   never requested again. Markets listed only in the archive use
   ``GET /historical/markets/{ticker}/candlesticks``.

Every response body is saved gzip-compressed under ``data/task3/raw/<kind>/<UTC date>/``.

Command line (daily update; picks up new games, skips finished ones)::

    cd backend && .venv/bin/python -m app.task3.backfill
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import gzip
import os
import sys
import time
from collections import Counter, deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from app.analysis.timestamps import iso, to_epoch
from app.errors import ReconError, RequestBudgetExceeded
from app.kalshi_client import CallResult, KalshiClient
from app.task3.store import NflStore, to_float, to_price

MODULE = "T3"
SERIES: dict[str, str] = {
    "KXNFLGAME": "Game winner",
    "KXNFLSPREAD": "Spread",
    "KXNFLTOTAL": "Total points",
}
DEFAULT_START = date(2026, 9, 14)
EASTERN = ZoneInfo("America/New_York")

BATCH_CANDLES = "/markets/candlesticks"
# Spec: up to 100 tickers and 10,000 candlesticks per request. Observed: the server counts
# requested minutes x markets (not candles returned) and rejects anything above 10,000.
BATCH_MAX_TICKERS = 100
BATCH_MAX_SLOTS = 10_000
# Observed 400 on /historical/markets/{ticker}/candlesticks: "max candlesticks: 5000".
HIST_MAX_SLOTS = 5_000
SETTLED_STATUSES = frozenset({"settled", "finalized"})
# Fallback when a game has no milestone: Kalshi sets expected_expiration_time 3 h after kickoff.
EXPECTED_EXPIRATION_AFTER_KICKOFF_S = 3 * 3600
MAX_PAGES = 50


class BudgetExhausted(Exception):
    """The run's request cap was reached; work done so far is kept."""


class BackfillBusy(Exception):
    """Another backfill (app job or command line) holds the lock."""


@dataclass
class Hooks:
    """Where progress and log lines go (the job stream in the app, stdout on the command line)."""

    log: Callable[[str, str], None] = lambda message, level="info": print(f"[{level}] {message}", flush=True)
    progress: Callable[[int, int, str], None] = lambda done, total, message: None
    check_cancelled: Callable[[], None] = lambda: None


class Fetcher:
    """GETs through the shared Kalshi client (rate limit, evidence log) and saves raw bodies."""

    def __init__(self, client: KalshiClient, store: NflStore, job_id: str | None = None, cap: int | None = None) -> None:
        self.client = client
        self.store = store
        self.job_id = job_id
        self.cap = cap
        self.sent = 0

    async def get(self, path: str, params: dict[str, Any] | None = None, kind: str = "listing") -> CallResult:
        if self.cap is not None and self.sent >= self.cap:
            raise BudgetExhausted()
        try:
            res = await self.client.call("GET", path, params=params, job_id=self.job_id, module=MODULE)
        except RequestBudgetExceeded:
            raise BudgetExhausted() from None
        self.sent += 1
        if res.ok and res.body:
            folder = self.store.raw_dir / kind / res.sent_at.strftime("%Y-%m-%d")
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{res.request_id}.json.gz").write_bytes(gzip.compress(res.body))
        return res

    async def paged(self, path: str, params: dict[str, Any], key: str, kind: str = "listing") -> list[dict[str, Any]]:
        """Follow ``cursor`` until it is empty (or MAX_PAGES)."""
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            res = await self.get(path, {**params, "cursor": cursor}, kind)
            body = res.json() if res.ok else None
            if not isinstance(body, dict):
                raise RuntimeError(f"GET {path} returned HTTP {res.status_code} (request {res.request_id}).")
            page = body.get(key)
            if isinstance(page, list):
                items.extend(i for i in page if isinstance(i, dict))
            cursor = body.get("cursor") or None
            if cursor is None:
                break
        return items


@contextmanager
def run_lock(store: NflStore) -> Iterator[None]:
    """One backfill at a time across the app and the command line."""
    handle = open(store.root / "backfill.lock", "w")  # noqa: SIM115 - held for the whole run
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BackfillBusy("Another backfill is already running (app job or command line).") from None
        handle.write(str(os.getpid()))
        handle.flush()
        yield
    finally:
        handle.close()


def _epoch(value: Any) -> int | None:
    ts = to_epoch(value)
    return int(ts) if ts is not None else None


def game_key(event_ticker: str) -> str:
    """``KXNFLSPREAD-26OCT19WASSF`` -> ``26OCT19WASSF`` (shared by a game's game, spread and total events)."""
    return event_ticker.split("-", 1)[1] if "-" in event_ticker else event_ticker


def kickoff_eastern_date(kickoff_ts: int) -> date:
    return datetime.fromtimestamp(kickoff_ts, UTC).astimezone(EASTERN).date()


def _market_row(m: dict[str, Any], series: str, key: str, listed_from: str) -> dict[str, Any]:
    return {
        "ticker": m.get("ticker"),
        "event_ticker": m.get("event_ticker"),
        "series_ticker": series,
        "market_type": SERIES.get(series, series),
        "game_key": key,
        "title": m.get("title"),
        "yes_sub_title": m.get("yes_sub_title"),
        "status": m.get("status"),
        "result": m.get("result"),
        "open_ts": _epoch(m.get("open_time")),
        "close_ts": _epoch(m.get("close_time")),
        "settle_ts": _epoch(m.get("settlement_ts")),
        "listed_from": listed_from,
    }


# ---- step 1: inventory ----------------------------------------------------------------------


async def refresh_inventory(
    fetcher: Fetcher, store: NflStore, start: date, series: list[str], hooks: Hooks
) -> dict[str, Any]:
    """List every NFL event and market (settled ones included) with kickoff on/after ``start``."""
    start_ts = int(datetime(start.year, start.month, start.day, tzinfo=EASTERN).timestamp())

    hooks.progress(0, 4, "Historical cutoff")
    res = await fetcher.get("/historical/cutoff")
    cutoff = res.json() if res.ok and isinstance(res.json(), dict) else {}
    store.set_meta("cutoff", {"fetched_at": int(time.time()), "values": cutoff, "request_id": res.request_id})

    hooks.progress(1, 4, "Series fee settings")
    fees: dict[str, Any] = {"series": {}, "series_changes": [], "event_overrides": []}
    for s in series:
        r = await fetcher.get(f"/series/{s}")
        body = r.json() if r.ok else None
        info = body.get("series") if isinstance(body, dict) else None
        if isinstance(info, dict):
            fees["series"][s] = {"fee_type": info.get("fee_type"), "fee_multiplier": info.get("fee_multiplier"), "title": info.get("title")}
    changes = await fetcher.paged("/series/fee_changes", {"show_historical": True}, "series_fee_change_arr")
    fees["series_changes"] = [c for c in changes if c.get("series_ticker") in series]
    overrides = await fetcher.paged("/events/fee_changes", {"limit": 200}, "event_fee_changes")
    fees["event_overrides"] = [c for c in overrides if c.get("series_ticker") in series]
    store.set_meta("fees", fees)

    hooks.progress(2, 4, "Game kickoff times (milestones)")
    since = (datetime(start.year, start.month, start.day, tzinfo=UTC) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    milestones = await fetcher.paged(
        "/milestones", {"limit": 500, "type": "football_game", "minimum_start_date": since}, "milestones"
    )
    by_key: dict[str, dict[str, Any]] = {}
    for m in milestones:
        details = m.get("details") if isinstance(m.get("details"), dict) else {}
        main = details.get("main_game_event_ticker")
        if details.get("league") == "NFL" and isinstance(main, str):
            by_key[game_key(main)] = m

    hooks.progress(3, 4, "Events and markets")
    games: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    markets: list[dict[str, Any]] = []
    skipped_before_start = 0
    archived_events = 0
    for s in series:
        listed = await fetcher.paged(
            "/events",
            {"series_ticker": s, "with_nested_markets": True, "min_close_ts": start_ts - 2 * 86_400, "limit": 200},
            "events",
        )
        for ev in listed:
            ticker = str(ev.get("event_ticker") or "")
            if not ticker:
                continue
            key = game_key(ticker)
            nested = [m for m in ev.get("markets") or [] if isinstance(m, dict)]
            listed_from = "live"
            if not nested:
                nested = await fetcher.paged("/historical/markets", {"event_ticker": ticker, "limit": 1000}, "markets")
                listed_from = "historical"
                archived_events += 1 if nested else 0
            game = games.get(key) or _game_record(key, by_key.get(key), ev, nested)
            if game["kickoff_ts"] is None or kickoff_eastern_date(game["kickoff_ts"]) < start:
                skipped_before_start += 1
                continue
            games[key] = game
            events.append(
                {
                    "event_ticker": ticker,
                    "series_ticker": s,
                    "market_type": SERIES.get(s, s),
                    "game_key": key,
                    "title": ev.get("title"),
                    "sub_title": ev.get("sub_title"),
                }
            )
            markets.extend(_market_row(m, s, key, listed_from) for m in nested if m.get("ticker"))

    store.upsert_games(games.values())
    store.upsert_events(events)
    new, updated = store.upsert_markets(markets)
    hooks.progress(4, 4, "Listing done")
    by_type = Counter(m["market_type"] for m in markets)
    summary = {
        "listed_at": int(time.time()),
        "start_date": start.isoformat(),
        "series": series,
        "games": len(games),
        "games_without_milestone": sum(1 for g in games.values() if g["kickoff_source"] != "milestone"),
        "events": len(events),
        "markets": len(markets),
        "markets_by_type": dict(by_type),
        "markets_settled": sum(1 for m in markets if m["status"] in SETTLED_STATUSES),
        "new_markets": new,
        "known_markets": updated,
        "events_listed_from_archive": archived_events,
        "events_before_start_skipped": skipped_before_start,
    }
    store.set_meta("inventory", summary)
    hooks.log(
        f"Listed {len(games)} games, {len(events)} events, {len(markets)} markets "
        f"({new} new, {summary['markets_settled']} settled).",
        "info",
    )
    return summary


def _game_record(key: str, milestone: dict[str, Any] | None, event: dict[str, Any], markets: list[dict[str, Any]]) -> dict[str, Any]:
    details = milestone.get("details") if milestone and isinstance(milestone.get("details"), dict) else {}
    season = details.get("season") if isinstance(details.get("season"), dict) else {}
    kickoff = _epoch(milestone.get("start_date")) if milestone else None
    source = "milestone"
    if kickoff is None:
        expected = [t for t in (_epoch(m.get("expected_expiration_time")) for m in markets) if t is not None]
        kickoff = min(expected) - EXPECTED_EXPIRATION_AFTER_KICKOFF_S if expected else None
        source = "estimated from expected_expiration_time" if kickoff is not None else "unknown"
    return {
        "game_key": key,
        "game_event_ticker": details.get("main_game_event_ticker") or f"KXNFLGAME-{key}",
        "title": (milestone or {}).get("title") or event.get("title"),
        "week": season.get("week"),
        "season_type": season.get("type"),
        "kickoff_ts": kickoff,
        "kickoff_source": source,
        "milestone_id": (milestone or {}).get("id"),
    }


# ---- step 2: cutoff check -------------------------------------------------------------------


async def cutoff_check(fetcher: Fetcher, store: NflStore, hooks: Hooks) -> dict[str, Any]:
    """How the historical cutoff treats older settled NFL markets, with request evidence."""
    cutoff = (store.get_meta("cutoff") or {}).get("values") or {}
    boundary = _epoch(cutoff.get("market_settled_ts"))
    ours = store.markets()
    sides = Counter(
        "not settled yet"
        if m["settle_ts"] is None
        else ("settled before the cutoff" if boundary is not None and m["settle_ts"] < boundary else "settled after the cutoff")
        for m in ours
    )

    samples: list[tuple[str, str]] = []
    archived = await fetcher.paged("/historical/markets", {"series_ticker": "KXNFLGAME", "limit": 1000}, "markets")
    archived = [m for m in archived if m.get("ticker")]
    if archived:
        archived.sort(key=lambda m: _epoch(m.get("settlement_ts")) or _epoch(m.get("close_time")) or 0)
        samples.append(("Newest archived NFL game market", str(archived[-1]["ticker"])))
        samples.append(("Oldest archived NFL game market on the first page", str(archived[0]["ticker"])))
    settled_ours = sorted((m for m in ours if m["settle_ts"] is not None), key=lambda m: m["settle_ts"])
    if settled_ours:
        samples.append(("Earliest-settled market in this season's set", settled_ours[0]["ticker"]))

    rows: list[dict[str, Any]] = []
    for index, (label, ticker) in enumerate(samples):
        hooks.check_cancelled()
        hooks.progress(index, len(samples), f"Cutoff check: {ticker}")
        live = await fetcher.get(f"/markets/{ticker}")
        hist = await fetcher.get(f"/historical/markets/{ticker}")
        live_m = (live.json() or {}).get("market") if live.ok else None
        hist_m = (hist.json() or {}).get("market") if hist.ok else None
        market = live_m if isinstance(live_m, dict) else hist_m if isinstance(hist_m, dict) else {}
        close = _epoch(market.get("close_time"))
        settled = _epoch(market.get("settlement_ts"))
        row: dict[str, Any] = {
            "label": label,
            "ticker": ticker,
            "status": market.get("status"),
            "settlement_ts": settled,
            "side": None if settled is None or boundary is None else ("before cutoff" if settled < boundary else "after cutoff"),
            "live_market_status": live.status_code,
            "historical_market_status": hist.status_code,
            "live_market_request_id": live.request_id,
            "historical_market_request_id": hist.request_id,
        }
        if close is not None:
            window = {"start_ts": close - 3600, "end_ts": close, "period_interval": 1}
            batch = await fetcher.get(BATCH_CANDLES, {**window, "market_tickers": ticker}, "candles")
            hc = await fetcher.get(f"/historical/markets/{ticker}/candlesticks", window, "candles")
            batch_body = batch.json() if batch.ok else None
            batch_markets = batch_body.get("markets") if isinstance(batch_body, dict) else None
            row.update(
                {
                    "window_start": window["start_ts"],
                    "window_end": window["end_ts"],
                    "batch_status": batch.status_code,
                    "batch_candles": sum(len(x.get("candlesticks") or []) for x in batch_markets or []),
                    "batch_request_id": batch.request_id,
                    "historical_candles_status": hc.status_code,
                    "historical_candles": len((hc.json() or {}).get("candlesticks") or []) if hc.ok else 0,
                    "historical_candles_request_id": hc.request_id,
                }
            )
        rows.append(row)
        hooks.log(
            f"Cutoff check {ticker}: live market HTTP {row['live_market_status']}, archive HTTP "
            f"{row['historical_market_status']}, batch candles {row.get('batch_candles', '–')}, "
            f"archive candles {row.get('historical_candles', '–')}.",
            "info",
        )

    result = {
        "checked_at": int(time.time()),
        "cutoff": cutoff,
        "market_settled_ts": boundary,
        "our_markets_by_side": dict(sides),
        "our_markets_listed_from": dict(Counter(m["listed_from"] for m in ours)),
        "samples": rows,
    }
    store.set_meta("cutoff_check", result)
    return result


# ---- step 3: candles ------------------------------------------------------------------------


@dataclass
class Chunk:
    """One candle request: up to 100 markets sharing one time window."""

    route: str
    market_ids: list[int]
    tickers: list[str]
    start_ts: int
    end_ts: int
    attempts: int = field(default=0)

    @property
    def slots(self) -> int:
        return len(self.tickers) * ((self.end_ts - self.start_ts) // 60 + 1)


def _floor_minute(ts: int) -> int:
    return ts - ts % 60


def _ceil_minute(ts: int) -> int:
    return ts if ts % 60 == 0 else ts + 60 - ts % 60


def market_window(m: dict[str, Any], now: int) -> tuple[int, int] | None:
    """Minutes still to fetch for a market: from open (or just after the last fetch) to
    settlement, or to the last finished minute if it is still trading."""
    if m["open_ts"] is None:
        return None
    settled = m["status"] in SETTLED_STATUSES
    end = max(m["close_ts"] or 0, m["settle_ts"] or 0) if settled else (m["close_ts"] or now)
    end = min(_floor_minute(end), _floor_minute(now) - 60)
    start = _ceil_minute(m["open_ts"] if m["fetched_through"] is None else m["fetched_through"] + 60)
    return (start, end) if end >= start else None


def _split(route: str, ids: list[int], tickers: list[str], start: int, end: int) -> list[Chunk]:
    cap = BATCH_MAX_SLOTS if route == "batch" else HIST_MAX_SLOTS
    span_min = max(1, cap // len(tickers) - 1)
    chunks: list[Chunk] = []
    s = start
    while s <= end:
        e = min(end, s + span_min * 60)
        chunks.append(Chunk(route, ids, tickers, s, e))
        s = e + 60
    return chunks


def plan_chunks(markets: list[dict[str, Any]], now: int) -> list[Chunk]:
    """Group markets of the same event and window into batch requests within the slot limit."""
    groups: dict[tuple[str, str, int, int], list[dict[str, Any]]] = {}
    for m in markets:
        if m["complete"]:
            continue
        window = market_window(m, now)
        if window is None:
            continue
        route = "historical" if m["listed_from"] == "historical" else "batch"
        key = (route, m["event_ticker"] if route == "batch" else m["ticker"], *window)
        groups.setdefault(key, []).append(m)
    chunks: list[Chunk] = []
    for (route, _, start, end), members in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][2])):
        for i in range(0, len(members), BATCH_MAX_TICKERS if route == "batch" else 1):
            part = members[i : i + (BATCH_MAX_TICKERS if route == "batch" else 1)]
            chunks.extend(_split(route, [m["id"] for m in part], [m["ticker"] for m in part], start, end))
    return chunks


def parse_candle(c: dict[str, Any]) -> tuple[Any, ...] | None:
    """Live (``*_dollars``/``*_fp``) or historical (plain names) candle -> stored row."""
    ts = c.get("end_period_ts")
    if not isinstance(ts, int):
        return None
    bid = c.get("yes_bid") or {}
    ask = c.get("yes_ask") or {}
    price = c.get("price") or {}
    return (
        ts,
        to_price(bid.get("close_dollars", bid.get("close"))),
        to_price(ask.get("close_dollars", ask.get("close"))),
        to_price(price.get("close_dollars", price.get("close"))),
        to_float(c.get("volume_fp", c.get("volume"))),
        to_float(c.get("open_interest_fp", c.get("open_interest"))),
    )


def finalize_complete(store: NflStore, now: int) -> int:
    """Mark settled markets whose window is fully fetched; they are never requested again."""
    done = [
        m["id"]
        for m in store.markets("complete = 0 AND status IN ('settled', 'finalized') AND fetched_through IS NOT NULL")
        if market_window(m, now) is None
    ]
    store.mark_complete(done)
    return len(done)


async def backfill_candles(fetcher: Fetcher, store: NflStore, hooks: Hooks, now: int | None = None) -> dict[str, Any]:
    """Fetch every missing minute for incomplete markets; returns a run summary."""
    now = int(time.time()) if now is None else now
    finalize_complete(store, now)
    queue = deque(plan_chunks(store.markets("complete = 0"), now))
    total = len(queue)
    failed: set[int] = set()
    candles_added = requests = errors = splits = 0
    stop_reason: str | None = None
    done = 0
    while queue:
        hooks.check_cancelled()
        chunk = queue.popleft()
        ids = [i for i in chunk.market_ids if i not in failed]
        if not ids:
            done += 1
            continue
        keep = [n for n, i in enumerate(chunk.market_ids) if i in ids]
        chunk = Chunk(chunk.route, ids, [chunk.tickers[n] for n in keep], chunk.start_ts, chunk.end_ts, chunk.attempts)
        hooks.progress(done, total, f"{chunk.tickers[0].rsplit('-', 1)[0]}: {iso(chunk.start_ts)} → {iso(chunk.end_ts)}")
        window = {"start_ts": chunk.start_ts, "end_ts": chunk.end_ts, "period_interval": 1}
        try:
            if chunk.route == "batch":
                res = await fetcher.get(BATCH_CANDLES, {**window, "market_tickers": ",".join(chunk.tickers)}, "candles")
            else:
                res = await fetcher.get(f"/historical/markets/{chunk.tickers[0]}/candlesticks", window, "candles")
        except BudgetExhausted:
            stop_reason = "request cap reached; run again to continue where it stopped"
            break
        requests += 1
        body = res.json()
        if res.status_code == 400 and "max candlesticks" in str(body) and chunk.end_ts > chunk.start_ts and chunk.attempts < 3:
            mid = _floor_minute(chunk.start_ts + (chunk.end_ts - chunk.start_ts) // 2)
            queue.appendleft(Chunk(chunk.route, ids, chunk.tickers, mid + 60, chunk.end_ts, chunk.attempts + 1))
            queue.appendleft(Chunk(chunk.route, ids, chunk.tickers, chunk.start_ts, mid, chunk.attempts + 1))
            total += 1
            splits += 1
            continue
        done += 1
        if not res.ok or not isinstance(body, dict):
            errors += 1
            failed.update(ids)
            store.set_error(ids, f"HTTP {res.status_code} (request {res.request_id})")
            hooks.log(f"HTTP {res.status_code} for {len(ids)} market(s) starting {chunk.tickers[0]}; they are retried next run.", "warn")
            continue
        if chunk.route == "batch":
            by_ticker = {str(x.get("market_ticker")): x.get("candlesticks") or [] for x in body.get("markets") or [] if isinstance(x, dict)}
        else:
            by_ticker = {chunk.tickers[0]: body.get("candlesticks") or []}
        for market_id, ticker in zip(ids, chunk.tickers, strict=True):
            rows = [r for r in (parse_candle(c) for c in by_ticker.get(ticker, []) if isinstance(c, dict)) if r is not None]
            store.save_candles(market_id, rows, chunk.end_ts, chunk.route)
            candles_added += len(rows)
        if done % 50 == 0:
            hooks.log(f"{done}/{total} requests, {candles_added:,} candles stored so far.", "info")
    completed = finalize_complete(store, now)
    hooks.progress(total, total, "Candles done")
    summary = {
        "ran_at": now,
        "planned_requests": total,
        "requests": requests,
        "candles_added": candles_added,
        "markets_failed": len(failed),
        "http_errors": errors,
        "chunk_splits": splits,
        "markets_completed": completed,
        "stop_reason": stop_reason,
    }
    hooks.log(
        f"Candles: {requests} requests, {candles_added:,} candles added, {completed} markets finished"
        + (f", stopped: {stop_reason}" if stop_reason else "")
        + ".",
        "warn" if stop_reason or errors else "info",
    )
    return summary


def estimate_candle_requests(store: NflStore, now: int | None = None) -> int:
    """Number of candle requests the next backfill will send (no requests are made)."""
    return len(plan_chunks(store.markets("complete = 0"), int(time.time()) if now is None else now))


# ---- command line ---------------------------------------------------------------------------


class _NoJobs:
    """Stand-in for the app's JobManager: command-line requests belong to no job."""

    def context(self, job_id: str) -> None:
        return None


async def run_daily(args: argparse.Namespace) -> int:
    from app.config import get_settings
    from app.db import Database
    from app.evidence import EvidenceLog
    from app.jobs import JobManager
    from app.kalshi_client import TokenBucket
    from app.settings_store import SettingsStore
    from app.spec_loader import OpenApiSpec
    from app.task3.costs import AnalysisParams, run_analysis

    config = get_settings()
    db = Database(config.db_path)
    spec = OpenApiSpec.load(config.specs_dir / "openapi.yaml")
    settings = SettingsStore(db, config, spec)
    secrets = [config.kalshi_key_id.get_secret_value()] if config.kalshi_key_id else []
    evidence = EvidenceLog(db, config.raw_dir, secrets)
    current = settings.get()
    bucket = TokenBucket(current.rate_limit_rps, current.rate_limit_burst)
    client = KalshiClient(config, spec, settings, evidence, cast(JobManager, _NoJobs()), bucket)
    store = NflStore(config.data_dir / "task3")
    hooks = Hooks()
    fetcher = Fetcher(client, store, cap=args.max_requests)
    started = int(time.time())
    try:
        with run_lock(store):
            inventory = None
            if not args.skip_list:
                inventory = await refresh_inventory(fetcher, store, args.start_date, args.series, hooks)
                await cutoff_check(fetcher, store, hooks)
            candles = await backfill_candles(fetcher, store, hooks)
            params = AnalysisParams(**(store.get_meta("analysis_params") or {}))
            run_analysis(store, params)
            store.set_meta(
                "last_run",
                {"source": "command line", "started_at": started, "finished_at": int(time.time()), "requests": fetcher.sent, "inventory": inventory, "candles": candles},
            )
            hooks.log(f"Done: {fetcher.sent} requests in {int(time.time()) - started} s. Results updated.", "info")
    except BackfillBusy as exc:
        print(exc, file=sys.stderr)
        return 2
    except ReconError as exc:
        print(f"Stopped: {exc.user_message} Progress so far is saved; run again to continue.", file=sys.stderr)
        return 1
    finally:
        await client.aclose()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill 1-minute candles for every NFL game, spread and total market.")
    parser.add_argument("--start-date", type=date.fromisoformat, default=DEFAULT_START, help="first kickoff date, US Eastern (default %(default)s)")
    parser.add_argument("--series", nargs="+", default=list(SERIES), choices=list(SERIES))
    parser.add_argument("--max-requests", type=int, default=None, help="stop after this many requests (default: no cap)")
    parser.add_argument("--skip-list", action="store_true", help="do not re-list games; only fetch missing candles")
    return asyncio.run(run_daily(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
