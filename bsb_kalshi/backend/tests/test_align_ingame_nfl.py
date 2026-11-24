"""Task 8 NFL alignment: odds conversion, Shin, slot matching of swing times to requests."""

import numpy as np
import pandas as pd
import pytest

from app.ingame import align_ingame_nfl as A
from app.task4.sportsbook_costs import shin_two_way


def test_implied_from_american_odds():
    assert A.implied(-150) == pytest.approx(0.6)
    assert A.implied(130) == pytest.approx(100 / 230)


def test_shin_two_way_sums_to_one_and_shades_longshot():
    fa, fb, z = shin_two_way(np.array([A.implied(-300)]), np.array([A.implied(240)]))
    assert fa[0] + fb[0] == pytest.approx(1)
    # Shin moves more margin off the longshot than proportional de-vigging does
    prop_b = A.implied(240) / (A.implied(-300) + A.implied(240))
    assert fb[0] < prop_b


def test_entries_map_each_swing_time_to_its_request_slot():
    sw = pd.DataFrame({"swing_id": ["g1-S01", "g2-S01"], "on_list": [True, True], "before_ts": [1_800_000_120, 1_800_000_180],
                       "after_ts": [1_800_000_960, 1_800_003_000], "game_id": ["g1", "g2"], "event_ticker": ["E1", "E2"],
                       "season": [2025, 2025], "week": [1, 1], "home": ["KC", "PHI"], "away": ["LAC", "DAL"],
                       "t_ts": [1_800_000_500, 1_800_000_900], "abs_move": [20, 15], "size_move": [20, -15],
                       "matched_play": ["touchdown", None]})
    # request at the earliest time in the shared slot covers both before times
    lst = pd.DataFrame({"request_ts": [1_800_000_120, 1_800_000_960, 1_800_003_000],
                        "request_time_utc": ["a", "b", "c"], "swing_ids": ["g1-S01|g2-S01", "g1-S01", "g2-S01"]})
    e = A.entries(lst, sw)
    assert len(e) == 4
    assert set(e.loc[e["request_time_utc"] == "a", "which"]) == {"before"}
    assert e.set_index(["swing_id", "which"]).loc[("g2-S01", "after"), "request_time_utc"] == "c"
