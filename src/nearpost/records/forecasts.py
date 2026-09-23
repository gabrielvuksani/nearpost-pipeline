"""Forecast ledger entries: one per (match, horizon, model), recorded before kickoff or never."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from nearpost.domain import Fixture
from nearpost.forecast import Forecast
from nearpost.ledger.repo import PendingEntry
from nearpost.tasks import Task
from nearpost.timeutil import format_utc, parse_utc

DECIMALS = 6


@dataclass(frozen=True)
class Unavailable:
    """The source answered but had nothing for this match. Recorded: it is a fact about that moment."""

    reason: str


@dataclass(frozen=True)
class Skipped:
    """The model could not run (a source failed, a team lacks history). Nothing is recorded,
    the task stays pending for the next run, and the run reports the reason loudly."""

    reason: str


@dataclass(frozen=True)
class ForecastBatch:
    entries: tuple[PendingEntry, ...]
    skipped: tuple[str, ...]


@dataclass(frozen=True)
class ModelSource:
    """A model ready to forecast this run, plus the snapshots it was built from."""

    model_id: str
    predict: Callable[[Fixture], Forecast | Unavailable | Skipped]
    inputs: tuple[Mapping[str, str], ...] = ()
    meta: Mapping[str, Any] = field(default_factory=dict)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, DECIMALS)


def _body(
    task: Task, fixture: Fixture, model: str, outcome: Forecast | Unavailable, source: ModelSource, now: datetime
) -> dict[str, Any]:
    forecast = outcome if isinstance(outcome, Forecast) else None
    meta = dict(source.meta)
    if forecast and forecast.n_books is not None:
        meta["n_books"] = forecast.n_books
    return {
        "match_id": fixture.match_id,
        "season": fixture.season,
        "gameweek": fixture.gameweek,
        "home": fixture.home,
        "away": fixture.away,
        "kickoff": format_utc(fixture.kickoff) if fixture.kickoff else None,
        "horizon": task.horizon,
        "model": model,
        "issued_at": format_utc(now),
        "probs": [_round(p) for p in forecast.probs] if forecast else None,
        "over_2_5": _round(forecast.over_2_5) if forecast else None,
        "btts": _round(forecast.btts) if forecast else None,
        "unavailable_reason": outcome.reason if isinstance(outcome, Unavailable) else None,
        "inputs": [dict(ref) for ref in source.inputs],
        "meta": meta,
    }


def build_forecasts(
    tasks: Sequence[Task], fixtures: Mapping[str, Fixture], sources: Mapping[str, ModelSource], *, now: datetime
) -> ForecastBatch:
    entries: list[PendingEntry] = []
    skipped: list[str] = []
    for task in tasks:
        if task.kind != "capture" or task.match_id is None:
            continue
        fixture = fixtures[task.match_id]
        closes = min(t for t in (task.window_end, fixture.kickoff) if t is not None) if fixture.kickoff else None
        if closes is None or now >= closes:
            # Built too late for this horizon's label (or after kickoff): record nothing. The
            # plan will show the window as missed rather than the ledger carrying a false label.
            skipped.extend(
                f"{fixture.match_id} {task.horizon} {m}: window closed before the forecast was built"
                for m in task.models
            )
            continue
        for model in task.models:
            source = sources.get(model)
            outcome = source.predict(fixture) if source else Skipped("no source this run")
            if isinstance(outcome, Skipped):
                skipped.append(f"{fixture.match_id} {task.horizon} {model}: {outcome.reason}")
                continue
            entries.append(("forecast", _body(task, fixture, model, outcome, source, now)))
    return ForecastBatch(tuple(entries), tuple(skipped))


def drop_late(
    entries: Sequence[PendingEntry], *, recorded_at: datetime
) -> tuple[tuple[PendingEntry, ...], tuple[str, ...]]:
    """Final guard, run with the append's own timestamp: a forecast whose kickoff is not
    strictly after the moment it enters the ledger is never written."""
    kept: list[PendingEntry] = []
    dropped: list[str] = []
    for kind, body in entries:
        if kind == "forecast" and parse_utc(body["kickoff"]) <= recorded_at:
            dropped.append(f"{body['match_id']} {body['horizon']} {body['model']}: kickoff passed before recording")
        else:
            kept.append((kind, body))
    return tuple(kept), tuple(dropped)
