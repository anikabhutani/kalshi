"""Route-level behavior for M1 defaults, the M5 ramp and pagination jobs, and M4 depth runs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.evidence import is_account_path
from tests.conftest import MakeApp, wait_for_job


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generic(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "markets": [{"ticker": "MKT-1", "event_ticker": "EVT-1"}],
            "event": {"event_ticker": "EVT-1", "series_ticker": "SER-1"},
            "cursor": "",
        },
    )


async def test_m1_plan_defaults_exclude_account_endpoints_with_cap_150(make_app: MakeApp) -> None:
    stack = make_app(_generic)
    default = (await stack.http.post("/api/m1/probe/plan", json={})).json()
    included = (await stack.http.post("/api/m1/probe/plan", json={"include_account": True})).json()
    assert default["estimate"]["cap"] == 150
    assert included["estimate"]["cap"] == 150
    assert included["targets"] > default["targets"]


async def test_m1_default_run_never_calls_account_endpoints(make_app: MakeApp) -> None:
    stack = make_app(_generic)
    job_id = (await stack.http.post("/api/m1/probe/run", json={})).json()["job_id"]
    job = await wait_for_job(stack.services, job_id, timeout_s=30)
    assert job["status"] == "succeeded", job["error_reason"]
    assert job["max_requests"] == 150
    assert job["params"] == {"include_account": False}
    logged = stack.services.evidence.all_requests()
    assert logged and all(r["method"] == "GET" for r in logged)
    assert not [r["path_template"] for r in logged if is_account_path(r["path_template"] or "")]
    assert len(logged) <= 150


async def test_ramp_stops_at_first_429(make_app: MakeApp) -> None:
    count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        count["n"] += 1
        if count["n"] == 4:
            return httpx.Response(429, json={"error": "too many requests"})
        return httpx.Response(200, json={"exchange_active": True}, headers={"X-Example-Remaining": "7"})

    stack = make_app(handler)
    params = {"path": "/exchange/status", "start_rps": 10, "step_rps": 5, "max_rps": 20, "requests_per_step": 3}
    plan = (await stack.http.post("/api/m5/ramp/plan", json=params)).json()
    assert plan["rates"] == [10.0, 15.0, 20.0]
    assert plan["estimate"]["total"] == 9

    job_id = (await stack.http.post("/api/m5/ramp/run", json=params)).json()["job_id"]
    job = await wait_for_job(stack.services, job_id)
    result = job["result"]
    assert job["status"] == "succeeded"
    assert len(stack.sent) == 4
    assert result["first_429"]["step"] == 1 and result["first_429"]["index"] == 0
    assert result["stopped_reason"] == "first HTTP 429"
    assert len(result["steps"]) == 2
    assert result["steps"][1]["rate_limited"] == 1
    assert "x-example-remaining" in result["rate_header_names_seen"]


async def test_ramp_cannot_exceed_global_rate_limit_or_use_listed_paths_only(make_app: MakeApp) -> None:
    stack = make_app(_generic)
    assert (await stack.http.put("/api/settings", json={"rate_limit_rps": 2})).status_code == 200
    too_fast = await stack.http.post("/api/m5/ramp/plan", json={"max_rps": 3, "start_rps": 1})
    assert too_fast.status_code == 422 and "global rate limit" in too_fast.json()["detail"]
    account = await stack.http.post("/api/m5/ramp/plan", json={"path": "/portfolio/balance", "max_rps": 2})
    assert account.status_code == 422
    big = await stack.http.post("/api/m5/ramp/plan", json={"start_rps": 0.1, "step_rps": 0.1, "max_rps": 2, "requests_per_step": 50})
    assert big.status_code == 422 and "hard cap" in big.json()["detail"]
    assert stack.sent == []


async def test_pagination_analyzer_boundaries_duplicates_and_last_page(make_app: MakeApp) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params
        if int(q.get("limit", "100")) > 1000:
            return httpx.Response(400, json={"error": "limit too large"})
        if q.get("cursor") == "c1":
            return httpx.Response(200, json={"markets": [{"ticker": "B"}, {"ticker": "C"}], "cursor": ""})
        return httpx.Response(200, json={"markets": [{"ticker": "A"}, {"ticker": "B"}], "cursor": "c1"})

    stack = make_app(handler)
    params: dict[str, Any] = {"path": "/markets", "filters": {"status": "open"}, "walk_size": 2, "page_cap": 5}
    plan = (await stack.http.post("/api/m5/pagination/plan", json=params)).json()
    assert plan["choice"]["size_param"] == "limit"
    assert plan["choice"]["size_maximum"] == 1000

    job_id = (await stack.http.post("/api/m5/pagination/run", json=params)).json()["job_id"]
    job = await wait_for_job(stack.services, job_id)
    result = job["result"]
    cases = {b["case"]: b for b in result["boundary"]}
    assert cases["Spec maximum + 1"]["status"] == 400
    assert cases["Spec maximum + 1"]["size_sent"] == 1001
    assert cases["No size parameter (server default)"]["size_sent"] is None
    assert [p["duplicates_of_earlier_pages"] for p in result["pages"]] == [0, 1]
    summary = result["summary"]
    assert summary == {
        "identity_key": "ticker",
        "unique_items": 3,
        "duplicate_items": 1,
        "pages_fetched": 2,
        "last_page_reached": True,
        "last_page_signal": "cursor is an empty string",
        "last_page_items": 2,
        "last_page_smaller_than_size": False,
    }
    assert all(r.url.params.get("status") == "open" for r in stack.sent)
    bad = await stack.http.post("/api/m5/pagination/plan", json={"path": "/markets", "filters": {"nope": "1"}})
    assert bad.status_code == 422


async def test_depth_run_brackets_oldest_trade_and_walks_archive(make_app: MakeApp) -> None:
    trades = [1_650_000_000, 1_700_000_000, 1_750_000_000]

    def handler(request: httpx.Request) -> httpx.Response:
        path, q = request.url.path, request.url.params
        if path.endswith("/historical/cutoff"):
            return httpx.Response(200, json={"market_settled_ts": _iso(1_720_000_000), "trades_created_ts": _iso(1_720_000_000)})
        if path.endswith("/markets/trades"):
            bound = int(q["max_ts"]) if "max_ts" in q else None
            before = [t for t in trades if bound is None or t < bound]
            items = [{"trade_id": str(max(before)), "created_time": _iso(max(before))}] if before else []
            return httpx.Response(200, json={"trades": items, "cursor": ""})
        if path.endswith("/historical/markets"):
            return httpx.Response(200, json={"markets": [{"ticker": "OLD", "settlement_ts": _iso(1_600_000_000)}], "cursor": ""})
        return httpx.Response(404, json={})

    stack = make_app(handler)
    params = {"targets": ["trades_live", "historical_markets"], "archive_matrix": False, "request_cap": 60, "search_from": "2020-01-01"}
    plan = (await stack.http.post("/api/m4/plan", json=params)).json()
    assert plan["estimate"]["cap"] == 60 and plan["estimate"]["matrix"] == 0

    job_id = (await stack.http.post("/api/m4/run", json=params)).json()["job_id"]
    job = await wait_for_job(stack.services, job_id)
    assert job["status"] == "succeeded", job["error_reason"]
    live, archive = job["result"]["targets"]
    assert live["bracket_lo"] <= trades[0] < live["bracket_hi"]
    assert live["bracket_hi"] - live["bracket_lo"] <= 86_400
    assert live["oldest_utc"] is not None
    assert archive["end_reached"] and archive["records_seen"] == 1
    assert archive["oldest_ts"] == 1_600_000_000
    assert job["result"]["cutoff"]["market_settled_ts"]["epoch_s"] == 1_720_000_000


async def test_depth_run_respects_request_cap(make_app: MakeApp) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        bound = int(request.url.params.get("max_ts", "2000000000"))
        items = [{"created_time": _iso(1_700_000_000)}] if bound > 1_700_000_000 else []
        return httpx.Response(200, json={"trades": items, "cursor": ""})

    stack = make_app(handler)
    params = {"targets": ["trades_live", "trades_historical"], "archive_matrix": True, "request_cap": 5}
    job_id = (await stack.http.post("/api/m4/run", json=params)).json()["job_id"]
    job = await wait_for_job(stack.services, job_id)
    assert job["status"] == "succeeded", job["error_reason"]
    assert len(stack.sent) == 5
    first, second = job["result"]["targets"]
    assert first["stop_reason"] == "request cap reached"
    assert second["stop_reason"] == "skipped: request cap reached"
    assert "Archive matrix skipped: request cap reached." in job["result"]["notes"]
