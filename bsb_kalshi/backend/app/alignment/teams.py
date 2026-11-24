"""The 32-team table: sportsbook team names <-> Kalshi team codes.

The canonical codes are the ones Kalshi uses, confirmed against the team's matching work
(anikabhutani/kalshi ``team_names.csv``, NFL weeks 2-5 of 2026: all 63 Kalshi games matched),
e.g. JAC, LAR, LAC, LV, NO, WAS. Other common spellings (JAX, LA, LVR, WSH, ...) are accepted too. A code not listed here is never guessed: the game gets the reason code
``unknown_team_code`` and the code is listed in the checks, so it can be added below.
"""

from __future__ import annotations

TEAMS: dict[str, tuple[str, ...]] = {
    # name used by the odds file: (canonical code, other accepted codes...)
    "Arizona Cardinals": ("ARI", "ARZ"),
    "Atlanta Falcons": ("ATL",),
    "Baltimore Ravens": ("BAL", "BLT"),
    "Buffalo Bills": ("BUF",),
    "Carolina Panthers": ("CAR",),
    "Chicago Bears": ("CHI",),
    "Cincinnati Bengals": ("CIN",),
    "Cleveland Browns": ("CLE", "CLV"),
    "Dallas Cowboys": ("DAL",),
    "Denver Broncos": ("DEN",),
    "Detroit Lions": ("DET",),
    "Green Bay Packers": ("GB", "GNB"),
    "Houston Texans": ("HOU", "HST"),
    "Indianapolis Colts": ("IND",),
    "Jacksonville Jaguars": ("JAC", "JAX"),
    "Kansas City Chiefs": ("KC", "KAN"),
    "Las Vegas Raiders": ("LV", "LVR", "OAK"),
    "Los Angeles Chargers": ("LAC",),
    "Los Angeles Rams": ("LAR", "LA"),
    "Miami Dolphins": ("MIA",),
    "Minnesota Vikings": ("MIN",),
    "New England Patriots": ("NE", "NWE"),
    "New Orleans Saints": ("NO", "NOR"),
    "New York Giants": ("NYG",),
    "New York Jets": ("NYJ",),
    "Philadelphia Eagles": ("PHI",),
    "Pittsburgh Steelers": ("PIT",),
    "San Francisco 49ers": ("SF", "SFO"),
    "Seattle Seahawks": ("SEA",),
    "Tampa Bay Buccaneers": ("TB", "TAM"),
    "Tennessee Titans": ("TEN",),
    "Washington Commanders": ("WAS", "WSH"),
}

CODE_TO_NAME: dict[str, str] = {code: name for name, codes in TEAMS.items() for code in codes}
NAME_TO_CODE: dict[str, str] = {name: codes[0] for name, codes in TEAMS.items()}


def team_name(code: str) -> str | None:
    """Sportsbook team name for a Kalshi code, or None if the code is not in the table."""
    return CODE_TO_NAME.get(code.upper())


def table_problems() -> list[str]:
    """Sanity of the table itself: 32 teams, no code used for two teams."""
    problems = []
    if len(TEAMS) != 32:
        problems.append(f"{len(TEAMS)} teams instead of 32")
    seen: dict[str, str] = {}
    for name, codes in TEAMS.items():
        for code in codes:
            if code in seen and seen[code] != name:
                problems.append(f"{code} used for {seen[code]} and {name}")
            seen[code] = name
    return problems
