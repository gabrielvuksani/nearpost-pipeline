from datetime import UTC, date, datetime

from nearpost.domain import Fixture, MatchResult
from nearpost.models.history import training_set

AS_OF = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def _result(day, home, away, hg=1, ag=0, division="E0"):
    return MatchResult(division, day, home, away, hg, ag)


def _fixture(kickoff, home, away, hg, ag, finished=True):
    return Fixture(
        match_id=f"2026-27:{home}-v-{away}",
        season="2026-27",
        fpl_id=1,
        gameweek=6,
        kickoff=kickoff,
        home=home,
        away=away,
        finished=finished,
        home_goals=hg,
        away_goals=ag,
    )


def test_results_on_or_after_the_forecast_day_are_excluded():
    history = [_result(date(2026, 10, 2), "arsenal", "chelsea"), _result(date(2026, 10, 3), "everton", "fulham")]
    assert training_set(history, [], as_of=AS_OF) == (history[0],)


def test_fpl_results_fill_the_gap_before_football_data_updates():
    fd = [_result(date(2026, 9, 20), "fulham", "manchester-united", 1, 1)]
    fpl = [
        _fixture(datetime(2026, 9, 20, 15, 30, tzinfo=UTC), "fulham", "manchester-united", 1, 1),
        _fixture(datetime(2026, 10, 3, 9, 0, tzinfo=UTC), "arsenal", "chelsea", 2, 2),
    ]
    merged = training_set(fd, fpl, as_of=AS_OF)
    assert len(merged) == 2
    assert merged[-1] == _result(date(2026, 10, 3), "arsenal", "chelsea", 2, 2)


def test_unfinished_or_future_fpl_fixtures_are_ignored():
    fpl = [
        _fixture(datetime(2026, 10, 3, 11, 30, tzinfo=UTC), "arsenal", "chelsea", 0, 0, finished=False),
        _fixture(datetime(2026, 10, 4, 14, 0, tzinfo=UTC), "everton", "fulham", 1, 0),
    ]
    assert training_set([], fpl, as_of=AS_OF) == ()


def test_training_set_is_sorted_by_date():
    history = [_result(date(2026, 9, 1), "b", "c"), _result(date(2025, 9, 1), "a", "b")]
    assert [r.played_on for r in training_set(history, [], as_of=AS_OF)] == [date(2025, 9, 1), date(2026, 9, 1)]
