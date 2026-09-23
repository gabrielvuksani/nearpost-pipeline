"""Value types shared across sources, models and jobs. All immutable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

Odds3 = tuple[float, float, float]  # decimal odds, home / draw / away
Odds2 = tuple[float, float]  # decimal odds, over / under 2.5 goals


def match_id(season: str, home: str, away: str) -> str:
    return f"{season}:{home}-v-{away}"


@dataclass(frozen=True)
class Fixture:
    """A Premier League fixture as FPL schedules it. FPL is our calendar of record."""

    match_id: str
    season: str
    fpl_id: int
    gameweek: int | None
    kickoff: datetime | None
    home: str
    away: str
    finished: bool
    home_goals: int | None
    away_goals: int | None


@dataclass(frozen=True)
class Gameweek:
    gameweek: int
    deadline: datetime
    finished: bool
    data_checked: bool


@dataclass(frozen=True)
class MatchResult:
    """A played match used to train the baseline models."""

    division: str
    played_on: date
    home: str
    away: str
    home_goals: int
    away_goals: int


@dataclass(frozen=True)
class MarketQuote:
    """Average-of-books and Betfair Exchange prices from football-data.co.uk."""

    avg_1x2: Odds3 | None
    exchange_1x2: Odds3 | None
    avg_over_under_2_5: Odds2 | None


@dataclass(frozen=True)
class BookQuote:
    key: str
    last_update: str | None
    h2h: Odds3 | None
    over_under_2_5: Odds2 | None


@dataclass(frozen=True)
class OddsEvent:
    """One match in a The Odds API response."""

    home: str
    away: str
    commence: datetime
    books: tuple[BookQuote, ...]
