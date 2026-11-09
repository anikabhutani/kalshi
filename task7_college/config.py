"""Every setting for Task 7 Part 1, college (ncaaf). Change a value here and rerun swings.py then
timestamp_list.py; nothing else holds a threshold.

The robustness reruns are one change: K_PCT = 97.5 or 99.5 (or ``--k-pct`` on the command line).
Runs at a K_PCT other than 99 write to output/k_p<pct>/ so they never overwrite the main files.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")          # cached raw inputs (gitignored)
OUT = os.path.join(HERE, "output")

SEASONS = (2025, 2026)
LEAGUE = "ncaaf"

# --------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------

# Task 5 raw pulls, reused before asking the API (paths are tried in order; missing zips are skipped
# and those events are pulled instead).
RAW_ZIPS = {
    2025: [os.path.join(HERE, "..", "..", "kalshi_raw_2025_season_nfl_ncaaf.zip")],
    2026: [os.path.join(HERE, "..", "..", "kalshi_raw_2026_college_ncaaf.zip")],
}
KALSHI_SERIES = "KXNCAAFGAME"
KALSHI_RPS = 4.0                 # unkeyed Kalshi throttles above ~4 req/s
CANDLE_PAD_BEFORE_H = 2          # candle window per game: scheduled start - 2 h ...
CANDLE_PAD_AFTER_H = 8           # ... to scheduled start + 8 h
FBS_ONLY = True                  # keep games with at least one FBS team (the Odds API ncaaf feed)

# Season = games kicking off in this UTC range; "to date" stops at games that finished.
SEASON_RANGE = {2025: ("2025-08-01", "2026-03-01"), 2026: ("2026-08-01", "2027-03-01")}

# CollegeFootballData: key in task7_college/.env as CFBD_API_KEY=... (free tier: 1,000 calls/month).
CFBD = "https://api.collegefootballdata.com"
CFBD_PLAY_CLASSIFICATIONS = ("fbs",)
# In-game win probability is one call per game, so it is fetched for a seeded random sample of
# good-timestamp games only. Every other play uses the Kalshi midpoint just before the play.
CFBD_WP_MAX_CALLS = 600
CFBD_WP_SEED = 7

# Kalshi event <-> CFBD game: same Eastern date +-1 day, each team's name score >= this.
NAME_MATCH_MIN = 0.75

# --------------------------------------------------------------------------------------
# Step 1: minute table
# --------------------------------------------------------------------------------------

PREGAME_MIN = 30                 # minutes kept before kickoff so 5-minute lookbacks work at kickoff
# Home market is "thin" (use the away market, flipped) when its filled share is this much higher
# than the away market's, or its in-game volume is under this share of the away market's.
THIN_FILLED_MARGIN = 0.10
THIN_VOLUME_SHARE = 0.25

# Fee: BSB-Kalshi alignment/costs.py fee_dollars (the function the NFL swings use):
# 0.07 x n x P x (1 - P) x multiplier, rounded UP to the cent per order. KXNCAAFGAME was
# quadratic x1 all of 2025 (no entry in the fee-change log) and is x1 in 2026.
TAKER_RATE = 0.07
FEE_MULTIPLIER = {2025: 1.0, 2026: 1.0}
# n_med: median KXNCAAFGAME trade size, block trades excluded (output/alignment/ncaaf/trade_sizes_<season>.md
# on the abhi-bsb-kalshi branch: 2025 median 50, 2026 median 23.61 -> 24).
N_MED = {2025: 50, 2026: 24}

# --------------------------------------------------------------------------------------
# Step 2: threshold
# --------------------------------------------------------------------------------------

QUIET_GAP_MIN = 5                # minutes within a TD / FG / turnover / failed 4th are not quiet
D_LAG = 5                        # d = midpoint change over 5 minutes
MID_LO, MID_HI = 10.0, 90.0
MAD_SCALE = 1.4826
SIGMA_FLOOR = 1.0
MIN_QUIET = 20                   # fewer quiet minutes -> league median sigma (marked)
K_PCT = 99.0                     # main threshold percentile
K_PCTS = (97.5, 99.0, 99.5)      # all reported

# Per-game play timestamp check (CFBD wallclock). Placeholder stamps are removed first: a bare date
# (00:00:00 UTC) or one time shared by this many plays of a game. A game passes only if all hold.
TS_SHARED_STAMP_PLAYS = 3
TS_MIN_COVERAGE = 0.90           # share of plays with a real wallclock
TS_KICK_OFFSET_MIN = (-15, 45)   # first play vs scheduled start, minutes
TS_LENGTH_H = (2.5, 5.5)         # first to last play
TS_BACKWARD_TOL_S = 120          # a step back in time larger than this counts as out of order
TS_MAX_BACKWARD_SHARE = 0.02     # share of consecutive plays allowed out of order
TS_MAX_GAP_MIN = 45              # longest allowed gap between consecutive plays (halftime ~20-30)

# --------------------------------------------------------------------------------------
# Step 3: swings
# --------------------------------------------------------------------------------------

HOLD_LAG = 3                     # move must hold 3 minutes later ...
HOLD_SHARE = 0.75                # ... at >= 3/4 of the threshold from where it started
GROUP_GAP_MIN = 10

# --------------------------------------------------------------------------------------
# Step 4: steady before / after
# --------------------------------------------------------------------------------------

STEADY_LEN = 5
STEADY_RANGE = 2.0               # midpoint range over the 5 minutes, points (1.0 = the tighter rule)
STEADY_SPREAD = 5.0              # cents
AFTER_SPREAD_TOL = 2.0           # after spread within 2c of the before spread
MAX_FROM_T = 20                  # before / after must be within 20 minutes of t
# Extra drop rules carried over from the NFL code so the leagues match (set False / None to turn off):
DROP_IF_PREV_SWING_AFTER_BEFORE = True   # mirror of "next swing starts before the after time"
SETTLED_SHARE = 0.5                      # drop if |after - before| < 0.5 x threshold (move reversed)

# --------------------------------------------------------------------------------------
# Step 5: checks
# --------------------------------------------------------------------------------------

MATCH_MIN = 3
WP_LO, WP_HI = 0.20, 0.80
N_PLOTS = 3

# --------------------------------------------------------------------------------------
# Step 6: timestamp list and credits
# --------------------------------------------------------------------------------------

ODDS_SPORT_KEY = "americanfootball_ncaaf"
SLOT_S = 300
CREDITS_PER_CALL = 10            # one region, one market (h2h) per historical call
BUDGET_CREDITS = 18_000


def out_dir(k_pct=None, steady_range=None):
    k_pct = K_PCT if k_pct is None else k_pct
    steady_range = STEADY_RANGE if steady_range is None else steady_range
    parts = []
    if k_pct != 99.0:
        parts.append(f"k_p{k_pct:g}")
    if steady_range != 2.0:
        parts.append(f"steady{steady_range:g}")
    path = os.path.join(OUT, "_".join(parts)) if parts else OUT
    os.makedirs(path, exist_ok=True)
    return path


def cfbd_key():
    key = os.environ.get("CFBD_API_KEY")
    if key:
        return key.strip()
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            if line.strip().startswith("CFBD_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None
