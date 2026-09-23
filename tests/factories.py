"""Synthetic payloads in the exact shapes the real sources return.

The numbers are invented: the repo is public and code-only, so no licensed data
(not even test samples) is committed.
"""

from __future__ import annotations

import json

FPL_TEAMS = [
    (1, "Arsenal"), (2, "Aston Villa"), (3, "Bournemouth"), (4, "Brentford"), (5, "Brighton"),
    (6, "Chelsea"), (7, "Coventry City"), (8, "Crystal Palace"), (9, "Everton"), (10, "Fulham"),
    (11, "Hull City"), (12, "Ipswich Town"), (13, "Leeds"), (14, "Liverpool"), (15, "Man City"),
    (16, "Man Utd"), (17, "Newcastle"), (18, "Nott'm Forest"), (19, "Spurs"), (20, "Sunderland"),
]  # fmt: skip


def fpl_bootstrap(events=None, elements=None) -> bytes:
    return json.dumps(
        {
            "teams": [{"id": i, "name": n, "short_name": n[:3].upper()} for i, n in FPL_TEAMS],
            "events": events
            or [
                {"id": 5, "deadline_time": "2026-09-18T17:30:00Z", "finished": True, "data_checked": True},
                {"id": 6, "deadline_time": "2026-10-10T10:00:00Z", "finished": False, "data_checked": False},
            ],
            "elements": elements
            or [
                {"id": 1, "team": 1, "element_type": 1, "web_name": "Keeper", "ep_next": "4.5", "now_cost": 55},
                {"id": 2, "team": 14, "element_type": 3, "web_name": "Winger", "ep_next": "7.1", "now_cost": 145},
                {"id": 3, "team": 20, "element_type": 4, "web_name": "Striker", "ep_next": None, "now_cost": 60},
            ],
        }
    ).encode()


def fpl_fixture(
    fid, event, kickoff, home, away, *, finished=False, started=False, home_goals=None, away_goals=None
) -> dict:
    return {
        "id": fid,
        "code": 1000 + fid,
        "event": event,
        "kickoff_time": kickoff,
        "team_h": home,
        "team_a": away,
        "finished": finished,
        "finished_provisional": finished,
        "started": started or finished,
        "team_h_score": home_goals,
        "team_a_score": away_goals,
        "minutes": 90 if finished else 0,
        "stats": [],
    }


def fpl_fixtures(*fixtures: dict) -> bytes:
    return json.dumps(list(fixtures)).encode()


FD_SEASON_HEADER = (
    "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HxG,AxG,AvgH,AvgD,AvgA,"
    "AvgCH,AvgCD,AvgCA,BFECH,BFECD,BFECA,AvgC>2.5,AvgC<2.5"
)


def fd_season_csv(*rows: str) -> bytes:
    """Rows in FD_SEASON_HEADER order. The real files start with a UTF-8 BOM, so this does too."""
    return ("﻿" + "\n".join([FD_SEASON_HEADER, *rows]) + "\n").encode()


FD_FIXTURES_HEADER = "Div,Date,Time,HomeTeam,AwayTeam,Referee,AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5"


def fd_fixtures_csv(*rows: str) -> bytes:
    return ("﻿" + "\n".join([FD_FIXTURES_HEADER, *rows]) + "\n").encode()


def odds_event(home, away, commence, books) -> dict:
    """books: list of (key, (h, d, a) or None, (over, under) at 2.5 or None)."""
    bookmakers = []
    for key, h2h, totals in books:
        markets = []
        if h2h:
            markets.append(
                {
                    "key": "h2h",
                    "last_update": "2026-10-09T10:00:00Z",
                    "outcomes": [
                        {"name": home, "price": h2h[0]},
                        {"name": "Draw", "price": h2h[1]},
                        {"name": away, "price": h2h[2]},
                    ],
                }
            )
        if totals:
            markets.append(
                {
                    "key": "totals",
                    "last_update": "2026-10-09T10:00:00Z",
                    "outcomes": [
                        {"name": "Over", "price": totals[0], "point": 2.5},
                        {"name": "Under", "price": totals[1], "point": 2.5},
                    ],
                }
            )
        bookmakers.append({"key": key, "title": key.title(), "last_update": "2026-10-09T10:00:00Z", "markets": markets})
    return {
        "id": f"evt-{home[:3]}-{away[:3]}",
        "sport_key": "soccer_epl",
        "commence_time": commence,
        "home_team": home,
        "away_team": away,
        "bookmakers": bookmakers,
    }


def odds_payload(*events: dict) -> bytes:
    return json.dumps(list(events)).encode()


PL_TEAMS_FD = [
    "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton", "Chelsea", "Coventry",
    "Crystal Palace", "Everton", "Fulham", "Hull", "Ipswich", "Leeds", "Liverpool", "Man City",
    "Man United", "Newcastle", "Nott'm Forest", "Tottenham", "Sunderland",
]  # fmt: skip


def synthetic_season_rows(teams, start, *, division="E0", seed=7, rounds=1):
    """A full double round robin with varied, deterministic scorelines (invented)."""
    from datetime import timedelta

    rows, day, n = [], start, 0
    for _ in range(rounds):
        for i, home in enumerate(teams):
            for j, away in enumerate(teams):
                if i == j:
                    continue
                n += 1
                strength = (len(teams) - i) - (len(teams) - j)
                hg = max(0, (seed * n) % 4 + (1 if strength > 5 else 0) - (1 if strength < -5 else 0))
                ag = max(0, (seed * n + 3) % 3 - (1 if strength > 5 else 0))
                rows.append(f"{division},{day:%d/%m/%Y},15:00,{home},{away},{hg},{ag},,,,2.0,3.4,3.8,,,,,,,,")
                if n % 10 == 0:
                    day += timedelta(days=7)
    return rows
