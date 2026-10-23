"""Local store for the NFL cost study: games, events, markets, 1-minute candles, run metadata.

A separate SQLite file (``data/task3/nfl_costs.db``) so millions of candle rows do not bloat the
evidence database. Prices are stored as integers in 1/10,000 of a dollar (``5800`` = $0.58),
which is the precision Kalshi returns. Raw response bodies are kept as gzip files next to it.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

PRICE_SCALE = 10_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_key TEXT PRIMARY KEY,
    game_event_ticker TEXT,
    title TEXT,
    week INTEGER,
    season_type TEXT,
    kickoff_ts INTEGER,
    kickoff_source TEXT,
    milestone_id TEXT,
    updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS events (
    event_ticker TEXT PRIMARY KEY,
    series_ticker TEXT,
    market_type TEXT,
    game_key TEXT,
    title TEXT,
    sub_title TEXT,
    updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS markets (
    id INTEGER PRIMARY KEY,
    ticker TEXT UNIQUE NOT NULL,
    event_ticker TEXT,
    series_ticker TEXT,
    market_type TEXT,
    game_key TEXT,
    title TEXT,
    yes_sub_title TEXT,
    status TEXT,
    result TEXT,
    open_ts INTEGER,
    close_ts INTEGER,
    settle_ts INTEGER,
    listed_from TEXT,
    fetched_through INTEGER,
    candle_count INTEGER NOT NULL DEFAULT 0,
    candle_source TEXT,
    complete INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at INTEGER
);
CREATE INDEX IF NOT EXISTS markets_event ON markets(event_ticker);
CREATE TABLE IF NOT EXISTS candles (
    market_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    bid INTEGER,
    ask INTEGER,
    last INTEGER,
    volume REAL,
    open_interest REAL,
    PRIMARY KEY (market_id, ts)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at INTEGER,
    params_json TEXT,
    result_json TEXT
);
"""

_MARKET_FIELDS = (
    "ticker",
    "event_ticker",
    "series_ticker",
    "market_type",
    "game_key",
    "title",
    "yes_sub_title",
    "status",
    "result",
    "open_ts",
    "close_ts",
    "settle_ts",
    "listed_from",
)


def to_price(value: Any) -> int | None:
    """Dollar string/number -> integer 1/10,000 dollars (None if missing or unparsable)."""
    if value is None or value == "":
        return None
    try:
        return round(float(value) * PRICE_SCALE)
    except (TypeError, ValueError):
        return None


def to_float(value: Any) -> float | None:
    """Fixed-point count string -> float (None if missing or unparsable)."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class NflStore:
    """Thin wrapper over one SQLite file; every call opens a short-lived connection."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.raw_dir = root / "raw"
        self.path = root / "nfl_costs.db"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Connection that commits on success; WAL so the app and the CLI can share the file."""
        conn = sqlite3.connect(self.path, timeout=60)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- metadata -------------------------------------------------------------------------

    def get_meta(self, key: str) -> Any:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row is not None else None

    def set_meta(self, key: str, value: Any) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value, default=str)),
            )

    # ---- inventory ------------------------------------------------------------------------

    def upsert_games(self, games: Iterable[dict[str, Any]]) -> None:
        now = int(time.time())
        with self.connect() as conn:
            conn.executemany(
                """INSERT INTO games(game_key, game_event_ticker, title, week, season_type, kickoff_ts,
                                     kickoff_source, milestone_id, updated_at)
                   VALUES(:game_key, :game_event_ticker, :title, :week, :season_type, :kickoff_ts,
                          :kickoff_source, :milestone_id, :updated_at)
                   ON CONFLICT(game_key) DO UPDATE SET
                     game_event_ticker = excluded.game_event_ticker, title = excluded.title,
                     week = excluded.week, season_type = excluded.season_type,
                     kickoff_ts = excluded.kickoff_ts, kickoff_source = excluded.kickoff_source,
                     milestone_id = excluded.milestone_id, updated_at = excluded.updated_at""",
                [{**g, "updated_at": now} for g in games],
            )

    def upsert_events(self, events: Iterable[dict[str, Any]]) -> None:
        now = int(time.time())
        with self.connect() as conn:
            conn.executemany(
                """INSERT INTO events(event_ticker, series_ticker, market_type, game_key, title, sub_title, updated_at)
                   VALUES(:event_ticker, :series_ticker, :market_type, :game_key, :title, :sub_title, :updated_at)
                   ON CONFLICT(event_ticker) DO UPDATE SET
                     series_ticker = excluded.series_ticker, market_type = excluded.market_type,
                     game_key = excluded.game_key, title = excluded.title, sub_title = excluded.sub_title,
                     updated_at = excluded.updated_at""",
                [{**e, "updated_at": now} for e in events],
            )

    def upsert_markets(self, markets: Iterable[dict[str, Any]]) -> tuple[int, int]:
        """Insert new markets and refresh listing fields of known ones; fetch state is kept.

        A market that was complete but has a later close or settlement time than before (for
        example a postponed game) is reopened so the missing minutes get fetched.
        Returns (new, updated).
        """
        now = int(time.time())
        new = updated = 0
        with self.connect() as conn:
            for m in markets:
                row = conn.execute(
                    "SELECT id, close_ts, settle_ts FROM markets WHERE ticker = ?", (m["ticker"],)
                ).fetchone()
                values = {f: m.get(f) for f in _MARKET_FIELDS}
                if row is None:
                    cols = ", ".join(_MARKET_FIELDS)
                    marks = ", ".join(f":{f}" for f in _MARKET_FIELDS)
                    conn.execute(
                        f"INSERT INTO markets({cols}, updated_at) VALUES({marks}, :updated_at)",
                        {**values, "updated_at": now},
                    )
                    new += 1
                    continue
                moved = (values["close_ts"] or 0) > (row["close_ts"] or 0) or (
                    values["settle_ts"] or 0
                ) > (row["settle_ts"] or 0)
                sets = ", ".join(f"{f} = :{f}" for f in _MARKET_FIELDS if f != "ticker")
                conn.execute(
                    f"UPDATE markets SET {sets}, updated_at = :updated_at"
                    + (", complete = 0" if moved else "")
                    + " WHERE ticker = :ticker",
                    {**values, "updated_at": now},
                )
                updated += 1
        return new, updated

    def markets(self, where: str = "1 = 1", params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(f"SELECT * FROM markets WHERE {where} ORDER BY id", params).fetchall()
        return [dict(r) for r in rows]

    def games(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM games ORDER BY kickoff_ts, game_key")]

    def events(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM events ORDER BY event_ticker")]

    # ---- candles --------------------------------------------------------------------------

    def save_candles(self, market_id: int, rows: list[tuple[Any, ...]], through_ts: int, source: str) -> int:
        """Store parsed candles ``(ts, bid, ask, last, volume, oi)`` and advance the fetch mark."""
        with self.connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO candles(market_id, ts, bid, ask, last, volume, open_interest) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                [(market_id, *r) for r in rows],
            )
            count = conn.execute("SELECT COUNT(*) FROM candles WHERE market_id = ?", (market_id,)).fetchone()[0]
            conn.execute(
                """UPDATE markets SET fetched_through = MAX(COALESCE(fetched_through, 0), ?),
                                      candle_count = ?, candle_source = ?, last_error = NULL
                   WHERE id = ?""",
                (through_ts, count, source, market_id),
            )
        return int(count)

    def set_error(self, market_ids: Iterable[int], message: str) -> None:
        with self.connect() as conn:
            conn.executemany("UPDATE markets SET last_error = ? WHERE id = ?", [(message, i) for i in market_ids])

    def mark_complete(self, market_ids: Iterable[int]) -> None:
        with self.connect() as conn:
            conn.executemany("UPDATE markets SET complete = 1 WHERE id = ?", [(i,) for i in market_ids])

    def quote_at(self, conn: sqlite3.Connection, market_id: int, at_ts: int) -> sqlite3.Row | None:
        """Latest candle ending at or before ``at_ts`` (its close bid/ask is the standing quote)."""
        return conn.execute(
            "SELECT ts, bid, ask, last FROM candles WHERE market_id = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
            (market_id, at_ts),
        ).fetchone()

    def candle_stats(self) -> dict[int, dict[str, int]]:
        """Per-market counts used by the quality check (one pass over the candle table)."""
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT market_id,
                          COUNT(*) AS candles,
                          SUM(bid > 0 AND ask < :top AND bid > ask) AS crossed,
                          SUM(bid > 0 AND ask < :top AND bid = ask) AS locked,
                          SUM(bid > 0 AND ask < :top AND ask - bid >= 300) AS wide,
                          SUM(bid IS NULL OR ask IS NULL OR bid <= 0 OR ask >= :top) AS one_sided,
                          MIN(ts) AS first_ts,
                          MAX(ts) AS last_ts
                   FROM candles GROUP BY market_id""",
                {"top": PRICE_SCALE},
            ).fetchall()
        return {int(r["market_id"]): {k: int(r[k] or 0) for k in r.keys() if k != "market_id"} for r in rows}

    def totals(self) -> dict[str, int]:
        with self.connect() as conn:
            return {
                "games": conn.execute("SELECT COUNT(*) FROM games").fetchone()[0],
                "events": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                "markets": conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0],
                "markets_complete": conn.execute("SELECT COUNT(*) FROM markets WHERE complete = 1").fetchone()[0],
                "markets_settled": conn.execute(
                    "SELECT COUNT(*) FROM markets WHERE status IN ('settled', 'finalized')"
                ).fetchone()[0],
                "markets_settled_complete": conn.execute(
                    "SELECT COUNT(*) FROM markets WHERE status IN ('settled', 'finalized') AND complete = 1"
                ).fetchone()[0],
                "candles": conn.execute("SELECT COALESCE(SUM(candle_count), 0) FROM markets").fetchone()[0],
            }

    # ---- analyses -------------------------------------------------------------------------

    def save_analysis(self, params: dict[str, Any], result: dict[str, Any]) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO analyses(created_at, params_json, result_json) VALUES(?, ?, ?)",
                (int(time.time()), json.dumps(params), json.dumps(result, default=str)),
            )
            conn.execute("DELETE FROM analyses WHERE id NOT IN (SELECT id FROM analyses ORDER BY id DESC LIMIT 20)")
            return int(cur.lastrowid or 0)

    def latest_analysis(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM analyses ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "params": json.loads(row["params_json"]),
            "result": json.loads(row["result_json"]),
        }
