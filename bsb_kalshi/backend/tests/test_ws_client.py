"""WebSocket read-only guard, URL pairing from auth_notes, and message/metric helpers (M6)."""

from __future__ import annotations

import json
import ssl
from types import SimpleNamespace
from typing import Any

import pytest

from app import ws_client

from app.analysis.ws_compare import (
    Observation,
    TradeSeen,
    change_times,
    latency_summary,
    match_trades,
    message_counts,
    parse_ws_message,
    rest_market_state,
    rest_miss_analysis,
    sequence_gaps,
)
from app.config import ROOT_DIR
from app.errors import WsCommandBlocked
from app.spec_loader import AsyncApiSpec
from app.ws_client import encode_outgoing, subscribe_command, ws_url_for, ws_url_table

SPEC_CHANNELS = AsyncApiSpec.load(ROOT_DIR / "specs" / "asyncapi.yaml").subscribe_channels()


def test_subscribe_command_shape_follows_spec() -> None:
    one = subscribe_command(1, ["ticker", "trade"], ["MKT-1"], SPEC_CHANNELS)
    assert one == {"id": 1, "cmd": "subscribe", "params": {"channels": ["ticker", "trade"], "market_ticker": "MKT-1"}}
    many = subscribe_command(2, ["ticker"], ["A", "B"], SPEC_CHANNELS)
    assert many["params"] == {"channels": ["ticker"], "market_tickers": ["A", "B"]}
    assert json.loads(encode_outgoing(one)) == one


@pytest.mark.parametrize(
    ("channels", "tickers"),
    [
        ([], ["MKT"]),
        (["ticker"], []),
        (["ticker"], [""]),
        (["fill"], ["MKT"]),
        (["user_orders"], ["MKT"]),
        (["market_positions"], ["MKT"]),
        (["not_a_channel"], ["MKT"]),
    ],
)
def test_subscribe_command_rejects_private_unknown_or_unscoped(channels: list[str], tickers: list[str]) -> None:
    with pytest.raises(WsCommandBlocked):
        subscribe_command(1, channels, tickers, SPEC_CHANNELS)


@pytest.mark.parametrize(
    "payload",
    [
        {"id": 1, "cmd": "unsubscribe", "params": {"sids": [1]}},
        {"id": 1, "cmd": "update_subscription", "params": {"sids": [1], "action": "add_markets"}},
        {"id": 1, "cmd": "list_subscriptions"},
        {"id": 1, "cmd": "create_order", "params": {}},
        {"id": 1, "cmd": "subscribe", "params": {"channels": ["fill"]}},
        {"id": 1, "cmd": "subscribe", "params": {}},
        {"id": 1},
    ],
)
def test_encode_outgoing_refuses_everything_but_market_data_subscribe(payload: dict[str, object]) -> None:
    with pytest.raises(WsCommandBlocked):
        encode_outgoing(payload)


def test_ws_url_table_pairs_hosts_from_auth_notes() -> None:
    table = ws_url_table((ROOT_DIR / "specs" / "auth_notes.md").read_text(encoding="utf-8"))
    assert ws_url_for("https://external-api.kalshi.com/trade-api/v2", table) == "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
    assert ws_url_for("https://external-api.demo.kalshi.co/trade-api/v2", table) == "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
    assert ws_url_for("https://example.com/trade-api/v2", table) is None


async def test_default_connector_verifies_tls_with_certifi(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_connect(url: str, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(response=None)

    monkeypatch.setattr(ws_client, "connect", fake_connect)
    await ws_client.default_connector("wss://example.test/trade-api/ws/v2", {})
    tls = captured["ssl"]
    assert isinstance(tls, ssl.SSLContext) and tls.verify_mode == ssl.CERT_REQUIRED and tls.check_hostname
    assert tls.cert_store_stats()["x509_ca"] > 0


def _ticker(seq: int, bid: str, ts_ms: int, recv: float) -> dict[str, object]:
    text = json.dumps(
        {
            "type": "ticker",
            "sid": 1,
            "seq": seq,
            "sending_ts_ms": ts_ms + 5,
            "msg": {"market_ticker": "M", "yes_bid_dollars": bid, "yes_ask_dollars": "0.60", "price_dollars": "0.55", "ts_ms": ts_ms},
        }
    )
    return parse_ws_message(text, recv)


def test_parse_ws_message_types() -> None:
    row = _ticker(1, "0.50", 1000, 1030.0)
    assert row["type"] == "ticker" and row["yes_bid"] == 0.5 and row["last_price"] == 0.55
    assert row["ts_ms"] == 1000 and row["sending_ts_ms"] == 1005
    trade = parse_ws_message(
        json.dumps({"type": "trade", "sid": 2, "seq": 1, "msg": {"trade_id": "T", "yes_price_dollars": "0.41", "count_fp": "3.00", "ts_ms": 5}}),
        9.0,
    )
    assert trade["trade_id"] == "T" and trade["yes_price"] == 0.41 and trade["count"] == 3.0
    err = parse_ws_message(json.dumps({"type": "error", "msg": {"code": 6, "msg": "Already subscribed"}}), 1.0)
    assert err["code"] == 6 and err["message"] == "Already subscribed"
    assert parse_ws_message("not json", 1.0)["type"] == "unparseable"


def test_rest_market_state_uses_dollar_fields() -> None:
    assert rest_market_state({"yes_bid_dollars": "0.40", "yes_ask_dollars": "0.42", "last_price_dollars": "0.41"}) == (0.4, 0.42, 0.41)
    assert rest_market_state({}) == (None, None, None)


def test_change_times_and_rest_misses() -> None:
    a, b, c = (0.40, 0.42, 0.41), (0.41, 0.42, 0.41), (0.42, 0.43, 0.41)
    ws = [Observation(t, s) for t, s in [(100, a), (150, b), (160, c), (170, b), (250, b), (400, c)]]
    changes = change_times(ws)
    assert changes == [150, 160, 170, 400]
    polls = [Observation(120, a), Observation(200, b), Observation(300, b), Observation(500, c)]
    result = rest_miss_analysis(changes, polls)
    assert [i["ws_changes"] for i in result["per_interval"]] == [3, 0, 1]
    assert [i["rest_changed"] for i in result["per_interval"]] == [True, False, True]
    assert [i["missed"] for i in result["per_interval"]] == [2, 0, 0]
    assert result["rest_missed_changes"] == 2
    assert result["intervals_multiple_ws_changes"] == 1
    assert result["intervals_ws_changed_rest_unchanged"] == 0
    assert result["intervals_rest_changed_ws_unchanged"] == 0


def test_rest_miss_counts_reverted_changes() -> None:
    a, b = (0.4, 0.5, 0.45), (0.41, 0.5, 0.45)
    result = rest_miss_analysis([10, 20], [Observation(0, a), Observation(30, a)])
    assert result["per_interval"][0] == {"start_ms": 0, "end_ms": 30, "ws_changes": 2, "rest_changed": False, "missed": 2}
    assert result["intervals_ws_changed_rest_unchanged"] == 1
    only_rest = rest_miss_analysis([], [Observation(0, a), Observation(30, b)])
    assert only_rest["intervals_rest_changed_ws_unchanged"] == 1 and only_rest["rest_missed_changes"] == 0


def test_match_trades_window_and_delay() -> None:
    ws = {
        "A": TradeSeen("A", 1_000, 1_010),
        "B": TradeSeen("B", 2_000, 2_010),
        "EARLY": TradeSeen("EARLY", 500, 600),
    }
    rest = {
        "A": TradeSeen("A", 1_000, 3_000),
        "C": TradeSeen("C", 2_500, 3_000),
        "LATE": TradeSeen("LATE", 9_000, 9_500),
    }
    out = match_trades(ws, rest, start_ms=900, rest_coverage_end_ms=5_000)
    assert (out["ws_trades"], out["rest_trades"], out["matched"], out["ws_only"], out["rest_only"]) == (2, 2, 1, 1, 1)
    assert out["ws_only_ids"] == ["B"] and out["rest_only_ids"] == ["C"]
    assert out["rest_delay_after_ws_ms"]["median"] == 1_990
    assert match_trades(ws, rest, 900, None)["matched"] == 0
    never_subscribed = match_trades(ws, rest, None, 5_000)
    assert never_subscribed["rest_trades"] == 0 and never_subscribed["rest_only"] == 0


def test_sequence_gaps_latency_and_counts() -> None:
    events = [_ticker(1, "0.5", 1000, 1040.0), _ticker(2, "0.5", 1100, 1120.0), _ticker(5, "0.5", 1200, 1230.0), _ticker(4, "0.5", 1300, 1310.0)]
    gaps = sequence_gaps(events)
    assert gaps == [{"sid": 1, "types": ["ticker"], "messages": 4, "first_seq": 1, "last_seq": 5, "missing": 2, "out_of_order": 1}]
    lat = latency_summary(events)["ticker"]
    assert lat["recv_minus_ts_ms"]["min"] == 10 and lat["recv_minus_ts_ms"]["max"] == 40
    assert lat["recv_minus_sending_ts_ms"]["min"] == 5
    assert message_counts([*events, {"type": "trade"}]) == {"ticker": 4, "trade": 1}
