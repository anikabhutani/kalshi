"""Task 7 Part 1: find the big in-game swings on Kalshi and pick steady before and after times.

Steps (numbers follow the task brief):

1. Minute table. For every game, the home team's winner market, one row per minute from kickoff to the
   final whistle (from play-by-play wall-clock times). If the home market is thin, the away market is
   used and its prices flipped (home bid = 100 - away ask). Each row: closing bid, ask, volume,
   midpoint, spread, and Kalshi cost per $10 for both teams at n_med, with the alignment fee
   (``0.07 x n x P x (1-P)`` rounded up to the cent per order). A minute whose quote has no bid or no
   ask carries the last two-sided quote forward and is marked ``filled``.
2. Threshold. Quiet minutes = in-game minutes more than 5 minutes from any touchdown, field goal,
   turnover or failed fourth down. d = 5-minute midpoint change. sigma_game = 1.4826 x MAD(d) over the
   game's quiet minutes (floor 1 point; under 20 quiet minutes -> league median, marked). k = 99th
   percentile of |d| / sigma_game over all quiet minutes of games with good play timestamps (97.5th
   and 99.5th reported too). Games without good timestamps: sigma_game from all usable in-game minutes.
3. Swings. A minute is flagged when |d| > k x sigma_game, the move holds 3 minutes later (still at
   least 3/4 of the threshold from where it started, same direction) and the midpoint is 10-90.
   Flagged minutes within 10 minutes of each other are one swing; t = the minute with the biggest
   one-minute jump.
4. Steady before and after. Steady = over the 5 minutes ending at the minute, midpoint range <= 2
   points, spread <= 5c, nothing filled. Before = the latest steady minute at least 1 minute before
   the price started moving; after = the first steady minute after t whose spread is within 2c of the
   before spread. Dropped (with the reason) if either is more than 20 minutes from t, if another swing
   starts before the after time, or if the previous swing happened after the before time.
5. Checks against real plays: catch rate, match rate, sigma range, plots.
7. Kalshi prices at every before and after time, and the summaries.

Step 6 (timestamp list and credits) is ``timestamp_list.py``.

NFL (default): Kalshi KXNFLGAME candles exported from the Task 3 store into
``data/ingame/nfl/<season>/candles/`` (``swing_data export-task3``), games and kickoff times from the Task 3
store (``events_task3.csv``), play-by-play from nflverse (``data/ingame/nfl/pbp/pbp_<season>.csv.gz``:
wall-clock ``time_of_day``, ``home_wp``, touchdown / interception / fumble_lost / fourth_down_failed /
field_goal_result). Preseason games are not in nflverse and are left out.
College: ``data/ingame/ncaaf/<season>/`` from ``swing_data pull`` (CollegeFootballData).
Outputs: ``data/ingame/<league>/out/``.

    cd backend && .venv/bin/python -m app.ingame.swings --league nfl --seasons 2025 2026
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.alignment.costs import fee_dollars
from app.ingame.swing_data import DATA, out_dir, ticker_date
from app.task4.common import EASTERN

MIN = 60
QUIET_GAP_MIN = 5
D_LAG = 5
HOLD_LAG = 3
HOLD_SHARE = 0.75
MID_LO, MID_HI = 10.0, 90.0
GROUP_GAP_MIN = 10
STEADY_LEN = 5
STEADY_SPREAD = 5.0
AFTER_SPREAD_TOL = 2.0
MAX_FROM_T = 20
SETTLED_SHARE = 0.5   # added guard: before -> after change must be at least half the threshold
MIN_QUIET = 20
SIGMA_FLOOR = 1.0
MAD_SCALE = 1.4826
PCTS = (97.5, 99.0, 99.5)
MATCH_MIN = 3
WP_LO, WP_HI = 0.20, 0.80

# CollegeFootballData play types
TD_WORDS = ("touchdown",)
TURNOVER_TYPES = {"interception", "pass interception return", "interception return touchdown",
                  "fumble recovery (opponent)", "fumble return touchdown", "pass interception"}
FG_TYPES = {"field goal good"}
NON_SNAPS = {"punt", "field goal good", "field goal missed", "missed field goal return", "blocked field goal",
             "blocked punt", "timeout", "end period", "end of half", "end of game", "end of regulation",
             "kickoff", "penalty", "uncategorized", "end of 1st period", "end of 3rd period", "coin toss",
             "blocked punt touchdown", "blocked field goal touchdown", "punt return touchdown"}


# --------------------------------------------------------------------------------------
# Names and games
# --------------------------------------------------------------------------------------

ALIASES = {"miami fl": "miami", "miami florida": "miami", "ole miss": "mississippi", "uconn": "connecticut",
           "fiu": "florida international", "fau": "florida atlantic", "utsa": "ut san antonio",
           "utep": "ut el paso", "umass": "massachusetts", "app state": "appalachian state",
           "ul monroe": "louisiana monroe", "ulm": "louisiana monroe", "southern miss": "southern mississippi",
           "pitt": "pittsburgh", "byu": "brigham young", "lsu": "louisiana state", "smu": "southern methodist",
           "tcu": "texas christian", "ucf": "central florida", "ucla": "ucla", "usc": "southern california",
           "unlv": "unlv", "hawai i": "hawaii", "nc state": "north carolina state", "n c state": "north carolina state",
           "sam houston state": "sam houston", "louisiana lafayette": "louisiana", "ul lafayette": "louisiana",
           "miami oh": "miami ohio", "miami (oh)": "miami ohio", "army west point": "army"}


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("(", " ").replace(")", " ")
    s = re.sub(r"[.'`]", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = s.split()
    toks = ["state" if (t == "st" and i == len(toks) - 1) else ("saint" if t == "st" else t)
            for i, t in enumerate(toks)]
    s = " ".join(toks)
    return ALIASES.get(s, s)


def name_score(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def load_events(folder: Path) -> pd.DataFrame:
    frames = [pd.read_csv(p) for p in (folder / "events.csv", folder / "events_from_zip.csv") if p.exists()]
    if not frames:
        return pd.DataFrame()
    ev = pd.concat(frames).drop_duplicates("event_ticker")
    return ev[ev["event_ticker"].str.startswith("KXNCAAFGAME")].reset_index(drop=True)


def load_cfbd_games(folder: Path) -> pd.DataFrame:
    p = folder / "cfbd" / "games.json"
    if not p.exists():
        return pd.DataFrame()
    g = pd.json_normalize(json.loads(p.read_text()))
    ren = {"startDate": "start", "start_date": "start", "homeTeam": "home", "home_team": "home",
           "awayTeam": "away", "away_team": "away", "homeClassification": "home_cls",
           "home_classification": "home_cls", "awayClassification": "away_cls",
           "away_classification": "away_cls", "seasonType": "season_type"}
    g = g.rename(columns={k: v for k, v in ren.items() if k in g.columns})
    g["start"] = pd.to_datetime(g["start"], utc=True)
    return g


def match_events(ev: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """One row per Kalshi event matched to a CollegeFootballData game (same Eastern date +-1 day,
    best combined name score, both teams >= 0.75)."""
    games = games.copy()
    games["et_date"] = games["start"].dt.tz_convert(EASTERN).dt.date
    rows, used = [], set()
    cands = []
    for _, e in ev.iterrows():
        d = ticker_date(e["event_ticker"])
        tickers = str(e["tickers"]).split("|")
        names = str(e["team_names"]).split("|")
        if d is None or len(tickers) != 2 or len(names) != 2:
            continue
        near = games[(games["et_date"] >= d - pd.Timedelta(days=1)) & (games["et_date"] <= d + pd.Timedelta(days=1))]
        for gi, g in near.iterrows():
            s_hh = (name_score(names[0], g["home"]), name_score(names[1], g["away"]))
            s_ha = (name_score(names[1], g["home"]), name_score(names[0], g["away"]))
            for (sh, sa), home_idx in ((s_hh, 0), (s_ha, 1)):
                if min(sh, sa) >= 0.75:
                    cands.append((sh + sa - 0.01 * abs((g["et_date"] - d).days), e["event_ticker"], gi, home_idx,
                                  min(sh, sa)))
    for score, et, gi, home_idx, worst in sorted(cands, reverse=True):
        if et in used or ("g", gi) in used:
            continue
        used.add(et)
        used.add(("g", gi))
        e = ev[ev["event_ticker"] == et].iloc[0]
        g = games.loc[gi]
        tickers = str(e["tickers"]).split("|")
        names = str(e["team_names"]).split("|")
        rows.append({"event_ticker": et, "game_id": int(g["id"]), "home": g["home"], "away": g["away"],
                     "kalshi_name_home": names[home_idx], "kalshi_name_away": names[1 - home_idx],
                     "ticker_home": tickers[home_idx], "ticker_away": tickers[1 - home_idx],
                     "scheduled_start": g["start"], "home_cls": g.get("home_cls"), "away_cls": g.get("away_cls"),
                     "match_score_worst": round(worst, 3)})
    return pd.DataFrame(rows)


def games_from_crosswalk(season: int) -> pd.DataFrame:
    """Test/dry-run source: the alignment crosswalk (no play-by-play)."""
    cw = pd.read_csv(DATA / "alignment" / "ncaaf" / str(season) / "crosswalk.csv")
    cw = cw[cw["status"] == "matched"]
    return pd.DataFrame({"event_ticker": cw["kalshi_event_ticker"], "game_id": np.nan,
                         "home": cw["home"], "away": cw["away"], "kalshi_name_home": cw["kalshi_name_home"],
                         "kalshi_name_away": cw["kalshi_name_away"], "ticker_home": cw["kalshi_ticker_home"],
                         "ticker_away": cw["kalshi_ticker_away"],
                         "scheduled_start": pd.to_datetime(cw["kickoff_utc"], utc=True),
                         "home_cls": "fbs", "away_cls": "fbs", "match_score_worst": np.nan})


# --------------------------------------------------------------------------------------
# Play-by-play
# --------------------------------------------------------------------------------------

def load_plays(folder: Path) -> pd.DataFrame:
    frames = []
    for p in sorted((folder / "cfbd").glob("plays_*.json")):
        body = json.loads(p.read_text())
        if body:
            frames.append(pd.json_normalize(body))
    if not frames:
        return pd.DataFrame()
    pl = pd.concat(frames, ignore_index=True)
    ren = {"gameId": "game_id", "playType": "play_type", "playText": "play_text", "driveId": "drive_id",
           "yardsGained": "yards_gained", "clock.minutes": "clock_min", "clock.seconds": "clock_sec"}
    pl = pl.rename(columns={k: v for k, v in ren.items() if k in pl.columns})
    if "wallclock" not in pl.columns:
        pl["wallclock"] = None
    pl["wall"] = pd.to_datetime(pl["wallclock"], utc=True, errors="coerce")
    pl = pl.drop_duplicates("id").sort_values(["game_id", "period", "clock_min", "clock_sec"],
                                                ascending=[True, True, False, False])
    return pl.reset_index(drop=True)


def classify_plays(pl: pd.DataFrame) -> pd.DataFrame:
    """Adds ``event``: touchdown / field_goal / turnover / failed_fourth (or empty)."""
    pl = pl.copy()
    pt = pl["play_type"].fillna("").str.lower()
    text = pl.get("play_text", pd.Series("", index=pl.index)).fillna("").str.lower()
    ev = np.full(len(pl), "", dtype=object)
    td = pt.str.contains("touchdown") | (pl.get("scoring", False).fillna(False).astype(bool)
                                         & text.str.contains("touchdown"))
    ev[pt.isin(FG_TYPES).to_numpy()] = "field_goal"
    ev[pt.isin(TURNOVER_TYPES).to_numpy()] = "turnover"
    ev[td.to_numpy()] = "touchdown"
    # failed fourth down: a 4th-down snap (not a punt or kick) after which the other team has the ball
    nxt_off = pl.groupby("game_id")["offense"].shift(-1)
    down = pd.to_numeric(pl.get("down"), errors="coerce")
    ff = (down == 4) & ~pt.isin(NON_SNAPS) & ~pt.str.contains("touchdown") & (nxt_off.notna()) \
        & (nxt_off != pl["offense"]) & (ev == "")
    ev[ff.to_numpy()] = "failed_fourth"
    pl["event"] = ev
    return pl


def timestamp_quality(pl: pd.DataFrame, sched: pd.Timestamp) -> tuple[bool, str, pd.Timestamp | None,
                                                                      pd.Timestamp | None]:
    """Good timestamps: >= 90% of plays have a wall clock, kickoff within -15/+45 min of the scheduled
    start, game length 2.5-5.5 h, <= 2% of consecutive plays out of order by > 2 min, no gap > 45 min."""
    n = len(pl)
    if n == 0:
        return False, "no plays", None, None
    w = pl["wall"]
    share = w.notna().mean()
    if share < 0.9:
        return False, f"wall clock on {share:.0%} of plays", None, None
    ww = w.dropna()
    k0, k1 = ww.min(), ww.max()
    off = (k0 - sched).total_seconds() / 60
    if not -15 <= off <= 45:
        return False, f"first play {off:+.0f} min from scheduled start", k0, k1
    length = (k1 - k0).total_seconds() / 3600
    if not 2.5 <= length <= 5.5:
        return False, f"game length {length:.1f} h", k0, k1
    diffs = ww.diff().dt.total_seconds().dropna()
    back = (diffs < -120).mean() if len(diffs) else 0
    if back > 0.02:
        return False, f"{back:.0%} of plays out of order", k0, k1
    if len(diffs) and diffs.max() > 45 * 60:
        return False, f"{diffs.max() / 60:.0f}-min gap between plays", k0, k1
    return True, "good", k0, k1


def load_wp(folder: Path, game_id: int) -> dict[int, float]:
    p = folder / "cfbd" / "wp" / f"{int(game_id)}.json"
    if not p.exists():
        return {}
    try:
        body = json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}
    out = {}
    for r in body or []:
        pid = r.get("playId", r.get("play_id"))
        wp = r.get("homeWinProbability", r.get("home_win_probability", r.get("home_win_prob")))
        if pid is not None and wp is not None:
            out[int(pid)] = float(wp)
    return out


# --------------------------------------------------------------------------------------
# Step 1: minute table
# --------------------------------------------------------------------------------------

def minute_end(ts: pd.Timestamp) -> int:
    """End of the minute containing ``ts`` (Unix s): a 19:42:11 play belongs to the minute ending 19:43:00."""
    s = ts.timestamp()
    return int(math.floor(s / MIN) * MIN + MIN)


def market_minutes(c: pd.DataFrame, grid: np.ndarray) -> pd.DataFrame:
    """Raw last quote at or before each grid minute, the minute's own volume, and whether a candle exists."""
    c = c.sort_values("ts")
    g = pd.DataFrame({"ts": grid})
    if c.empty:
        return g.assign(bid=np.nan, ask=np.nan, volume=0.0, has_candle=False)
    m = pd.merge_asof(g, c[["ts", "bid", "ask"]], on="ts", direction="backward")
    vol = c.groupby("ts")["volume"].sum()
    m["volume"] = g["ts"].map(vol).fillna(0.0).to_numpy()
    m["has_candle"] = g["ts"].isin(set(c["ts"])).to_numpy()
    return m


def two_sided(m: pd.DataFrame) -> pd.DataFrame:
    """bid/ask from the last valid two-sided quote; ``filled`` where the minute's own quote is not two-sided."""
    valid = m["bid"].gt(0) & m["ask"].lt(100) & m["ask"].gt(m["bid"])
    out = m.copy()
    out["filled"] = ~valid
    out.loc[~valid, ["bid", "ask"]] = np.nan
    out[["bid", "ask"]] = out[["bid", "ask"]].ffill()
    out.loc[out["bid"].isna(), "filled"] = True
    return out


def fee_cents(ask_c: np.ndarray, n: int) -> np.ndarray:
    return np.array([np.nan if not 0 < a < 100 else fee_dollars(n, a / 100) / n * 100 for a in ask_c])


def cost_per_10(mid: np.ndarray, ask: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    f = fee_cents(ask, n)
    return 10 * (1 - mid / (ask + f)), f


def build_minutes(cands: pd.DataFrame, g: pd.Series, k0: pd.Timestamp, k1: pd.Timestamp,
                  n_med: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    start = minute_end(k0)
    end = minute_end(k1)
    grid = np.arange(start - 30 * MIN, end + 1, MIN, dtype=np.int64)
    sides = {}
    info: dict[str, Any] = {}
    for side, tk in (("home", g["ticker_home"]), ("away", g["ticker_away"])):
        m = two_sided(market_minutes(cands[cands["ticker"] == tk], grid))
        ing = (m["ts"] >= start) & (m["ts"] <= end)
        info[f"{side}_filled_share"] = round(float(m.loc[ing, "filled"].mean()), 4)
        info[f"{side}_volume"] = float(m.loc[ing, "volume"].sum())
        sides[side] = m
    thin_home = (info["home_filled_share"] > info["away_filled_share"] + 0.10) or \
                (info["home_volume"] < 0.25 * info["away_volume"])
    src = "away" if thin_home else "home"
    m = sides[src]
    df = pd.DataFrame({"ts": grid})
    if src == "home":
        df["bid"], df["ask"] = m["bid"].to_numpy(), m["ask"].to_numpy()
    else:
        df["bid"], df["ask"] = 100 - m["ask"].to_numpy(), 100 - m["bid"].to_numpy()
    df["volume"] = m["volume"].to_numpy()
    df["volume_both"] = sides["home"]["volume"].to_numpy() + sides["away"]["volume"].to_numpy()
    df["filled"] = m["filled"].to_numpy()
    df["new_candle"] = m["has_candle"].to_numpy()
    df["mid"] = (df["bid"] + df["ask"]) / 2
    df["spread"] = df["ask"] - df["bid"]
    df["cost_home_per10"], df["fee_home_c"] = cost_per_10(df["mid"].to_numpy(), df["ask"].to_numpy(), n_med)
    away_mid, away_ask = 100 - df["mid"].to_numpy(), 100 - df["bid"].to_numpy()
    df["cost_away_per10"], df["fee_away_c"] = cost_per_10(away_mid, away_ask, n_med)
    df["in_game"] = (df["ts"] >= start) & (df["ts"] <= end)
    info.update({"source_market": src, "kickoff_minute": start, "end_minute": end})
    return df, info


def steady_flags(df: pd.DataFrame, rng: float) -> np.ndarray:
    mid = df["mid"]
    hi = mid.rolling(STEADY_LEN, min_periods=STEADY_LEN).max()
    lo = mid.rolling(STEADY_LEN, min_periods=STEADY_LEN).min()
    sp = df["spread"].rolling(STEADY_LEN, min_periods=STEADY_LEN).max()
    fl = df["filled"].astype(float).rolling(STEADY_LEN, min_periods=STEADY_LEN).max()
    return ((hi - lo <= rng + 1e-9) & (sp <= STEADY_SPREAD + 1e-9) & (fl == 0)).to_numpy()


def usable_d(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """d = 5-minute midpoint change, and whether the minute can be used for sigma (no filled minute at
    either end, midpoint 10-90 at both ends, in-game)."""
    mid = df["mid"].to_numpy()
    filled = df["filled"].to_numpy()
    d = mid - np.roll(mid, D_LAG)
    d[:D_LAG] = np.nan
    prev_f = np.roll(filled, D_LAG)
    prev_f[:D_LAG] = True
    prev_mid = np.roll(mid, D_LAG)
    ok = (df["in_game"].to_numpy() & ~filled & ~prev_f & (mid >= MID_LO) & (mid <= MID_HI)
          & (prev_mid >= MID_LO) & (prev_mid <= MID_HI) & ~np.isnan(d))
    return d, ok


def mad_sigma(d: np.ndarray) -> float:
    if len(d) == 0:
        return float("nan")
    return float(MAD_SCALE * np.median(np.abs(d - np.median(d))))


# --------------------------------------------------------------------------------------
# Steps 3-4: swings and steady times
# --------------------------------------------------------------------------------------

@dataclass
class GameState:
    key: str
    df: pd.DataFrame
    info: dict[str, Any]
    events: pd.DataFrame = field(default_factory=pd.DataFrame)
    sigma: float = float("nan")
    sigma_note: str = ""


def find_swings(st: GameState, thr: float, rng: float) -> list[dict[str, Any]]:
    df = st.df
    mid = df["mid"].to_numpy()
    ts = df["ts"].to_numpy()
    filled = df["filled"].to_numpy()
    in_game = df["in_game"].to_numpy()
    n = len(df)
    d, _ = usable_d(df)
    fwd = np.full(n, np.nan)
    fwd[D_LAG:n - HOLD_LAG] = mid[D_LAG + HOLD_LAG:] - mid[:n - D_LAG - HOLD_LAG]
    prev_f = np.roll(filled, D_LAG)
    prev_f[:D_LAG] = True
    with np.errstate(invalid="ignore"):
        flag = (in_game & ~filled & ~prev_f & (np.abs(d) > thr) & (fwd * np.sign(d) >= HOLD_SHARE * thr)
                & (mid >= MID_LO) & (mid <= MID_HI))
    df["flagged"] = flag
    steady = steady_flags(df, rng) & in_game
    df["steady"] = steady
    idx = np.flatnonzero(flag)
    groups: list[list[int]] = []
    for i in idx:
        if groups and i - groups[-1][-1] <= GROUP_GAP_MIN:
            groups[-1].append(i)
        else:
            groups.append([i])
    jump = np.abs(np.diff(mid, prepend=np.nan))
    swings = []
    for gi, grp in enumerate(groups):
        f = grp[0]
        t = max(grp, key=lambda i: (np.nan_to_num(jump[i]), -i))
        base = mid[f - D_LAG]
        move = [s for s in range(f - D_LAG + 1, t + 1) if abs(mid[s] - base) >= 1]
        s0 = move[0] if move else f
        peak_z = float(np.nanmax(np.abs(d[grp])) / st.sigma)
        swings.append({"i_first": f, "i_last": grp[-1], "i_t": t, "i_start": s0, "base": base, "peak_z": peak_z})
    out = []
    for j, sw in enumerate(swings):
        t, s0 = sw["i_t"], sw["i_start"]
        lo_b = max(0, t - MAX_FROM_T)
        b_c = [i for i in range(s0 - 1, lo_b - 1, -1) if steady[i]]
        b = b_c[0] if b_c else None
        a = None
        hi_a = min(n - 1, t + MAX_FROM_T)
        for i in range(t + 1, hi_a + 1):
            if steady[i] and (b is None or abs(df["spread"].iat[i] - df["spread"].iat[b]) <= AFTER_SPREAD_TOL + 1e-9):
                a = i
                break
        reason = ""
        if b is None:
            reason = "no steady before time within 20 min"
        elif a is None:
            reason = "no steady after time within 20 min"
        elif j + 1 < len(swings) and swings[j + 1]["i_start"] <= a:
            reason = "next swing starts before the after time"
        elif j > 0 and swings[j - 1]["i_last"] >= b:
            reason = "previous swing is after the before time"
        elif abs(mid[a] - mid[b]) < SETTLED_SHARE * thr:
            reason = "move reversed: settled change under half the threshold"
        vol10 = float(df["volume_both"].iloc[max(0, t - 5):t + 6].sum())
        size = (mid[a] - mid[b]) if (a is not None and b is not None) else (mid[min(n - 1, t + HOLD_LAG)] - sw["base"])
        out.append({
            "swing_id": f"{st.key}-S{j + 1:02d}", "t_utc": iso(ts[t]), "t_ts": int(ts[t]),
            "first_flag_utc": iso(ts[sw["i_first"]]), "move_start_utc": iso(ts[s0]),
            "mid_at_start": round(sw["base"], 2), "mid_at_t": round(mid[t], 2),
            "mid_before": None if b is None else round(mid[b], 2), "mid_after": None if a is None else round(mid[a], 2),
            "size_move": round(float(size), 2), "abs_move": round(abs(float(size)), 2),
            "before_utc": None if b is None else iso(ts[b]), "after_utc": None if a is None else iso(ts[a]),
            "before_ts": None if b is None else int(ts[b]), "after_ts": None if a is None else int(ts[a]),
            "min_before_to_t": None if b is None else int((ts[t] - ts[b]) // MIN),
            "minutes_to_settle": None if a is None else int((ts[a] - ts[t]) // MIN),
            "sigma_game": round(st.sigma, 3), "threshold": round(thr, 3), "peak_z": round(sw["peak_z"], 2),
            "kalshi_volume_10min": round(vol10, 2), "rank_score": round(abs(float(size)) * vol10, 1),
            "status": "kept" if not reason else "dropped", "drop_reason": reason,
        })
    return out


def iso(ts: int | float) -> str:
    return pd.Timestamp(int(ts), unit="s", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------------------

def n_med(season: int, league: str) -> tuple[int, str]:
    """Median Kalshi game-winner trade size (contracts, block trades excluded) for the season; a season
    without its own file uses the other season's."""
    folder, grp = (DATA / "alignment" / "ncaaf", "KXNCAAFGAME") if league == "ncaaf" else (DATA / "alignment", "KXNFLGAME")
    for yr in (season, season + 1, season - 1):
        p = folder / f"trade_sizes_{yr}.json"
        if p.exists():
            stats = json.loads(p.read_text()).get("stats", {})
            s = (stats.get(grp) or {}).get("excluding block trades", {}).get("per_trade", {})
            if s.get("p50"):
                note = "" if yr == season else f" (no {season} file: {yr} sizes)"
                return max(1, math.ceil(s["p50"])), f"{p.name}, {grp}, median per trade excl. blocks ({s['p50']}){note}"
    return 24, "fallback 24 (trade_sizes file not found)"


# --------------------------------------------------------------------------------------
# League loaders: one games frame and one plays frame with the same columns for both leagues
#   games: event_ticker, game_id, season, season_type, week, home, away, ticker_home, ticker_away,
#          scheduled_start, kalshi_name_home, kalshi_name_away
#   plays: game_id, id, wall, event, wp_home, play_text
# --------------------------------------------------------------------------------------

NFL_CODE = {"JAC": "JAX", "LAR": "LA", "WSH": "WAS", "OAK": "LV", "SD": "LAC", "STL": "LA"}
NFL_TICKER = re.compile(r"^KXNFLGAME-(\d{2})([A-Z]{3})(\d{2})([A-Z]+)$")


def nfl_events_events(season: int) -> pd.DataFrame:
    f = out_dir(season, "nfl")
    frames = [pd.read_csv(p) for p in (f / "events_task3.csv", f / "events.csv") if p.exists()]
    return pd.concat(frames).drop_duplicates("event_ticker") if frames else pd.DataFrame()


def load_nfl(seasons: list[int]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    games, plays, log = [], [], {}
    for season in seasons:
        pbp_path = DATA / "ingame" / "nfl" / "pbp" / f"pbp_{season}.csv.gz"
        if not pbp_path.exists():
            raise SystemExit(f"{pbp_path} is missing (nflverse play_by_play_{season}.csv.gz).")
        cols = ["game_id", "play_id", "season_type", "week", "home_team", "away_team", "game_date", "time_of_day", "start_time",
                "desc", "play_type", "touchdown", "interception", "fumble_lost", "fourth_down_failed",
                "field_goal_result", "home_wp", "qtr"]
        pbp = pd.read_csv(pbp_path, usecols=cols, low_memory=False)
        gl = pbp.groupby("game_id").first()[["season_type", "week", "home_team", "away_team", "game_date",
                                             "start_time"]].reset_index()
        # nflverse start_time is Eastern ("9/7/25, 13:02:38"): the game's listed start
        gl["start_utc"] = pd.to_datetime(gl["start_time"], format="%m/%d/%y, %H:%M:%S", errors="coerce") \
            .dt.tz_localize(EASTERN, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
        gl["game_date"] = pd.to_datetime(gl["game_date"]).dt.date
        ev = nfl_events_events(season)
        rows, unmatched = [], []
        for _, e in ev.iterrows():
            m = NFL_TICKER.match(str(e["event_ticker"]))
            d = ticker_date(str(e["event_ticker"]))
            tks = str(e["tickers"]).split("|")
            if not m or d is None or len(tks) != 2:
                unmatched.append((e["event_ticker"], "ticker format"))
                continue
            codes = {t.rsplit("-", 1)[1]: t for t in tks}
            nfl = {NFL_CODE.get(c, c): t for c, t in codes.items()}
            cand = gl[(gl["home_team"].isin(nfl)) & (gl["away_team"].isin(nfl))
                      & (gl["game_date"].map(lambda x: abs((x - d).days) <= 1))]
            if len(cand) != 1:
                unmatched.append((e["event_ticker"], "no nflverse game (preseason or not played)" if cand.empty
                                  else "two nflverse games"))
                continue
            g = cand.iloc[0]
            names = dict(zip(tks, str(e.get("team_names", "")).split("|")))
            th, ta = nfl[g["home_team"]], nfl[g["away_team"]]
            kick = pd.Timestamp(int(e["kickoff_ts"]), unit="s", tz="UTC")
            est = str(e.get("kickoff_source", "")).startswith("estimated")
            if est and pd.notna(g["start_utc"]):
                kick, ksrc = g["start_utc"], "nflverse start_time (Task 3 kickoff was estimated)"
            else:
                ksrc = f"Task 3 ({e.get('kickoff_source')})"
            rows.append({"event_ticker": e["event_ticker"], "game_id": g["game_id"], "season": season,
                         "season_type": g["season_type"], "week": int(g["week"]), "home": g["home_team"],
                         "away": g["away_team"], "ticker_home": th, "ticker_away": ta,
                         "kalshi_name_home": names.get(th), "kalshi_name_away": names.get(ta),
                         "scheduled_start": kick, "scheduled_start_source": ksrc})
        games.append(pd.DataFrame(rows))
        log[str(season)] = {"kalshi_events": len(ev), "matched_to_nflverse": len(rows),
                            "nflverse_games": int(len(gl)),
                            "nflverse_games_without_kalshi_event": int(len(set(gl["game_id"]) - {r["game_id"] for r in rows})),
                            "unmatched_reasons": pd.Series([u[1] for u in unmatched]).value_counts().to_dict()}
        p = pbp.copy()
        p["wall"] = pd.to_datetime(p["time_of_day"], utc=True, errors="coerce", format="ISO8601")
        tov = (p["interception"] == 1) | (p["fumble_lost"] == 1)
        ev_lab = np.full(len(p), "", dtype=object)
        ev_lab[(p["fourth_down_failed"] == 1).to_numpy()] = "failed_fourth"
        ev_lab[(p["field_goal_result"] == "made").to_numpy()] = "field_goal"
        ev_lab[(p["touchdown"] == 1).to_numpy()] = "touchdown"
        ev_lab[tov.to_numpy()] = "turnover"   # a pick-six or fumble-return TD counts as the turnover
        p["event"] = ev_lab
        p["touchdown_flag"] = p["touchdown"] == 1
        p["wp_home"] = p["home_wp"]
        p["play_text"] = p["desc"]
        p["id"] = p["game_id"] + "_" + p["play_id"].astype("Int64").astype(str)
        plays.append(p[["game_id", "id", "wall", "event", "touchdown_flag", "wp_home", "play_text", "play_type", "qtr"]])
    return pd.concat(games, ignore_index=True), pd.concat(plays, ignore_index=True), log


def load_ncaaf(seasons: list[int], games_from: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    games, plays, log = [], [], {}
    for season in seasons:
        folder = out_dir(season, "ncaaf")
        if games_from == "crosswalk":
            g = games_from_crosswalk(season)
            log[str(season)] = {"dry_run_from_crosswalk": len(g)}
            pl = pd.DataFrame()
        else:
            ev, cg = load_events(folder), load_cfbd_games(folder)
            if cg.empty:
                raise SystemExit(f"No CollegeFootballData games in {folder / 'cfbd'}: run swing_data pull first.")
            g = match_events(ev, cg)
            n = len(g)
            g = g[(g["home_cls"] == "fbs") | (g["away_cls"] == "fbs")]
            log[str(season)] = {"kalshi_events": len(ev), "matched": n, "with_fbs_team": len(g)}
            pl = classify_plays(load_plays(folder))
            cfbd_folder = folder
            if not pl.empty:
                wp = {}
                for gid in g["game_id"].dropna().unique():
                    wp.update({(int(gid), k): v for k, v in load_wp(cfbd_folder, gid).items()})
                pl["wp_home"] = [wp.get((int(a), int(b))) for a, b in zip(pl["game_id"], pl["id"])]
                pl["touchdown_flag"] = pl["event"] == "touchdown"
                pl = pl[["game_id", "id", "wall", "event", "touchdown_flag", "wp_home", "play_text"]]
        g = g.assign(season=season, season_type="", week=np.nan)
        games.append(g)
        plays.append(pl)
    return pd.concat(games, ignore_index=True), pd.concat(plays, ignore_index=True), log


def run(seasons: list[int], games_from: str, steady_range: float, pct_main: float = 99.0,
        league: str = "ncaaf") -> int:
    out = DATA / "ingame" / league / "out"
    out.mkdir(parents=True, exist_ok=True)
    nms = {s: n_med(s, league) for s in seasons}
    for s_, (nm, src) in nms.items():
        print(f"{s_}: n_med = {nm} ({src})")
    if league == "nfl":
        games, plays, load_log = load_nfl(seasons)
    else:
        games, plays, load_log = load_ncaaf(seasons, games_from)
    print(json.dumps(load_log, default=str))

    states: list[GameState] = []
    glog = []
    for _, g in games.iterrows():
        cpath = out_dir(int(g["season"]), league) / "candles" / f"{g['event_ticker']}.csv.gz"
        nm = nms[int(g["season"])][0]
        row = {"event_ticker": g["event_ticker"], "game_id": g["game_id"], "season": int(g["season"]),
               "season_type": g.get("season_type"), "week": g.get("week"), "home": g["home"],
               "away": g["away"], "scheduled_start_utc": g["scheduled_start"].strftime("%Y-%m-%dT%H:%M:%SZ"),
               "scheduled_start_source": g.get("scheduled_start_source")}
        if not cpath.exists():
            glog.append({**row, "status": "no candles"})
            continue
        gp = plays[plays["game_id"] == g["game_id"]] if not plays.empty else pd.DataFrame()
        good, why, k0, k1 = timestamp_quality(gp, g["scheduled_start"]) if not gp.empty else (False, "no plays", None, None)
        cands = pd.read_csv(cpath)
        times_src = "play-by-play"
        if k0 is None or k1 is None or not good:
            # kickoff = scheduled start; final whistle = last minute the price is still undecided (2-98),
            # within 5.5 h of kickoff
            k0 = g["scheduled_start"]
            k1, times_src = kalshi_end(cands, g, k0), "scheduled start / Kalshi price"
        df, info = build_minutes(cands, g, k0, k1, nm)
        key = (str(g["game_id"]) if league == "nfl" else str(int(g["game_id"]))) if pd.notna(g["game_id"]) \
            else g["event_ticker"]
        st = GameState(key, df, {**row, **info, "good_timestamps": good, "timestamp_check": why,
                                 "game_times_from": times_src, "kickoff_utc": iso(info["kickoff_minute"]),
                                 "final_whistle_utc": iso(info["end_minute"])})
        if good and not gp.empty:
            e = gp[gp["event"] != ""].dropna(subset=["wall"]).copy()
            e["minute_ts"] = [minute_end(w) for w in e["wall"]]
            st.events = e
        states.append(st)
        glog.append({**st.info, "status": "used"})

    # Step 2: sigma per game and k
    quiet_z_rows = []
    for st in states:
        d, ok = usable_d(st.df)
        ts = st.df["ts"].to_numpy()
        if st.info["good_timestamps"]:
            ev_ts = st.events["minute_ts"].to_numpy() if not st.events.empty else np.array([])
            near = np.zeros(len(ts), bool)
            for e in ev_ts:
                near |= np.abs(ts - e) <= QUIET_GAP_MIN * MIN
            quiet = st.df["in_game"].to_numpy() & ~near
            st.df["quiet"] = quiet
            qd = d[quiet & ok]
            st.info["quiet_minutes"] = int(len(qd))
            st.sigma = mad_sigma(qd) if len(qd) >= MIN_QUIET else float("nan")
        else:
            st.df["quiet"] = pd.NA
            ad = d[ok]
            st.info["quiet_minutes"] = None
            st.sigma = mad_sigma(ad) if len(ad) >= MIN_QUIET else float("nan")
            st.sigma_note = "all usable minutes (no good play timestamps)"
    raw = np.array([s.sigma for s in states if np.isfinite(s.sigma)])
    league_med = float(np.median(np.maximum(raw, SIGMA_FLOOR))) if len(raw) else SIGMA_FLOOR
    for st in states:
        notes = [st.sigma_note] if st.sigma_note else []
        if not np.isfinite(st.sigma):
            st.sigma = league_med
            notes.append(f"under {MIN_QUIET} usable minutes: league median sigma")
        elif st.sigma < SIGMA_FLOOR:
            notes.append(f"floor: MAD sigma {st.sigma:.2f} raised to {SIGMA_FLOOR}")
            st.sigma = SIGMA_FLOOR
        st.sigma_note = "; ".join(notes)
        st.info["sigma_game"] = round(st.sigma, 4)
        st.info["sigma_note"] = st.sigma_note
        if st.info["good_timestamps"]:
            d, ok = usable_d(st.df)
            q = st.df["quiet"].to_numpy(dtype=bool) & ok
            for z in np.abs(d[q]) / st.sigma:
                quiet_z_rows.append(z)
    qz = np.array(quiet_z_rows)
    good_games = sum(1 for s in states if s.info["good_timestamps"])
    if len(qz) == 0:
        print("No quiet minutes from games with good play timestamps: k cannot be set from the data.",
              file=sys.stderr)
        if games_from != "crosswalk":
            return 2
        # dry run only: k from all usable minutes of all games (clearly labelled)
        for st in states:
            d, ok = usable_d(st.df)
            qz = np.concatenate([qz, np.abs(d[ok]) / st.sigma])
    ks = {p: float(np.percentile(qz, p)) for p in PCTS}
    k = ks[pct_main]
    print("k: " + ", ".join(f"p{p:g} = {v:.3f}" for p, v in ks.items()) + f" from {len(qz):,} minutes, "
          f"{good_games} games with good play timestamps")

    # Steps 3-4
    swings = []
    for st in states:
        sw = find_swings(st, k * st.sigma, steady_range)
        for s in sw:
            s.update({"event_ticker": st.info["event_ticker"], "game_id": st.info["game_id"],
                      "season": st.info["season"], "season_type": st.info["season_type"], "week": st.info["week"],
                      "home": st.info["home"], "away": st.info["away"], "good_timestamps": st.info["good_timestamps"]})
        swings += sw
        st.info["swings"] = len(sw)
        st.info["swings_kept"] = sum(1 for s in sw if s["status"] == "kept")
    sw = pd.DataFrame(swings)
    sens = {}
    for p, kv in ks.items():   # swing counts and check rates at the other thresholds (paper robustness)
        alt = []
        for st in states:
            r = find_swings(GameState(st.key, st.df.copy(), st.info, st.events, st.sigma), kv * st.sigma, steady_range)
            for x in r:
                x["event_ticker"] = st.info["event_ticker"]
            alt += r
        alt_df = pd.DataFrame(alt)
        if len(alt_df):
            match_cols(alt_df, states)
            rr = rates(alt_df, states).get(f"within_{MATCH_MIN}_min", {})
        else:
            rr = {}
        sens[f"p{p:g}"] = {"k": round(kv, 4), "swings": len(alt), "kept": sum(1 for x in alt if x["status"] == "kept"),
                           "catch_rate_3min": rr.get("catch_rate"), "match_rate_3min": rr.get("match_rate")}
    # restore flags for the main threshold
    for st in states:
        find_swings(st, k * st.sigma, steady_range)

    # Step 5 checks
    match_cols(sw, states)
    checks = rates(sw, states)

    # outputs
    mt = []
    for st in states:
        d, _ = usable_d(st.df)
        x = st.df[st.df["in_game"]].copy()
        x.insert(0, "event_ticker", st.info["event_ticker"])
        x.insert(1, "game_id", st.info["game_id"])
        x.insert(2, "minute_utc", [iso(v) for v in x["ts"]])
        x["source_market"] = st.info["source_market"]
        x["d5"] = d[st.df["in_game"].to_numpy()]
        mt.append(x)
    minutes = pd.concat(mt, ignore_index=True) if mt else pd.DataFrame()
    num = minutes.select_dtypes("float").columns
    minutes[num] = minutes[num].round(4)
    season_of = {s.info["event_ticker"]: s.info["season"] for s in states}
    for s_ in seasons:
        minutes[minutes["event_ticker"].map(season_of) == s_].to_csv(out / f"kalshi_minutes_{league}_{s_}.csv", index=False)
    gdf = pd.DataFrame(glog)
    used = pd.DataFrame([s.info for s in states])
    gdf = gdf.drop(columns=[c for c in gdf.columns if c in used.columns and c not in ("event_ticker",)], errors="ignore") \
        .merge(used, on="event_ticker", how="left") if not used.empty else gdf
    gdf.to_csv(out / f"games_{league}.csv", index=False)
    sw.to_csv(out / f"swings_{league}.csv", index=False)
    at = kalshi_at_swings(sw, states)
    at.to_csv(out / f"kalshi_at_swings_{league}.csv", index=False)
    summ = {"all": summaries(sw, at)}
    for s_ in seasons:
        summ[str(s_)] = summaries(sw[sw["season"] == s_], at[at["swing_id"].isin(sw.loc[sw["season"] == s_, "swing_id"])]) \
            if len(sw) else {}
    sig = used["sigma_game"] if not used.empty else pd.Series(dtype=float)
    thr = {
        "league": league, "seasons": seasons, "load": load_log, "games_used": len(states),
        "games_used_by_season": {str(s_): sum(1 for s in states if s.info["season"] == s_) for s_ in seasons}, "games_with_good_timestamps": good_games,
        "quiet_minutes": int(len(qz)) if len(quiet_z_rows) else 0,
        "k": {f"p{p:g}": round(v, 4) for p, v in ks.items()}, "k_main": f"p{pct_main:g}",
        "threshold_points_median_game": round(float(np.median(sig * k)), 3) if len(sig) else None,
        "sigma_game": {"min": round(float(sig.min()), 3), "median": round(float(sig.median()), 3),
                       "max": round(float(sig.max()), 3)} if len(sig) else None,
        "sigma_by_source": {
            "good timestamps (quiet minutes)": round(float(used.loc[used.good_timestamps, "sigma_game"].median()), 3)
            if good_games else None,
            "no good timestamps (all minutes)": round(float(used.loc[~used.good_timestamps, "sigma_game"].median()), 3)
            if (~used.good_timestamps).any() else None},
        "games_floor": used.loc[used.sigma_note.str.contains("floor"), "event_ticker"].tolist() if len(used) else [],
        "games_league_median": used.loc[used.sigma_note.str.contains("league median"), "event_ticker"].tolist()
        if len(used) else [],
        "sensitivity": sens, "steady_range_points": steady_range,
        "n_med": {str(k_): {"n": v[0], "source": v[1]} for k_, v in nms.items()},
        "checks": checks, "dry_run": games_from == "crosswalk",
    }
    (out / f"threshold_{league}.json").write_text(json.dumps(thr, indent=2, default=str))
    (out / f"threshold_{league}.md").write_text(threshold_md(thr))
    (out / f"summaries_{league}.json").write_text(json.dumps(summ, indent=2, default=str))
    plots(states, sw, out, n=5 if league == "nfl" else 3)
    print(json.dumps({"swings": len(sw), "kept": int((sw.status == "kept").sum()) if len(sw) else 0,
                      "checks": checks}, indent=1, default=str))
    return 0


def threshold_md(t: dict[str, Any]) -> str:
    c3, c5 = t["checks"].get("within_3_min", {}), t["checks"].get("within_5_min", {})
    pct = lambda v: "n/a" if v is None else f"{v:.1%}"  # noqa: E731
    sens = "".join(f"| {p} | {v['k']:.3f} | {v['swings']} | {v['kept']} | {pct(v.get('catch_rate_3min'))} | "
                   f"{pct(v.get('match_rate_3min'))} |\n" for p, v in t["sensitivity"].items())
    by_t = c3.get("by_type", {})
    return (f"# Swing threshold ({t['league']}, seasons {', '.join(map(str, t['seasons']))})\n\n"
            f"Games used: {t['games_used']} ({', '.join(f'{k} {v}' for k, v in t['games_used_by_season'].items())}); "
            f"with good play timestamps: {t['games_with_good_timestamps']}. k comes from {t['quiet_minutes']:,} quiet "
            f"minutes of those games.\n\n"
            f"| Percentile | k | Swings | Kept | Catch rate (3 min) | Match rate (3 min) |\n|---|---|---|---|---|---|\n{sens}\n"
            f"Main threshold: {t['k_main']}. At it: catch rate {pct(c3.get('catch_rate'))} of {c3.get('plays_checked')} "
            f"touchdowns and turnovers at 20-80% win probability (touchdowns {by_t.get('touchdown', {}).get('caught')}/"
            f"{by_t.get('touchdown', {}).get('plays')}, turnovers {by_t.get('turnover', {}).get('caught')}/"
            f"{by_t.get('turnover', {}).get('plays')}); match rate {pct(c3.get('match_rate'))} of "
            f"{c3.get('swings_checked')} swings. Within 5 minutes: catch {pct(c5.get('catch_rate'))}, match "
            f"{pct(c5.get('match_rate'))}.\n\n"
            f"sigma_game: min {t['sigma_game']['min']}, median {t['sigma_game']['median']}, max {t['sigma_game']['max']} "
            f"points; threshold in the median game {t['threshold_points_median_game']} points.\n\n"
            f"1-point floor used: {', '.join(t['games_floor']) or 'none'}.\n\n"
            f"League-median sigma used ({len(t['games_league_median'])} games, under {MIN_QUIET} usable quiet minutes): "
            f"{', '.join(t['games_league_median']) or 'none'}.\n\n"
            f"Steady range {t['steady_range_points']} points; n_med {json.dumps(t['n_med'])}.\n")


def kalshi_end(cands: pd.DataFrame, g: pd.Series, k0: pd.Timestamp) -> pd.Timestamp:
    tk = g["ticker_home"] if (cands["ticker"] == g["ticker_home"]).any() else g["ticker_away"]
    c = cands[(cands["ticker"] == tk) & (cands["ts"] >= k0.timestamp()) & (cands["ts"] <= k0.timestamp() + 5.5 * 3600)]
    c = c[c["bid"].gt(0) & c["ask"].lt(100)]
    mid = (c["bid"] + c["ask"]) / 2
    live = c.loc[(mid > 2) & (mid < 98), "ts"]
    if live.empty:
        return k0 + pd.Timedelta(hours=3.5)
    return pd.Timestamp(int(live.max()), unit="s", tz="UTC")


def match_cols(sw: pd.DataFrame, states: list[GameState]) -> None:
    """Nearest real play (touchdown, field goal, turnover, failed fourth down) to each swing's t."""
    by = {s.info["event_ticker"]: s for s in states}
    near_type, near_gap, near_text = [], [], []
    for _, r in sw.iterrows():
        st = by[r["event_ticker"]]
        if st.events.empty or not st.info["good_timestamps"]:
            near_type.append(None), near_gap.append(None), near_text.append(None)
            continue
        gap = (st.events["minute_ts"] - r["t_ts"]) / MIN
        j = gap.abs().idxmin()
        near_type.append(st.events.at[j, "event"])
        near_gap.append(int(gap[j]))
        near_text.append(str(st.events.at[j, "play_text"])[:160] if "play_text" in st.events else None)
    if len(sw):
        sw["nearest_play"] = near_type
        sw["nearest_play_min_from_t"] = near_gap
        sw["nearest_play_text"] = near_text
        ok = sw["nearest_play_min_from_t"].abs() <= MATCH_MIN
        sw["matched_play"] = sw["nearest_play"].where(ok)
        sw["matched_play_text"] = sw["nearest_play_text"].where(ok)


def rates(sw: pd.DataFrame, states: list[GameState]) -> dict[str, Any]:
    good = [s for s in states if s.info["good_timestamps"] and not s.events.empty]
    if not good:
        return {"note": "no games with good play timestamps: catch and match rates need play-by-play"}
    out: dict[str, Any] = {}
    for tol in (MATCH_MIN, 5):
        caught = total = 0
        wp_src = {"play_by_play": 0, "kalshi_mid_fallback": 0}
        by_type = {"touchdown": [0, 0], "turnover": [0, 0]}
        for st in good:
            ts_sw = sw.loc[sw["event_ticker"] == st.info["event_ticker"], "t_ts"].to_numpy() if len(sw) else np.array([])
            mid_by_ts = dict(zip(st.df["ts"], st.df["mid"]))
            for _, e in st.events[st.events["event"].isin(["touchdown", "turnover"])].iterrows():
                wp = e.get("wp_home")
                if wp is None or (isinstance(wp, float) and np.isnan(wp)):
                    m = mid_by_ts.get(e["minute_ts"] - MIN)
                    if m is None:
                        continue
                    wp = m / 100
                    wp_src["kalshi_mid_fallback"] += 1
                else:
                    wp_src["play_by_play"] += 1
                if not WP_LO <= wp <= WP_HI:
                    continue
                hit = bool(len(ts_sw)) and bool((np.abs(ts_sw - e["minute_ts"]) <= tol * MIN).any())
                total += 1
                caught += hit
                by_type[e["event"]][0] += hit
                by_type[e["event"]][1] += 1
        sw_good = sw[sw["event_ticker"].isin([s.info["event_ticker"] for s in good])] if len(sw) else sw
        if len(sw_good):
            gaps = sw_good["nearest_play_min_from_t"].abs()
            match = float((gaps <= tol).mean())
        else:
            match = float("nan")
        out[f"within_{tol}_min"] = {
            "catch_rate": round(caught / total, 4) if total else None, "plays_checked": total,
            "caught": caught, "by_type": {k: {"caught": v[0], "plays": v[1]} for k, v in by_type.items()},
            "wp_source": wp_src,
            "match_rate": round(match, 4) if match == match else None, "swings_checked": int(len(sw_good)),
        }
    return out


def kalshi_at_swings(sw: pd.DataFrame, states: list[GameState]) -> pd.DataFrame:
    by = {s.info["event_ticker"]: s for s in states}
    rows = []
    for _, r in sw.iterrows():
        st = by[r["event_ticker"]]
        df = st.df.set_index("ts")
        for kind in ("before", "after"):
            t = r[f"{kind}_ts"]
            if t is None or (isinstance(t, float) and np.isnan(t)):
                continue
            x = df.loc[int(t)]
            for team, side in ((st.info["home"], "home"), (st.info["away"], "away")):
                if side == "home":
                    bid, ask, mid, cost, fee = x["bid"], x["ask"], x["mid"], x["cost_home_per10"], x["fee_home_c"]
                else:
                    bid, ask, mid, cost, fee = 100 - x["ask"], 100 - x["bid"], 100 - x["mid"], x["cost_away_per10"], x["fee_away_c"]
                rows.append({"swing_id": r["swing_id"], "event_ticker": r["event_ticker"],
                             "game_id": r["game_id"], "status": r["status"], "kind": kind,
                             "time_utc": iso(t), "team": team, "side": side, "bid": round(bid, 2),
                             "ask": round(ask, 2), "midpoint": round(mid, 2), "spread": round(ask - bid, 2),
                             "fee_per_contract_c": round(fee, 4), "cost_per_10": round(cost, 4),
                             "abs_move": r["abs_move"], "source_market": st.info["source_market"]})
    return pd.DataFrame(rows)


def summaries(sw: pd.DataFrame, at: pd.DataFrame) -> dict[str, Any]:
    if sw.empty:
        return {}
    kept = sw[sw["status"] == "kept"]
    a = at[at["status"] == "kept"]
    out: dict[str, Any] = {
        "swings_found": int(len(sw)), "swings_kept": int(len(kept)),
        "dropped_by_reason": sw.loc[sw.status == "dropped", "drop_reason"].value_counts().to_dict(),
        "median_minutes_to_settle_kept": float(kept["minutes_to_settle"].median()) if len(kept) else None,
        "minutes_to_settle_kept_p25_p75": [float(kept["minutes_to_settle"].quantile(q)) for q in (0.25, 0.75)]
        if len(kept) else None,
        "median_minutes_to_settle_all_with_after": float(sw["minutes_to_settle"].dropna().median())
        if sw["minutes_to_settle"].notna().any() else None,
        "median_cost_per_10": {k: round(float(a.loc[a.kind == k, "cost_per_10"].median()), 4) for k in ("before", "after")}
        if len(a) else None,
        "median_spread_c": {k: round(float(a.loc[a.kind == k, "spread"].median()), 3) for k in ("before", "after")}
        if len(a) else None,
    }
    if len(a):
        bins = [0, 10, 20, 30, 101]
        labels = ["<10 pts", "10-20 pts", "20-30 pts", "30+ pts"]
        a = a.assign(size_bin=pd.cut(a["abs_move"], bins, labels=labels, right=False))
        k2 = kept.assign(size_bin=pd.cut(kept["abs_move"], bins, labels=labels, right=False))
        by = {}
        for lab in labels:
            x = a[a.size_bin == lab]
            by[lab] = {"swings": int((k2.size_bin == lab).sum()),
                       "median_cost_before": round(float(x.loc[x.kind == "before", "cost_per_10"].median()), 4) if len(x) else None,
                       "median_cost_after": round(float(x.loc[x.kind == "after", "cost_per_10"].median()), 4) if len(x) else None,
                       "median_minutes_to_settle": float(k2.loc[k2.size_bin == lab, "minutes_to_settle"].median())
                       if (k2.size_bin == lab).any() else None}
        out["by_swing_size"] = by
        if "matched_play" in kept:
            bt = {}
            for typ in ("touchdown", "turnover", "field_goal", "failed_fourth"):
                ids = kept.loc[kept["matched_play"] == typ, "swing_id"]
                x = a[a["swing_id"].isin(ids)]
                bt[typ] = {"swings": int(len(ids)),
                           "median_cost_before": round(float(x.loc[x.kind == "before", "cost_per_10"].median()), 4) if len(x) else None,
                           "median_cost_after": round(float(x.loc[x.kind == "after", "cost_per_10"].median()), 4) if len(x) else None,
                           "median_abs_move": float(kept.loc[kept["swing_id"].isin(ids), "abs_move"].median()) if len(ids) else None,
                           "median_minutes_to_settle": float(kept.loc[kept["swing_id"].isin(ids), "minutes_to_settle"].median())
                           if len(ids) else None}
            bt["no play within 3 min"] = {"swings": int(kept["matched_play"].isna().sum())}
            out["by_play_type"] = bt
        # paired: same swing and team, after minus before
        p = a.pivot_table(index=["swing_id", "side"], columns="kind", values="cost_per_10")
        if {"before", "after"} <= set(p.columns):
            diff = (p["after"] - p["before"]).dropna()
            out["paired_after_minus_before_cost_per_10"] = {"median": round(float(diff.median()), 4),
                                                             "mean": round(float(diff.mean()), 4), "n": int(len(diff))}
    return out


def plots(states: list[GameState], sw: pd.DataFrame, out: Path, n: int = 3) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    good = [s for s in states if s.info["good_timestamps"] and not s.events.empty]
    pool = good if good else states
    scored = []
    for s in pool:
        x = sw[sw["event_ticker"] == s.info["event_ticker"]] if len(sw) else sw
        scored.append(((x["status"] == "kept").sum() if len(x) else 0, len(x), s))
    scored.sort(key=lambda r: (-r[0], -r[1], r[2].info["event_ticker"]))
    # three games with the most kept swings, spread across the season (not three from one week)
    picks: list[GameState] = []
    for _, _, s in scored:
        if all(abs(s.info["kickoff_minute"] - p.info["kickoff_minute"]) > 5 * 86400 for p in picks):
            picks.append(s)
        if len(picks) == n:
            break
    for s in picks:
        df = s.df[s.df["in_game"]]
        x = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(EASTERN)
        fig, ax = plt.subplots(figsize=(11, 4.2))
        ax.plot(x, df["mid"], color="#222", lw=1.2, label="Kalshi midpoint (home)")
        filled = df["filled"].to_numpy()
        if filled.any():
            ax.scatter(x[filled], df["mid"][filled], s=6, color="#bbb", label="filled minute", zorder=2)
        colors = {"touchdown": "#1a9850", "turnover": "#d73027", "field_goal": "#7570b3", "failed_fourth": "#e6ab02"}
        if not s.events.empty:
            for typ, col in colors.items():
                e = s.events[s.events["event"] == typ]
                for i, t in enumerate(e["minute_ts"]):
                    ax.axvline(pd.Timestamp(int(t), unit="s", tz="UTC").tz_convert(EASTERN), color=col, lw=0.8,
                               ls="--", alpha=0.7, label=typ.replace("_", " ") if i == 0 else None)
        xs = sw[sw["event_ticker"] == s.info["event_ticker"]] if len(sw) else sw
        to_dt = lambda v: pd.Timestamp(int(v), unit="s", tz="UTC").tz_convert(EASTERN)  # noqa: E731
        mid_by = dict(zip(s.df["ts"], s.df["mid"]))
        for i, (_, r) in enumerate(xs.iterrows()):
            ax.scatter([to_dt(r["t_ts"])], [mid_by[r["t_ts"]]], marker="v", s=60, color="black", zorder=5,
                       label="swing t" if i == 0 else None)
            for kind, col, mk in (("before", "#2166ac", "o"), ("after", "#f46d43", "s")):
                v = r[f"{kind}_ts"]
                if v is not None and not (isinstance(v, float) and np.isnan(v)):
                    ax.scatter([to_dt(v)], [mid_by[int(v)]], marker=mk, s=40, color=col, zorder=6,
                               edgecolor="white", label=f"{kind} time" if i == 0 else None)
            if r["status"] == "dropped":
                ax.annotate("dropped", (to_dt(r["t_ts"]), mid_by[r["t_ts"]]), textcoords="offset points",
                            xytext=(4, 6), fontsize=7, color="#555")
        ax.set_ylim(0, 100)
        ax.set_ylabel("Home win price (cents)")
        ax.set_xlabel("Eastern time")
        ax.set_title(f"{s.info['away']} at {s.info['home']}  ({s.info['event_ticker']}, sigma {s.sigma:.2f}, "
                     f"threshold {xs['threshold'].iloc[0] if len(xs) else float('nan'):.1f} pts)", fontsize=10)
        ax.grid(alpha=0.25)
        h, l_ = ax.get_legend_handles_labels()
        ax.legend(h, l_, fontsize=7, loc="upper left", ncol=3, framealpha=0.9)
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(out / f"swings_{s.info['event_ticker']}.png", dpi=150)
        plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Task 7: in-game swings on Kalshi (NFL or college)")
    ap.add_argument("--league", choices=["nfl", "ncaaf"], default="nfl")
    ap.add_argument("--seasons", type=int, nargs="+", default=[2025, 2026])
    ap.add_argument("--games-from", choices=["pbp", "crosswalk"], default="pbp",
                    help="pbp (real run) or crosswalk (college dry run without play-by-play)")
    ap.add_argument("--steady-range", type=float, default=2.0, help="max midpoint range over a steady stretch")
    a = ap.parse_args(argv)
    return run(a.seasons, a.games_from, a.steady_range, league=a.league)


if __name__ == "__main__":
    raise SystemExit(main())
