"""Shared helpers for data.py, swings.py and timestamp_list.py: names, candles, fee, play-by-play."""

import glob
import json
import math
import os
import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher

import numpy as np
import pandas as pd

import config as C

EASTERN = "America/New_York"
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP",
                                       "OCT", "NOV", "DEC"], 1)}
TICKER_DATE = re.compile(r"^KX[A-Z]+-(\d{2})([A-Z]{3})(\d{2})")


def season_dir(season, *parts):
    p = os.path.join(C.DATA, str(season), *parts)
    os.makedirs(p if not os.path.splitext(p)[1] else os.path.dirname(p), exist_ok=True)
    return p


def ticker_date(ticker):
    m = TICKER_DATE.match(str(ticker))
    if not m or m.group(2) not in MONTHS:
        return None
    return date(2000 + int(m.group(1)), MONTHS[m.group(2)], int(m.group(3)))


def iso(ts):
    return pd.Timestamp(int(ts), unit="s", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def unix(ts):
    """Unix seconds of a tz-aware Timestamp (independent of the pandas datetime unit)."""
    return int(pd.Timestamp(ts).timestamp())


def minute_end(ts):
    """End of the minute containing ts (Unix s): a play at 19:42:11 belongs to the candle ending 19:43:00."""
    s = pd.Timestamp(ts).timestamp()
    return int(math.floor(s / 60) * 60 + 60)


# --------------------------------------------------------------------------------------
# Team names (Kalshi yes_sub_title vs CollegeFootballData school)
# --------------------------------------------------------------------------------------

ALIASES = {"miami fl": "miami", "miami florida": "miami", "ole miss": "mississippi", "uconn": "connecticut",
           "fiu": "florida international", "fau": "florida atlantic", "utsa": "ut san antonio",
           "utep": "ut el paso", "umass": "massachusetts", "app state": "appalachian state",
           "appalachian st": "appalachian state", "ul monroe": "louisiana monroe", "ulm": "louisiana monroe",
           "southern miss": "southern mississippi", "pitt": "pittsburgh", "byu": "brigham young",
           "lsu": "louisiana state", "smu": "southern methodist", "tcu": "texas christian",
           "ucf": "central florida", "usc": "southern california", "hawai i": "hawaii",
           "nc state": "north carolina state", "n c state": "north carolina state",
           "sam houston state": "sam houston", "louisiana lafayette": "louisiana", "ul lafayette": "louisiana",
           "miami oh": "miami ohio", "army west point": "army", "san jose state": "san jose state",
           "texas a and m": "texas a and m", "southern methodist": "southern methodist",
           "middle tennessee state": "middle tennessee", "mtsu": "middle tennessee", "wku": "western kentucky",
           "uab": "alabama birmingham", "unc": "north carolina", "uga": "georgia",
           # FCS names Kalshi and CFBD write differently
           "liu": "long island university", "nicholls state": "nicholls", "southeastern louisiana": "se louisiana",
           "southern university": "southern", "tennessee martin": "ut martin", "university at albany": "ualbany",
           "penn": "pennsylvania"}


def norm(name):
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("(", " ").replace(")", " ")
    s = re.sub(r"[.'`]", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = s.split()
    toks = ["state" if (t == "st" and i == len(toks) - 1) else ("saint" if t == "st" else t)
            for i, t in enumerate(toks)]
    s = " ".join(toks)
    return ALIASES.get(s, s)


def name_score(a, b):
    a, b = norm(a), norm(b)
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


# --------------------------------------------------------------------------------------
# Candles
# --------------------------------------------------------------------------------------

CANDLE_COLS = ["ticker", "ts", "bid", "ask", "volume", "price"]


def _cents(side):
    if not side:
        return None
    v = side.get("close_dollars", side.get("close"))
    return None if v in (None, "") else round(float(v) * 100, 4)


def candle_rows(ticker, candles, lo=None, hi=None):
    """Kalshi candles -> rows in cents. ``ts`` = end of the minute. Works for live (``*_dollars``,
    ``volume_fp``) and historical (``close``, ``volume``) field names."""
    rows = []
    for c in candles:
        ts = int(c["end_period_ts"])
        if (lo is not None and ts < lo) or (hi is not None and ts > hi):
            continue
        price = c.get("price") or {}
        p = price.get("close_dollars", price.get("close"))
        rows.append({"ticker": ticker, "ts": ts, "bid": _cents(c.get("yes_bid")), "ask": _cents(c.get("yes_ask")),
                     "volume": float(c.get("volume_fp", c.get("volume", 0)) or 0),
                     "price": None if p in (None, "") else round(float(p) * 100, 4)})
    return rows


def save_candles(path, rows):
    df = pd.DataFrame(rows, columns=CANDLE_COLS)
    if not df.empty:
        df = df.drop_duplicates(["ticker", "ts"], keep="last").sort_values(["ticker", "ts"])
    df.to_csv(path, index=False, compression="gzip")
    return len(df)


# --------------------------------------------------------------------------------------
# Fee and cost (BSB-Kalshi alignment/costs.py fee_dollars, with the season's multiplier)
# --------------------------------------------------------------------------------------

def fee_dollars(n, price, multiplier=1.0):
    """Kalshi taker fee for one order of n contracts at ``price`` dollars, rounded up to the cent."""
    raw = C.TAKER_RATE * multiplier * n * price * (1 - price)
    return math.ceil(round(raw * 100, 9)) / 100


def fee_cents(ask_c, n, multiplier):
    return np.array([np.nan if not (0 < a < 100) else fee_dollars(n, a / 100, multiplier) / n * 100
                     for a in ask_c])


def cost_per_10(mid_c, ask_c, n, multiplier):
    """$10 x (1 - midpoint / (ask + fee)); returns (cost, fee per contract in cents)."""
    f = fee_cents(ask_c, n, multiplier)
    return 10 * (1 - mid_c / (ask_c + f)), f


# --------------------------------------------------------------------------------------
# CollegeFootballData play-by-play
# --------------------------------------------------------------------------------------

TOUCHDOWN_TYPES = {"passing touchdown", "rushing touchdown", "fumble return touchdown",
                   "interception return touchdown", "punt return touchdown", "kickoff return touchdown",
                   "blocked punt touchdown", "blocked field goal touchdown", "missed field goal return touchdown"}
TURNOVER_TYPES = {"pass interception return", "interception", "interception return touchdown",
                  "pass interception", "fumble recovery (opponent)", "fumble return touchdown"}
FIELD_GOAL_TYPES = {"field goal good"}
# 4th-down plays that are not a "go for it" attempt
NOT_ATTEMPTS = {"punt", "punt return", "safety", "field goal good", "field goal missed", "missed field goal return", "blocked field goal",
                "blocked punt", "timeout", "end period", "end of half", "end of game", "end of regulation",
                "kickoff", "uncategorized", "end of 1st period", "end of 3rd period", "coin toss",
                "blocked punt touchdown", "blocked field goal touchdown", "punt return touchdown",
                "missed field goal return touchdown", "penalty", "kickoff return (offense)",
                "kickoff return touchdown"}


def load_plays(season):
    frames = []
    for p in sorted(glob.glob(os.path.join(season_dir(season, "cfbd"), "plays_*.json"))):
        body = json.load(open(p, encoding="utf-8"))
        if body:
            frames.append(pd.json_normalize(body))
    if not frames:
        return pd.DataFrame()
    pl = pd.concat(frames, ignore_index=True).drop_duplicates("id")
    pl = pl.rename(columns={"gameId": "game_id", "playType": "play_type", "playText": "play_text",
                            "driveNumber": "drive_number", "playNumber": "play_number",
                            "clock.minutes": "clock_min", "clock.seconds": "clock_sec"})
    if "wallclock" not in pl.columns:
        pl["wallclock"] = None
    pl["wall"] = pd.to_datetime(pl["wallclock"], utc=True, errors="coerce", format="ISO8601")
    # game order: quarter, clock running down, then drive and play number
    pl = pl.sort_values(["game_id", "period", "clock_min", "clock_sec", "drive_number", "play_number"],
                        ascending=[True, True, False, False, True, True], na_position="last")
    return classify(clean_wall(pl.reset_index(drop=True)))


def clean_wall(pl):
    """CFBD wallclock has two kinds of placeholder stamp: a bare date (exactly 00:00:00 UTC) and one time
    copied onto many plays of a game. Both are treated as missing: ``wall_ok`` is False and ``wall`` becomes
    NaT. ``wall_fill`` is ``wall`` with the missing plays interpolated (in game order) between their
    neighbours; it is used only to keep minutes near a scoring play out of the quiet set."""
    w = pl["wall"]
    midnight = w.notna() & (w.dt.hour == 0) & (w.dt.minute == 0) & (w.dt.second == 0)
    shared = pl.groupby(["game_id", "wall"])["wall"].transform("size").fillna(0) >= C.TS_SHARED_STAMP_PLAYS
    pl["wall_raw"] = w
    pl["wall_ok"] = w.notna() & ~midnight & ~shared
    pl["wall"] = w.where(pl["wall_ok"])
    sec = pl["wall"].map(lambda t: t.timestamp() if pd.notna(t) else np.nan)
    sec = sec.groupby(pl["game_id"]).transform(lambda s: s.interpolate(limit_area="inside").ffill().bfill())
    pl["wall_fill"] = pd.to_datetime(sec, unit="s", utc=True)
    return pl


def classify(pl):
    """Adds ``event``: touchdown / turnover / field_goal / failed_fourth (or ''), plus ``is_touchdown``.
    A turnover returned for a touchdown is labelled turnover (same rule as the NFL run)."""
    pt = pl["play_type"].fillna("").str.lower()
    ev = np.full(len(pl), "", dtype=object)
    td = pt.isin(TOUCHDOWN_TYPES)
    ev[pt.isin(FIELD_GOAL_TYPES).to_numpy()] = "field_goal"
    ev[td.to_numpy()] = "touchdown"
    ev[pt.isin(TURNOVER_TYPES).to_numpy()] = "turnover"
    # failed fourth down: a 4th-down attempt (not a punt, kick, safety or penalty) that CFBD calls a turnover
    # on downs, or that fell short of the line to gain with the other team on offense next
    nxt_off = pl.groupby("game_id")["offense"].shift(-1)
    down = pd.to_numeric(pl.get("down"), errors="coerce")
    text = pl["play_text"].fillna("").str.lower()
    short = pd.to_numeric(pl.get("yards_gained", pl.get("yardsGained")), errors="coerce") < \
        pd.to_numeric(pl.get("distance"), errors="coerce")
    tod = text.str.contains("turnover on downs")
    ff = ((down == 4) & ~pt.isin(NOT_ATTEMPTS) & (ev == "")
          & (tod | (short & nxt_off.notna() & (nxt_off != pl["offense"]))))
    ev[ff.to_numpy()] = "failed_fourth"
    pl["event"] = ev
    pl["is_touchdown"] = td.to_numpy()
    return pl


def timestamp_quality(pl, sched):
    """Is this game's CFBD wallclock good enough to place plays to the minute?

    Returns (good, reason, first_play, last_play). Checks, in order: coverage (share of plays with a real
    wallclock, placeholders removed by clean_wall), first play near the scheduled start, plausible length,
    times only move forward (few steps back in game order) and no long hole."""
    n = len(pl)
    if n == 0:
        return False, "no plays", None, None
    w = pl["wall"]
    share = float(w.notna().mean())
    if share < C.TS_MIN_COVERAGE:
        return False, f"wallclock on {share:.0%} of plays", None, None
    ww = w.dropna()
    k0, k1 = ww.min(), ww.max()
    off = (k0 - sched).total_seconds() / 60
    lo, hi = C.TS_KICK_OFFSET_MIN
    if not lo <= off <= hi:
        return False, f"first play {off:+.0f} min from scheduled start", k0, k1
    length = (k1 - k0).total_seconds() / 3600
    if not C.TS_LENGTH_H[0] <= length <= C.TS_LENGTH_H[1]:
        return False, f"game length {length:.1f} h", k0, k1
    diffs = ww.diff().dt.total_seconds().dropna()
    back = float((diffs < -C.TS_BACKWARD_TOL_S).mean()) if len(diffs) else 0.0
    if back > C.TS_MAX_BACKWARD_SHARE:
        return False, f"{back:.1%} of plays step back in time", k0, k1
    if len(diffs) and diffs.max() > C.TS_MAX_GAP_MIN * 60:
        return False, f"{diffs.max() / 60:.0f}-min gap between plays", k0, k1
    return True, "good", k0, k1


def load_cfbd_games(season):
    p = season_dir(season, "cfbd", "games.json")
    if not os.path.exists(p):
        return pd.DataFrame()
    g = pd.json_normalize(json.load(open(p, encoding="utf-8")))
    g = g.rename(columns={"startDate": "start", "homeTeam": "home", "awayTeam": "away",
                          "homeClassification": "home_cls", "awayClassification": "away_cls",
                          "seasonType": "season_type", "neutralSite": "neutral_site",
                          "startTimeTBD": "start_tbd"})
    g["start"] = pd.to_datetime(g["start"], utc=True, format="ISO8601")
    return g
