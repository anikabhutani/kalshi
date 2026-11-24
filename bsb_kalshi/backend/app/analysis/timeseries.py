"""Time-series metrics: inter-arrival statistics, gap detection, and ``price_at``.

All inputs are unix seconds. Definitions:
- Slot: a fixed-width interval ``[origin + i*interval, origin + (i+1)*interval)``. A slot is
  *filled* if at least one timestamp falls inside it, otherwise it is *empty* (a gap).
- Inter-arrival delta: the difference between consecutive sorted, distinct timestamps.
  The finest granularity observed is the smallest positive delta.
- ``price_at(t)``: the most recent observation at or before ``t`` that has a price;
  staleness is ``t`` minus that observation's timestamp.
"""

from __future__ import annotations

import bisect
import math
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

MAX_GAP_RUNS = 2000


@dataclass(frozen=True)
class InterArrival:
    """Spacing between consecutive distinct timestamps."""

    count: int
    min_positive_delta_s: float | None
    median_delta_s: float | None
    max_delta_s: float | None


def inter_arrival(timestamps: Sequence[float]) -> InterArrival:
    """Spacing statistics over sorted distinct timestamps."""
    distinct = sorted(set(timestamps))
    deltas = [b - a for a, b in zip(distinct, distinct[1:], strict=False)]
    if not deltas:
        return InterArrival(len(timestamps), None, None, None)
    return InterArrival(
        count=len(timestamps),
        min_positive_delta_s=min(deltas),
        median_delta_s=float(statistics.median(deltas)),
        max_delta_s=max(deltas),
    )


@dataclass(frozen=True)
class GapRun:
    """A run of consecutive empty slots, as a half-open time range."""

    start_s: float
    end_s: float
    slots: int


@dataclass(frozen=True)
class GapStats:
    """Slot coverage of a time series over a window."""

    interval_s: float
    origin_s: float | None
    expected_slots: int
    filled_slots: int
    empty_slots: int
    empty_pct: float | None
    longest_empty_run_slots: int
    longest_empty_run_s: float
    median_empty_run_s: float | None
    runs: list[GapRun]
    runs_truncated: bool

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly representation."""
        return asdict(self)


def compute_gaps(
    timestamps: Sequence[float],
    interval_s: float,
    origin_s: float | None = None,
    end_s: float | None = None,
) -> GapStats:
    """Count filled and empty slots of width ``interval_s`` from ``origin_s`` to ``end_s``.

    ``origin_s`` defaults to the earliest timestamp and ``end_s`` to the latest; the slot
    containing ``end_s`` is included. Timestamps outside the window are ignored.
    """
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")
    ordered = sorted(timestamps)
    if origin_s is None:
        origin_s = ordered[0] if ordered else None
    if end_s is None:
        end_s = ordered[-1] if ordered else None
    if origin_s is None or end_s is None or end_s < origin_s:
        return GapStats(interval_s, origin_s, 0, 0, 0, None, 0, 0.0, None, [], False)

    expected = math.floor((end_s - origin_s) / interval_s) + 1
    filled = {
        math.floor((t - origin_s) / interval_s)
        for t in ordered
        if origin_s <= t <= end_s
    }

    runs: list[GapRun] = []
    run_start: int | None = None
    for index in range(expected + 1):
        is_empty = index < expected and index not in filled
        if is_empty and run_start is None:
            run_start = index
        elif not is_empty and run_start is not None:
            runs.append(
                GapRun(
                    start_s=origin_s + run_start * interval_s,
                    end_s=origin_s + index * interval_s,
                    slots=index - run_start,
                )
            )
            run_start = None

    empty = expected - len(filled)
    longest = max((r.slots for r in runs), default=0)
    run_lengths = [r.slots * interval_s for r in runs]
    return GapStats(
        interval_s=interval_s,
        origin_s=origin_s,
        expected_slots=expected,
        filled_slots=len(filled),
        empty_slots=empty,
        empty_pct=round(100.0 * empty / expected, 3) if expected else None,
        longest_empty_run_slots=longest,
        longest_empty_run_s=longest * interval_s,
        median_empty_run_s=float(statistics.median(run_lengths)) if run_lengths else None,
        runs=sorted(runs, key=lambda r: -r.slots)[:MAX_GAP_RUNS],
        runs_truncated=len(runs) > MAX_GAP_RUNS,
    )


def aligned_origin(first_ts: float, window_start_s: float, interval_s: float) -> float:
    """Earliest slot boundary >= window start that is aligned with an observed timestamp.

    Candle period ends are not always aligned to UTC midnight (e.g. daily candles), so the
    grid is anchored on a real observation and extended backward to the window start.
    """
    steps_back = math.floor((first_ts - window_start_s) / interval_s)
    return first_ts - max(0, steps_back) * interval_s


@dataclass(frozen=True)
class PricePoint:
    """One observation of a price series. ``price`` is None when the source had no price."""

    ts: float
    price: float | None


@dataclass(frozen=True)
class PriceAt:
    """Answer of ``price_at``: last known price at or before the query time."""

    query_ts: float
    price: float | None
    price_ts: float | None
    staleness_s: float | None
    before_first_record: bool
    after_last_record: bool
    records_considered: int


def price_at(points: Sequence[PricePoint], at: float) -> PriceAt:
    """Most recent priced observation with ``ts <= at``, and its staleness in seconds.

    ``points`` must be sorted by ``ts`` ascending. Observations without a price (e.g. a
    candle with no trade) are skipped, so staleness measures time since a real price.
    """
    timestamps = [p.ts for p in points]
    index = bisect.bisect_right(timestamps, at)
    before_first = index == 0
    after_last = bool(points) and at > points[-1].ts
    for candidate in reversed(points[:index]):
        if candidate.price is not None:
            return PriceAt(
                query_ts=at,
                price=candidate.price,
                price_ts=candidate.ts,
                staleness_s=at - candidate.ts,
                before_first_record=before_first,
                after_last_record=after_last,
                records_considered=len(points),
            )
    return PriceAt(at, None, None, None, before_first, after_last, len(points))
