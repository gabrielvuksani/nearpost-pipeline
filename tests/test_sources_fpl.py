import json
from datetime import UTC, datetime

import pytest

from nearpost.sources.errors import SchemaError
from nearpost.sources.fpl import extract_ep_next, parse_events, parse_fixtures, parse_teams
from tests.factories import fpl_bootstrap, fpl_fixture, fpl_fixtures


def test_parse_teams_maps_fpl_ids_to_canonical_slugs():
    teams = parse_teams(fpl_bootstrap())
    assert teams[19] == "tottenham-hotspur"
    assert teams[16] == "manchester-united"
    assert len(teams) == 20


def test_parse_events_reads_deadlines():
    events = parse_events(fpl_bootstrap())
    assert events[1].gameweek == 6
    assert events[1].deadline == datetime(2026, 10, 10, 10, 0, tzinfo=UTC)
    assert events[0].finished and events[0].data_checked


def test_parse_fixtures_builds_season_scoped_match_ids():
    payload = fpl_fixtures(
        fpl_fixture(51, 6, "2026-10-10T11:30:00Z", 1, 6),
        fpl_fixture(1, 1, "2026-08-21T19:00:00Z", 1, 7, finished=True, home_goals=3, away_goals=0),
    )
    upcoming, played = parse_fixtures(payload, parse_teams(fpl_bootstrap()))

    assert upcoming.match_id == "2026-27:arsenal-v-chelsea"
    assert upcoming.kickoff == datetime(2026, 10, 10, 11, 30, tzinfo=UTC)
    assert upcoming.gameweek == 6
    assert not upcoming.finished
    assert (played.finished, played.home_goals, played.away_goals) == (True, 3, 0)


def test_unscheduled_fixtures_have_no_kickoff_and_no_match_id_season_guess():
    payload = fpl_fixtures(fpl_fixture(99, None, None, 2, 3))
    [fixture] = parse_fixtures(payload, parse_teams(fpl_bootstrap()), season="2026-27")
    assert fixture.kickoff is None
    assert fixture.match_id == "2026-27:aston-villa-v-bournemouth"


def test_unscheduled_fixture_without_a_season_hint_is_rejected():
    payload = fpl_fixtures(fpl_fixture(99, None, None, 2, 3))
    with pytest.raises(SchemaError, match="season"):
        parse_fixtures(payload, parse_teams(fpl_bootstrap()))


def test_a_fixture_referencing_an_unknown_team_id_fails_loudly():
    payload = fpl_fixtures(fpl_fixture(51, 6, "2026-10-10T11:30:00Z", 1, 42))
    with pytest.raises(SchemaError, match="42"):
        parse_fixtures(payload, parse_teams(fpl_bootstrap()))


def test_schema_drift_is_reported_with_the_missing_field():
    with pytest.raises(SchemaError, match="kickoff_time"):
        parse_fixtures(b'[{"id": 1, "team_h": 1, "team_a": 2}]', parse_teams(fpl_bootstrap()))


def test_extract_ep_next_keeps_only_what_the_benchmark_needs():
    table = extract_ep_next(fpl_bootstrap())
    assert table == [
        {"id": 1, "team": 1, "element_type": 1, "ep_next": 4.5},
        {"id": 2, "team": 14, "element_type": 3, "ep_next": 7.1},
        {"id": 3, "team": 20, "element_type": 4, "ep_next": None},
    ]


def test_a_provisionally_finished_fixture_counts_as_played():
    # FPL sets `finished` only after bonus points are confirmed; the score is final at the whistle.
    raw = fpl_fixture(7, 5, "2026-09-20T15:30:00Z", 10, 16, home_goals=1, away_goals=1)
    raw["finished_provisional"] = True
    [fixture] = parse_fixtures(fpl_fixtures(raw), parse_teams(fpl_bootstrap()))
    assert fixture.finished


_GOOD = {
    "id": 1,
    "event": 6,
    "kickoff_time": "2026-10-10T11:30:00Z",
    "team_h": 1,
    "team_a": 6,
    "finished": False,
    "team_h_score": None,
    "team_a_score": None,
}


@pytest.mark.parametrize(
    "payload",
    [
        json.dumps([{**_GOOD, "id": "abc"}]).encode(),
        json.dumps([{**_GOOD, "kickoff_time": "not a date"}]).encode(),
        b"[42]",
    ],
)
def test_malformed_fixtures_are_schema_errors(payload):
    with pytest.raises(SchemaError):
        parse_fixtures(payload, parse_teams(fpl_bootstrap()))
