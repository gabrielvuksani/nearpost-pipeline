"""An offline world for end-to-end runs: every source URL answered with synthetic data."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import httpx

from nearpost.jobs.context import RunContext
from nearpost.settings import Settings
from nearpost.snapshots import Fetcher
from nearpost.sources.client import SourceClient
from nearpost.store.local import LocalStore
from tests.factories import (
    PL_TEAMS_FD,
    fd_fixtures_csv,
    fd_season_csv,
    fpl_bootstrap,
    fpl_fixture,
    fpl_fixtures,
    odds_event,
    odds_payload,
    synthetic_season_rows,
)

KICKOFF = datetime(2026, 10, 10, 11, 30, tzinfo=UTC)
MATCH = "2026-27:arsenal-v-chelsea"
CHAMPIONSHIP = ["Burnley", "Leicester", "Southampton", "West Ham", "Wolves", "Norwich"]


@dataclass
class World:
    """Mutable on purpose: tests move the clock and change what sources say between runs."""

    now: datetime
    fixtures: list[dict] = field(default_factory=lambda: [fpl_fixture(51, 6, "2026-10-10T11:30:00Z", 1, 6)])
    odds_status: int = 200
    odds_events: list[dict] = field(
        default_factory=lambda: [
            odds_event(
                "Arsenal",
                "Chelsea",
                "2026-10-10T11:30:00Z",
                [("pinnacle", (1.8, 3.8, 4.6), (1.9, 1.95)), ("betfair_ex_eu", (1.82, 3.9, 4.8), None)],
            )
        ]
    )
    credits_remaining: int = 450
    fd_fixture_rows: list[str] = field(
        default_factory=lambda: ["E0,10/10/2026,12:30,Arsenal,Chelsea,,1.85,3.7,4.4,1.9,1.9"]
    )
    current_e0_rows: list[str] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        host, path = request.url.host, request.url.path
        if host == "fantasy.premierleague.com":
            if path.endswith("/bootstrap-static/"):
                return _json(fpl_bootstrap())
            if path.endswith("/fixtures/"):
                return _json(fpl_fixtures(*self.fixtures))
            if "/event/" in path:
                return _json(json.dumps({"elements": [{"id": 1, "stats": {"total_points": 6}}]}).encode())
        if host == "api.the-odds-api.com":
            if self.odds_status != 200:
                return httpx.Response(self.odds_status, content=b'{"message": "quota"}')
            headers = {"x-requests-remaining": str(self.credits_remaining), "x-requests-used": "50"}
            return _json(odds_payload(*self.odds_events), headers)
        if host == "www.football-data.co.uk":
            if path == "/fixtures.csv":
                return _csv(fd_fixtures_csv(*self.fd_fixture_rows), {"last-modified": "Fri, 09 Oct 2026 13:00:00 GMT"})
            if path.endswith("/2627/E0.csv"):
                history = synthetic_season_rows(PL_TEAMS_FD, date(2026, 8, 15))[:40]
                return _csv(fd_season_csv(*history, *self.current_e0_rows))
            if path.endswith("/E0.csv"):
                return _csv(fd_season_csv(*synthetic_season_rows(PL_TEAMS_FD, _season_start(path))))
            if path.endswith("/E1.csv"):
                rows = synthetic_season_rows(CHAMPIONSHIP, _season_start(path), division="E1")
                return _csv(fd_season_csv(*rows))
        return httpx.Response(404, content=f"no route for {url}".encode())


def _season_start(path: str) -> date:
    code = path.split("/")[-2]
    return date(2000 + int(code[:2]), 8, 16)


def _json(body: bytes, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(200, content=body, headers={"content-type": "application/json", **(headers or {})})


def _csv(body: bytes, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(200, content=body, headers={"content-type": "text/csv", **(headers or {})})


def context(world: World, root, **settings) -> RunContext:
    store = LocalStore(root)
    fetcher = Fetcher(
        httpx.Client(transport=httpx.MockTransport(world.handle)), clock=lambda: world.now, sleep=lambda s: None
    )
    defaults = {"odds_api_key": "test-key-123", "training_seasons": 2}
    return RunContext(
        store=store,
        client=SourceClient(fetcher, store),
        clock=lambda: world.now,
        settings=Settings(**{**defaults, **settings}),
    )
