"""In-game analysis: a clean synthetic season passes every check, numbers match hand calculations,
and each kind of mistake is caught."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from app.ingame import analysis as ig
from app.task3.store import NflStore

MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
CODES = ["ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB", "HOU", "IND",
         "JAC", "KC", "LV", "LAC", "LAR", "MIA", "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SF",
         "SEA", "TB", "TEN", "WAS"]
N_GAMES = 40


def _price(q: float, outcome: int, minute: float) -> float:
    """Pre-game price q; in-game it drifts linearly toward the result over three hours."""
    w = min(1.0, max(0.0, minute / 180))
    return float(np.clip(q + (outcome - q) * w, 0.03, 0.97))


def build(root, seed: int = 1, tie: bool = False, both_yes: bool = False):
    rng = np.random.default_rng(seed)
    store = NflStore(root / "task3")
    trades_dir = root / "trades"
    (trades_dir / "2026").mkdir(parents=True)
    base = pd.Timestamp("2026-09-13 17:00", tz="UTC")
    games, n_trades = [], 0
    for g in range(N_GAMES):
        kick = base + pd.Timedelta(days=7 * (g // 10)) + pd.Timedelta(hours=3 * (g % 3))
        d = kick.tz_convert("America/New_York")
        away, home = CODES[(2 * g) % 32], CODES[(2 * g + 1) % 32]
        ev = f"KXNFLGAME-{d:%y}{MON[d.month - 1]}{d:%d}{away}{home}"
        q = float(rng.uniform(0.2, 0.8))  # home win chance
        outcome = int(rng.random() < q)
        k = int(kick.timestamp())
        settle = k + 3 * 3600 + 900
        res_home, res_away = ("yes", "no") if outcome else ("no", "yes")
        if tie and g == 0:
            res_home = res_away = "scalar"
        if both_yes and g == 0:
            res_home = res_away = "yes"
        store.upsert_markets([
            {"ticker": f"{ev}-{home}", "event_ticker": ev, "series_ticker": "KXNFLGAME", "result": res_home, "settle_ts": settle},
            {"ticker": f"{ev}-{away}", "event_ticker": ev, "series_ticker": "KXNFLGAME", "result": res_away, "settle_ts": settle},
        ])
        store.upsert_games([{"game_key": ev[10:], "game_event_ticker": ev, "title": ev, "week": 1 + g // 10,
                             "season_type": "REG", "kickoff_ts": k, "kickoff_source": "milestone", "milestone_id": str(g)}])
        ids = {r["ticker"]: r["id"] for r in store.markets("event_ticker = ?", (ev,))}
        for code, qq, out in ((home, q, outcome), (away, 1 - q, 1 - outcome)):
            rows = []
            for m in range(-200, 186):
                p = _price(qq, out, m)
                rows.append((k + m * 60, round((p - 0.01) * 10_000), round((p + 0.01) * 10_000), None, 1.0, 1.0))
            store.save_candles(ids[f"{ev}-{code}"], rows, k + 186 * 60, "test")
            trows = []
            for i in range(30):
                m = float(rng.uniform(-150, 180))
                p = _price(qq, out, m)
                side = "yes" if rng.random() < 0.5 else "no"
                t = kick + pd.Timedelta(minutes=m)
                trows.append({"trade_id": f"{ev}-{code}-{i}", "ticker": f"{ev}-{code}",
                              "count": round(float(rng.uniform(0.5, 150)), 2), "yes_price": round(p, 2),
                              "created_time": t.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "is_block_trade": False,
                              "taker_outcome_side": side})
            pd.DataFrame(trows).to_csv(trades_dir / "2026" / f"{ev}-{code}.csv.gz", index=False, compression="gzip")
            n_trades += len(trows)
        games.append((ev, k, outcome))
    # one preseason market that must be ignored
    store.upsert_markets([{"ticker": "KXNFLGAME-26AUG20ARIATL-ARI", "event_ticker": "KXNFLGAME-26AUG20ARIATL",
                           "series_ticker": "KXNFLGAME", "result": "yes"}])
    align = root / "align"
    align.mkdir()
    (align / "trade_sizes_2026.json").write_text(json.dumps({"stats": {"KXNFLGAME": {
        "including block trades": {"trades": n_trades},
        "excluding block trades": {"trades": n_trades, "per_trade": {"p50": 24.0, "p75": 70.0, "p90": 200.0}}}}}))
    return dict(db=root / "task3" / "nfl_costs.db", trades_dir=trades_dir, align_dir=align, out_dir=root / "out"), games


@pytest.fixture
def season(tmp_path):
    paths, games = build(tmp_path)
    return paths, games


def _status(r) -> dict[str, str]:
    return {c["id"]: c["status"] for c in r["checks"]}


def test_clean_run(season):
    paths, games = season
    r = ig.analyze(2026, **paths)
    st = _status(r)
    assert not [c for c in r["checks"] if c["status"] == "fail"], r["checks"]
    for cid in ("trades_reconcile", "bins_complete", "fee_recompute", "no_trades_after_settle", "returns_identity",
                "kickoff_sources", "results_consistent", "no_lookahead", "quotes_valid", "calibration_sample"):
        assert st[cid] == "pass", (cid, r["checks"])
    assert r["games"] == N_GAMES  # preseason game left out
    t = r["trades"]
    assert sum(x["dollar_share"] for x in t["by_bin"]) == pytest.approx(1, abs=1e-4)
    assert sum(x["fee_share"] for x in t["by_phase_group"]) == pytest.approx(1, abs=1e-4)
    # prices converge on the result in-game, so accuracy improves (lower Brier)
    b = r["facts"]["brier"]
    assert b[180] < b[60] < b[-60]
    # the n used for costs comes from the trade sizes
    assert r["n_contracts"] == 24
    # files written
    assert (paths["out_dir"] / "2026" / "results.json").exists()
    assert json.loads((paths["out_dir"] / "index.json").read_text())["seasons"] == [2026]


def test_hand_checked_market():
    """Three trades worked out by hand."""
    t = pd.DataFrame({
        "count": [10.0, 1.0, 100.0], "yes_price": [0.70, 0.95, 0.30],
        "created_time": ["2026-09-13T16:00:00Z", "2026-09-13T18:00:00.5Z", "2026-09-13T19:00:00Z"],
        "taker_outcome_side": ["yes", "yes", "no"]})
    kick = pd.Timestamp("2026-09-13T17:00:00Z").timestamp()
    d = ig.process_market(t, kick, "yes", None)
    a = d["agg"]
    # trade 1: pre-game (last hour), p 0.70, fee ceil(0.147) = 0.15, wins
    # trade 2: 60 min in, p 0.95, fee ceil(0.003325) = 0.01, wins
    # trade 3: 120 min in, NO side so p = 0.70, fee ceil(1.47) = 1.47, loses (result yes)
    assert a["trades"].sum() == 3 and a["fee"].sum() == pytest.approx(0.15 + 0.01 + 1.47)
    assert a["dollars"].sum() == pytest.approx(7.0 + 0.95 + 70.0)
    assert a["won"].sum() == pytest.approx(10 + 1)
    assert sorted(a["bin"]) == [ig.BIN_LABELS.index("Last hour"), ig.BIN_LABELS.index("60–90 min"),
                                ig.BIN_LABELS.index("120–150 min")]
    assert list(d["inplay"]) == [False, True, True]
    assert ig.fee_dollars(np.array([10.0]), np.array([0.7]))[0] == pytest.approx(0.15)
    assert ig.fee_dollars(np.array([100.0]), np.array([0.5]))[0] == pytest.approx(1.75)  # exact, not 1.76
    # the real trade that broke float arithmetic: exactly $411.60, not $411.61
    assert ig.fee_dollars(np.array([28000.0]), np.array([0.7]))[0] == pytest.approx(411.60)
    assert ig.fee_dollars(np.array([1.0]), np.array([0.9999]))[0] == pytest.approx(0.01)  # never below a cent


def test_catches_missing_and_double_counted_trades(tmp_path):
    paths, _ = build(tmp_path)
    j = json.loads((paths["align_dir"] / "trade_sizes_2026.json").read_text())
    j["stats"]["KXNFLGAME"]["including block trades"]["trades"] += 7
    (paths["align_dir"] / "trade_sizes_2026.json").write_text(json.dumps(j))
    assert _status(ig.analyze(2026, **paths))["trades_reconcile"] == "fail"


def test_catches_wrong_results_and_lists_ties(tmp_path):
    paths, _ = build(tmp_path / "a", both_yes=True)
    assert _status(ig.analyze(2026, **paths))["results_consistent"] == "fail"
    paths, games = build(tmp_path / "b", tie=True)
    r = ig.analyze(2026, **paths)
    c = next(c for c in r["checks"] if c["id"] == "results_consistent")
    assert c["status"] == "pass" and games[0][0] in c["detail"]
    assert r["calibration"]["by_checkpoint"][0]["games"] == N_GAMES - 1


def test_catches_rounded_down_fees(season, monkeypatch):
    paths, _ = season
    monkeypatch.setattr(ig, "fee_dollars", lambda c, p: np.floor(0.07 * c * p * (1 - p) * 100) / 100)
    assert _status(ig.analyze(2026, **paths))["fee_recompute"] == "fail"


def test_catches_look_ahead_and_crossed_quotes(season):
    paths, _ = season
    markets = ig.load_markets(2026, paths["db"], paths["align_dir"])
    grid = ig.candle_grid(markets, paths["db"])
    cal = ig.calibration(grid, markets)
    bad = grid.copy()
    bad.loc[bad.index[:3], "age_min"] = -5
    bad.loc[bad.index[3:5], ["bid", "ask"]] = [[0.6, 0.5], [0.6, 0.5]]
    st = {c["id"]: c["status"] for c in ig.run_checks(2026, markets, {}, None, bad, cal, paths["align_dir"])}
    assert st["no_lookahead"] == "fail" and st["quotes_valid"] == "fail"


def test_kickoff_problems(season):
    paths, _ = season
    markets = ig.load_markets(2026, paths["db"], paths["align_dir"])
    cal = {"games_by_checkpoint": {}}
    m = markets.copy()
    m.loc[0, "kickoff_source"] = "none"
    st = {c["id"]: c["status"] for c in ig.run_checks(2026, m, {}, None, pd.DataFrame(), cal, paths["align_dir"])}
    assert st["kickoff_sources"] == "fail"
    m = markets.copy()
    m["kickoff_sportsbook"] = m["kickoff_milestone"] + 3600  # sportsbook feed an hour off
    st = {c["id"]: c["status"] for c in ig.run_checks(2026, m, {}, None, pd.DataFrame(), cal, paths["align_dir"])}
    assert st["kickoff_sources"] == "warn"


def test_taker_returns_against_direct_sum(season):
    """Bucket results equal a plain per-trade calculation, and the interval contains the estimate."""
    paths, _ = season
    r = ig.analyze(2026, **paths)
    tot_win = tot_paid = tot_fee = 0.0
    markets = ig.load_markets(2026, paths["db"], paths["align_dir"]).set_index("ticker")
    for f in (paths["trades_dir"] / "2026").glob("*.csv.gz"):
        t = pd.read_csv(f)
        res = markets.loc[t["ticker"].iat[0], "result"]
        for row in t.itertuples():
            p = row.yes_price if row.taker_outcome_side == "yes" else 1 - row.yes_price
            tot_paid += row.count * p
            tot_win += row.count * (row.taker_outcome_side == res)
            tot_fee += float(ig.fee_dollars(np.array([row.count]), np.array([p]))[0])
    direct = 10 * (tot_win - tot_paid - tot_fee) / tot_paid
    rows = r["trades"]["returns_by_phase"]
    via = sum(x["after_fees"] * x["dollars"] for x in rows) / sum(x["dollars"] for x in rows)
    assert via == pytest.approx(direct, abs=1e-3)
    for x in rows:
        assert x["after_lo"] <= x["after_fees"] <= x["after_hi"]


def test_logistic_fit_recovers_slope():
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1.5, 20_000)
    y = (rng.random(20_000) < 1 / (1 + np.exp(-(0.2 + 0.7 * x)))).astype(float)
    a, b = ig.logistic_fit(x, y)
    assert a == pytest.approx(0.2, abs=0.05) and b == pytest.approx(0.7, abs=0.05)


def test_api_reads_results(season, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.modules import ingame as mod

    paths, _ = season
    monkeypatch.setattr(mod, "OUT_DIR", paths["out_dir"])
    app = FastAPI()
    app.include_router(mod.router)
    with TestClient(app) as client:
        assert client.get("/api/ingame/results").json() is None
        ig.analyze(2026, **paths)
        body = client.get("/api/ingame/results").json()
        assert [s["season"] for s in body["seasons"]] == [2026]
        assert body["seasons"][0]["facts"]["has_trades"] is True
        json.dumps(body, allow_nan=False)  # valid JSON for the browser: no NaN anywhere
