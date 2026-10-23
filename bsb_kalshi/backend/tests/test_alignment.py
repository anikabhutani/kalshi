"""Alignment pipeline and trade sizes: a clean run passes, and each kind of error is caught."""

from __future__ import annotations

import asyncio
import json
import sqlite3

import numpy as np
import pandas as pd
import pytest

from app.alignment import pipeline as pl
from app.alignment import trade_sizes as ts
from app.alignment.checks import run_checks
from app.task3.store import NflStore

COLS = ["snapshot_ts", "snapshot_type", "sport", "event_id", "commence_time", "home_team", "away_team",
        "bookmaker", "book_last_update", "market", "market_last_update", "outcome", "point",
        "price_american", "price_decimal", "implied_prob"]

# (game_id, away, home, scheduled kickoff UTC, final kickoff UTC, home win prob)
GAMES = [
    ("g26a", "San Francisco 49ers", "Los Angeles Rams", "2026-09-11T00:20:00Z", "2026-09-11T00:20:00Z", 0.55),  # Thu night: ET Sept 10
    ("g26b", "Cleveland Browns", "Jacksonville Jaguars", "2026-09-13T17:00:00Z", "2026-09-13T17:00:00Z", 0.70),
    ("g26c", "Minnesota Vikings", "Chicago Bears", "2026-09-20T17:00:00Z", "2026-09-20T17:02:38Z", 0.66),  # starts late
    ("g25a", "Buffalo Bills", "New York Jets", "2025-09-14T17:00:00Z", "2025-09-14T17:00:00Z", 0.25),
    ("g25b", "Kansas City Chiefs", "Philadelphia Eagles", "2025-09-14T20:25:00Z", "2025-09-14T20:25:00Z", 0.60),
]
CODE = {"San Francisco 49ers": "SF", "Los Angeles Rams": "LA", "Cleveland Browns": "CLE",
        "Jacksonville Jaguars": "JAC", "Minnesota Vikings": "MIN", "Chicago Bears": "CHI",
        "Buffalo Bills": "BUF", "New York Jets": "NYJ", "Kansas City Chiefs": "KC", "Philadelphia Eagles": "PHI"}
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _american(p: float) -> int:
    a = round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)
    return a if abs(a) >= 100 else (100 if a > 0 else -100)


def make_snapshots(path) -> pd.DataFrame:
    rows = []
    for gid, away, home, sched, final, ph in GAMES:
        s, f = pd.Timestamp(sched), pd.Timestamp(final)
        for when, listed, p in ((s - pd.Timedelta(days=2), s, ph), (s - pd.Timedelta(hours=26), s, ph),
                                (s - pd.Timedelta(minutes=10), s, ph),
                                (f + pd.Timedelta(minutes=90), f, 1 - ph)):  # in-game: the price flips
            for book, m in (("DraftKings", 0.045), ("FanDuel", 0.04), ("Pinnacle", 0.025)):
                for team, q in ((home, p), (away, 1 - p)):
                    a = _american(q + m / 2)
                    rows.append(dict(snapshot_ts=when.strftime("%Y-%m-%dT%H:%M:%SZ"), snapshot_type="daily",
                                     sport="americanfootball_nfl", event_id=gid,
                                     commence_time=listed.strftime("%Y-%m-%dT%H:%M:%SZ"), home_team=home,
                                     away_team=away, bookmaker=book, book_last_update="", market="h2h",
                                     market_last_update="", outcome=team, point="", price_american=str(a),
                                     price_decimal="", implied_prob=""))
    df = pd.DataFrame(rows, columns=COLS)
    df.to_csv(path, index=False, compression="gzip")
    return df


def make_store(root, codes: dict[str, str] | None = None, ticker_shift_days: int = 0) -> NflStore:
    """Kalshi events in Task 3's format; candles every minute from 26 h before to 10 min after kickoff."""
    codes = codes or CODE
    store = NflStore(root)
    for gid, away, home, sched, final, ph in GAMES:
        f = pd.Timestamp(final)
        d = (pd.Timestamp(sched).tz_convert("America/New_York") + pd.Timedelta(days=ticker_shift_days))
        a, h = codes[away], codes[home]
        ev = f"KXNFLGAME-{d:%y}{MON[d.month - 1]}{d:%d}{a}{h}"
        store.upsert_markets([{"ticker": f"{ev}-{c}", "event_ticker": ev, "series_ticker": "KXNFLGAME",
                               "market_type": "Game winner"} for c in (a, h)])
        ids = {r["ticker"]: r["id"] for r in store.markets("event_ticker = ?", (ev,))}
        kick = int(f.timestamp())
        t = np.arange(kick - 26 * 3600, kick + 600, 60)
        t = t[(t % 600) != 0]  # some quiet minutes
        for code, p in ((h, ph), (a, 1 - ph)):
            b = int(round(p * 100 - 0.5))
            store.save_candles(ids[f"{ev}-{code}"], [(int(x), b * 100, (b + 1) * 100, None, 1.0, 1.0) for x in t],
                               int(t[-1]), "test")
    return store


@pytest.fixture
def env(tmp_path):
    snaps_path = tmp_path / "snapshots.csv.gz"
    make_snapshots(snaps_path)
    make_store(tmp_path / "task3")
    return tmp_path, snaps_path, tmp_path / "task3" / "nfl_costs.db"


def _run_parts(snaps_path, db, season):
    snaps = pl.load_sportsbook(snaps_path)
    games = pl.game_list(snaps, season)
    markets = pl.load_kalshi_markets(db)
    events = pl.kalshi_events(markets)
    events = events.loc[np.array([d is not None and pl._season_of(d) == season for d in events["ticker_date"]], bool)]
    cw, left = pl.crosswalk(games, events)
    ids = pd.concat([cw["kalshi_market_id_home"], cw["kalshi_market_id_away"]]).dropna().astype(int).tolist()
    candles = pl.load_candles(ids, db)
    snap = pl.snapshots(cw, snaps, candles)
    costs = pl.compute_costs(snap, season, db.parent / "no_trade_sizes_here")
    return dict(season=season, games=games, events=events, cw=cw, leftover=left, snap=snap, candles=candles,
                snaps=snaps, costs=costs, kalshi_present=not markets.empty)


def _status(parts) -> dict[str, str]:
    return {c["id"]: c["status"] for c in run_checks(**parts)}


def test_clean_run_both_seasons(env):
    tmp, snaps_path, db = env
    for season, n in ((2026, 3), (2025, 2)):
        code = pl.run(season, sportsbook=snaps_path, db=db, out_dir=tmp / "out")
        assert code == 0
        cw = pd.read_csv(tmp / "out" / str(season) / "crosswalk.csv")
        assert len(cw) == n and (cw["status"] == "matched").all()
        checks = json.loads((tmp / "out" / str(season) / "checks.json").read_text())
        assert not [c for c in checks if c["status"] == "fail"], checks
        snap = pd.read_csv(tmp / "out" / str(season) / "snapshots.csv")
        assert len(snap) == n * 2 * 5 * 4


def test_final_kickoff_and_eastern_dates(env):
    tmp, snaps_path, db = env
    p = _run_parts(snaps_path, db, 2026)
    g = p["games"].set_index("game_id")
    assert g.loc["g26c", "kickoff_utc"] == pd.Timestamp("2026-09-20T17:02:38Z")  # provider's final start time
    assert g.loc["g26c", "kickoff_moved_min"] == pytest.approx(2.6, abs=0.1)
    cw = p["cw"].set_index("game_id")
    assert cw.loc["g26a", "kalshi_event_ticker"] == "KXNFLGAME-26SEP10SFLA"  # Thursday night: Eastern date
    assert cw.loc["g26a", "date_diff_days"] == 0


def test_snapshot_is_latest_at_or_before_and_age_is_right(env):
    tmp, snaps_path, db = env
    s = _run_parts(snaps_path, db, 2026)["snap"]
    row = s[(s["game_id"] == "g26c") & (s["side"] == "home") & (s["checkpoint"] == "15m") & (s["source"] == "Kalshi")].iloc[0]
    cp = pd.Timestamp("2026-09-20T17:02:38Z") - pd.Timedelta(minutes=15)
    assert pd.Timestamp(row["checkpoint_utc"]) == cp
    assert pd.Timestamp(row["price_ts_utc"]) <= cp and row["age_s"] == (cp - pd.Timestamp(row["price_ts_utc"])).total_seconds()
    assert row["age_s"] < 60  # a candle in the last minute
    book = s[(s["game_id"] == "g26c") & (s["side"] == "home") & (s["checkpoint"] == "close") & (s["source"] == "Pinnacle")].iloc[0]
    # the in-game snapshot (after kickoff) must not be used; the 10-minutes-before one is
    assert pd.Timestamp(book["price_ts_utc"]) == pd.Timestamp("2026-09-20T16:50:00Z")
    assert book["book_price_american"] < 0  # Chicago favoured before kickoff (the in-game price flipped)


def test_catches_the_1970_timestamp_bug(env, monkeypatch):
    """pandas 3 stores microseconds; dividing by 10**9 puts every checkpoint in 1970."""
    tmp, snaps_path, db = env
    monkeypatch.setattr(pl, "epoch_seconds", lambda t: (t.astype("int64") // 10**9).astype("int64"))
    s = _status(_run_parts(snaps_path, db, 2026))
    assert s["no_lookahead"] == "fail" and s["asof_recompute"] == "fail" and s["complete_grid"] == "fail"


def test_catches_markets_filed_under_the_wrong_team(env):
    tmp, snaps_path, db = env
    with sqlite3.connect(db) as conn:  # swap the prices of Chicago's and Minnesota's markets
        ids = dict(conn.execute("SELECT ticker, id FROM markets WHERE event_ticker LIKE '%MINCHI'").fetchall())
        chi, mn = ids["KXNFLGAME-26SEP20MINCHI-CHI"], ids["KXNFLGAME-26SEP20MINCHI-MIN"]
        conn.execute("UPDATE candles SET market_id = -1 WHERE market_id = ?", (chi,))
        conn.execute("UPDATE candles SET market_id = ? WHERE market_id = ?", (chi, mn))
        conn.execute("UPDATE candles SET market_id = ? WHERE market_id = -1", (mn,))
    assert _status(_run_parts(snaps_path, db, 2026))["team_alignment"] == "fail"


def test_catches_look_ahead_and_wrong_prices(env):
    tmp, snaps_path, db = env
    p = _run_parts(snaps_path, db, 2026)
    k = p["snap"].index[(p["snap"]["source"] == "Kalshi")][0]
    p2 = {**p, "snap": p["snap"].copy()}
    p2["snap"].loc[k, "price_ts_utc"] = pd.Timestamp(p2["snap"].loc[k, "checkpoint_utc"]) + pd.Timedelta(minutes=1)
    assert _status(p2)["no_lookahead"] == "fail"
    p3 = {**p, "snap": p["snap"].copy()}
    p3["snap"].loc[k, "kalshi_bid"] += 0.05
    assert _status(p3)["asof_recompute"] == "fail"


def test_catches_market_ticker_not_matching_team(env):
    tmp, snaps_path, db = env
    p = _run_parts(snaps_path, db, 2026)
    cw = p["cw"].copy()
    i = cw.index[cw["status"] == "matched"][0]
    cw.loc[i, ["kalshi_ticker_home", "kalshi_ticker_away"]] = cw.loc[i, ["kalshi_ticker_away", "kalshi_ticker_home"]].to_numpy()
    assert _status({**p, "cw": cw})["one_to_one"] == "fail"


def test_unknown_team_code_gets_reason_not_a_guess(tmp_path):
    snaps_path = tmp_path / "s.csv.gz"
    make_snapshots(snaps_path)
    make_store(tmp_path / "t3", codes={**CODE, "Jacksonville Jaguars": "JAG"})
    p = _run_parts(snaps_path, tmp_path / "t3" / "nfl_costs.db", 2026)
    cw = p["cw"].set_index("game_id")
    assert cw.loc["g26b", "reason_code"] == "unknown_team_code" and cw.loc["g26b", "status"] == "unmatched"
    s = _status(p)
    assert s["unknown_codes"] == "warn" and s["every_game_accounted"] == "warn"


def test_ticker_a_day_off_is_matched_and_flagged(tmp_path):
    snaps_path = tmp_path / "s.csv.gz"
    make_snapshots(snaps_path)
    make_store(tmp_path / "t3", ticker_shift_days=1)
    p = _run_parts(snaps_path, tmp_path / "t3" / "nfl_costs.db", 2026)
    assert (p["cw"]["status"] == "matched").all()
    assert _status(p)["ticker_dates"] == "warn"


def test_no_kalshi_data_is_reported_not_failed(tmp_path):
    snaps_path = tmp_path / "s.csv.gz"
    make_snapshots(snaps_path)
    code = pl.run(2026, sportsbook=snaps_path, db=tmp_path / "missing.db", out_dir=tmp_path / "out")
    assert code == 0
    cw = pd.read_csv(tmp_path / "out" / "2026" / "crosswalk.csv")
    assert set(cw["reason_code"]) == {"no_kalshi_data"}


def test_team_table():
    from app.alignment import teams

    assert teams.table_problems() == []
    assert teams.team_name("JAX") == teams.team_name("JAC") == "Jacksonville Jaguars"
    assert teams.team_name("LA") == teams.team_name("LAR") == "Los Angeles Rams"
    assert teams.team_name("LAC") == "Los Angeles Chargers"
    assert teams.team_name("ZZZ") is None


# --------------------------------------------------------------------------------------
# Trade sizes
# --------------------------------------------------------------------------------------


def _fake_getter(trades_live: dict, trades_hist: dict, page: int = 2):
    calls = []

    async def get(path, params):
        calls.append((path, dict(params)))
        src = trades_live if path == "/markets/trades" else trades_hist
        data = src.get(params["ticker"], [])
        start = int(params.get("cursor") or 0)
        chunk = data[start:start + page]
        nxt = start + page
        return {"trades": chunk, "cursor": str(nxt) if nxt < len(data) else ""}
    return get, calls


def _trade(i, ticker, n, block=False):
    return {"trade_id": f"t{i}", "ticker": ticker, "count_fp": f"{n:.2f}", "yes_price_dollars": "0.5000",
            "created_time": "2026-09-20T16:00:00Z", "is_block_trade": block, "taker_outcome_side": "yes"}


def test_trade_pull_pages_merges_and_dedupes(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "PAGE", 2)
    tk = "KXNFLGAME-26SEP20MINCHI-CHI"
    live = {tk: [_trade(i, tk, n) for i, n in enumerate([1, 1, 2])]}
    hist = {tk: [_trade(2, tk, 2), _trade(3, tk, 3), _trade(4, tk, 10, block=True)]}  # t2 in both
    get, calls = _fake_getter(live, hist)
    df, info = asyncio.run(ts.pull_market(get, tk))
    assert sorted(df["trade_id"]) == ["t0", "t1", "t2", "t3", "t4"] and info["duplicates_merged"] == 1
    assert info["pages"] == 4 and not info["truncated"]


def test_trade_percentiles_and_checks(tmp_path):
    tk = "KXNFLGAME-26SEP20MINCHI-CHI"
    markets = pd.DataFrame({"ticker": [tk], "series": ["KXNFLGAME"], "game_date": [None], "status": ["settled"]})
    live = {tk: [_trade(i, tk, n) for i, n in enumerate([1, 1, 2, 3])] + [_trade(4, tk, 10, block=True)]}
    get, _ = _fake_getter(live, {})
    asyncio.run(ts.pull_season(get, markets, 2026, out=tmp_path))
    assert ts.report(2026, markets, out=tmp_path) == 0
    r = json.loads((tmp_path / "trade_sizes_2026.json").read_text())
    inc = r["stats"]["all NFL markets"]["including block trades"]
    # sizes 1,1,2,3,10: real-value percentiles
    assert inc["per_trade"] == {"p50": 2.0, "p75": 3.0, "p90": 10.0}
    # by contract: cumulative contracts 1,2,4,7,17 of 17 -> the median contract sits in the 10-lot
    assert inc["per_contract"]["p50"] == 10.0
    exc = r["stats"]["all NFL markets"]["excluding block trades"]
    assert exc["trades"] == 4 and exc["per_trade"]["p90"] == 3.0
    assert {c["id"]: c["status"] for c in r["checks"]}["percentiles_recomputed"] == "pass"


def test_truncated_market_fails_and_resume_skips_done(tmp_path, monkeypatch):
    tk1, tk2 = "KXNFLGAME-26SEP20MINCHI-CHI", "KXNFLGAME-26SEP20MINCHI-MIN"
    markets = pd.DataFrame({"ticker": [tk1, tk2], "series": ["KXNFLGAME"] * 2, "game_date": [None] * 2,
                            "status": ["settled"] * 2})
    monkeypatch.setattr(ts, "PAGE", 1)
    monkeypatch.setattr(ts, "SAFETY_PAGES", 2)
    live = {tk1: [_trade(i, tk1, 1) for i in range(5)], tk2: [_trade(9, tk2, 4)]}
    get, calls = _fake_getter(live, {}, page=1)
    asyncio.run(ts.pull_season(get, markets, 2026, out=tmp_path))
    assert ts.report(2026, markets, out=tmp_path) == 1  # tk1 truncated: the check fails
    n = len(calls)
    asyncio.run(ts.pull_season(get, markets, 2026, out=tmp_path))
    assert all(c[1]["ticker"] == tk1 for c in calls[n:])  # tk2 was done; only tk1 is pulled again


def test_season_market_selection(tmp_path):
    store = NflStore(tmp_path)
    store.upsert_markets([
        {"ticker": "KXNFLGAME-26SEP20MINCHI-CHI", "event_ticker": "KXNFLGAME-26SEP20MINCHI"},
        {"ticker": "KXNFLSPREAD-26SEP20MINCHI-CHI3", "event_ticker": "KXNFLSPREAD-26SEP20MINCHI"},
        {"ticker": "KXNFLGAME-26JAN11BUFJAC-BUF", "event_ticker": "KXNFLGAME-26JAN11BUFJAC"},  # 2025 playoffs
        {"ticker": "KXNFLGAME-26OCT25MINCHI-CHI", "event_ticker": "KXNFLGAME-26OCT25MINCHI"},  # not played yet
    ])
    from datetime import date

    m26 = ts.season_markets(2026, db=tmp_path / "nfl_costs.db", today=date(2026, 10, 21))
    m25 = ts.season_markets(2025, db=tmp_path / "nfl_costs.db", today=date(2026, 10, 21))
    assert set(m26["ticker"]) == {"KXNFLGAME-26SEP20MINCHI-CHI", "KXNFLSPREAD-26SEP20MINCHI-CHI3"}
    assert set(m25["ticker"]) == {"KXNFLGAME-26JAN11BUFJAC-BUF"}


def test_trade_endpoints_exist_in_the_spec(spec):
    assert spec.match_get("/markets/trades") is not None
    assert spec.match_get("/historical/trades") is not None


async def test_trade_pull_through_the_real_client(make_stack, tmp_path):
    """The real Kalshi client against a fake server: paths, paging params, 404s, and a 429 stop."""
    import httpx

    from app.errors import RateLimited

    tk1, tk2 = "KXNFLGAME-26SEP20MINCHI-CHI", "KXNFLGAME-26SEP20MINCHI-MIN"
    pages = {"/trade-api/v2/markets/trades": {tk1: [[_trade(1, tk1, 5), _trade(2, tk1, 7)], [_trade(3, tk1, 1)]]}}

    def handler(request: httpx.Request) -> httpx.Response:
        q = dict(request.url.params)
        if q.get("ticker") == tk2:
            return httpx.Response(429, json={"error": "rate limited"})
        if request.url.path.endswith("/historical/trades"):
            return httpx.Response(404, json={"error": "not found"})
        chunks = pages["/trade-api/v2/markets/trades"][q["ticker"]]
        i = int(q.get("cursor") or 0)
        return httpx.Response(200, json={"trades": chunks[i], "cursor": str(i + 1) if i + 1 < len(chunks) else ""})

    stack = make_stack(handler)
    markets = pd.DataFrame({"ticker": [tk1, tk2], "series": ["KXNFLGAME"] * 2, "game_date": [None] * 2,
                            "status": ["settled"] * 2})
    with pytest.raises(RateLimited):
        await ts.pull_season(ts.client_getter(stack.client), markets, 2026, out=tmp_path)
    sent = [(r.url.path, dict(r.url.params)) for r in stack.sent]
    assert sent[0][0].endswith("/markets/trades") and sent[0][1]["ticker"] == tk1 and sent[0][1]["limit"] == "1000"
    assert sent[1][1].get("cursor") == "1"
    assert any(p.endswith("/historical/trades") for p, _ in sent)
    prog = json.loads((tmp_path / "trades" / "2026" / "_progress.json").read_text())
    assert prog["markets"][tk1]["done"] and prog["markets"][tk1]["trades"] == 3  # saved before the 429
    assert tk2 not in prog["markets"]


def test_codes_match_the_teams_kalshi_table():
    """Kalshi's own codes (from the team's matching work) are the canonical ones here."""
    from app.alignment import teams

    kalshi = {"Arizona Cardinals": "ARI", "Jacksonville Jaguars": "JAC", "Los Angeles Rams": "LAR",
              "Los Angeles Chargers": "LAC", "Las Vegas Raiders": "LV", "New Orleans Saints": "NO",
              "Washington Commanders": "WAS", "Green Bay Packers": "GB", "Kansas City Chiefs": "KC",
              "New England Patriots": "NE", "San Francisco 49ers": "SF", "Tampa Bay Buccaneers": "TB"}
    assert {n: teams.NAME_TO_CODE[n] for n in kalshi} == kalshi


# ---------------------------------------------------------------- step 4: costs


def test_costs_clean_and_hand_checked(env):
    """One cost worked out by hand, and every cost check passes on clean data."""
    from app.alignment import costs as cm

    tmp, snaps_path, db = env
    p = _run_parts(snaps_path, db, 2026)
    st = _status(p)
    for cid in ("cost_grid", "ruler_sums", "cost_recompute", "own_margin_positive", "fee_rounding",
                "n_assignment", "freshness_rule"):
        assert st[cid] == "pass", (cid, [c for c in run_checks(**p) if c["id"] == cid])
    assert st["n_values"] == "warn"  # placeholder sizes until trade sizes exist
    c = p["costs"]
    # g26b Jaguars at the 24h checkpoint, Kalshi at n=10 against Kalshi's own ruler.
    # Candles: Jaguars bid 0.70 ask 0.71, Browns bid 0.30 ask 0.31.
    # Price: min(Jaguars YES ask 0.71, Browns NO = 1 - 0.30 = 0.70) = 0.70 via the Browns market;
    # fee = ceil(0.07*10*0.7*0.3 = $0.147) = $0.15 -> 0.015/contract, so 0.715 paid.
    # Fair: mids 0.705 and 0.305 -> 0.705/1.01. Cost = 10*(1 - 0.69802/0.715) = $0.2375.
    r = c[(c.game_id == "g26b") & (c.team == "Jacksonville Jaguars") & (c.checkpoint == "24h")
          & (c.venue == "Kalshi") & (c.ruler == "A_Kalshi") & (c.n == 10)].iloc[0]
    assert r.kalshi_price == pytest.approx(0.70) and r.fee_per_contract == pytest.approx(0.015)
    assert r.kalshi_route == "no_opponent_market"
    assert r.cost_per_10 == pytest.approx(10 * (1 - (0.705 / 1.01) / 0.715))
    # fee rounding makes 1 contract dearer per contract than 100
    k = c[(c.game_id == "g26b") & (c.team == "Jacksonville Jaguars") & (c.checkpoint == "24h")
          & (c.venue == "Kalshi") & (c.ruler == "A_Kalshi")].set_index("n")
    assert k.loc[1, "fee_per_contract"] == pytest.approx(0.02) and k.loc[100, "fee_per_contract"] == pytest.approx(0.0147)
    # the 15m sportsbook snapshot is 10 min before a game that started 2.6 min late -> 12.6 min old: not usable
    late = c[(c.game_id == "g26c") & (c.checkpoint == "15m") & (c.venue == "Pinnacle")]
    assert not late["usable"].any() and late["unusable_reason"].str.contains("min old").all()
    # costs.csv written by the full run, and the summary has the table
    assert pl.run(2026, sportsbook=snaps_path, db=db, out_dir=tmp / "out") == 0
    assert (tmp / "out" / "2026" / "costs.csv").exists()
    assert "Median cost per $10" in (tmp / "out" / "2026" / "summary.md").read_text()
    cm.table(c)  # builds


def test_cost_checks_catch_each_mistake(env, monkeypatch):
    from app.alignment import costs as cm

    tmp, snaps_path, db = env
    p = _run_parts(snaps_path, db, 2026)

    def broken(**changes):
        q = dict(p)
        q.update(changes)
        return _status(q)

    c = p["costs"]
    # fee rounded down instead of up
    monkeypatch.setattr(cm, "fee_dollars", lambda n, price: int(0.07 * n * price * (1 - price) * 100) / 100)
    st = broken(costs=pl.compute_costs(p["snap"], 2026, db.parent))
    assert st["cost_recompute"] == "fail" and st["fee_rounding"] == "fail"
    monkeypatch.undo()
    # proportional fair price swapped in for Shin
    bad = c.copy()
    m = bad["ruler"] != "A_Kalshi"
    bad.loc[m, "cost_per_10"] = bad.loc[m, "cost_per_10_proportional"]
    bad.loc[m, "fair"] = bad.loc[m, "fair_proportional"]
    assert broken(costs=bad)["cost_recompute"] == "fail"
    # a row dropped / duplicated
    assert broken(costs=c.iloc[1:])["cost_grid"] == "fail"
    assert broken(costs=pd.concat([c, c.iloc[:1]]))["cost_grid"] == "fail"
    # teams swapped under one ruler
    sw = c.copy()
    i = sw.index[(sw.ruler == "B_Pinnacle") & (sw.side == "home")]
    sw.loc[i, "fair"] = 1 - sw.loc[i, "fair"] + 0.05
    assert broken(costs=sw)["ruler_sums"] == "fail"
    # a stale price marked usable
    st_ = c.copy()
    st_.loc[st_["price_age_min"].notna(), "usable"] = True
    assert broken(costs=st_)["freshness_rule"] == "fail"
    # sportsbook rows repeated per n
    nn = c.copy()
    nn.loc[nn.venue == "Pinnacle", "n"] = 10
    assert broken(costs=nn)["n_assignment"] == "fail"
    # step skipped
    assert broken(costs=None)["costs"] == "fail"


def test_real_trade_sizes_are_used(env):
    from app.alignment import costs as cm

    tmp, snaps_path, db = env
    folder = tmp / "sizes"
    folder.mkdir()
    pt = {"p50": 12.0, "p75": 40.5, "p90": 150.0}
    (folder / "trade_sizes_2026.json").write_text(json.dumps(
        {"stats": {"all NFL markets": {"excluding block trades": {"per_trade": pt}}}}))
    n, src = cm.n_values(2026, folder)
    assert n == [("median", 12), ("p75", 41), ("p90", 150)] and src == "trade_sizes_2026.json"
    p = _run_parts(snaps_path, db, 2026)
    p["costs"] = pl.compute_costs(p["snap"], 2026, folder)
    st = _status(p)
    assert st["n_values"] == "pass" and st["cost_grid"] == "pass" and st["cost_recompute"] == "pass"
    assert set(p["costs"].loc[p["costs"].venue == "Kalshi", "n"]) == {12, 41, 150}
