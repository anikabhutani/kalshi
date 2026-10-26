"""College alignment: name matching, ticker/title parsing, duplicate listings, learned team table."""

from __future__ import annotations

import json
import zipfile
from datetime import date

import pandas as pd
import pytest

from app.alignment import college as col


@pytest.mark.parametrize(("kalshi", "feed", "score"), [
    ("Ohio St.", "Ohio State Buckeyes", 1.0),
    ("Oregon", "Oregon Ducks", 1.0),
    ("Oregon", "Oregon State Beavers", 0.5),  # a different school
    ("Texas", "Texas A&M Aggies", 0.5),
    ("Miami (FL)", "Miami Hurricanes", 1.0),
    ("Miami (FL)", "Miami (OH) RedHawks", 0.5),
    ("Miami (OH)", "Miami (OH) RedHawks", 1.0),
    ("North Carolina St.", "NC State Wolfpack", 1.0),
    ("North Carolina", "NC State Wolfpack", 0.0),
    ("Louisiana-Monroe", "UL Monroe Warhawks", 1.0),
    ("Louisiana", "UL Monroe Warhawks", 0.0),
    ("San José St.", "San Jose State Spartans", 1.0),
])
def test_name_scores(kalshi, feed, score):
    assert col.name_score(kalshi, feed) == pytest.approx(score)


def test_title_split_and_hyphen_codes():
    assert col.split_title("University at Albany at Iowa Winner?", {"University at Albany", "Iowa"}) == ("University at Albany", "Iowa")
    assert col.split_title("UC Davis vs Washington Winner?", {"UC Davis", "Washington"}) == ("UC Davis", "Washington")
    assert col.TICKER_RE.match("KXNCAAFGAME-25OCT18EMUM-OH")  # Miami (OH) is "M-OH"


def _markets(rows):
    m = pd.DataFrame(rows, columns=["ticker", "event_ticker", "kalshi_name", "title", "result", "volume", "has_candles"])
    m["id"] = range(1, len(m) + 1)
    m["code"] = [t[len(e) + 1:] for t, e in zip(m["ticker"], m["event_ticker"])]
    return m


def _games(rows):
    g = pd.DataFrame(rows, columns=["game_id", "away", "home", "kickoff_utc"])
    g["kickoff_utc"] = pd.to_datetime(g["kickoff_utc"], utc=True)
    g["kickoff_first_listed_utc"] = g["kickoff_utc"]
    g["kickoff_moved_min"] = 0.0
    g["season"], g["week"], g["week_label"], g["postseason"] = 2025, 1, "Week 1", False
    return g


def test_crosswalk_picks_the_right_school_and_handles_duplicates():
    t = "Oregon at Washington Winner?"
    m = _markets([
        ("KXNCAAFGAME-25NOV29OREWASH-ORE", "KXNCAAFGAME-25NOV29OREWASH", "Oregon", t, "yes", 10, True),
        ("KXNCAAFGAME-25NOV29OREWASH-WASH", "KXNCAAFGAME-25NOV29OREWASH", "Washington", t, "no", 10, True),
        # a second listing of the same game (Kalshi did this once in 2025); smaller and no candles
        ("KXNCAAFGAME-25NOV29OREUW-ORE", "KXNCAAFGAME-25NOV29OREUW", "Oregon", t, "yes", 5, False),
        ("KXNCAAFGAME-25NOV29OREUW-UW", "KXNCAAFGAME-25NOV29OREUW", "Washington", t, "no", 5, False),
        ("KXNCAAFGAME-25NOV29M-OHBALL-M-OH", "KXNCAAFGAME-25NOV29M-OHBALL", "Miami (OH)", "Miami (OH) at Ball St. Winner?", "no", 1, True),
        ("KXNCAAFGAME-25NOV29M-OHBALL-BALL", "KXNCAAFGAME-25NOV29M-OHBALL", "Ball St.", "Miami (OH) at Ball St. Winner?", "yes", 1, True),
    ])
    g = _games([
        ("g1", "Oregon Ducks", "Washington Huskies", "2025-11-29 20:30"),
        ("g2", "Oregon State Beavers", "Washington State Cougars", "2025-11-29 23:00"),  # same day, other schools
        ("g3", "Miami (OH) RedHawks", "Ball State Cardinals", "2025-11-29 17:00"),
        ("g4", "Harvard Crimson", "Yale Bulldogs", "2025-11-22 17:00"),  # not on Kalshi
    ])
    ev = col.kalshi_events(m, 2025)
    assert ev.set_index("event_ticker").loc["KXNCAAFGAME-25NOV29OREUW", "parse_reason"] == "duplicate_listing"
    cw, left, _ = col.crosswalk(g, ev)
    r = cw.set_index("game_id")
    assert r.loc["g1", "kalshi_event_ticker"] == "KXNCAAFGAME-25NOV29OREWASH" and r.loc["g1", "status"] == "matched"
    assert r.loc["g1", "kalshi_code_away"] == "ORE" and r.loc["g1", "kalshi_code_home"] == "WASH"
    assert r.loc["g2", "status"] == "unmatched"  # never paired with the Oregon/Washington market
    assert r.loc["g3", "kalshi_code_away"] == "M-OH"
    assert r.loc["g4", "reason_code"] == "no_kalshi_event"
    assert list(left["reason"]) == ["duplicate_listing"]
    table = col.team_table(cw)
    assert set(table["kalshi_code"]) == {"ORE", "WASH", "M-OH", "BALL"}


def test_team_table_check_catches_a_wrong_school():
    table = pd.DataFrame({"kalshi_code": ["ORE", "ORE"], "kalshi_name": ["Oregon", "Oregon"],
                          "feed_name": ["Oregon Ducks", "Oregon State Beavers"], "games": [5, 1]})
    games = _games([("g1", "A", "B", "2025-09-01 17:00")])
    cw = games.assign(status="matched", reason_code="matched", kalshi_event_ticker="E", kalshi_market_id_home=1,
                      kalshi_market_id_away=2, match_score=2.0, runner_up_score=0.0, date_diff_days=0)
    snaps = pd.DataFrame({"event_id": ["g1"], "snapshot_ts": [games["kickoff_utc"][0]], "commence_time": [games["kickoff_utc"][0]]})
    left = pd.DataFrame({"ticker_date": [], "reason": []})
    st = {c["id"]: c["status"] for c in col.crosswalk_checks(games, pd.DataFrame(), cw, left, table, snaps, [])}
    assert st["team_table"] == "fail"


def test_weeks_and_postseason():
    assert col.college_week(date(2025, 8, 23), 2025) == 0
    assert col.college_week(date(2025, 8, 30), 2025) == 1
    assert col.postseason_start(2025) == date(2025, 12, 14)  # day after Army-Navy (Dec 13, 2025)


def test_reads_candles_from_the_zip(tmp_path):
    z = tmp_path / "k.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("raw/candles/KXNCAAFGAME/T-A.json", json.dumps({"candlesticks": [
            {"end_period_ts": 100, "yes_bid": {"close": "0.4100"}, "yes_ask": {"close": "0.4300"}, "price": {}},
            {"end_period_ts": 160, "yes_bid": {"close": None}, "yes_ask": {"close": "0.4400"}, "price": {}}]}))
    c, missing = col.load_candles({"T-A": 7, "T-B": 8}, z)
    assert missing == ["T-B"] and list(c["bid"]) == [4100, None] or list(c["bid"].fillna(-1)) == [4100, -1]
    assert list(c["ask"]) == [4300, 4400] and set(c["market_id"]) == {7}


def test_reads_the_2026_layout(tmp_path):
    """Events with nested markets ("A vs B" titles) and per-event candle chunks."""
    z = tmp_path / "k26.zip"
    ev = "KXNCAAFGAME-26OCT24NDSUUNM"
    mk = lambda code, name: {"ticker": f"{ev}-{code}", "event_ticker": ev, "title": f"{name} wins",  # noqa: E731
                             "yes_sub_title": name, "result": "", "volume_fp": "5.00"}
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("raw/discovery/events_KXNCAAFGAME_p000.json", json.dumps({"events": [
            {"event_ticker": ev, "title": "North Dakota St. vs New Mexico",
             "markets": [mk("NDSU", "North Dakota St."), mk("UNM", "New Mexico")]}]}))
        for start, bid in ((100, "0.4000"), (400, "0.4500")):
            f.writestr(f"raw/candles/{ev}/{ev}__g0__{start}.json", json.dumps({"markets": [
                {"market_ticker": f"{ev}-UNM", "candlesticks": [
                    {"end_period_ts": start + 60, "yes_bid": {"close_dollars": bid}, "yes_ask": {"close_dollars": "0.5000"}}]},
                {"market_ticker": f"{ev}-NDSU", "candlesticks": []}]}))
    m = col.load_kalshi_markets(z)
    assert set(m["code"]) == {"NDSU", "UNM"} and m["has_candles"].all()
    e = col.kalshi_events(m, 2026)
    assert e.iloc[0]["away_name"] == "North Dakota St." and e.iloc[0]["home_name"] == "New Mexico"
    ids = dict(zip(m["ticker"], m["id"]))
    c, missing = col.load_candles(ids, z)
    assert list(c["ts"]) == [160, 460] and list(c["bid"]) == [4000, 4500]
    assert missing == [f"{ev}-NDSU"]  # no candles for that market: reported, not invented


def test_drops_odds_feed_duplicate_listings():
    t = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
    snaps = pd.DataFrame({
        "event_id": ["old", "old", "new", "other"],
        "home_team": ["New Mexico Lobos"] * 3 + ["Iowa Hawkeyes"],
        "away_team": ["Mercyhurst Lakers"] * 3 + ["Ohio State Buckeyes"],
        "commence_time": [t("2026-09-11 14:00")] * 2 + [t("2026-09-12 20:00"), t("2026-09-12 20:00")],
        "snapshot_ts": [t("2026-09-05"), t("2026-09-08"), t("2026-09-12 19:00"), t("2026-09-12")],
    })
    kept, dropped = col.drop_feed_duplicates(snaps)
    assert dropped == ["old"] and set(kept["event_id"]) == {"new", "other"}


def test_college_trade_size_markets_come_from_the_crosswalk(tmp_path):
    from app.alignment import trade_sizes as ts

    folder = tmp_path / "2025"
    folder.mkdir()
    pd.DataFrame({
        "status": ["matched", "matched", "unmatched"],
        "kalshi_ticker_home": ["KXNCAAFGAME-25SEP06OSUTEX-OSU", "KXNCAAFGAME-25DEC01AB-A", None],
        "kalshi_ticker_away": ["KXNCAAFGAME-25SEP06OSUTEX-TEX", "KXNCAAFGAME-25DEC01AB-B", None],
    }).to_csv(folder / "crosswalk.csv", index=False)
    m = ts.college_markets(2025, tmp_path, today=date(2025, 11, 1))
    # both teams' markets of matched games, only games before today
    assert sorted(m["ticker"]) == ["KXNCAAFGAME-25SEP06OSUTEX-OSU", "KXNCAAFGAME-25SEP06OSUTEX-TEX"]
    assert set(m["series"]) == {"KXNCAAFGAME"}
    assert ts.college_markets(2026, tmp_path).empty  # no crosswalk: nothing, not an error


def test_college_trade_size_report_and_n_values(tmp_path):
    from app.alignment import costs as cm
    from app.alignment import trade_sizes as ts

    markets = pd.DataFrame({"ticker": ["KXNCAAFGAME-25SEP06OSUTEX-OSU"], "series": ["KXNCAAFGAME"],
                            "game_date": [date(2025, 9, 6)], "status": ["matched"]})
    folder = tmp_path / "trades" / "2025"
    folder.mkdir(parents=True)
    pd.DataFrame({"trade_id": list("abcde"), "ticker": ["KXNCAAFGAME-25SEP06OSUTEX-OSU"] * 5,
                  "count": [1, 2, 5, 10, 400], "yes_price": [0.5] * 5, "created_time": ["2025-09-06T12:00:00Z"] * 5,
                  "is_block_trade": [False, False, False, False, True], "taker_outcome_side": ["yes"] * 5}
                 ).to_csv(folder / "KXNCAAFGAME-25SEP06OSUTEX-OSU.csv.gz", index=False, compression="gzip")
    (tmp_path / "trades" / "2025" / "_progress.json").write_text(json.dumps(
        {"markets": {"KXNCAAFGAME-25SEP06OSUTEX-OSU": {"done": True, "trades": 5}}}))
    assert ts.report(2025, markets, tmp_path, league="ncaaf") == 0
    stats = json.loads((tmp_path / "trade_sizes_2025.json").read_text())["stats"]
    assert set(stats) == {"all college markets", "KXNCAAFGAME"}
    assert stats["KXNCAAFGAME"]["excluding block trades"]["per_trade"] == {"p50": 2.0, "p75": 5.0, "p90": 10.0}
    # the college costs pick these up (game-winner group), for 2025 and, labelled, for 2026
    n, src = cm.n_values(2025, tmp_path, groups=("KXNCAAFGAME", "all college markets"))
    assert n == [("median", 2), ("p75", 5), ("p90", 10)] and src == "trade_sizes_2025.json, KXNCAAFGAME"
    assert "2025 sizes used for 2026" in cm.n_values(2026, tmp_path, groups=("KXNCAAFGAME",))[1]
    # an NFL file has no college groups: not used for college
    assert cm.n_values(2025, tmp_path, groups=("KXNFLGAME", "all NFL markets"))[1].startswith("placeholder")
