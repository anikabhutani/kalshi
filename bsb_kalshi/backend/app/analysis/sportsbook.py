"""M7 helpers: sportsbook CSV parsing, two-way no-vig grouping, dummy data, and the overlay.

CSV contract (the template has exactly these columns):
- ``timestamp_utc``: ISO 8601. A value without an offset is read as UTC (and counted).
- ``book``, ``event``, ``market``: free text. ``market`` names the outcome the odds are for.
- ``odds_american`` and/or ``odds_decimal``: at least one per row. If both are present they
  must agree within 0.01 in decimal terms; the American value is used.

Two-way grouping: rows sharing (timestamp_utc, book, event) form a group. A group with exactly
two rows on different ``market`` values gets no-vig probabilities; any other group size gets
none, and the reason is stated on the row.

Overlay: for each sportsbook row of the chosen outcome, ``price_at`` on the chosen Kalshi
series gives the latest Kalshi price at or before the row's timestamp. The gap is
``Kalshi probability - sportsbook probability`` in percentage points, computed only when the
Kalshi price is at most ``max_staleness_s`` old.
"""

from __future__ import annotations

import csv
import io
import math
import random
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.analysis.limits import describe
from app.analysis.odds import (
    american_to_decimal,
    american_to_probability,
    decimal_to_probability,
    kalshi_price_to_probability,
    no_vig_two_way,
    overround,
    probability_to_american,
)
from app.analysis.timeseries import PricePoint, price_at
from app.analysis.timestamps import iso, parse_timestamp

REQUIRED_COLUMNS = ("timestamp_utc", "book", "event", "market")
ODDS_COLUMNS = ("odds_american", "odds_decimal")
TEMPLATE_COLUMNS = (*REQUIRED_COLUMNS, *ODDS_COLUMNS)
MAX_ROWS = 20_000
MAX_CSV_BYTES = 2_000_000
MAX_ERRORS_REPORTED = 200
DECIMAL_AGREEMENT = 0.01
DUMMY_LABEL = "DUMMY DATA"
DUMMY_BOOKS = (("DUMMY BOOK A", 0.045), ("DUMMY BOOK B", 0.06))
DUMMY_OUTCOMES = ("YES side (dummy)", "NO side (dummy)")
DUMMY_MAX_POINTS = 1000
_OFFSET_RE = re.compile(r"(Z|[+-]\d{2}:?\d{2})$", re.IGNORECASE)

TEMPLATE_CSV = (
    ",".join(TEMPLATE_COLUMNS)
    + "\n"
    + "\n".join(
        [
            "2026-01-01T00:00:00Z,DUMMY BOOK A,DUMMY DATA example event,DUMMY outcome A,-120,",
            "2026-01-01T00:00:00Z,DUMMY BOOK A,DUMMY DATA example event,DUMMY outcome B,+100,",
            "2026-01-01T00:05:00Z,DUMMY BOOK A,DUMMY DATA example event,DUMMY outcome A,,1.80",
            "2026-01-01T00:05:00Z,DUMMY BOOK A,DUMMY DATA example event,DUMMY outcome B,,2.05",
        ]
    )
    + "\n"
)


class CsvError(ValueError):
    """The file as a whole cannot be used (missing columns, too large, no valid rows)."""


@dataclass
class ParsedCsv:
    """Valid rows (with probabilities) and per-line problems."""

    rows: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    columns: list[str]
    naive_timestamps: int = 0
    error_count: int = 0
    notes: list[str] = field(default_factory=list)


def _number(column: str, text: str) -> float | None:
    if not text.strip():
        return None
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"{column} {text!r} is not a number") from None


def _odds(american_text: str, decimal_text: str) -> tuple[float | None, float, str]:
    """(american, decimal, format used) for one row, validated."""
    american = _number("odds_american", american_text)
    decimal = _number("odds_decimal", decimal_text)
    if any(v is not None and not math.isfinite(v) for v in (american, decimal)):
        raise ValueError("odds must be finite numbers")
    if american is None and decimal is None:
        raise ValueError("no odds_american or odds_decimal value")
    if american is not None:
        american_decimal = american_to_decimal(american)
        if decimal is not None and abs(decimal - american_decimal) > DECIMAL_AGREEMENT:
            raise ValueError(
                f"odds_american {american:g} (= decimal {american_decimal:.3f}) disagrees with odds_decimal {decimal:g}"
            )
        return american, american_decimal, "american"
    assert decimal is not None
    decimal_to_probability(decimal)
    return None, decimal, "decimal"


def parse_csv(text: str) -> ParsedCsv:
    """Parse and validate an uploaded sportsbook CSV, then add two-way no-vig values."""
    if len(text.encode("utf-8")) > MAX_CSV_BYTES:
        raise CsvError(f"The file is larger than {MAX_CSV_BYTES // 1_000_000} MB.")
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    columns = [c.strip().lower() for c in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    if missing:
        raise CsvError(f"Missing column(s): {', '.join(missing)}. Expected: {', '.join(TEMPLATE_COLUMNS)}.")
    if not any(c in columns for c in ODDS_COLUMNS):
        raise CsvError("Add an odds_american or odds_decimal column.")

    parsed = ParsedCsv(rows=[], errors=[], columns=columns)
    for index, raw in enumerate(reader):
        line = index + 2
        if index >= MAX_ROWS:
            raise CsvError(f"More than {MAX_ROWS} rows; split the file.")
        record = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k is not None}
        try:
            ts_text = record.get("timestamp_utc", "")
            moment = parse_timestamp(ts_text)
            if moment is None:
                raise ValueError(f"timestamp_utc {ts_text!r} is not ISO 8601")
            if not _OFFSET_RE.search(ts_text):
                parsed.naive_timestamps += 1
            for name in ("book", "event", "market"):
                if not record.get(name):
                    raise ValueError(f"{name} is empty")
            american, decimal, used = _odds(record.get("odds_american", ""), record.get("odds_decimal", ""))
            implied = american_to_probability(american) if american is not None else decimal_to_probability(decimal)
        except ValueError as exc:
            parsed.error_count += 1
            if len(parsed.errors) < MAX_ERRORS_REPORTED:
                parsed.errors.append({"line": line, "message": str(exc)})
            continue
        parsed.rows.append(
            {
                "line": line,
                "ts": moment.timestamp(),
                "timestamp_utc": moment.isoformat(),
                "book": record["book"],
                "event": record["event"],
                "market": record["market"],
                "odds_american": american,
                "odds_decimal": round(decimal, 6),
                "odds_format": used,
                "implied_prob": implied,
            }
        )
    if not parsed.rows:
        if not parsed.errors:
            raise CsvError("The file has a header but no data rows.")
        raise CsvError("No valid rows. " + "; ".join(f"line {e['line']}: {e['message']}" for e in parsed.errors[:5]))
    add_no_vig(parsed.rows)
    if parsed.naive_timestamps:
        parsed.notes.append(f"{parsed.naive_timestamps} timestamp(s) had no UTC offset and were read as UTC.")
    return parsed


def add_no_vig(rows: list[dict[str, Any]]) -> None:
    """Set ``no_vig_prob``, ``overround`` and ``group_note`` on every row (in place)."""
    groups: dict[tuple[float, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["ts"], row["book"], row["event"]), []).append(row)
    for members in groups.values():
        markets = {m["market"] for m in members}
        if len(members) == 2 and len(markets) == 2:
            a, b = members
            na, nb = no_vig_two_way(a["implied_prob"], b["implied_prob"])
            over = overround(a["implied_prob"], b["implied_prob"])
            a.update(no_vig_prob=na, overround=over, group_note=None)
            b.update(no_vig_prob=nb, overround=over, group_note=None)
        else:
            note = (
                f"{len(members)} row(s) for this timestamp/book/event; no-vig needs exactly two outcomes"
                if len(markets) == len(members)
                else "duplicate outcome rows for this timestamp/book/event"
            )
            for m in members:
                m.update(no_vig_prob=None, overround=None, group_note=note)


def _round_american(value: float) -> int:
    rounded = int(round(value / 5.0) * 5)
    if -100 < rounded < 100:
        return 100 if value > 0 else -100
    return rounded


def dummy_csv(start_ts: float, end_ts: float, label: str, seed: int) -> str:
    """Generated two-book, two-outcome odds over a window, labelled DUMMY DATA everywhere.

    The probabilities are a seeded random walk; they are not derived from any Kalshi data.
    """
    span = max(60.0, end_ts - start_ts)
    step = max(300.0, span / DUMMY_MAX_POINTS)
    rng = random.Random(seed)
    p = 0.5
    lines = [",".join(TEMPLATE_COLUMNS)]
    t = start_ts
    event = f"{DUMMY_LABEL} ({label})"
    while t <= end_ts:
        p = min(0.92, max(0.08, p + rng.gauss(0.0, 0.02)))
        stamp = iso(t)
        for book, vig in DUMMY_BOOKS:
            for outcome, prob in zip(DUMMY_OUTCOMES, (p, 1.0 - p), strict=True):
                american = _round_american(probability_to_american(min(0.97, prob + vig / 2)))
                lines.append(f"{stamp},{book},{event},{outcome},{american:+d},")
        t += step
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class KalshiSeries:
    """One Kalshi price series from a stored Timestamp Lab run."""

    id: str
    label: str
    note: str
    points: list[PricePoint]


def _kalshi_prob(price: float | None) -> float | None:
    if price is None:
        return None
    try:
        return kalshi_price_to_probability(price)
    except ValueError:
        return None


def overlay(
    rows: Sequence[dict[str, Any]],
    selection: str,
    series: KalshiSeries,
    max_staleness_s: float,
) -> dict[str, Any]:
    """Match each row of the chosen outcome to the Kalshi price at or before its timestamp."""
    matched: list[dict[str, Any]] = []
    for row in sorted((r for r in rows if r["market"] == selection), key=lambda r: (r["ts"], r["book"])):
        answer = price_at(series.points, row["ts"])
        kalshi_prob = _kalshi_prob(answer.price)
        fresh = answer.staleness_s is not None and answer.staleness_s <= max_staleness_s
        novig = row.get("no_vig_prob")
        matched.append(
            {
                "timestamp_utc": row["timestamp_utc"],
                "ts": row["ts"],
                "book": row["book"],
                "event": row["event"],
                "market": row["market"],
                "implied_prob": row["implied_prob"],
                "no_vig_prob": novig,
                "kalshi_price": answer.price,
                "kalshi_price_ts": iso(answer.price_ts),
                "kalshi_prob": kalshi_prob,
                "staleness_s": answer.staleness_s,
                "within_staleness": fresh,
                "gap_no_vig_pp": (kalshi_prob - novig) * 100 if fresh and kalshi_prob is not None and novig is not None else None,
                "gap_implied_pp": (kalshi_prob - row["implied_prob"]) * 100 if fresh and kalshi_prob is not None else None,
            }
        )
    books: dict[str, list[dict[str, Any]]] = {}
    for m in matched:
        books.setdefault(m["book"], []).append(m)
    summary = []
    for book, items in sorted(books.items()):
        gaps = [i["gap_no_vig_pp"] for i in items if i["gap_no_vig_pp"] is not None]
        raw_gaps = [i["gap_implied_pp"] for i in items if i["gap_implied_pp"] is not None]
        summary.append(
            {
                "book": book,
                "rows": len(items),
                "with_kalshi_price": sum(1 for i in items if i["kalshi_price"] is not None),
                "within_staleness": sum(1 for i in items if i["within_staleness"]),
                "gap_no_vig_pp": describe(gaps),
                "mean_abs_gap_no_vig_pp": sum(abs(g) for g in gaps) / len(gaps) if gaps else None,
                "gap_implied_pp": describe(raw_gaps),
            }
        )
    return {"rows": matched, "summary": summary}
