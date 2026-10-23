"""Timestamp Lab normalization, request planning, and per-source metrics."""

from __future__ import annotations

from app.modules.m3_timestamps import (
    HIST_TRADES,
    LIVE_TRADES,
    RunParams,
    candle_chunks,
    candle_metrics,
    estimate_requests,
    normalize_candle,
    normalize_trade,
    trade_metrics,
    trade_plan,
)
from app.spec_loader import OpenApiSpec

LIVE_CANDLE = {
    "end_period_ts": 1_790_560_800,
    "price": {"close_dollars": "0.9500", "open_dollars": "0.9400"},
    "yes_bid": {"close_dollars": "0.0700"},
    "yes_ask": {"close_dollars": "0.9500"},
    "volume_fp": "1.05",
    "open_interest_fp": "1.05",
}
HIST_CANDLE = {
    "end_period_ts": 1_790_560_800,
    "price": {"close": "0.5000", "open": None},
    "yes_bid": {"close": "0.4900"},
    "yes_ask": {"close": "0.5100"},
    "volume": "10.00",
    "open_interest": "3.00",
}


def test_normalizes_live_and_historical_candles() -> None:
    live = normalize_candle(LIVE_CANDLE)
    hist = normalize_candle(HIST_CANDLE)
    assert live is not None and hist is not None
    assert (live["close"], live["bid_close"], live["volume"]) == (0.95, 0.07, 1.05)
    assert (hist["close"], hist["open"], hist["ask_close"], hist["open_interest"]) == (0.5, None, 0.51, 3.0)


def test_candle_without_trade_has_null_close() -> None:
    row = normalize_candle({"end_period_ts": 60, "price": {}, "yes_bid": {}, "yes_ask": {}})
    assert row is not None and row["close"] is None
    assert normalize_candle({"price": {}}) is None


def test_normalizes_trade_timestamp() -> None:
    row = normalize_trade(
        {"created_time": "2026-10-01T05:05:45.5Z", "yes_price_dollars": "0.0100", "count_fp": "654.63"},
        "live",
    )
    assert row is not None
    assert row["ts"] == 1_790_831_145.5
    assert (row["price"], row["count"], row["source"]) == (0.01, 654.63, "live")
    assert normalize_trade({"created_time": None}, "live") is None


def test_candle_chunks_cover_window_without_overlap() -> None:
    chunks = candle_chunks(0, 3 * 86_400 + 10, interval_min=1)
    assert chunks[0] == (0, 86_400)
    assert chunks[-1] == (3 * 86_400, 3 * 86_400 + 10)
    assert len(chunks) == 4
    assert candle_chunks(0, 86_400 * 30, interval_min=60) == [(0, 86_400 * 30)]


def test_trade_plan_splits_at_cutoff() -> None:
    assert trade_plan(0, 100, None) == [(LIVE_TRADES, 0, 100)]
    assert trade_plan(0, 100, 50) == [(HIST_TRADES, 0, 50), (LIVE_TRADES, 50, 100)]
    assert trade_plan(60, 100, 50) == [(LIVE_TRADES, 60, 100)]
    assert trade_plan(0, 40, 50) == [(HIST_TRADES, 0, 40)]


def test_estimate_counts_every_spec_interval(spec: OpenApiSpec) -> None:
    params = RunParams(market_ticker="M", series_ticker="S", start_ts=0, end_ts=2 * 86_400, trade_page_cap=3)
    estimate = estimate_requests(spec, params)
    assert estimate["candles"] == 2 + 1 + 1
    assert estimate["total"] == estimate["fixed"] + estimate["candles"] + estimate["trades_max"]
    assert estimate["cap"] > estimate["total"]


def test_candle_metrics_separate_missing_periods_from_no_trade_periods() -> None:
    rows = [
        {"ts": 60, "close": 0.5},
        {"ts": 120, "close": None},
        {"ts": 240, "close": 0.6},
    ]
    metrics = candle_metrics(rows, 60, start_ts=0, end_ts=240, raw_example=1_790_560_800)
    # Spec: candles "ending on or after start_ts" are included, so period ends 0..240 are expected.
    assert metrics["missing_periods"]["expected_slots"] == 5
    assert metrics["missing_periods"]["empty_slots"] == 2
    assert metrics["periods_without_trade"]["empty_slots"] == 3
    assert metrics["candles_without_trade"] == 1
    assert metrics["finest_granularity_s"] == 60
    assert metrics["timestamp_format"] == "unix seconds (integer)"


def test_trade_metrics_shrink_window_when_truncated() -> None:
    rows = [{"ts": 1000.0}, {"ts": 1030.0}, {"ts": 1200.0}]
    full = trade_metrics(rows, 60, 0, 1200, truncated=False, raw_times=["2026-10-01T05:05:45Z"])
    cut = trade_metrics(rows, 60, 0, 1200, truncated=True, raw_times=[])
    assert full["empty_buckets"]["expected_slots"] == 21
    assert cut["empty_buckets"]["expected_slots"] == 4
    assert cut["empty_buckets"]["filled_slots"] == 2
    assert full["timestamp_formats"] == ["ISO 8601 (UTC 'Z')"]
    assert full["finest_granularity_s"] == 30
