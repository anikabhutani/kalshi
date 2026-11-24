"""M4 helpers: depth targets resolved from the spec, and oldest-record bisection.

Bisection rule: for a list endpoint with an upper time-bound parameter (for example
``max_ts``, "Filter items before this Unix timestamp"), "at least one record exists before T"
can only switch from false to true as T grows. A binary search over T with ``limit=1``
therefore brackets the oldest retrievable record to within the chosen resolution using
O(log n) requests. No ordering of results is assumed: any record returned for bound T proves
data exists before T, and that record's own timestamp tightens the upper bracket.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from app.spec_loader import OpenApiSpec

DepthMode = Literal["bisect", "walk"]


class ProbeBudgetExhausted(Exception):
    """Raised by a probe function when the job's request cap leaves no room for another call."""


@dataclass(frozen=True)
class DepthTargetDef:
    """One endpoint the depth tester can measure, and how (all names checked against the spec)."""

    id: str
    label: str
    path: str
    list_key: str
    ts_field: str
    mode: DepthMode
    bound_param: str | None = None
    fixed: tuple[tuple[str, str], ...] = ()
    series_param: str | None = None
    ticker_param: str | None = None


TARGET_DEFS: tuple[DepthTargetDef, ...] = (
    DepthTargetDef(
        "trades_live", "Trades (live endpoint)", "/markets/trades", "trades", "created_time",
        "bisect", bound_param="max_ts", ticker_param="ticker",
    ),
    DepthTargetDef(
        "trades_historical", "Trades (historical endpoint)", "/historical/trades", "trades",
        "created_time", "bisect", bound_param="max_ts", ticker_param="ticker",
    ),
    DepthTargetDef(
        "markets_settled", "Settled markets (live endpoint)", "/markets", "markets",
        "settlement_ts", "bisect", bound_param="max_settled_ts", fixed=(("status", "settled"),),
        series_param="series_ticker",
    ),
    DepthTargetDef(
        "markets_closed", "Markets by close time (live endpoint)", "/markets", "markets",
        "close_time", "bisect", bound_param="max_close_ts", series_param="series_ticker",
    ),
    DepthTargetDef(
        "historical_markets", "Archived markets (historical endpoint)", "/historical/markets",
        "markets", "settlement_ts", "walk", series_param="series_ticker",
    ),
)
DEFAULT_TARGETS = ("trades_live", "trades_historical", "markets_settled", "historical_markets")


@dataclass(frozen=True)
class ResolvedTarget:
    """A target definition plus what the spec says about it (or why it is unavailable)."""

    definition: DepthTargetDef
    available: bool
    reason: str | None
    bound_description: str | None
    ts_format: str | None
    page_limit: int | None

    def to_dict(self) -> dict[str, Any]:
        """JSON shape for the UI."""
        d = self.definition
        return {
            "id": d.id,
            "label": d.label,
            "path": d.path,
            "mode": d.mode,
            "list_key": d.list_key,
            "ts_field": d.ts_field,
            "ts_format": self.ts_format,
            "bound_param": d.bound_param,
            "bound_description": self.bound_description,
            "fixed_params": dict(d.fixed),
            "series_param": d.series_param,
            "ticker_param": d.ticker_param,
            "page_limit": self.page_limit,
            "available": self.available,
            "reason": self.reason,
        }


def resolve_targets(spec: OpenApiSpec) -> list[ResolvedTarget]:
    """Check every target definition against the spec; unavailable ones carry a TODO reason."""
    resolved: list[ResolvedTarget] = []
    for d in TARGET_DEFS:
        endpoint = spec.find("GET", d.path)
        problems: list[str] = []
        bound_description: str | None = None
        page_limit: int | None = None
        ts_format: str | None = None
        if endpoint is None:
            problems.append(f"GET {d.path} is not in the spec")
        else:
            names = {p.name for p in endpoint.params}
            for name in [d.bound_param, d.series_param, d.ticker_param, *dict(d.fixed)]:
                if name is not None and name not in names:
                    problems.append(f"parameter '{name}' is not declared")
            for name, value in d.fixed:
                param = endpoint.param(name)
                if param is not None and param.enum and value not in param.enum:
                    problems.append(f"'{value}' is not in the enum of '{name}'")
            if d.bound_param is not None and (bound := endpoint.param(d.bound_param)) is not None:
                bound_description = bound.description
            limit = endpoint.param("limit")
            if limit is not None and limit.maximum is not None:
                page_limit = int(limit.maximum)
            props = spec.response_object_properties(d.path, d.list_key)
            if d.ts_field not in props:
                problems.append(f"'{d.list_key}[].{d.ts_field}' is not in the response schema")
            else:
                ts_format = props[d.ts_field].format
        reason = f"TODO(spec): {'; '.join(problems)}." if problems else None
        resolved.append(
            ResolvedTarget(d, not problems, reason, bound_description, ts_format, page_limit)
        )
    return resolved


@dataclass
class Probe:
    """One bounded ``limit=1`` request and what it returned."""

    bound: int | None
    status: int | None
    records: int
    record_ts: list[float]
    request_id: int | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """HTTP 2xx."""
        return self.status is not None and 200 <= self.status < 300

    @property
    def found(self) -> bool:
        """At least one record came back."""
        return self.records > 0

    def to_dict(self) -> dict[str, Any]:
        """JSON shape for the stored result."""
        return {
            "bound": self.bound,
            "status": self.status,
            "records": self.records,
            "record_ts": min(self.record_ts) if self.record_ts else None,
            "request_id": self.request_id,
            "error": self.error,
        }


ProbeFn = Callable[[int | None], Awaitable[Probe]]


@dataclass
class BisectResult:
    """Outcome of a bisection: every probe, the final bracket, and why it stopped."""

    lower_bound: int
    upper_bound: int
    resolution_s: int
    probes: list[Probe] = field(default_factory=list)
    bracket_lo: int | None = None
    bracket_hi: int | None = None
    stop_reason: str | None = None
    beyond_lower_bound: bool = False
    no_records: bool = False

    @property
    def oldest_ts(self) -> float | None:
        """Oldest record timestamp observed in any probe."""
        values = [t for p in self.probes for t in p.record_ts]
        return min(values) if values else None

    @property
    def newest_ts(self) -> float | None:
        """Newest record timestamp observed in any probe."""
        values = [t for p in self.probes for t in p.record_ts]
        return max(values) if values else None

    def to_dict(self) -> dict[str, Any]:
        """JSON shape for the stored result."""
        return {
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "resolution_s": self.resolution_s,
            "probes": [p.to_dict() for p in self.probes],
            "bracket_lo": self.bracket_lo,
            "bracket_hi": self.bracket_hi,
            "stop_reason": self.stop_reason,
            "beyond_lower_bound": self.beyond_lower_bound,
            "no_records": self.no_records,
            "oldest_ts": self.oldest_ts,
            "newest_ts": self.newest_ts,
        }


def bisect_request_estimate(lower: int, upper: int, resolution_s: int) -> int:
    """Upper bound on requests: one unbounded probe, one at the lower bound, then halvings."""
    span = max(1, upper - lower)
    return 2 + max(0, math.ceil(math.log2(max(1.0, span / resolution_s))))


def _tightened(bound: int, probe: Probe) -> int:
    """A found probe proves records exist before ``oldest returned + 1`` as well as ``bound``."""
    if not probe.record_ts:
        return bound
    return min(bound, int(math.floor(min(probe.record_ts))) + 1)


async def bisect_oldest(probe: ProbeFn, lower: int, upper: int, resolution_s: int) -> BisectResult:
    """Bracket the oldest record between ``lower`` and ``upper`` (unix seconds)."""
    if resolution_s <= 0:
        raise ValueError("resolution_s must be positive")
    out = BisectResult(lower_bound=lower, upper_bound=upper, resolution_s=resolution_s)

    async def run(bound: int | None) -> Probe:
        result = await probe(bound)
        out.probes.append(result)
        return result

    def failed(p: Probe) -> bool:
        if p.ok:
            return False
        where = "without a bound" if p.bound is None else f"at bound {p.bound}"
        out.stop_reason = f"HTTP {p.status if p.status is not None else 'error'} {where}"
        return True

    lo, hi = lower, upper
    try:
        first = await run(None)
        if failed(first):
            return out
        if not first.found:
            out.no_records = True
            return out
        hi = max(lo + 1, _tightened(upper, first))
        floor = await run(lower)
        if failed(floor):
            return out
        if floor.found:
            out.beyond_lower_bound = True
            out.bracket_hi = lower
            return out
        while hi - lo > resolution_s:
            mid = lo + (hi - lo) // 2
            p = await run(mid)
            if failed(p):
                break
            if p.found:
                hi = max(lo + 1, _tightened(mid, p))
            else:
                lo = mid
    except ProbeBudgetExhausted:
        out.stop_reason = "request cap reached"
    floor_probed = len(out.probes) >= 2 and out.probes[1].ok
    if floor_probed and not out.beyond_lower_bound:
        out.bracket_lo, out.bracket_hi = lo, hi
    return out
