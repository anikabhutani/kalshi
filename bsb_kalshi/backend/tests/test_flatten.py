"""Field dictionary flattening."""

from __future__ import annotations

from app.analysis.flatten import flatten_samples


def _by_path(samples: list[object]) -> dict[str, dict[str, object]]:
    return {row.path: row.to_dict() for row in flatten_samples(samples)}


def test_flattens_nested_objects_and_arrays() -> None:
    rows = _by_path(
        [{"ticker": "A", "price": {"close_dollars": "0.50"}, "levels": [["0.1", "5"]], "tags": ["x"]}]
    )
    assert set(rows) == {"ticker", "price", "price.close_dollars", "levels", "levels[]", "levels[][]", "tags", "tags[]"}
    assert rows["price"]["types"] == ["object"]
    assert rows["price.close_dollars"]["example"] == "0.50"
    assert rows["levels[][]"]["types"] == ["string"]


def test_aggregates_presence_nulls_and_types_across_samples() -> None:
    rows = _by_path(
        [
            {"ticker": "A", "settlement_ts": None, "floor": 1},
            {"ticker": "B", "settlement_ts": "2026-10-01T05:09:36.660851Z", "floor": 1.5},
            {"ticker": "C"},
        ]
    )
    settlement = rows["settlement_ts"]
    assert settlement["present_in"] == 2
    assert settlement["samples"] == 3
    assert settlement["null_count"] == 1
    assert settlement["nullable_observed"] is True
    assert settlement["types"] == ["null", "string"]
    assert settlement["example"] == "2026-10-01T05:09:36.660851Z"
    assert settlement["timestamp_like"] is True
    assert settlement["name_looks_like_timestamp"] is True
    assert rows["floor"]["types"] == ["integer", "number"]
    assert rows["ticker"]["distinct_values"] == ["A", "B", "C"]


def test_detects_epoch_integers_and_keeps_prices_unflagged() -> None:
    rows = _by_path([{"end_period_ts": 1_790_560_560, "yes_bid_dollars": "0.0300"}])
    assert rows["end_period_ts"]["timestamp_format"] == "unix seconds (integer)"
    assert rows["yes_bid_dollars"]["timestamp_like"] is False


def test_distinct_values_are_capped() -> None:
    rows = _by_path([{"status": f"s{i}"} for i in range(15)])
    assert len(rows["status"]["distinct_values"]) == 10
    assert rows["status"]["distinct_values_truncated"] is True
