"""Shared paths, constants and helpers for Task 4."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "task4"
RAW_DIR = DATA_DIR / "raw"
RESULTS_DIR = DATA_DIR / "results"
CHARTS_DIR = DATA_DIR / "charts"
MANIFEST = DATA_DIR / "manifest.json"
SNAPSHOTS = DATA_DIR / "snapshots.csv.gz"
GAMES = DATA_DIR / "games.csv"

SPORT = "americanfootball_nfl"
BOOKS = ("DraftKings", "FanDuel", "Pinnacle")
MARKETS = ("h2h", "spreads", "totals")
MARKET_LABELS = {"h2h": "Moneyline", "spreads": "Spread", "totals": "Total"}

# NFL weeks are counted Tuesday to Monday in Eastern time, so a Wednesday/Thursday opener and
# the Monday night game land in the same week. Each season starts on the Tuesday before its
# opener: 2025 opened Thursday Sept 4, 2025; 2026 opened Wednesday Sept 9, 2026.
SEASON_STARTS: dict[int, date] = {2025: date(2025, 9, 2), 2026: date(2026, 9, 8)}
SEASONS: tuple[int, ...] = tuple(sorted(SEASON_STARTS))
REGULAR_SEASON_WEEKS = 18
PLAYOFF_LABELS = {19: "Wild Card", 20: "Divisional", 21: "Conference"}  # later weeks: Super Bowl
EASTERN = ZoneInfo("America/New_York")

TIME_COLUMNS = ("snapshot_ts", "commence_time", "book_last_update", "market_last_update")


def parse_times(df: pd.DataFrame) -> pd.DataFrame:
    """Parse the timestamp columns as UTC. The source mixes 'Z' and space-separated forms."""
    out = df.copy()
    for col in TIME_COLUMNS:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, format="mixed")
    return out


def nfl_season(kickoff_utc: pd.Series) -> pd.Series:
    """Season a game belongs to: its Eastern-time year, or the year before for Jan-Jul games."""
    local = kickoff_utc.dt.tz_convert(EASTERN)
    return (local.dt.year - (local.dt.month < 8).astype("int64")).astype("int64")


def nfl_week(kickoff_utc: pd.Series) -> pd.Series:
    """NFL week number within its own season (week 1 = the opener's week), Tuesday-Monday Eastern.

    Weeks 1-18 are the regular season; 19+ are the playoffs (see ``week_label``).
    """
    local_dates = kickoff_utc.dt.tz_convert(EASTERN).dt.tz_localize(None).dt.normalize()
    starts = nfl_season(kickoff_utc).map(lambda s: pd.Timestamp(season_start(s)))
    days = (local_dates - starts).dt.days
    return (days // 7 + 1).astype("int64")


def week_label(week: int) -> str:
    """'1'..'18' for the regular season, then the playoff round."""
    week = int(week)
    if week <= REGULAR_SEASON_WEEKS:
        return str(week)
    return PLAYOFF_LABELS.get(week, "Super Bowl")


def season_start(season: int) -> date:
    """Tuesday before the opener. Unknown seasons fall back to the first Tuesday after Sept 1."""
    if season in SEASON_STARTS:
        return SEASON_STARTS[season]
    d = date(season, 9, 1)
    return date.fromordinal(d.toordinal() + (1 - d.weekday()) % 7)


def season_start_utc(season: int | None = None) -> datetime:
    s = season_start(SEASONS[0] if season is None else season)
    return datetime(s.year, s.month, s.day, tzinfo=EASTERN)
