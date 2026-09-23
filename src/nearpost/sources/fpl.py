"""Fantasy Premier League API (Amber tier: fetched server-side, never redistributed raw)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from nearpost.domain import Fixture, Gameweek, match_id
from nearpost.sources.errors import SchemaError
from nearpost.teams import UnknownTeamError, resolve_team
from nearpost.timeutil import parse_utc, season_of

BASE_URL = "https://fantasy.premierleague.com/api"
BOOTSTRAP_URL = f"{BASE_URL}/bootstrap-static/"
FIXTURES_URL = f"{BASE_URL}/fixtures/"


def live_url(gameweek: int) -> str:
    return f"{BASE_URL}/event/{gameweek}/live/"


def _load(payload: bytes) -> Any:
    try:
        return json.loads(payload)
    except json.JSONDecodeError as error:
        raise SchemaError(f"FPL returned invalid JSON: {error}") from error


def _field(record: Mapping[str, Any], name: str, context: str) -> Any:
    try:
        return record[name]
    except (KeyError, TypeError):
        raise SchemaError(f"FPL {context} is missing field {name!r}") from None


def parse_teams(bootstrap: bytes) -> dict[int, str]:
    teams = _field(_load(bootstrap), "teams", "bootstrap-static")
    try:
        return {int(_field(t, "id", "team")): resolve_team(_field(t, "name", "team")) for t in teams}
    except UnknownTeamError as error:
        raise SchemaError(f"FPL team name not recognised: {error}") from error


def parse_events(bootstrap: bytes) -> list[Gameweek]:
    events = _field(_load(bootstrap), "events", "bootstrap-static")
    return [
        Gameweek(
            gameweek=int(_field(e, "id", "event")),
            deadline=parse_utc(_field(e, "deadline_time", "event")),
            finished=bool(_field(e, "finished", "event")),
            data_checked=bool(_field(e, "data_checked", "event")),
        )
        for e in events
    ]


def parse_fixtures(payload: bytes, teams: Mapping[int, str], *, season: str | None = None) -> list[Fixture]:
    """Fixtures with canonical team slugs.

    Unscheduled fixtures have no kickoff, so their season comes from the `season` hint.
    """
    fixtures = _load(payload)
    if not isinstance(fixtures, list):
        raise SchemaError("FPL fixtures payload is not a list")
    try:
        return [_fixture(raw, teams, season) for raw in fixtures]
    except (TypeError, ValueError, AttributeError) as error:
        if isinstance(error, SchemaError):
            raise
        raise SchemaError(f"FPL fixture has an unexpected shape: {type(error).__name__}: {error}") from error


def _fixture(raw: Mapping[str, Any], teams: Mapping[int, str], season_hint: str | None) -> Fixture:
    kickoff_text = _field(raw, "kickoff_time", "fixture")
    kickoff = parse_utc(kickoff_text) if kickoff_text else None
    season = season_of(kickoff) if kickoff else season_hint
    if season is None:
        raise SchemaError(f"FPL fixture {raw.get('id')} has no kickoff and no season hint was given")
    home, away = (_team(teams, _field(raw, side, "fixture")) for side in ("team_h", "team_a"))
    return Fixture(
        match_id=match_id(season, home, away),
        season=season,
        fpl_id=int(_field(raw, "id", "fixture")),
        gameweek=_field(raw, "event", "fixture"),
        kickoff=kickoff,
        home=home,
        away=away,
        finished=bool(_field(raw, "finished", "fixture")) or bool(raw.get("finished_provisional")),
        home_goals=_field(raw, "team_h_score", "fixture"),
        away_goals=_field(raw, "team_a_score", "fixture"),
    )


def _team(teams: Mapping[int, str], team_id: int) -> str:
    try:
        return teams[int(team_id)]
    except KeyError:
        raise SchemaError(f"FPL fixture references unknown team id {team_id}") from None


def extract_ep_next(bootstrap: bytes) -> list[dict[str, Any]]:
    """FPL's own expected points for the next gameweek: the benchmark our projections must beat."""
    elements = _field(_load(bootstrap), "elements", "bootstrap-static")
    return [
        {
            "id": int(_field(e, "id", "element")),
            "team": int(_field(e, "team", "element")),
            "element_type": int(_field(e, "element_type", "element")),
            "ep_next": None if _field(e, "ep_next", "element") is None else float(e["ep_next"]),
        }
        for e in elements
    ]
