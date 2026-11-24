"""M6 helpers: parse WebSocket messages and compare the WS feed with REST polling.

Definitions (all times are local receive times in unix milliseconds unless stated):
- Price state: the tuple (yes bid, yes ask, last trade price). WS ``ticker`` messages carry
  ``yes_bid_dollars``, ``yes_ask_dollars`` and ``price_dollars`` ("Last traded price"); REST
  ``GET /markets/{ticker}`` carries ``yes_bid_dollars``, ``yes_ask_dollars`` and
  ``last_price_dollars`` ("Price for the last traded YES contract"). Pairing
  ``price_dollars`` with ``last_price_dollars`` is by their spec descriptions.
- Change: an observation whose price state differs from the previous observation of the same
  feed. The first observation of a feed is its baseline, not a change.
- REST miss: in each interval between two consecutive successful polls ``(t_prev, t_cur]``,
  ``max(0, WS changes in the interval - (1 if the polled state changed else 0))``. A poll can
  reveal at most one net change, so every additional WS change in the interval was not
  observable by REST. WS changes before the first or after the last poll are not counted.
- Update latency: receive time minus the message's exchange timestamp (``ts_ms``) or minus
  ``sending_ts_ms`` ("when Kalshi queued this message"). Both include the local clock offset.
- Trade coverage: trades are matched by ``trade_id``. Only trades whose exchange time lies
  between the first confirmed subscription (the ``subscribed`` ack's ``sending_ts_ms``, on
  Kalshi's clock like trade times) and the last successful REST trades poll are compared;
  earlier trades could not have been streamed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.analysis.limits import describe

PriceState = tuple[float | None, float | None, float | None]


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Observation:
    """One observed price state at a local time."""

    t_ms: float
    state: PriceState


@dataclass(frozen=True)
class TradeSeen:
    """A trade as first seen by one feed."""

    trade_id: str
    exchange_ms: float | None
    first_seen_ms: float


def parse_ws_message(text: str, recv_ms: float) -> dict[str, Any]:
    """Flatten one WS message into a compact event row (unknown shapes keep only the type)."""
    try:
        raw = json.loads(text)
    except ValueError:
        return {"recv_ms": recv_ms, "type": "unparseable"}
    if not isinstance(raw, dict):
        return {"recv_ms": recv_ms, "type": "unparseable"}
    msg = raw.get("msg") if isinstance(raw.get("msg"), dict) else {}
    row: dict[str, Any] = {
        "recv_ms": recv_ms,
        "type": str(raw.get("type") or "unknown"),
        "sid": raw.get("sid"),
        "seq": raw.get("seq"),
        "sending_ts_ms": _num(raw.get("sending_ts_ms")),
        "ts_ms": _num(msg.get("ts_ms")),
        "market_ticker": msg.get("market_ticker"),
    }
    if row["type"] == "ticker":
        row.update(
            yes_bid=_num(msg.get("yes_bid_dollars")),
            yes_ask=_num(msg.get("yes_ask_dollars")),
            last_price=_num(msg.get("price_dollars")),
            volume=_num(msg.get("volume_fp")),
        )
    elif row["type"] == "trade":
        row.update(
            trade_id=msg.get("trade_id"),
            yes_price=_num(msg.get("yes_price_dollars")),
            count=_num(msg.get("count_fp")),
            taker_outcome_side=msg.get("taker_outcome_side"),
        )
    elif row["type"] == "orderbook_delta":
        row.update(price=_num(msg.get("price_dollars")), delta=_num(msg.get("delta_fp")), side=msg.get("side"))
    elif row["type"] == "error":
        row.update(code=msg.get("code"), message=msg.get("msg"))
    return row


def rest_market_state(market: Mapping[str, Any]) -> PriceState:
    """Price state from a REST ``market`` object."""
    return (
        _num(market.get("yes_bid_dollars")),
        _num(market.get("yes_ask_dollars")),
        _num(market.get("last_price_dollars")),
    )


def ws_ticker_state(row: Mapping[str, Any]) -> PriceState:
    """Price state from a parsed WS ``ticker`` event row."""
    return (row.get("yes_bid"), row.get("yes_ask"), row.get("last_price"))


def change_times(observations: Sequence[Observation]) -> list[float]:
    """Times at which the state differs from the previous observation (first is baseline)."""
    return [
        cur.t_ms
        for prev, cur in zip(observations, observations[1:], strict=False)
        if cur.state != prev.state
    ]


def rest_miss_analysis(ws_changes: Sequence[float], polls: Sequence[Observation]) -> dict[str, Any]:
    """Per poll interval: WS changes inside it, whether REST saw a change, and misses."""
    ordered = sorted(ws_changes)
    per_interval: list[dict[str, Any]] = []
    for prev, cur in zip(polls, polls[1:], strict=False):
        ws_k = sum(1 for t in ordered if prev.t_ms < t <= cur.t_ms)
        rest_changed = cur.state != prev.state
        per_interval.append(
            {
                "start_ms": prev.t_ms,
                "end_ms": cur.t_ms,
                "ws_changes": ws_k,
                "rest_changed": rest_changed,
                "missed": max(0, ws_k - (1 if rest_changed else 0)),
            }
        )
    return {
        "intervals": len(per_interval),
        "ws_changes_between_polls": sum(i["ws_changes"] for i in per_interval),
        "rest_changes": sum(1 for i in per_interval if i["rest_changed"]),
        "rest_missed_changes": sum(i["missed"] for i in per_interval),
        "intervals_ws_changed_rest_unchanged": sum(
            1 for i in per_interval if i["ws_changes"] > 0 and not i["rest_changed"]
        ),
        "intervals_rest_changed_ws_unchanged": sum(
            1 for i in per_interval if i["ws_changes"] == 0 and i["rest_changed"]
        ),
        "intervals_multiple_ws_changes": sum(1 for i in per_interval if i["ws_changes"] > 1),
        "per_interval": per_interval,
    }


def match_trades(
    ws: Mapping[str, TradeSeen],
    rest: Mapping[str, TradeSeen],
    start_ms: float | None,
    rest_coverage_end_ms: float | None,
) -> dict[str, Any]:
    """Trades seen by each feed inside the comparable window, and REST's extra delay.

    ``start_ms`` is None when no subscription was confirmed, and ``rest_coverage_end_ms`` is
    None when no trades poll succeeded; either way nothing is comparable.
    """
    if start_ms is None or rest_coverage_end_ms is None:
        return {
            "window_start_ms": start_ms,
            "window_end_ms": None,
            "ws_trades": 0,
            "rest_trades": 0,
            "matched": 0,
            "ws_only": 0,
            "rest_only": 0,
            "ws_only_ids": [],
            "rest_only_ids": [],
            "rest_delay_after_ws_ms": describe([]),
        }

    def eligible(t: TradeSeen) -> bool:
        return t.exchange_ms is not None and start_ms <= t.exchange_ms <= rest_coverage_end_ms

    ws_ids = {k for k, v in ws.items() if eligible(v)}
    rest_ids = {k for k, v in rest.items() if eligible(v)}
    matched = ws_ids & rest_ids
    delays = [rest[k].first_seen_ms - ws[k].first_seen_ms for k in matched]
    return {
        "window_start_ms": start_ms,
        "window_end_ms": rest_coverage_end_ms,
        "ws_trades": len(ws_ids),
        "rest_trades": len(rest_ids),
        "matched": len(matched),
        "ws_only": len(ws_ids - rest_ids),
        "rest_only": len(rest_ids - ws_ids),
        "ws_only_ids": sorted(ws_ids - rest_ids)[:50],
        "rest_only_ids": sorted(rest_ids - ws_ids)[:50],
        "rest_delay_after_ws_ms": describe(delays),
    }


def sequence_gaps(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Per subscription id, in arrival order: messages, missing seq numbers, out-of-order."""
    by_sid: dict[Any, dict[str, Any]] = {}
    for e in events:
        sid, seq = e.get("sid"), e.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool):
            continue
        entry = by_sid.setdefault(
            sid, {"sid": sid, "types": set(), "messages": 0, "first_seq": seq, "last_seq": None, "missing": 0, "out_of_order": 0}
        )
        entry["types"].add(e.get("type"))
        prev = entry["last_seq"]
        if prev is not None:
            if seq > prev + 1:
                entry["missing"] += seq - prev - 1
            elif seq <= prev:
                entry["out_of_order"] += 1
        entry["messages"] += 1
        entry["last_seq"] = seq if prev is None else max(prev, seq)
    return [{**v, "types": sorted(str(t) for t in v["types"])} for v in by_sid.values()]


def message_counts(events: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Number of WS messages per ``type``."""
    counts: dict[str, int] = {}
    for e in events:
        key = str(e.get("type"))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def latency_summary(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Receive minus ``ts_ms`` and minus ``sending_ts_ms``, per message type."""
    out: dict[str, Any] = {}
    for kind in sorted({str(e.get("type")) for e in events}):
        rows = [e for e in events if e.get("type") == kind]
        exchange = [e["recv_ms"] - e["ts_ms"] for e in rows if e.get("ts_ms") is not None]
        sending = [e["recv_ms"] - e["sending_ts_ms"] for e in rows if e.get("sending_ts_ms") is not None]
        if exchange or sending:
            out[kind] = {"recv_minus_ts_ms": describe(exchange), "recv_minus_sending_ts_ms": describe(sending)}
    return out
