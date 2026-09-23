"""What the recorder owes: pending work, and work whose window closed undone.

Pure: derived from the FPL calendar, the ledger index and the clock, so any run can
recompute it and a failed run is simply retried by the next one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from nearpost.domain import Fixture, Gameweek
from nearpost.horizons import HORIZONS, window
from nearpost.ledger.index import LedgerIndex, forecast_key
from nearpost.timeutil import format_utc, parse_utc

SETTLE_AFTER_KICKOFF = timedelta(hours=2, minutes=15)
EP_NEXT_BEFORE_DEADLINE = timedelta(hours=1)
MISSED_LOOKBACK = timedelta(days=7)


@dataclass(frozen=True)
class Task:
    kind: str  # "capture" | "settle" | "fpl-deadline"
    due_at: datetime
    window_end: datetime | None = None
    match_id: str | None = None
    horizon: str | None = None
    kickoff: datetime | None = None
    gameweek: int | None = None
    models: tuple[str, ...] = ()


@dataclass(frozen=True)
class Plan:
    pending: tuple[Task, ...]
    missed: tuple[Task, ...]


def _captures(fixture: Fixture, index: LedgerIndex) -> Iterable[Task]:
    assert fixture.kickoff is not None
    for horizon in HORIZONS:
        kickoff = format_utc(fixture.kickoff)
        done = {
            m for m in horizon.models if forecast_key(fixture.match_id, kickoff, horizon.name, m) in index.forecasts
        }
        missing = tuple(m for m in horizon.models if m not in done)
        if missing:
            start, end = window(horizon, fixture.kickoff)
            yield Task(
                "capture", start, end, fixture.match_id, horizon.name, fixture.kickoff, fixture.gameweek, missing
            )


def plan_work(fixtures: Iterable[Fixture], gameweeks: Iterable[Gameweek], index: LedgerIndex, *, now: datetime) -> Plan:
    genesis = parse_utc(index.genesis_at) if index.genesis_at else None
    pending: list[Task] = []
    missed: list[Task] = []

    def triage(task: Task) -> None:
        assert task.window_end is not None
        if task.window_end > now:
            pending.append(task)
        elif genesis is not None and genesis <= task.window_end and now - task.window_end <= MISSED_LOOKBACK:
            missed.append(task)

    for fixture in fixtures:
        if fixture.kickoff is None:
            continue
        for task in _captures(fixture, index):
            triage(task)
        if fixture.match_id not in index.settled and index.has_forecasts_for(fixture.match_id):
            pending.append(
                Task("settle", fixture.kickoff + SETTLE_AFTER_KICKOFF, None, fixture.match_id, kickoff=fixture.kickoff)
            )

    for gameweek in gameweeks:
        if gameweek.gameweek not in index.fpl_ep_next:
            due_at = gameweek.deadline - EP_NEXT_BEFORE_DEADLINE
            triage(Task("fpl-deadline", due_at, gameweek.deadline, gameweek=gameweek.gameweek))

    return Plan(tuple(sorted(pending, key=lambda t: t.due_at)), tuple(sorted(missed, key=lambda t: t.due_at)))


def due(plan: Plan, now: datetime) -> tuple[Task, ...]:
    return tuple(t for t in plan.pending if t.due_at <= now)


def task_to_status(task: Task) -> dict[str, Any]:
    status: dict[str, Any] = {"kind": task.kind, "due_at": format_utc(task.due_at)}
    if task.match_id is not None:
        status["match_id"] = task.match_id
    if task.horizon is not None:
        status["horizon"] = task.horizon
    if task.kickoff is not None:
        status["kickoff"] = format_utc(task.kickoff)
    if task.kind == "fpl-deadline":
        status["gameweek"] = task.gameweek
    return status


def missed_to_status(task: Task) -> dict[str, Any]:
    assert task.window_end is not None
    status = {k: v for k, v in task_to_status(task).items() if k not in ("due_at", "kickoff")}
    return {**status, "window_closed_at": format_utc(task.window_end)}
