"""rate_limits.md parsing, ramp metrics, and pagination helpers."""

from __future__ import annotations

from app.analysis.limits import (
    end_signal,
    identity,
    list_key,
    parse_rate_doc,
    percentile,
    ramp_rates,
    rate_headers,
    step_metrics,
)
from app.config import ROOT_DIR


def test_parses_tier_table_and_default_cost_from_real_doc() -> None:
    doc = parse_rate_doc((ROOT_DIR / "specs" / "rate_limits.md").read_text(encoding="utf-8"))
    tiers = {t["tier"]: t for t in doc["tiers"]}
    assert tiers["Basic"] == {"tier": "Basic", "read_budget": 200.0, "write_budget": 100.0}
    assert tiers["Premier"]["read_budget"] == 1200.0
    assert tiers["Prestige"] == {"tier": "Prestige", "read_budget": 12000.0, "write_budget": 9600.0}
    assert len(doc["tiers"]) == 7
    assert doc["default_cost_tokens"] == 10
    assert any(s["heading"] == "Tiers and budgets" for s in doc["sections"])


def test_parse_handles_missing_table_and_cost() -> None:
    doc = parse_rate_doc("# Title\n\n## Only prose\nNothing numeric here.\n")
    assert doc["tiers"] == []
    assert doc["default_cost_tokens"] is None
    assert doc["sections"] == [{"heading": "Only prose", "text": "Nothing numeric here."}]


def test_rate_headers_keeps_only_rate_like_names() -> None:
    headers = {"Content-Type": "application/json", "X-RateLimit-Remaining": "9", "Retry-After": "2", "Date": "x"}
    assert rate_headers(headers) == {"x-ratelimit-remaining": "9", "retry-after": "2"}


def test_percentile_nearest_rank() -> None:
    assert percentile([], 95) is None
    assert percentile([5.0], 95) == 5.0
    assert percentile([float(i) for i in range(1, 21)], 95) == 19.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.0


def test_step_metrics_rate_latency_and_statuses() -> None:
    rows = [
        {"t_s": 0.0, "latency_ms": 100.0, "status": 200},
        {"t_s": 0.5, "latency_ms": 120.0, "status": 200},
        {"t_s": 1.0, "latency_ms": 300.0, "status": 200},
        {"t_s": 1.5, "latency_ms": None, "status": 429},
    ]
    m = step_metrics(rows, 2.0)
    assert m["achieved_rps"] == 2.0
    assert m["latency_median_ms"] == 120.0
    assert m["latency_max_ms"] == 300.0
    assert m["status_counts"] == {"200": 3, "429": 1}
    assert m["rate_limited"] == 1
    assert step_metrics([{"t_s": 0.0, "latency_ms": 1.0, "status": None}], 1.0)["achieved_rps"] is None


def test_ramp_rates_inclusive_of_maximum() -> None:
    assert ramp_rates(1.0, 0.5, 2.0) == [1.0, 1.5, 2.0]
    assert ramp_rates(0.1, 0.1, 0.3) == [0.1, 0.2, 0.3]
    assert ramp_rates(3.0, 1.0, 2.0) == []


def test_end_signal_variants() -> None:
    assert end_signal({"cursor": "abc", "markets": []}) is None
    assert end_signal({"cursor": "", "markets": []}) == "cursor is an empty string"
    assert end_signal({"cursor": None}) == "cursor is null"
    assert end_signal({"markets": []}) == "cursor field missing"
    assert end_signal(None) == "no JSON body"


def test_identity_prefers_known_keys_then_hashes() -> None:
    assert identity({"trade_id": "t1", "ticker": "M"}) == ("trade_id", "t1")
    assert identity({"ticker": "M", "event_ticker": "E"}) == ("ticker", "M")
    assert identity({"event_ticker": "E", "series_ticker": "S"}) == ("event_ticker", "E")
    key, digest = identity({"x": 1})
    assert key == "json-hash" and digest == identity({"x": 1})[1]
    assert identity({"x": 1})[1] != identity({"x": 2})[1]


def test_list_key_prefers_spec_keys() -> None:
    body = {"cursor": "c", "milestones": [], "markets": [{}]}
    assert list_key(body, ["markets"]) == "markets"
    assert list_key(body) == "milestones"
    assert list_key({"cursor": "c"}) is None
    assert list_key([1, 2]) is None
