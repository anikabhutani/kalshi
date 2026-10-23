"""Route-level behavior for the M6 recorder (fake WebSocket, mocked REST) and M7 overlay."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response

from app.analysis.sportsbook import TEMPLATE_CSV
from app.jobs import JobContext
from app.modules import m6_rest_ws
from tests.conftest import TEST_KEY_ID, MakeApp, wait_for_job


class FakeConnection:
    """Answers one subscribe with acks, then streams scripted market-data messages."""

    def __init__(self, shared: dict[str, Any]) -> None:
        self.shared = shared
        self.sent: list[str] = []
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(message)
        command = json.loads(message)
        now = int(time.time() * 1000)
        for sid, channel in enumerate(command["params"]["channels"], start=1):
            await self.queue.put(
                json.dumps({"id": command["id"], "type": "subscribed", "msg": {"channel": channel, "sid": sid}, "sending_ts_ms": now})
            )
        self.shared["trade_ts_ms"] = now
        for seq, bid in ((1, "0.40"), (2, "0.41"), (4, "0.42")):
            await self.queue.put(
                json.dumps(
                    {
                        "type": "ticker",
                        "sid": 1,
                        "seq": seq,
                        "sending_ts_ms": now + 2,
                        "msg": {"market_ticker": "MKT-1", "yes_bid_dollars": bid, "yes_ask_dollars": "0.45", "price_dollars": "0.43", "ts_ms": now},
                    }
                )
            )
        await self.queue.put(
            json.dumps(
                {"type": "trade", "sid": 2, "seq": 1, "sending_ts_ms": now + 2, "msg": {"trade_id": "T1", "market_ticker": "MKT-1", "yes_price_dollars": "0.43", "count_fp": "1.00", "ts_ms": now}}
            )
        )

    async def recv(self) -> str:
        return await self.queue.get()

    async def close(self) -> None:
        self.closed = True


def _rest_handler(shared: dict[str, Any]) -> Any:
    calls = {"market": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/markets/trades"):
            trades = []
            if "trade_ts_ms" in shared:
                created = datetime.fromtimestamp(shared["trade_ts_ms"] / 1000, UTC).isoformat()
                trades = [{"trade_id": "T1", "created_time": created, "yes_price_dollars": "0.43"}]
            return httpx.Response(200, json={"trades": trades, "cursor": ""})
        if path.endswith("/markets/MKT-1"):
            calls["market"] += 1
            bid = "0.40" if calls["market"] == 1 else "0.42"
            market = {"ticker": "MKT-1", "status": "active", "yes_bid_dollars": bid, "yes_ask_dollars": "0.45", "last_price_dollars": "0.43"}
            return httpx.Response(200, json={"market": market}, headers={"Date": "Thu, 01 Oct 2026 00:00:00 GMT"})
        return httpx.Response(404, json={})

    return handler


RECORDER = {"market_ticker": "MKT-1", "duration_min": 1, "poll_interval_s": 0.5, "channels": ["ticker", "trade"], "poll_trades": True}


async def test_m6_spec_view_and_plan(make_app: MakeApp) -> None:
    stack = make_app(_rest_handler({}))
    view = (await stack.http.get("/api/m6/spec")).json()
    assert view["ws_url"] == "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
    assert view["recordable_channels"] == ["ticker", "trade", "orderbook_delta"]
    aspects = [r["aspect"] for r in view["rows"]]
    assert "Authentication" in aspects and "Rate limits" in aspects
    rate_row = next(r for r in view["rows"] if r["aspect"] == "Rate limits")
    assert "does not mention WebSocket" in rate_row["websocket"]

    plan = (await stack.http.post("/api/m6/plan", json=RECORDER)).json()["estimate"]
    assert plan["rest_cycles"] == 120 and plan["rest_requests"] == 240
    assert plan["ws_requests_max"] == 12 and plan["cap"] == 257

    assert (await stack.http.put("/api/settings", json={"rate_limit_rps": 2})).status_code == 200
    too_fast = await stack.http.post("/api/m6/plan", json=RECORDER)
    assert too_fast.status_code == 422 and "global rate limit" in too_fast.json()["detail"]
    bad_channel = await stack.http.post("/api/m6/plan", json={**RECORDER, "channels": ["fill"]})
    assert bad_channel.status_code == 422
    assert stack.sent == []


async def test_m6_recorder_subscribes_only_and_compares_feeds(make_app: MakeApp, monkeypatch: pytest.MonkeyPatch) -> None:
    shared: dict[str, Any] = {}
    connections: list[FakeConnection] = []

    async def connector(url: str, headers: dict[str, str]) -> tuple[FakeConnection, int, dict[str, str]]:
        assert url == "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
        assert headers["KALSHI-ACCESS-KEY"] == TEST_KEY_ID and headers["KALSHI-ACCESS-SIGNATURE"]
        conn = FakeConnection(shared)
        connections.append(conn)
        return conn, 101, {"Upgrade": "websocket"}

    monkeypatch.setattr(m6_rest_ws, "connector", connector)
    monkeypatch.setattr(m6_rest_ws, "seconds_per_minute", 1.2)
    stack = make_app(_rest_handler(shared))
    job_id = (await stack.http.post("/api/m6/run", json=RECORDER)).json()["job_id"]
    job = await wait_for_job(stack.services, job_id, timeout_s=15)
    assert job["status"] == "succeeded", job["error_reason"]
    result = job["result"]

    (conn,) = connections
    assert [json.loads(m) for m in conn.sent] == [
        {"id": 1, "cmd": "subscribe", "params": {"channels": ["ticker", "trade"], "market_ticker": "MKT-1"}}
    ]
    assert conn.closed
    assert result["stopped_reason"] is None and result["reconnects"] == 0
    assert [a["msg"]["channel"] for a in result["acks"]] == ["ticker", "trade"]
    assert result["ws"]["messages"] == 4
    assert result["ws"]["message_counts"] == {"ticker": 3, "trade": 1}
    assert result["ws"]["price_changes"] == 2
    seq = {s["sid"]: s for s in result["ws"]["sequence"]}
    assert seq[1]["missing"] == 1 and seq[2]["missing"] == 0
    assert result["ws"]["latency"]["ticker"]["recv_minus_ts_ms"]["count"] == 3
    assert result["rest"]["polls"] == 3 and result["rest"]["ok_polls"] == 3
    assert result["rest"]["price_changes"] == 1
    assert result["trades"]["matched"] == 1 and result["trades"]["ws_only"] == 0
    assert result["market_status"] == "active"

    logged = stack.services.evidence.all_requests()
    templates = [r["path_template"] for r in logged]
    assert templates.count("WS handshake") == 1 and templates.count("WS subscribe") == 1
    assert {r["method"] for r in logged} <= {"GET", "WS_SEND"}
    assert TEST_KEY_ID not in json.dumps(logged, default=str)
    assert job["request_count"] == len(logged)
    raw = (stack.services.config.raw_dir / f"ws-{job_id}.jsonl").read_text().splitlines()
    assert len(raw) == 4


async def test_m6_handshake_rejection_stops_the_job(make_app: MakeApp, monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"n": 0}

    async def connector(url: str, headers: dict[str, str]) -> tuple[FakeConnection, int, dict[str, str]]:
        attempts["n"] += 1
        raise InvalidStatus(Response(401, "Unauthorized", Headers()))

    monkeypatch.setattr(m6_rest_ws, "connector", connector)
    monkeypatch.setattr(m6_rest_ws, "seconds_per_minute", 1.0)
    stack = make_app(_rest_handler({}))
    job_id = (await stack.http.post("/api/m6/run", json={**RECORDER, "poll_trades": False})).json()["job_id"]
    job = await wait_for_job(stack.services, job_id)
    assert job["status"] == "succeeded"
    assert attempts["n"] == 1
    assert job["result"]["stopped_reason"] == "WebSocket handshake rejected with HTTP 401."
    assert job["result"]["connections"][0]["status"] == 401


async def test_m6_gives_up_after_max_handshakes_and_stops_polling(make_app: MakeApp, monkeypatch: pytest.MonkeyPatch) -> None:
    async def connector(url: str, headers: dict[str, str]) -> tuple[FakeConnection, int, dict[str, str]]:
        raise OSError("certificate verify failed")

    monkeypatch.setattr(m6_rest_ws, "connector", connector)
    monkeypatch.setattr(m6_rest_ws, "backoff_base_s", 0.01)
    monkeypatch.setattr(m6_rest_ws, "seconds_per_minute", 30.0)
    stack = make_app(_rest_handler({}))
    job_id = (await stack.http.post("/api/m6/run", json={**RECORDER, "poll_trades": False})).json()["job_id"]
    job = await wait_for_job(stack.services, job_id, timeout_s=10)
    result = job["result"]
    assert len(result["connections"]) == m6_rest_ws.MAX_HANDSHAKES
    assert result["stopped_reason"].startswith(f"WebSocket gave up after {m6_rest_ws.MAX_HANDSHAKES} connection attempts")
    assert "certificate verify failed" in result["stopped_reason"]
    assert result["recorded_s"] < 5


async def test_m6_unknown_market_stops_after_first_poll(make_app: MakeApp, monkeypatch: pytest.MonkeyPatch) -> None:
    connections: list[FakeConnection] = []

    async def connector(url: str, headers: dict[str, str]) -> tuple[FakeConnection, int, dict[str, str]]:
        conn = FakeConnection({})
        connections.append(conn)
        return conn, 101, {}

    monkeypatch.setattr(m6_rest_ws, "connector", connector)
    monkeypatch.setattr(m6_rest_ws, "seconds_per_minute", 30.0)
    stack = make_app(_rest_handler({}))
    job_id = (await stack.http.post("/api/m6/run", json={**RECORDER, "market_ticker": "NOPE-1"})).json()["job_id"]
    job = await wait_for_job(stack.services, job_id, timeout_s=10)
    result = job["result"]
    assert result["stopped_reason"] == "GET /markets/NOPE-1 returned HTTP 404; check the market ticker."
    assert result["rest"]["polls"] == 1 and result["recorded_s"] < 5
    assert all(c.closed for c in connections)


async def _lab_run(stack: Any, start: int) -> str:
    result = {
        "params": {"market_ticker": "MKT-1", "start_ts": start, "end_ts": start + 3600},
        "sources": {
            "trades": {"kind": "trades", "rows": [{"ts": start + 60, "price": 0.55}, {"ts": start + 1800, "price": 0.6}]},
            "candles_1m": {"kind": "candles", "rows": [{"ts": start + 60, "close": 0.5, "bid_close": 0.49, "ask_close": 0.51}]},
            "orderbook": {"kind": "orderbook", "snapshot_ts": start + 10, "mid": 0.5},
        },
    }

    async def runner(ctx: JobContext) -> dict[str, Any]:
        return result

    job_id = stack.services.jobs.start("M3", "price_sources", result["params"], runner, max_requests=0)
    await wait_for_job(stack.services, job_id)
    return job_id


async def test_m7_template_upload_dummy_and_overlay(make_app: MakeApp) -> None:
    stack = make_app(_rest_handler({}))
    template = await stack.http.get("/api/m7/template")
    assert template.status_code == 200 and template.text == TEMPLATE_CSV
    assert "attachment" in template.headers["content-disposition"]

    bad = await stack.http.post("/api/m7/datasets", json={"name": "x", "csv_text": "a,b\n1,2\n"})
    assert bad.status_code == 422 and "Missing column" in bad.json()["detail"]
    uploaded = (await stack.http.post("/api/m7/datasets", json={"name": "Template", "csv_text": TEMPLATE_CSV})).json()
    assert uploaded["rows"] == 4 and not uploaded["is_dummy"]

    start = 1_767_225_600
    lab_id = await _lab_run(stack, start)
    series = (await stack.http.get(f"/api/m7/lab_runs/{lab_id}/series")).json()
    ids = [s["id"] for s in series["series"]]
    assert ids == ["trades:price", "candles_1m:close", "candles_1m:bid_close", "candles_1m:ask_close"]

    dummy = (await stack.http.post("/api/m7/datasets/dummy", json={"lab_job_id": lab_id})).json()
    assert dummy["is_dummy"] and dummy["name"].startswith("DUMMY DATA")
    assert dummy["first_ts"] == "2026-01-01T00:00:00+00:00"
    listing = (await stack.http.get("/api/m7/datasets")).json()
    assert {d["id"] for d in listing} == {uploaded["id"], dummy["id"]}

    body = {"dataset_id": dummy["id"], "lab_job_id": lab_id, "selection": "YES side (dummy)", "series_id": "trades:price", "max_staleness_s": 600}
    out = (await stack.http.post("/api/m7/overlay", json=body)).json()
    assert out["is_dummy"] and out["market_ticker"] == "MKT-1"
    assert len(out["rows"]) == 26
    assert out["rows"][0]["kalshi_price"] is None
    with_price = [r for r in out["rows"] if r["within_staleness"]]
    assert with_price and all(r["gap_no_vig_pp"] is not None for r in with_price)
    assert [p["price"] for p in out["kalshi_points"]] == [0.55, 0.6]
    assert {s["book"] for s in out["summary"]} == {"DUMMY BOOK A", "DUMMY BOOK B"}

    missing = await stack.http.post("/api/m7/overlay", json={**body, "selection": "nope"})
    assert missing.status_code == 422
    wrong_series = await stack.http.post("/api/m7/overlay", json={**body, "series_id": "orderbook:mid"})
    assert wrong_series.status_code == 422
    assert (await stack.http.delete(f"/api/m7/datasets/{dummy['id']}")).json() == {"deleted": True}
    assert (await stack.http.get(f"/api/m7/datasets/{dummy['id']}")).status_code == 404
    assert stack.sent == []
