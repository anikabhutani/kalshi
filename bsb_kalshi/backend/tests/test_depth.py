"""Oldest-record bisection and depth targets resolved from the real spec."""

from __future__ import annotations

import pytest

from app.analysis.depth import (
    DEFAULT_TARGETS,
    Probe,
    ProbeBudgetExhausted,
    ProbeFn,
    bisect_oldest,
    bisect_request_estimate,
    resolve_targets,
)
from app.spec_loader import OpenApiSpec

DAY = 86_400
LOWER = 1_500_000_000
UPPER = 1_710_000_000


def dataset_probe(timestamps: list[int], calls: list[int | None]) -> ProbeFn:
    """A probe over fake data: ``bound`` means "records strictly before bound", newest first."""

    async def probe(bound: int | None) -> Probe:
        calls.append(bound)
        before = [t for t in timestamps if bound is None or t < bound]
        newest = [max(before)] if before else []
        return Probe(bound, 200, len(newest), [float(t) for t in newest], len(calls))

    return probe


async def test_bisect_brackets_oldest_record_within_resolution() -> None:
    oldest = 1_600_000_123
    data = [oldest, oldest + 5 * DAY, 1_700_000_000]
    calls: list[int | None] = []
    result = await bisect_oldest(dataset_probe(data, calls), LOWER, UPPER, DAY)

    assert result.stop_reason is None
    assert result.bracket_lo is not None and result.bracket_hi is not None
    assert result.bracket_lo <= oldest < result.bracket_hi
    assert result.bracket_hi - result.bracket_lo <= DAY
    assert result.oldest_ts == oldest
    assert result.newest_ts == 1_700_000_000
    assert len(calls) <= bisect_request_estimate(LOWER, UPPER, DAY)
    assert calls[:2] == [None, LOWER]


async def test_records_older_than_search_window_are_flagged() -> None:
    result = await bisect_oldest(dataset_probe([LOWER - DAY, UPPER - DAY], []), LOWER, UPPER, DAY)
    assert result.beyond_lower_bound
    assert result.bracket_hi == LOWER
    assert result.bracket_lo is None


async def test_empty_endpoint_reports_no_records_after_one_request() -> None:
    calls: list[int | None] = []
    result = await bisect_oldest(dataset_probe([], calls), LOWER, UPPER, DAY)
    assert result.no_records
    assert calls == [None]
    assert result.bracket_lo is None and result.bracket_hi is None


async def test_request_cap_stops_search_and_keeps_partial_bracket() -> None:
    calls: list[int | None] = []
    inner = dataset_probe([1_600_000_000], calls)

    async def capped(bound: int | None) -> Probe:
        if len(calls) >= 4:
            raise ProbeBudgetExhausted()
        return await inner(bound)

    result = await bisect_oldest(capped, LOWER, UPPER, DAY)
    assert result.stop_reason == "request cap reached"
    assert len(result.probes) == 4
    assert result.bracket_lo is not None and result.bracket_hi is not None
    assert result.bracket_lo <= 1_600_000_000 < result.bracket_hi
    assert result.bracket_hi - result.bracket_lo > DAY


async def test_http_error_stops_without_guessing() -> None:
    async def failing(bound: int | None) -> Probe:
        return Probe(bound, 500, 0, [], 1, "server error")

    result = await bisect_oldest(failing, LOWER, UPPER, DAY)
    assert result.stop_reason == "HTTP 500 without a bound"
    assert result.bracket_lo is None and result.bracket_hi is None
    assert not result.no_records


def test_request_estimate_is_logarithmic() -> None:
    assert bisect_request_estimate(LOWER, LOWER + DAY, DAY) == 2
    assert bisect_request_estimate(LOWER, LOWER + 1024 * DAY, DAY) == 12


async def test_invalid_resolution_rejected() -> None:
    with pytest.raises(ValueError):
        await bisect_oldest(dataset_probe([], []), LOWER, UPPER, 0)


def test_default_targets_resolve_against_real_spec(spec: OpenApiSpec) -> None:
    targets = {t.definition.id: t for t in resolve_targets(spec)}
    for target_id in DEFAULT_TARGETS:
        target = targets[target_id]
        assert target.available, target.reason
        assert target.reason is None
    assert targets["trades_live"].bound_description is not None
    assert targets["historical_markets"].definition.mode == "walk"
    assert targets["historical_markets"].page_limit is not None
