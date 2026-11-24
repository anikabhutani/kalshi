"""Task 3: fee math, request planning, incremental backfill and cost results (mocked Kalshi)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.task3.backfill import (
    BATCH_MAX_SLOTS,
    Fetcher,
    Hooks,
    backfill_candles,
    estimate_candle_requests,
    market_window,
    plan_chunks,
    refresh_inventory,
)
from app.task3.costs import AnalysisParams, bet_costs, fee_dollars, price_group, run_analysis
from app.task3.store import NflStore

KICKOFF = 1_790_000_100 - 1_790_000_100 % 60
OPEN = KICKOFF - 2 * 86_400
CLOSE = KICKOFF + 3 * 3600


def test_fee_rounds_up_to_the_cent_or_to_a_hundredth_of_a_cent() -> None:
    assert fee_dollars(1, 0.50, 1.0) == pytest.approx(0.02)
    assert fee_dollars(10, 0.50, 1.0) == pytest.approx(0.18)
    assert fee_dollars(100, 0.50, 1.0) == pytest.approx(1.75)
    assert fee_dollars(1, 0.055, 1.0, "exact") == pytest.approx(0.0037)
    assert fee_dollars(100, 0.50, 0.5) == pytest.approx(0.88)


def test_bet_costs_half_gap_plus_fee_per_ten_dollars() -> None:
    rows = {(r["side"], r["size"]): r for r in bet_costs(4800, 5000, 1.0, "cent")}
    yes10 = rows[("yes", 10)]
    assert yes10["price_paid"] == pytest.approx(0.50)
    assert yes10["cost"] == pytest.approx(10 * 0.01 + 0.18)
    assert yes10["cost_per_10"] == pytest.approx(10 * 0.28 / 5.0)
    no1 = rows[("no", 1)]
    assert no1["price_paid"] == pytest.approx(0.52)
    assert no1["fee"] == pytest.approx(0.02)
    assert price_group(0.05) == "1–9¢" and price_group(0.52) == "50–59¢" and price_group(0.99) == "90–99¢"


def _market(i: int, **extra: Any) -> dict[str, Any]:
    return {
        "id": i,
        "ticker": f"EV-{i}",
        "event_ticker": "EV",
        "listed_from": "live",
        "status": "finalized",
        "open_ts": OPEN,
        "close_ts": CLOSE,
        "settle_ts": CLOSE + 300,
        "fetched_through": None,
        "complete": 0,
        **extra,
    }


def test_plan_chunks_stays_within_the_slot_limit_and_covers_the_window() -> None:
    markets = [_market(i) for i in range(25)]
    chunks = plan_chunks(markets, now=CLOSE + 86_400)
    assert all(c.slots <= BATCH_MAX_SLOTS for c in chunks)
    assert chunks[0].start_ts == OPEN and chunks[-1].end_ts >= CLOSE
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert b.start_ts == a.end_ts + 60
    assert {len(c.tickers) for c in chunks} == {25}


def test_market_window_is_incremental() -> None:
    now = CLOSE + 86_400
    assert market_window(_market(1, fetched_through=CLOSE + 300), now) is None
    start, end = market_window(_market(1, fetched_through=KICKOFF), now)  # type: ignore[misc]
    assert start == KICKOFF + 60 and end == CLOSE + 300
    active = _market(1, status="active", close_ts=now + 86_400, settle_ts=None)
    assert market_window(active, now)[1] == now - now % 60 - 60  # type: ignore[index]


def _kalshi(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/trade-api/v2")
    q = request.url.params
    if path == "/historical/cutoff":
        return httpx.Response(200, json={"market_settled_ts": "2026-08-01T00:00:00Z"})
    if path.startswith("/series/fee_changes"):
        return httpx.Response(200, json={"series_fee_change_arr": []})
    if path == "/events/fee_changes":
        return httpx.Response(200, json={"event_fee_changes": [], "cursor": ""})
    if path.startswith("/series/"):
        return httpx.Response(200, json={"series": {"ticker": path.split("/")[2], "fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1}})
    if path == "/milestones":
        return httpx.Response(
            200,
            json={
                "cursor": "",
                "milestones": [
                    {
                        "id": "m1",
                        "title": "AAA at BBB",
                        "start_date": "2026-09-20T17:00:00Z",
                        "details": {"league": "NFL", "main_game_event_ticker": "KXNFLGAME-26SEP20AAABBB", "season": {"week": 2, "type": "REG"}},
                    }
                ],
            },
        )
    if path == "/events":
        series = q["series_ticker"]
        event = f"{series}-26SEP20AAABBB"
        markets = [
            {
                "ticker": f"{event}-{side}",
                "event_ticker": event,
                "status": "finalized",
                "open_time": "2026-09-18T17:00:00Z",
                "close_time": "2026-09-20T20:00:00Z",
                "settlement_ts": "2026-09-20T20:05:00Z",
                "expected_expiration_time": "2026-09-20T20:00:00Z",
            }
            for side in ("AAA", "BBB")
        ]
        return httpx.Response(200, json={"cursor": "", "events": [{"event_ticker": event, "title": "AAA vs BBB", "markets": markets}]})
    if path == "/markets/candlesticks":
        start, end = int(q["start_ts"]), int(q["end_ts"])
        out = []
        for ticker in q["market_tickers"].split(","):
            candles = [
                {
                    "end_period_ts": ts,
                    "yes_bid": {"close_dollars": "0.4800"},
                    "yes_ask": {"close_dollars": "0.5000"},
                    "price": {},
                    "volume_fp": "1.00",
                    "open_interest_fp": "10.00",
                }
                for ts in range(start - start % 3600 + 3600, end + 1, 3600)
            ]
            out.append({"market_ticker": ticker, "candlesticks": candles})
        return httpx.Response(200, json={"markets": out})
    return httpx.Response(404, json={"error": "not mocked"})


async def test_backfill_is_incremental_and_feeds_the_cost_results(make_stack: Any, tmp_path: Path) -> None:
    stack = make_stack(_kalshi)
    store = NflStore(tmp_path / "task3")
    fetcher = Fetcher(stack.client, store)
    hooks = Hooks(log=lambda m, level="info": None)

    summary = await refresh_inventory(fetcher, store, date(2026, 9, 14), ["KXNFLGAME", "KXNFLSPREAD"], hooks)
    assert summary["games"] == 1 and summary["markets"] == 4 and summary["new_markets"] == 4
    game = store.games()[0]
    assert game["week"] == 2 and game["kickoff_source"] == "milestone"

    first = await backfill_candles(fetcher, store, hooks)
    assert first["requests"] > 0 and first["candles_added"] > 0
    assert first["markets_completed"] == 4
    batch_calls = [r for r in stack.sent if r.url.path.endswith("/markets/candlesticks")]
    assert all(len(r.url.params["market_tickers"].split(",")) == 2 for r in batch_calls)
    assert any((store.raw_dir / "candles").rglob("*.json.gz"))

    await refresh_inventory(fetcher, store, date(2026, 9, 14), ["KXNFLGAME", "KXNFLSPREAD"], hooks)
    assert estimate_candle_requests(store) == 0
    sent_before = len(stack.sent)
    second = await backfill_candles(fetcher, store, hooks)
    assert second["requests"] == 0 and len(stack.sent) == sent_before

    result = run_analysis(store, AnalysisParams())
    by_type = {(r["checkpoint"], r["size"], r["market_type"]): r for r in result["results"]["by_market_type"]}
    row = by_type[("1h", 10, "Game winner")]
    assert row["n"] == 4  # two markets x yes/no
    assert result["quality"]["totals"]["bid_above_ask"] == 0
    assert result["quality"]["missing_candles_total"] == 0
    assert (store.root / "exports" / "checkpoint_costs.csv").is_file()
