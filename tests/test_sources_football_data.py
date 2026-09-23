from datetime import date

import pytest

from nearpost.sources.errors import SchemaError
from nearpost.sources.football_data import parse_closing, parse_results, parse_upcoming
from tests.factories import fd_fixtures_csv, fd_season_csv

E0_ROWS = (
    "E0,21/08/2026,20:00,Arsenal,Coventry,3,0,H,2.1,0.4,1.25,6.5,11,1.22,6.8,12,1.23,7.0,13.5,1.6,2.4",
    "E0,20/09/2026,16:30,Fulham,Man United,1,1,D,1.6,1.6,3.5,3.8,2.0,3.6,3.8,2.0,3.7,3.9,2.06,1.9,1.95",
    "E0,26/09/2026,15:00,Spurs,Hull,,,,,,1.5,4.2,6.0,,,,,,,,",
)


def test_parse_results_skips_unplayed_rows_and_reads_dates():
    results = parse_results(fd_season_csv(*E0_ROWS[:2], E0_ROWS[2].replace("Spurs", "Tottenham")))
    assert len(results) == 2
    first = results[0]
    assert (first.played_on, first.home, first.away, first.home_goals, first.away_goals) == (
        date(2026, 8, 21),
        "arsenal",
        "coventry-city",
        3,
        0,
    )


def test_history_rows_for_clubs_we_never_join_on_get_stable_slugs():
    csv = fd_season_csv("E1,09/08/2025,15:00,Sheffield Weds,Oxford,1,2,A,,,2.5,3.2,2.9,,,,,,,,")
    [row] = parse_results(csv)
    assert (row.home, row.away) == ("sheffield-weds", "oxford")


def test_parse_closing_reads_average_and_exchange_closes():
    closing = parse_closing(fd_season_csv(*E0_ROWS[:2]))
    fulham = closing[("fulham", "manchester-united")]
    assert fulham.avg_1x2 == (3.6, 3.8, 2.0)
    assert fulham.exchange_1x2 == (3.7, 3.9, 2.06)
    assert fulham.avg_over_under_2_5 == (1.9, 1.95)


def test_parse_closing_leaves_missing_prices_as_none():
    closing = parse_closing(fd_season_csv("E0,26/09/2026,15:00,Tottenham,Hull,2,0,H,,,1.5,4.2,6.0,,,,,,,,"))
    spurs = closing[("tottenham-hotspur", "hull-city")]
    assert spurs.avg_1x2 is None
    assert spurs.exchange_1x2 is None


def test_parse_upcoming_filters_to_one_division():
    csv = fd_fixtures_csv(
        "E0,03/10/2026,15:00,Chelsea,Everton,,2.0,3.5,3.9,1.8,2.0",
        "B1,03/10/2026,19:45,Gent,Standard,,1.8,3.4,4.2,1.9,1.9",
    )
    upcoming = parse_upcoming(csv, division="E0")
    assert list(upcoming) == [("chelsea", "everton")]
    assert upcoming[("chelsea", "everton")].avg_1x2 == (2.0, 3.5, 3.9)
    assert upcoming[("chelsea", "everton")].avg_over_under_2_5 == (1.8, 2.0)


def test_missing_required_column_is_a_schema_error():
    with pytest.raises(SchemaError, match="FTHG"):
        parse_results(b"Div,Date,HomeTeam,AwayTeam\nE0,21/08/2026,Arsenal,Coventry\n")


def test_short_rows_are_skipped_not_crashed_on():
    csv = fd_season_csv("E0,21/08/2026,20:00,Arsenal,Coventry")  # truncated row: no goals columns
    assert parse_results(csv) == []


def test_invalid_odds_are_treated_as_missing():
    csv = fd_season_csv("E0,26/09/2026,15:00,Tottenham,Hull,2,0,H,,,1.5,4.2,6.0,1.0,4.2,6.0,,,,,")
    assert parse_closing(csv)[("tottenham-hotspur", "hull-city")].avg_1x2 is None


def test_non_numeric_goals_are_schema_errors():
    with pytest.raises(SchemaError, match="goals"):
        parse_results(fd_season_csv("E0,21/08/2026,20:00,Arsenal,Coventry,three,0,H,,,,,,,,,,,,,"))


def test_csv_library_errors_become_schema_errors():
    with pytest.raises(SchemaError):
        parse_results(b"Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\n" + b'E0,"' + b"x" * 200_000 + b'",A,B,1,0\n')
