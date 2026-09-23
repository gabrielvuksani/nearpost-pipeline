"""football-data.co.uk CSVs (Green tier): results, closing odds and upcoming-round odds.

Used as model input and as the closing-line benchmark. Raw rows are never republished.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping
from datetime import date, datetime

from nearpost.domain import MarketQuote, MatchResult
from nearpost.sources.errors import SchemaError
from nearpost.sources.prices import decimal_price
from nearpost.teams import UnknownTeamError, resolve_team, team_id

BASE_URL = "https://www.football-data.co.uk"
FIXTURES_URL = f"{BASE_URL}/fixtures.csv"


def season_url(season: str, division: str) -> str:
    """e.g. season "2026-27", division "E0" -> .../mmz4281/2627/E0.csv"""
    start, end = season.split("-")
    return f"{BASE_URL}/mmz4281/{start[2:]}{end}/{division}.csv"


def _rows(payload: bytes, required: Iterable[str]) -> list[dict[str, str]]:
    try:
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
        missing = [c for c in required if c not in (reader.fieldnames or [])]
        if missing:
            raise SchemaError(f"football-data CSV is missing columns {missing}")
        rows = list(reader)
    except (csv.Error, UnicodeDecodeError) as error:
        raise SchemaError(f"football-data CSV is unreadable: {error}") from error
    # Short rows leave trailing fields as None; normalise them to empty strings.
    return [{k: (v or "").strip() for k, v in row.items() if k is not None} for row in rows if any(row.values())]


def _date(text: str) -> date:
    for pattern in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text.strip(), pattern).date()
        except ValueError:
            continue
    raise SchemaError(f"unrecognised football-data date {text!r}")


def _odds(row: Mapping[str, str], columns: tuple[str, ...]) -> tuple[float, ...] | None:
    prices = [decimal_price(row.get(c)) for c in columns]
    return tuple(p for p in prices if p is not None) if all(p is not None for p in prices) else None


def _goals(row: Mapping[str, str], column: str) -> int:
    try:
        return int(row[column])
    except ValueError:
        raise SchemaError(f"non-numeric goals {row[column]!r} in {column}") from None


def _strict(name: str) -> str:
    try:
        return resolve_team(name)
    except UnknownTeamError as error:
        raise SchemaError(str(error)) from error


def parse_results(payload: bytes) -> list[MatchResult]:
    """Played matches only. Clubs we never join on keep a stable slug, so history can include them."""
    rows = _rows(payload, ("Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"))
    return [
        MatchResult(
            division=row["Div"],
            played_on=_date(row["Date"]),
            home=team_id(row["HomeTeam"]),
            away=team_id(row["AwayTeam"]),
            home_goals=_goals(row, "FTHG"),
            away_goals=_goals(row, "FTAG"),
        )
        for row in rows
        if row.get("FTHG") and row.get("FTAG") and row.get("HomeTeam") and row.get("AwayTeam")
    ]


def _quote(row: Mapping[str, str], avg: tuple[str, ...], exchange: tuple[str, ...], ou: tuple[str, ...]) -> MarketQuote:
    return MarketQuote(
        avg_1x2=_odds(row, avg),  # type: ignore[arg-type]
        exchange_1x2=_odds(row, exchange),  # type: ignore[arg-type]
        avg_over_under_2_5=_odds(row, ou),  # type: ignore[arg-type]
    )


_CLOSE_1X2 = ("AvgCH", "AvgCD", "AvgCA")


def parse_closing(payload: bytes) -> dict[tuple[str, str], MarketQuote]:
    """Closing prices for a current-season file, keyed by canonical (home, away)."""
    rows = _rows(payload, ("HomeTeam", "AwayTeam", *_CLOSE_1X2))
    return {
        (_strict(row["HomeTeam"]), _strict(row["AwayTeam"])): _quote(
            row, _CLOSE_1X2, ("BFECH", "BFECD", "BFECA"), ("AvgC>2.5", "AvgC<2.5")
        )
        for row in rows
        if row.get("HomeTeam") and row.get("AwayTeam")
    }


_PRE_1X2 = ("AvgH", "AvgD", "AvgA")


def parse_upcoming(payload: bytes, *, division: str) -> dict[tuple[str, str], MarketQuote]:
    """Pre-match prices for the upcoming round from fixtures.csv (published weekly)."""
    rows = _rows(payload, ("Div", "HomeTeam", "AwayTeam", *_PRE_1X2))
    return {
        (_strict(row["HomeTeam"]), _strict(row["AwayTeam"])): _quote(
            row, _PRE_1X2, ("BFEH", "BFED", "BFEA"), ("Avg>2.5", "Avg<2.5")
        )
        for row in rows
        if row.get("Div") == division and row.get("HomeTeam") and row.get("AwayTeam")
    }
