"""In-game odds comparison: calm check, cost math, exclusions."""

import numpy as np
import pandas as pd
import pytest

from app.ingame import compare_odds as C


def _kalshi(mids, start=1_800_000_000 // 60 * 60):
    ts = start + 60 * np.arange(len(mids))
    m = np.array(mids, float)
    k = pd.DataFrame({"ts": ts, "bid": m - 0.5, "ask": m + 0.5, "mid": m, "spread": 1.0, "filled": False})
    k["cost_home_per10"] = 10 * (1 - k["mid"] / (k["ask"] + 1.0))
    k["cost_away_per10"] = 10 * (1 - (100 - k["mid"]) / (100 - k["bid"] + 1.0))
    return k.set_index("ts")


def _odds(snap, upd, side="home", implied=0.55):
    return pd.DataFrame({"game_id": ["g"], "snap_ts": [snap], "upd_ts": [upd], "side": [side], "implied_prob": [implied]})


def test_calm_row_costs():
    k = _kalshi([50.0] * 20)
    snap = int(k.index[10]) + 37
    d = C.attach_kalshi(_odds(snap, snap - 20), {"g": k})
    assert d["calm"].iloc[0]
    assert d["book_cost"].iloc[0] == pytest.approx(10 * (1 - 0.5 / 0.55))
    assert d["k_cost"].iloc[0] == pytest.approx(10 * (1 - 50 / 51.5))
    assert d["extra_cost"].iloc[0] == pytest.approx(d["book_cost"].iloc[0] - d["k_cost"].iloc[0])


def test_move_between_book_update_and_snapshot_excludes_row():
    k = _kalshi([50.0] * 8 + [60.0] * 12)
    snap = int(k.index[9]) + 37
    d = C.attach_kalshi(_odds(snap, int(k.index[6])), {"g": k})   # book price from before the jump
    assert not d["calm"].iloc[0] and "moved" in d["exclusion"].iloc[0]
    d2 = C.attach_kalshi(_odds(int(k.index[15]) + 37, int(k.index[15])), {"g": k})   # well after: calm again
    assert d2["calm"].iloc[0]


def test_strict_window_needs_five_calm_minutes():
    k = _kalshi([50.0] * 8 + [60.0] * 12)
    snap = int(k.index[10]) + 37
    assert C.attach_kalshi(_odds(snap, snap - 10), {"g": k}, 60)["calm"].iloc[0]
    assert not C.attach_kalshi(_odds(snap, snap - 10), {"g": k}, 240)["calm"].iloc[0]


def test_away_side_flips_kalshi_and_extreme_price_excluded():
    k = _kalshi([95.0] * 10)
    snap = int(k.index[5]) + 37
    d = C.attach_kalshi(_odds(snap, snap - 5, side="away", implied=0.07), {"g": k})
    assert d["k_mid"].iloc[0] == 5.0 and d["exclusion"].iloc[0] == "fair price outside 10-90"
