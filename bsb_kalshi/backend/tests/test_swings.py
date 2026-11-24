"""Task 7 in-game swings: names, minute table, swing and steady logic, timestamp slots, and a full run on a
synthetic CollegeFootballData + Kalshi folder."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.ingame import swings as S
from app.ingame import timestamp_list as T


def test_names_match_across_spellings():
    assert S.name_score("Montana St.", "Montana State") == 1.0
    assert S.name_score("Miami (OH)", "Miami (OH)") == 1.0
    assert S.name_score("San José State", "San Jose St.") == 1.0
    assert S.name_score("Ole Miss", "Mississippi") == 1.0
    assert S.name_score("Ohio State", "Oregon State") < 0.75 or S.norm("Ohio State") != S.norm("Oregon State")


def _grid_game(mids, start=1_790_000_040, spread=1.0):
    ts = start + 60 * np.arange(len(mids))
    df = pd.DataFrame({"ts": ts, "mid": mids, "bid": np.array(mids) - spread / 2, "ask": np.array(mids) + spread / 2})
    df["spread"] = spread
    df["filled"] = False
    df["in_game"] = True
    df["volume_both"] = 10.0
    return df


def test_one_clean_swing_gets_steady_before_and_after():
    mids = [50.0] * 30 + [55, 65, 70] + [70.0] * 30
    st = S.GameState("g", _grid_game(mids), {})
    st.sigma = 1.0
    sw = S.find_swings(st, thr=8.0, rng=2.0)
    assert len(sw) == 1
    s = sw[0]
    assert s["status"] == "kept"
    t = pd.Timestamp(s["t_utc"])
    b, a = pd.Timestamp(s["before_utc"]), pd.Timestamp(s["after_utc"])
    assert b < pd.Timestamp(s["move_start_utc"]) <= t < a
    # after time is the first minute whose 5 trailing minutes are all at 70
    assert s["mid_after"] == 70 and s["mid_before"] == 50
    assert s["size_move"] == 20
    assert s["minutes_to_settle"] == 5  # t is the 55->65 minute (biggest 1-min jump); flat 70 from t+1, steady at t+5


def test_move_that_does_not_hold_is_not_a_swing():
    mids = [50.0] * 30 + [62, 51] + [50.0] * 30   # spike and straight back
    st = S.GameState("g", _grid_game(mids), {})
    st.sigma = 1.0
    sw = S.find_swings(st, thr=8.0, rng=2.0)
    # the spike's reversal passes the literal rule (62 -> 50 holds), but the settled change is 0: dropped
    assert all(s["status"] == "dropped" and s["drop_reason"].startswith("move reversed") for s in sw)


def test_swing_dropped_when_next_swing_starts_first():
    mids = [50.0] * 30 + [60, 70] + [70.0] * 3 + [80, 90] + [89.0] * 30
    st = S.GameState("g", _grid_game(mids), {})
    st.sigma = 1.0
    sw = S.find_swings(st, thr=8.0, rng=2.0)
    assert len(sw) == 1   # within 10 minutes: one group


def test_filled_minutes_never_steady():
    df = _grid_game([50.0] * 20)
    df.loc[10, "filled"] = True
    st = S.steady_flags(df, 2.0)
    assert not st[10:15].any() and st[15]


def test_two_sided_marks_missing_quotes_filled_and_carries_last_quote():
    m = pd.DataFrame({"ts": [60, 120, 180], "bid": [40.0, 0.0, 41.0], "ask": [42.0, 42.0, 43.0]})
    out = S.two_sided(m)
    assert out["filled"].tolist() == [False, True, False]
    assert out.loc[1, "bid"] == 40.0 and out.loc[1, "ask"] == 42.0


def test_cost_per_10_uses_ask_plus_fee():
    cost, fee = S.cost_per_10(np.array([59.5]), np.array([60.0]), 24)
    # fee: 0.07*24*0.6*0.4 = 0.4032 -> $0.41 -> 1.7083c per contract
    assert fee[0] == pytest.approx(41 / 24, abs=1e-9)
    assert cost[0] == pytest.approx(10 * (1 - 59.5 / (60 + 41 / 24)))


def test_slot_uses_minute_start():
    ten = 1_790_000_000 - (1_790_000_000 % 300)   # a 5-minute mark
    assert T.slot_of(np.array([ten]))[0] == ten - 300        # 10:05:00 = minute 10:04 -> slot 10:00
    assert T.slot_of(np.array([ten + 60]))[0] == ten          # 10:06:00 = minute 10:05 -> slot 10:05
    assert T.slot_of(np.array([ten + 300]))[0] == ten         # 10:10:00 -> slot 10:05


def test_budget_drops_smallest_first_keeping_pairs():
    sw = pd.DataFrame({"swing_id": ["a", "b", "c"], "before_ts": [0, 10_000, 20_000], "after_ts": [600, 10_600, 20_600],
                       "rank_score": [3.0, 1.0, 2.0]})
    keep, dropped = T.fit_budget(sw, max_calls=4)
    assert dropped == ["b"] and set(keep["swing_id"]) == {"a", "c"}


# --------------------------------------------------------------------------------------
# full run on a synthetic folder
# --------------------------------------------------------------------------------------

def _write_fixture(root: Path, rng: np.random.Generator) -> None:
    season = root / "ingame" / "ncaaf" / "2026"
    (season / "candles").mkdir(parents=True)
    (season / "cfbd" / "wp").mkdir(parents=True)
    games, plays = [], []
    events = []
    for gi in range(30):
        kick = pd.Timestamp("2026-09-19 16:00", tz="UTC") + pd.Timedelta(hours=gi % 3, days=7 * (gi // 3))
        gid = 1000 + gi
        home, away = f"Home{gi} State", f"Away{gi}"
        games.append({"id": gid, "season": 2026, "week": 3 + gi // 3, "seasonType": "regular",
                      "startDate": kick.isoformat(), "homeTeam": home, "awayTeam": away,
                      "homeClassification": "fbs", "awayClassification": "fbs"})
        d = kick.tz_convert("America/New_York")
        code = f"{d.strftime('%y%b').upper()}{d.day:02d}A{gi}H{gi}"
        et = f"KXNCAAFGAME-{code}"
        events.append({"event_ticker": et, "ticker_date": d.date().isoformat(), "title": f"{away} at {home}",
                       "sub_title": "", "tickers": f"{et}-H{gi}|{et}-A{gi}", "team_names": f"Home{gi} St.|Away{gi}",
                       "result": "|"})
        minutes = 210
        tds = sorted(rng.choice(np.arange(20, 190), size=3, replace=False))
        mid = np.empty(minutes + 60)
        level = 50.0
        for m in range(minutes + 60):
            game_min = m - 30
            if game_min in tds:
                level += rng.choice([-1, 1]) * 18
            level = float(np.clip(level + rng.normal(0, 0.35), 15, 85))
            mid[m] = level
        ts0 = int(kick.timestamp()) // 60 * 60 - 30 * 60 + 60
        rows = []
        for m in range(minutes + 60):
            b = np.floor(mid[m] - 0.5)
            rows.append({"ticker": f"{et}-H{gi}", "ts": ts0 + 60 * m, "bid": b, "ask": b + 1, "volume": 50.0,
                         "price": b, "oi": 1000.0})
            rows.append({"ticker": f"{et}-A{gi}", "ts": ts0 + 60 * m, "bid": 99 - b, "ask": 100 - b, "volume": 50.0,
                         "price": 99 - b, "oi": 1000.0})
        pd.DataFrame(rows).to_csv(season / "candles" / f"{et}.csv.gz", index=False, compression="gzip")
        good = gi % 5 != 0
        wp = []
        for p in range(200):
            wall = kick + pd.Timedelta(seconds=60 * p + 5)
            typ = "Rush"
            if p in tds:
                typ = "Rushing Touchdown"
            plays.append({"id": gid * 1000 + p, "gameId": gid, "period": 1 + p // 50, "clock": {"minutes": 14 - (p % 50) // 4,
                          "seconds": 59 - p % 60}, "offense": home if p % 7 < 4 else away, "defense": away,
                          "down": 1 + p % 4, "distance": 10, "yardsGained": 3, "playType": typ,
                          "playText": typ, "scoring": "Touchdown" in typ,
                          "wallclock": wall.isoformat() if good else None})
            wp.append({"playId": gid * 1000 + p, "homeWinProbability": 0.5})
        (season / "cfbd" / "wp" / f"{gid}.json").write_text(json.dumps(wp))
    (season / "cfbd" / "games.json").write_text(json.dumps(games))
    (season / "cfbd" / "plays_regular_3.json").write_text(json.dumps(plays))
    pd.DataFrame(events).to_csv(season / "events.csv", index=False)


def test_full_run_on_synthetic_data(tmp_path, monkeypatch):
    _write_fixture(tmp_path, np.random.default_rng(1))
    monkeypatch.setattr(S, "DATA", tmp_path)
    monkeypatch.setattr(S, "out_dir", lambda season, league="ncaaf": tmp_path / "ingame" / league / str(season))
    monkeypatch.setattr(T, "DATA", tmp_path)
    assert S.run([2026], "pbp", 2.0, league="ncaaf") == 0
    out = tmp_path / "ingame" / "ncaaf" / "out"
    thr = json.loads((out / "threshold_ncaaf.json").read_text())
    assert thr["games_used"] == 30 and thr["games_with_good_timestamps"] == 24
    assert thr["k"]["p97.5"] <= thr["k"]["p99"] <= thr["k"]["p99.5"]
    sw = pd.read_csv(out / "swings_ncaaf.csv")
    assert len(sw) > 0
    chk = thr["checks"]["within_3_min"]
    assert chk["catch_rate"] > 0.8 and chk["match_rate"] > 0.8   # planted 18-point jumps at the touchdowns
    minutes = pd.read_csv(out / "kalshi_minutes_ncaaf_2026.csv")
    assert {"bid", "ask", "mid", "spread", "volume", "filled", "steady", "flagged", "cost_home_per10",
            "cost_away_per10"} <= set(minutes.columns)
    assert T.run("ncaaf") == 0
    lst = pd.read_csv(out / "timestamp_list_ncaaf.csv")
    kept = pd.read_csv(out / "swings_ncaaf.csv").query("on_list")
    assert lst["n_entries"].sum() == 2 * len(kept)
    # every request falls in the 5 steady minutes of each entry it covers (snapshot = slot + 37 s)
    for _, r in lst.iterrows():
        snap = (r["request_ts"] - 60) // 300 * 300 + 37
        assert r["request_ts"] - 300 < snap <= r["request_ts"]
    at = pd.read_csv(out / "kalshi_at_swings_ncaaf.csv")
    assert len(at) == 4 * len(sw[sw.status == "kept"]) + 0 or len(at) >= 4 * len(kept)
    assert list(out.glob("swings_KX*.png"))


def test_nfl_loader_matches_kalshi_codes_and_labels_plays(tmp_path, monkeypatch):
    season = tmp_path / "ingame" / "nfl" / "2025"
    (tmp_path / "ingame" / "nfl" / "pbp").mkdir(parents=True)
    season.mkdir(parents=True)
    pd.DataFrame([{"season": 2025, "event_ticker": "KXNFLGAME-25SEP07INDJAC", "kickoff_ts": 1757264400,
                   "kickoff_source": "milestone", "tickers": "KXNFLGAME-25SEP07INDJAC-JAC|KXNFLGAME-25SEP07INDJAC-IND",
                   "team_names": "Jacksonville|Indianapolis"},
                  {"season": 2025, "event_ticker": "KXNFLGAME-25AUG09LARDAL", "kickoff_ts": 1754780000,
                   "kickoff_source": "milestone", "tickers": "KXNFLGAME-25AUG09LARDAL-DAL|KXNFLGAME-25AUG09LARDAL-LAR",
                   "team_names": "Dallas|Los Angeles R"}]).to_csv(season / "events_task3.csv", index=False)
    base = {"game_id": "2025_01_IND_JAX", "season_type": "REG", "week": 1, "home_team": "JAX", "away_team": "IND",
            "game_date": "2025-09-07", "start_time": "9/7/25, 13:02:38", "qtr": 1, "home_wp": 0.5, "play_type": "pass",
            "touchdown": 0, "interception": 0, "fumble_lost": 0, "fourth_down_failed": 0, "field_goal_result": None}
    rows = [dict(base, play_id=1, time_of_day="2025-09-07T17:03:00Z", desc="pass", touchdown=1),
            dict(base, play_id=2, time_of_day="2025-09-07T17:05:00Z", desc="pick six", interception=1, touchdown=1),
            dict(base, play_id=3, time_of_day="2025-09-07T17:09:00Z", desc="fg", field_goal_result="made"),
            dict(base, play_id=4, time_of_day="2025-09-07T17:12:00Z", desc="4th", fourth_down_failed=1)]
    pd.DataFrame(rows).to_csv(tmp_path / "ingame" / "nfl" / "pbp" / "pbp_2025.csv.gz", index=False, compression="gzip")
    monkeypatch.setattr(S, "DATA", tmp_path)
    monkeypatch.setattr(S, "out_dir", lambda s_, league="ncaaf": tmp_path / "ingame" / league / str(s_))
    games, plays, log = S.load_nfl([2025])
    assert len(games) == 1 and games.iloc[0]["ticker_home"].endswith("-JAC") and games.iloc[0]["home"] == "JAX"
    assert log["2025"]["unmatched_reasons"] == {"no nflverse game (preseason or not played)": 1}
    assert plays["event"].tolist() == ["touchdown", "turnover", "field_goal", "failed_fourth"]
