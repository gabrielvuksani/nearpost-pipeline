"""The training set a baseline forecast is allowed to see."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from nearpost.domain import Fixture, MatchResult
from nearpost.timeutil import season_of


def training_set(
    football_data: Iterable[MatchResult], fpl_fixtures: Iterable[Fixture], *, as_of: datetime
) -> tuple[MatchResult, ...]:
    """Results strictly before the forecast, oldest first.

    football-data.co.uk only has match dates and updates twice a week, so its rows
    count only from earlier days. Finished FPL fixtures (exact kickoffs, updated within
    hours) fill in the matches football-data hasn't published yet.
    """
    history = [r for r in football_data if r.played_on < as_of.date()]
    seen = {(season_of(datetime.combine(r.played_on, as_of.timetz())), r.home, r.away) for r in history}
    for fixture in fpl_fixtures:
        if not (fixture.finished and fixture.kickoff and fixture.kickoff < as_of):
            continue
        if (fixture.season, fixture.home, fixture.away) in seen:
            continue
        if fixture.home_goals is None or fixture.away_goals is None:
            continue
        history.append(
            MatchResult(
                "E0", fixture.kickoff.date(), fixture.home, fixture.away, fixture.home_goals, fixture.away_goals
            )
        )
    return tuple(sorted(history, key=lambda r: r.played_on))
