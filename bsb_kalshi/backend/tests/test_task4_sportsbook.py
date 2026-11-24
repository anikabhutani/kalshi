"""Task 4: sportsbook backfill, cost per $10 and quality check."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.task4 import sportsbook_backfill as bf
from app.task4.sportsbook_costs import closing_lines, compute

COLS = ["snapshot_ts", "snapshot_type", "sport", "event_id", "commence_time", "home_team",
        "away_team", "bookmaker", "book_last_update", "market", "market_last_update", "outcome",
        "point", "price_american", "price_decimal", "implied_prob"]


def _prob(a: float) -> float:
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def _dec(a: float) -> float:
    return 1 + a / 100 if a > 0 else 1 + 100 / -a


def rows(event: str, snap: str, kick: str, book: str, market: str, a: float, b: float,
         point: float | None = None) -> list[dict]:
    home, away = "Home Team", "Away Team"
    if market == "totals":
        outs = [("Over", point), ("Under", point)]
    else:
        outs = [(home, point), (away, -point if point is not None else None)]
    out = []
    for (name, pt), price in zip(outs, (a, b)):
        out.append(dict(
            snapshot_ts=snap, snapshot_type="daily", sport="americanfootball_nfl", event_id=event,
            commence_time=kick, home_team=home, away_team=away, bookmaker=book,
            book_last_update=snap, market=market, market_last_update=snap, outcome=name,
            point="" if pt is None else str(pt), price_american=str(int(price)),
            price_decimal=f"{_dec(price):.4f}", implied_prob=f"{_prob(price):.4f}",
        ))
    return out


KICK = "2026-09-13T17:00:00Z"


def sample() -> pd.DataFrame:
    r = []
    for snap in ("2026-09-11T16:00:00Z", "2026-09-13T16:50:00Z"):
        r += rows("g1", snap, KICK, "DraftKings", "h2h", -200, 170)
        r += rows("g1", snap, KICK, "FanDuel", "spreads", -110, -110, -3.5)
        r += rows("g1", snap, KICK, "DraftKings", "totals", -110, -110, 44.5)
    # Pinnacle only near kickoff -> one missing-Pinnacle issue at the earlier snapshot
    r += rows("g1", "2026-09-13T16:50:00Z", KICK, "Pinnacle", "h2h", -190, 175)
    # a live line after kickoff
    r += rows("g1", "2026-09-13T17:30:00Z", KICK, "DraftKings", "h2h", -400, 300)
    return pd.DataFrame(r, columns=COLS)


def test_cost_per_10_standard_line():
    r = compute(sample())
    m = r["markets"]
    tot = m[(m["market"] == "totals")].iloc[0]
    # -110/-110: overround 0.0476, cost = 10 * (1 - 1/1.0476) = 0.4545
    assert tot["overround"] == pytest.approx(0.047619, abs=1e-5)
    assert tot["cost_per_10"] == pytest.approx(0.454545, abs=1e-5)


def test_closing_line_ignores_post_kickoff_snapshot():
    m = compute(sample())["markets"]
    close = closing_lines(m)
    dk = close[(close["bookmaker"] == "DraftKings") & (close["market"] == "h2h")].iloc[0]
    assert str(dk["snapshot_ts"]).startswith("2026-09-13 16:50")
    assert dk["price_american_a"] == -200


def test_cost_vs_pinnacle():
    s = compute(sample())["sides"]
    fav = s[(s["bookmaker"] == "DraftKings") & (s["market"] == "h2h") & (s["outcome"] == "Home Team")
            & (s["snapshot_ts"].astype(str).str.startswith("2026-09-13 16:50"))].iloc[0]
    from app.task4.sportsbook_costs import shin_two_way

    pa, pb = _prob(-190), _prob(175)
    fa, _, _ = shin_two_way([pa], [pb])
    assert fav["cost_vs_pinnacle_per_10"] == pytest.approx(10 * (1 - fa[0] * _dec(-200)), abs=1e-6)
    assert fav["cost_vs_pinnacle_proportional"] == pytest.approx(10 * (1 - pa / (pa + pb) * _dec(-200)), abs=1e-6)


def test_shin_charges_the_longshot_more():
    """The flaw the proportional method had: both sides of -400/+300 cost the same."""
    from app.task4.sportsbook_costs import shin_two_way

    pf, pl = _prob(-400), _prob(300)
    ff, fl, z = shin_two_way([pf], [pl])
    assert ff[0] + fl[0] == pytest.approx(1, abs=1e-12) and 0 < z[0] < 0.1
    fav_cost, long_cost = 10 * (1 - ff[0] / pf), 10 * (1 - fl[0] / pl)
    assert long_cost > 2 * fav_cost
    # a balanced -110/-110 market: Shin equals proportional, both sides cost 10 * (1 - 1/1.0476)
    fa, fb, _ = shin_two_way([_prob(-110)], [_prob(-110)])
    assert fa[0] == pytest.approx(0.5) and fb[0] == pytest.approx(0.5)


def test_quality_checks():
    df = sample()
    # corrupt one price into an invalid American value
    bad = (df["bookmaker"] == "DraftKings") & (df["market"] == "totals") & (df["outcome"] == "Over")
    df.loc[bad & df["snapshot_ts"].str.startswith("2026-09-11"), "price_american"] = "50"
    qc = compute(df)["qc"]
    checks = qc["check"].value_counts()
    assert checks["post_kickoff_snapshot_excluded"] == 1
    assert checks["bad_odds_invalid_american"] == 1
    assert checks["missing_pinnacle_line"] >= 1
    r = compute(df)
    assert r["markets"]["has_bad_odds"].sum() == 1


def test_backfill_is_incremental(tmp_path, monkeypatch):
    for name, value in {
        "DATA_DIR": tmp_path, "RAW_DIR": tmp_path / "raw", "MANIFEST": tmp_path / "manifest.json",
        "SNAPSHOTS": tmp_path / "snapshots.csv.gz", "GAMES": tmp_path / "games.csv",
    }.items():
        monkeypatch.setattr(bf, name, value)
    df = sample()
    future = pd.DataFrame(rows("g2", "2026-09-13T16:50:00Z", "2026-09-20T17:00:00Z",
                               "DraftKings", "h2h", -150, 130), columns=COLS)
    df = pd.concat([df, future], ignore_index=True)
    first = bf.backfill(df, "test", as_of=pd.Timestamp("2026-09-14T00:00:00Z").to_pydatetime())
    assert (first.played, first.saved_complete, first.not_played_yet) == (1, 1, 1)
    second = bf.backfill(df, "test", as_of=pd.Timestamp("2026-09-14T00:00:00Z").to_pydatetime())
    assert (second.skipped_complete, second.saved_complete) == (1, 0)
    games = pd.read_csv(tmp_path / "games.csv")
    assert list(games["event_id"]) == ["g1"]
    assert games.loc[0, "Pinnacle h2h"] == "yes" and games.loc[0, "Pinnacle spreads"] == "no"
    assert games.loc[0, "week"] == 1


def _patch_paths(monkeypatch, tmp_path):
    from app.modules import t4_sportsbook as mod
    from app.task4 import kalshi as kalshi_mod
    from app.task4 import sportsbook_report as rep

    paths = {
        "DATA_DIR": tmp_path, "RAW_DIR": tmp_path / "raw", "MANIFEST": tmp_path / "manifest.json",
        "SNAPSHOTS": tmp_path / "snapshots.csv.gz", "GAMES": tmp_path / "games.csv",
        "RESULTS_DIR": tmp_path / "results", "CHARTS_DIR": tmp_path / "charts",
    }
    for module in (bf, mod, rep):
        for name, value in paths.items():
            if hasattr(module, name):
                monkeypatch.setattr(module, name, value)
    monkeypatch.setattr(kalshi_mod, "KALSHI_EXPORTS", tmp_path / "no_task3")  # Kalshi absent
    return mod


def test_routes_run_and_results(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    mod = _patch_paths(monkeypatch, tmp_path)
    src = tmp_path / "history_americanfootball_nfl.csv"
    two_seasons().to_csv(src, index=False)

    app = FastAPI()
    app.include_router(mod.router)
    with TestClient(app) as c:
        assert c.get("/api/t4/results").json() is None
        assert c.post("/api/t4/run", json={}).status_code == 400  # no path yet
        assert c.post("/api/t4/run", json={"path": str(tmp_path / "missing.zip")}).status_code == 400
        run = c.post("/api/t4/run", json={"path": str(src)}).json()
        assert run["backfill"]["saved_complete"] == 8
        assert [s["season"] for s in run["seasons"]] == [2025, 2026]
        assert all(s["checks_failed"] == 0 for s in run["seasons"])
        again = c.post("/api/t4/run", json={}).json()  # reuses the last path, skips saved games
        assert again["backfill"]["skipped_complete"] == 8
        res = c.get("/api/t4/results").json()
        by = {s["season"]: s for s in res["seasons"]}
        assert set(by) == {2025, 2026}
        assert len(by[2025]["games"]) == 5 and len(by[2026]["games"]) == 3
        assert by[2025]["facts"]["games"] == 5 and by[2026]["facts"]["games"] == 3
        assert {r["bookmaker"] for r in by[2026]["by_book_market"]} >= {"DraftKings", "FanDuel"}
        assert all(c_["status"] != "fail" for s in res["seasons"] for c_ in s["checks"])
        assert c.get("/api/t4/state").json()["games_by_season"] == {"2025": 5, "2026": 3}
        assert c.get("/api/t4/exports/2025/by_week.csv").status_code == 200
        assert c.get("/api/t4/exports/2025/checks.json").status_code == 200
        assert c.get("/api/t4/exports/2024/by_week.csv").status_code == 404
        assert c.get("/api/t4/exports/2025/manifest.json").status_code == 404
        assert by[2025]["kalshi_info"]["available"] is False
    assert (tmp_path / "charts" / "2025" / "3_cost_by_week.png").exists()
    assert (tmp_path / "charts" / "2026" / "1_cost_by_book_market.png").exists()


def _task3_exports(path):
    """A tiny Task 3 export: one game, a game-winner pair and a 3-strike spread ladder."""
    from app.task3.costs import bet_costs

    path.mkdir(parents=True, exist_ok=True)
    quotes, costs = [], []
    ladder = [("KXNFLGAME-G1", "Game winner", "KXNFLGAME-G1-A", 30, 32),
              ("KXNFLGAME-G1", "Game winner", "KXNFLGAME-G1-B", 68, 70),
              ("KXNFLSPREAD-G1", "Spread", "KXNFLSPREAD-G1-3", 48, 50),
              ("KXNFLSPREAD-G1", "Spread", "KXNFLSPREAD-G1-7", 20, 22),
              ("KXNFLSPREAD-G1", "Spread", "KXNFLSPREAD-G1-10", 10, 12)]
    for ev, mtype, tk, bid, ask in ladder:
        for cp in ("24h", "15m"):
            quotes.append(dict(ticker=tk, event_ticker=ev, market_type=mtype, kickoff_utc=KICK,
                               checkpoint=cp, bid=bid / 100, ask=ask / 100, status="ok"))
            for row in bet_costs(bid * 100, ask * 100, 1.0, "cent"):
                costs.append(dict(ticker=tk, market_type=mtype, checkpoint=cp, **row))
    pd.DataFrame(quotes).to_csv(path / "checkpoint_quotes.csv", index=False)
    pd.DataFrame(costs).to_csv(path / "checkpoint_costs.csv", index=False)


def test_kalshi_main_line_and_tables(tmp_path):
    from app.task4 import kalshi as kalshi_mod
    from app.task4 import sportsbook_report as rep

    _task3_exports(tmp_path)
    k = kalshi_mod.load(tmp_path)
    close = k[k["main_line"] & (k["checkpoint"] == "15m")]
    # both game-winner markets kept; only the spread strike nearest 50c kept
    assert set(close.loc[close["market"] == "h2h", "ticker"]) == {"KXNFLGAME-G1-A", "KXNFLGAME-G1-B"}
    assert set(close.loc[close["market"] == "spreads", "ticker"]) == {"KXNFLSPREAD-G1-3"}
    assert set(k["checkpoint"]) == {"24h", "15m"} and (k["bookmaker"] == "Kalshi").all()
    # Yes at 50c ask, 10 contracts: half gap 1c x 10 + fee ceil(0.07*10*0.5*0.5 = 17.5c) = 28c on $5
    yes = close[(close["ticker"] == "KXNFLSPREAD-G1-3") & (close["side"] == "yes")].iloc[0]
    assert yes["cost_per_10"] == pytest.approx(10 * (10 * 0.01 + 0.18) / (10 * 0.50), abs=1e-6)

    t = rep.build_tables(compute(sample()), k)
    bm = t["by_book_market"]
    assert {"Kalshi", "DraftKings"} <= set(bm["bookmaker"])
    assert t["_kalshi_info"]["available"] and t["_kalshi_info"]["games_by_market"]["spreads"] == 1
    tk = t["by_time_to_kickoff"]
    assert set(tk.loc[tk["bookmaker"] == "Kalshi", "time_bucket"].astype(str)) == {"under 1 h", "1-24 h"}
    strikes = t["kalshi_all_strikes"].set_index(["market", "rows"])["mean"]
    assert strikes[("spreads", "every strike, Yes and No")] > strikes[("spreads", "main line only (used in charts)")]


def test_kalshi_missing_is_reported(tmp_path):
    from app.task4 import kalshi as kalshi_mod
    from app.task4 import sportsbook_report as rep

    assert kalshi_mod.load(tmp_path / "nothing") is None
    t = rep.build_tables(compute(sample()), None)
    assert t["_kalshi_info"]["available"] is False
    assert "Kalshi" not in set(t["by_book_market"]["bookmaker"])


# --------------------------------------------------------------------------------------
# Seasons and self-checks
# --------------------------------------------------------------------------------------


def _american(p: float) -> int:
    a = -100 * p / (1 - p) if p >= 0.5 else 100 * (1 - p) / p
    a = round(a)
    return a if abs(a) >= 100 else (100 if a > 0 else -100)


def two_seasons() -> pd.DataFrame:
    """5 games in 2025 (Sept 7) and 3 in 2026 (Sept 13), lopsided and even, 3 books x 3 bets.

    Margins lean on the longshot (as real books do), so a correct pipeline passes every check.
    """
    games = {"2025-09-07T17:00:00Z": [0.85, 0.7, 0.55, 0.3, 0.15], "2026-09-13T17:00:00Z": [0.8, 0.6, 0.2]}
    margin = {"DraftKings": 0.045, "FanDuel": 0.04, "Pinnacle": 0.025}
    rows = []
    for kick, probs in games.items():
        k = pd.Timestamp(kick)
        for i, p in enumerate(probs):
            ev = f"g{k.year}_{i}"
            home, away = f"Home {k.year}-{i}", f"Away {k.year}-{i}"
            # two days out, ten minutes out, and an in-game price 30 minutes after kickoff
            for snap in (k - pd.Timedelta(days=2), k - pd.Timedelta(minutes=10), k + pd.Timedelta(minutes=30)):
                s = snap.strftime("%Y-%m-%dT%H:%M:%SZ")
                for book, m in margin.items():
                    fav, dog = max(p, 1 - p), min(p, 1 - p)
                    imp_home = (fav + m * 0.3) if p >= 0.5 else (dog + m * 0.7)
                    imp_away = (dog + m * 0.7) if p >= 0.5 else (fav + m * 0.3)
                    juice = -110 if book != "Pinnacle" else -105
                    for market, sides in (
                        ("h2h", [(home, None, _american(imp_home)), (away, None, _american(imp_away))]),
                        ("spreads", [(home, -3.5, juice), (away, 3.5, juice)]),
                        ("totals", [("Over", 44.5, juice), ("Under", 44.5, juice)]),
                    ):
                        for name, pt, price in sides:
                            rows.append(dict(
                                snapshot_ts=s, snapshot_type="daily", sport="americanfootball_nfl", event_id=ev,
                                commence_time=kick, home_team=home, away_team=away, bookmaker=book,
                                book_last_update=s, market=market, market_last_update=s, outcome=name,
                                point="" if pt is None else str(pt), price_american=str(price),
                                price_decimal=f"{_dec(price):.4f}", implied_prob=f"{_prob(price):.4f}"))
    return pd.DataFrame(rows, columns=COLS)


def _season_bundle(season: int):
    """Everything run_checks needs for one season of ``two_seasons()``."""
    from app.task4 import sportsbook_report as rep

    df = two_seasons()
    r = compute(df)
    games = bf.build_games_table(df)
    manifest = {"games": {e: {"season": int(s), "status": "complete"}
                          for e, s in zip(games["event_id"], games["season"])}}
    rs = rep.split_season(r, season)
    t = rep.build_tables(rs, None)
    sg = games[games["season"] == season]
    facts = rep.build_facts(t, season, sg)
    return t, rs, facts, sg, manifest, r


def _status(season=2025, mutate=None):
    import copy

    from app.task4.checks import run_checks

    t, rs, facts, sg, manifest, r = _season_bundle(season)
    t = {k: (v.copy() if hasattr(v, "copy") else copy.deepcopy(v)) for k, v in t.items()}
    rs = {k: v.copy() for k, v in rs.items()}
    facts = copy.deepcopy(facts)
    if mutate:
        mutate(t, rs, facts)
    return {c["id"]: c["status"] for c in run_checks(season, t, rs, facts, sg, manifest, r)}


def test_week_and_season_labels():
    from app.task4.common import nfl_season, nfl_week, week_label

    k = pd.to_datetime(pd.Series([
        "2025-09-05T00:20:00Z",  # 2025 opener, Thursday night
        "2026-01-05T01:20:00Z",  # 2025 week 18
        "2026-01-11T21:30:00Z", "2026-01-18T20:00:00Z", "2026-01-25T23:30:00Z", "2026-02-08T23:30:00Z",
        "2026-09-10T00:15:00Z",  # 2026 opener, Wednesday night
        "2026-09-15T00:15:00Z",  # Monday night, still week 1
    ]), utc=True)
    w = nfl_week(k)
    assert nfl_season(k).tolist() == [2025] * 6 + [2026] * 2
    assert [week_label(x) for x in w] == ["1", "18", "Wild Card", "Divisional", "Conference", "Super Bowl", "1", "1"]


def test_clean_data_passes_every_check():
    for season in (2025, 2026):
        statuses = _status(season)
        assert "fail" not in statuses.values(), (season, statuses)
        assert statuses["longshot_costs_more"] == "pass"
        assert statuses["groups_not_mirrored"] == "pass"


def test_check_catches_old_proportional_method():
    """The mistake your partner caught: both sides of a bet charged the same."""
    def proportional(t, rs, facts):
        m = rs["markets"]
        m["fair_a"], m["fair_b"] = m["fair_a_proportional"], m["fair_b_proportional"]
        m["cost_a_per_10"] = m["cost_b_per_10"] = m["cost_per_10"] = m["cost_per_10_proportional"]
        t["by_price_group"]["mean"] = t["by_price_group"]["mean_cost_proportional"]
    s = _status(mutate=proportional)
    assert s["longshot_costs_more"] == "fail"
    assert s["groups_not_mirrored"] == "fail"


def test_checks_catch_each_kind_of_error():
    def drop_game(t, rs, facts):
        t["_close"] = t["_close"][t["_close"]["event_id"] != "g2025_0"]

    def wrong_note(t, rs, facts):
        facts["games"] += 1  # a chart note saying the wrong number of games

    def stale_close(t, rs, facts):
        t["_close"].loc[t["_close"].index[0], "minutes_to_kickoff"] = 300.0

    def live_close(t, rs, facts):
        t["_close"].loc[t["_close"].index[0], "minutes_to_kickoff"] = -5.0

    def other_season(t, rs, facts):
        rs["markets"].loc[rs["markets"].index[0], "commence_time"] = pd.Timestamp("2026-10-01T17:00:00Z")

    def wrong_cost(t, rs, facts):
        m = rs["markets"]
        i = m.index[m["pre_kickoff"]][0]
        m.loc[i, "cost_per_10"] += 0.01

    def wrong_odds(t, rs, facts):
        rs["sides_raw"].loc[rs["sides_raw"].index[0], "p_implied"] += 0.001

    for mutate, check in ((drop_game, "all_games_included"), (wrong_note, "notes_match_data"),
                          (stale_close, "closing_fresh"), (live_close, "no_live_prices"),
                          (other_season, "season_isolation"), (wrong_cost, "cost_recompute"),
                          (wrong_odds, "odds_conversion")):
        assert _status(mutate=mutate)[check] == "fail", mutate.__name__


def test_shin_unsolvable_market_gets_no_fair_price():
    """A suspended in-game line priced -100000/-100000 must not get an invented fair price."""
    from app.task4.sportsbook_costs import shin_two_way

    fa, fb, z = shin_two_way([0.999], [0.999])
    assert np.isnan(fa[0]) and np.isnan(fb[0]) and np.isnan(z[0])


def test_closing_line_must_be_within_an_hour():
    from app.task4.sportsbook_costs import closing_lines, stale_closing

    df = two_seasons()
    late = df["snapshot_ts"].str.endswith("16:50:00Z") & (df["event_id"] == "g2026_0") & (df["bookmaker"] == "FanDuel")
    r = compute(df[~late])  # FanDuel's last pre-game price for g2026_0 is now two days old
    close = closing_lines(r["markets"])
    assert not ((close["event_id"] == "g2026_0") & (close["bookmaker"] == "FanDuel")).any()
    assert (close["minutes_to_kickoff"] <= 60).all()
    assert len(stale_closing(r["markets"])) == 3
    assert (r["qc"]["check"] == "stale_closing_line").sum() == 3


def test_app_starts_without_optional_chart_libraries():
    """The earlier crash: the whole backend failed to start without matplotlib."""
    import subprocess
    import sys

    code = (
        "import sys\n"
        "class Block:\n"
        "    def find_spec(self, name, path, target=None):\n"
        "        if name.split('.')[0] in ('matplotlib', 'tabulate'):\n"
        "            raise ModuleNotFoundError(name)\n"
        "sys.meta_path.insert(0, Block())\n"
        "import app.main, app.task4.sportsbook_report\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    assert out.returncode == 0, out.stderr


def test_no_season_numbers_typed_into_notes():
    """Chart notes and page text must come from the data (the stale '80 games' / FanDuel-note mistakes)."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    banned = re.compile(r"\b80 games\b|\bof 80\b|9[–-]15 min|20 of 80|13[–-]18 bets|week 6 =")
    for rel in ("backend/app/task4/sportsbook_report.py", "frontend/src/pages/Task4Page.tsx",
                "frontend/src/components/task4/figures.ts"):
        for n, line in enumerate((root / rel).read_text().splitlines(), 1):
            assert not banned.search(line), f"{rel}:{n}: {line.strip()}"


def test_game_with_only_stale_prices_is_explained_not_failed():
    """A game no book priced in its last hour is correctly left out; the check must not fail on it."""
    import copy

    from app.task4 import sportsbook_report as rep
    from app.task4.checks import run_checks

    df = two_seasons()
    late = df["snapshot_ts"].str.endswith("16:50:00Z") & (df["event_id"] == "g2026_1")
    df = df[~late]  # g2026_1 now has only a two-day-old price before kickoff
    r = compute(df)
    games = bf.build_games_table(df)
    manifest = {"games": {e: {"season": int(s), "status": "complete"} for e, s in zip(games["event_id"], games["season"])}}
    rs = rep.split_season(r, 2026)
    t = rep.build_tables(rs, None)
    sg = games[games["season"] == 2026]
    facts = rep.build_facts(t, 2026, sg)
    status = {c["id"]: (c["status"], c["detail"]) for c in run_checks(2026, t, rs, copy.deepcopy(facts), sg, manifest, r)}
    assert status["all_games_included"][0] == "pass", status["all_games_included"]
    assert "1 left out" in status["all_games_included"][1]
    assert status["closing_fresh"][0] == "warn"


def test_rows_use_each_games_final_start_time():
    """Flexed games: the provider moves the start time; every row must use the final one."""
    from app.task4.sportsbook_costs import prepare

    df = two_seasons()
    early = df["snapshot_ts"] < "2026-09-12"
    df.loc[early & (df["event_id"] == "g2026_0"), "commence_time"] = "2026-09-13T20:25:00Z"  # first listed later
    s = prepare(df)
    g = s[s["event_id"] == "g2026_0"]
    assert g["commence_time"].nunique() == 1
    assert g["commence_time"].iloc[0] == pd.Timestamp("2026-09-13T17:00:00Z")
    assert g["commence_time_listed"].nunique() == 2


def test_check_catches_two_kickoff_times_for_one_game():
    def two_times(t, rs, facts):
        raw = rs["sides_raw"]
        raw.loc[raw.index[0], "commence_time"] = raw.loc[raw.index[0], "commence_time"] + pd.Timedelta(hours=3)
    assert _status(mutate=two_times)["kickoff_final"] == "fail"
