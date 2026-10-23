"""Auth-probe planning against the real spec, and status classification."""

from __future__ import annotations

from app.analysis.auth_probe import (
    build_request,
    classify_probe,
    endpoint_id,
    path_param_kind,
    plan_probe,
)
from app.spec_loader import OpenApiSpec


def test_ticker_resolved_by_preceding_segment() -> None:
    assert path_param_kind("/markets/{ticker}", "ticker") == "market_ticker"
    assert path_param_kind("/series/{series_ticker}/events/{ticker}/candlesticks", "ticker") == "event_ticker"
    assert path_param_kind("/series/{series_ticker}", "series_ticker") == "series_ticker"
    assert path_param_kind("/historical/markets/{ticker}", "ticker") == "historical_market_ticker"
    assert path_param_kind("/portfolio/orders/{order_id}", "order_id") is None


def test_plan_only_contains_spec_get_endpoints(spec: OpenApiSpec) -> None:
    plan = plan_probe(spec, include_account=True)
    spec_gets = {endpoint_id(e) for e in spec.get_endpoints()}
    planned = {endpoint_id(t.endpoint) for t in plan.targets}
    skipped = {endpoint_id(s.endpoint) for s in plan.skipped}
    assert planned | skipped == spec_gets
    assert not planned & skipped
    assert all(t.endpoint.method == "GET" for t in plan.targets)


def test_unknown_ids_and_required_params_are_skipped_with_reason(spec: OpenApiSpec) -> None:
    plan = plan_probe(spec, include_account=True)
    reasons = {endpoint_id(s.endpoint): s.reason for s in plan.skipped}
    assert "order_id" in reasons["GET /portfolio/orders/{order_id}"]
    assert "subtrader_id" in reasons["GET /fcm/subtraders/blocked_categories"]


def test_account_endpoints_can_be_excluded(spec: OpenApiSpec) -> None:
    plan = plan_probe(spec, include_account=False)
    assert not any(t.endpoint.path.startswith("/portfolio") for t in plan.targets)
    assert any("excluded" in s.reason for s in plan.skipped)


def test_build_request_fills_ids_time_range_and_page_size(spec: OpenApiSpec) -> None:
    plan = plan_probe(spec, include_account=True)
    by_id = {endpoint_id(t.endpoint): t for t in plan.targets}
    ids = {"market_ticker": "MKT-1", "event_ticker": "EVT-1", "series_ticker": "SER"}

    candles = by_id["GET /series/{series_ticker}/markets/{ticker}/candlesticks"]
    built = build_request(candles, ids, now_s=1_000_000)
    assert built is not None
    path, params = built
    assert path == "/series/SER/markets/MKT-1/candlesticks"
    assert params["period_interval"] == 60
    assert params["end_ts"] == 1_000_000
    assert params["start_ts"] == 1_000_000 - 3 * 3600

    trades = build_request(by_id["GET /markets/trades"], ids, now_s=0)
    assert trades == ("/markets/trades", {"limit": 1})

    assert build_request(by_id["GET /milestones/{milestone_id}"], ids, now_s=0) is None


class TestClassify:
    def test_public_matches_spec(self) -> None:
        verdict = classify_probe(200, 200, spec_auth_required=False)
        assert verdict.classification == "public"
        assert verdict.mismatch is False

    def test_public_but_spec_says_key(self) -> None:
        verdict = classify_probe(200, 200, spec_auth_required=True)
        assert verdict.classification == "public"
        assert verdict.mismatch is True

    def test_key_required_matches_spec(self) -> None:
        verdict = classify_probe(401, 200, spec_auth_required=True)
        assert verdict.classification == "key required"
        assert verdict.mismatch is False

    def test_key_required_but_spec_says_public(self) -> None:
        verdict = classify_probe(403, 200, spec_auth_required=False)
        assert verdict.mismatch is True

    def test_denied_with_key_is_inconclusive(self) -> None:
        verdict = classify_probe(401, 403, spec_auth_required=True)
        assert verdict.classification == "denied even with key"
        assert verdict.mismatch is None

    def test_other_statuses_are_inconclusive(self) -> None:
        assert classify_probe(404, 404, spec_auth_required=False).classification == "inconclusive"
        assert classify_probe(401, None, spec_auth_required=True).mismatch is None
        assert classify_probe(None, None, spec_auth_required=False).classification == "error"
