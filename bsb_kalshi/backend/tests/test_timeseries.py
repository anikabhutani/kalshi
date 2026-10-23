"""Gap computation, inter-arrival statistics, and price_at staleness logic."""

from __future__ import annotations

import pytest

from app.analysis.timeseries import (
    PricePoint,
    aligned_origin,
    compute_gaps,
    inter_arrival,
    price_at,
)


class TestComputeGaps:
    def test_no_gaps_when_every_slot_filled(self) -> None:
        stats = compute_gaps([0, 60, 120, 180], 60)
        assert stats.expected_slots == 4
        assert stats.filled_slots == 4
        assert stats.empty_slots == 0
        assert stats.empty_pct == 0.0
        assert stats.runs == []

    def test_counts_and_percentages(self) -> None:
        stats = compute_gaps([0, 60, 300], 60)
        assert stats.expected_slots == 6
        assert stats.filled_slots == 3
        assert stats.empty_slots == 3
        assert stats.empty_pct == 50.0
        assert stats.longest_empty_run_slots == 3
        assert stats.longest_empty_run_s == 180

    def test_runs_are_half_open_ranges_sorted_longest_first(self) -> None:
        stats = compute_gaps([0, 120, 480], 60)
        assert [(r.start_s, r.end_s, r.slots) for r in stats.runs] == [(180, 480, 5), (60, 120, 1)]
        assert stats.median_empty_run_s == 180.0

    def test_explicit_window_counts_leading_and_trailing_gaps(self) -> None:
        stats = compute_gaps([120], 60, origin_s=0, end_s=300)
        assert stats.expected_slots == 6
        assert stats.filled_slots == 1
        assert [(r.start_s, r.end_s) for r in stats.runs] == [(180, 360), (0, 120)]

    def test_multiple_points_in_one_slot_count_once(self) -> None:
        stats = compute_gaps([0, 1, 59, 60], 60)
        assert stats.filled_slots == 2
        assert stats.empty_slots == 0

    def test_points_outside_window_ignored(self) -> None:
        stats = compute_gaps([-500, 0, 60, 9999], 60, origin_s=0, end_s=60)
        assert stats.expected_slots == 2
        assert stats.filled_slots == 2

    def test_empty_series_without_window(self) -> None:
        stats = compute_gaps([], 60)
        assert stats.expected_slots == 0
        assert stats.empty_pct is None

    def test_empty_series_with_window_is_all_gap(self) -> None:
        stats = compute_gaps([], 60, origin_s=0, end_s=119)
        assert stats.expected_slots == 2
        assert stats.empty_slots == 2
        assert stats.empty_pct == 100.0

    def test_rejects_non_positive_interval(self) -> None:
        with pytest.raises(ValueError):
            compute_gaps([0], 0)


def test_aligned_origin_anchors_on_observation() -> None:
    assert aligned_origin(first_ts=14_400 + 86_400, window_start_s=0, interval_s=86_400) == 14_400
    assert aligned_origin(first_ts=100, window_start_s=100, interval_s=60) == 100
    assert aligned_origin(first_ts=100, window_start_s=500, interval_s=60) == 100


def test_inter_arrival_uses_distinct_sorted_timestamps() -> None:
    stats = inter_arrival([10, 0, 10, 40, 100])
    assert stats.count == 5
    assert stats.min_positive_delta_s == 10
    assert stats.median_delta_s == 30.0
    assert stats.max_delta_s == 60
    assert inter_arrival([5]).min_positive_delta_s is None


class TestPriceAt:
    POINTS = [
        PricePoint(100, 0.40),
        PricePoint(160, None),
        PricePoint(220, 0.55),
        PricePoint(280, None),
    ]

    def test_exact_match_has_zero_staleness(self) -> None:
        answer = price_at(self.POINTS, 220)
        assert answer.price == 0.55
        assert answer.price_ts == 220
        assert answer.staleness_s == 0

    def test_between_points_uses_last_known(self) -> None:
        answer = price_at(self.POINTS, 250)
        assert answer.price == 0.55
        assert answer.staleness_s == 30

    def test_skips_observations_without_price(self) -> None:
        answer = price_at(self.POINTS, 200)
        assert answer.price == 0.40
        assert answer.price_ts == 100
        assert answer.staleness_s == 100

    def test_before_first_record_has_no_price(self) -> None:
        answer = price_at(self.POINTS, 50)
        assert answer.price is None
        assert answer.staleness_s is None
        assert answer.before_first_record

    def test_after_last_record_is_flagged_and_staleness_grows(self) -> None:
        answer = price_at(self.POINTS, 1000)
        assert answer.price == 0.55
        assert answer.staleness_s == 780
        assert answer.after_last_record

    def test_no_priced_point_at_or_before(self) -> None:
        answer = price_at([PricePoint(10, None), PricePoint(20, 0.5)], 15)
        assert answer.price is None
        assert not answer.before_first_record

    def test_empty_series(self) -> None:
        answer = price_at([], 10)
        assert answer.price is None
        assert answer.before_first_record
        assert not answer.after_last_record
