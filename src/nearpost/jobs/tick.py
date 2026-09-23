"""`tick`: do whatever work is due right now, and nothing else."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from nearpost.domain import Fixture, Gameweek, MatchResult
from nearpost.horizons import INDEPENDENT_MODELS
from nearpost.jobs.context import JobReport, RunContext
from nearpost.jobs.modelling import football_data_market, independent_sources, odds_api_market, odds_budget_block
from nearpost.ledger.index import LedgerIndex
from nearpost.ledger.repo import LedgerRepo, PendingEntry
from nearpost.market import FOOTBALL_DATA_MODEL_ID, ODDS_API_MODEL_ID
from nearpost.models.errors import ModelInputError
from nearpost.models.history import training_set
from nearpost.records.forecasts import ModelSource, Unavailable, build_forecasts, drop_late
from nearpost.records.settlements import build_settlement
from nearpost.snapshots import Snapshot, write_once
from nearpost.sources import fpl, odds_api
from nearpost.sources.errors import SchemaError, SourceError
from nearpost.sources.football_data import FIXTURES_URL, parse_results, parse_upcoming
from nearpost.tasks import Task, due, plan_work
from nearpost.timeutil import format_utc, season_of

RECOVERABLE = (SourceError, SchemaError, ModelInputError)


@dataclass(frozen=True)
class Calendar:
    bootstrap: Snapshot
    fixtures: list[Fixture]
    fixtures_ref: dict[str, str]
    gameweeks: list[Gameweek]


def read_calendar(ctx: RunContext, now: datetime) -> Calendar:
    """FPL is the calendar of record. If it can't be read, no work can be planned: that
    failure is fatal for the run and propagates."""
    bootstrap = ctx.client.peek("fpl-bootstrap", fpl.BOOTSTRAP_URL)
    teams = fpl.parse_teams(bootstrap.body)
    snapshot, ref = ctx.client.fetch("fpl-fixtures", fpl.FIXTURES_URL)
    fixtures = fpl.parse_fixtures(snapshot.body, teams, season=season_of(now))
    return Calendar(bootstrap, fixtures, ref, fpl.parse_events(bootstrap.body))


def _seasons(current: str, count: int) -> list[str]:
    start = int(current[:4])
    return [f"{y}-{(y + 1) % 100:02d}" for y in range(start, start - count, -1)]


def _history(ctx: RunContext, now: datetime) -> tuple[list[MatchResult], list[dict[str, str]]]:
    current = season_of(now)
    results: list[MatchResult] = []
    refs: list[dict[str, str]] = []
    for season in _seasons(current, ctx.settings.training_seasons):
        for division in ("E0", "E1"):
            body, ref = ctx.client.football_data_season(season, division, current=season == current)
            results.extend(parse_results(body))
            refs.append(ref)
    return results, refs


def _wants(captures: Sequence[Task], models: Sequence[str]) -> bool:
    return any(m in models for t in captures for m in t.models)


def _sources(
    ctx: RunContext, captures: Sequence[Task], calendar: Calendar, now: datetime, credits: int | None
) -> tuple[dict[str, ModelSource], list[str], dict[str, Any] | None]:
    sources: dict[str, ModelSource] = {}
    problems: list[str] = []
    odds_state: dict[str, Any] | None = None

    if _wants(captures, INDEPENDENT_MODELS):
        try:
            results, refs = _history(ctx, now)
            history = training_set(results, calendar.fixtures, as_of=now)
            fitted, fit_problems = independent_sources(history, as_of=now, inputs=(calendar.fixtures_ref, *refs))
            sources |= fitted
            problems.extend(fit_problems)
        except RECOVERABLE as error:
            problems.append(f"independent models unavailable: {error}")

    if _wants(captures, [FOOTBALL_DATA_MODEL_ID]):
        try:
            snapshot, ref = ctx.client.fetch("fdco-fixtures", FIXTURES_URL)
            upcoming = parse_upcoming(snapshot.body, division="E0")
            sources[FOOTBALL_DATA_MODEL_ID] = football_data_market(
                upcoming, ref=ref, observed_at=snapshot.headers.get("last-modified")
            )
        except RECOVERABLE as error:
            problems.append(f"football-data fixtures.csv unavailable: {error}")

    block = odds_budget_block(captures, credits_remaining=credits, reserve=ctx.settings.odds_credit_reserve)
    if block is None:
        if not ctx.settings.odds_api_key:
            problems.append("ODDS_API_KEY is not configured; market captures stay pending")
        else:
            request = odds_api.OddsApiRequest(regions=ctx.settings.odds_regions, markets=ctx.settings.odds_markets)
            try:
                snapshot, ref = ctx.client.fetch(
                    "odds-api-epl",
                    request.url,
                    params=request.params(api_key=ctx.settings.odds_api_key),
                    public_url=request.redacted_url,
                )
                credits_seen = odds_api.credit_state(snapshot.headers)
                if credits_seen:
                    odds_state = {**credits_seen, "observed_at": format_utc(snapshot.fetched_at)}
                sources[ODDS_API_MODEL_ID] = odds_api_market(odds_api.parse_odds(snapshot.body), ref=ref)
            except SchemaError as error:
                # The credit is already spent and a retry would likely get the same payload:
                # record the absence for these horizons and alert once, rather than loop.
                problems.append(f"odds-api payload unparseable: {error}")
                reason = f"The Odds API payload was unparseable: {error}"[:300]
                sources[ODDS_API_MODEL_ID] = ModelSource(ODDS_API_MODEL_ID, lambda f: Unavailable(reason), (ref,))
            except RECOVERABLE as error:
                problems.append(f"odds-api unavailable: {error}")
    elif _wants(captures, [ODDS_API_MODEL_ID]):
        reason = block
        sources[ODDS_API_MODEL_ID] = ModelSource(ODDS_API_MODEL_ID, lambda f: Unavailable(reason))

    return sources, problems, odds_state


def _ep_next_entry(ctx: RunContext, task: Task, calendar: Calendar, now: datetime) -> PendingEntry:
    ref = ctx.client.keep(calendar.bootstrap)
    table = fpl.extract_ep_next(calendar.bootstrap.body)
    data = json.dumps({"gameweek": task.gameweek, "players": table}, sort_keys=True).encode()
    table_sha = hashlib.sha256(data).hexdigest()
    table_key = f"derived/fpl/ep-next/gw{task.gameweek:02d}-{table_sha[:12]}.json"
    write_once(ctx.store, table_key, data, "application/json", must_match=True)
    return (
        "fpl-ep-next",
        {
            "gameweek": task.gameweek,
            "deadline": format_utc(task.window_end) if task.window_end else None,
            "captured_at": format_utc(now),
            "source": ref,
            "table": {"key": table_key, "sha256": table_sha},
            "n_players": len(table),
        },
    )


def run_tick(ctx: RunContext, *, credits: int | None, calendar: Calendar | None = None) -> JobReport:
    now = ctx.clock()
    calendar = calendar or read_calendar(ctx, now)
    repo = LedgerRepo(ctx.store)
    index: LedgerIndex = repo.load_index()
    todo = due(plan_work(calendar.fixtures, calendar.gameweeks, index, now=now), now)
    by_id = {f.match_id: f for f in calendar.fixtures}

    entries: list[PendingEntry] = []
    problems: list[str] = []
    odds_state = None

    captures = [t for t in todo if t.kind == "capture"]
    if captures:
        sources, source_problems, odds_state = _sources(ctx, captures, calendar, now, credits)
        batch = build_forecasts(captures, by_id, sources, now=ctx.clock())
        entries.extend(batch.entries)
        problems.extend(source_problems)
        problems.extend(f"skipped {s}" for s in batch.skipped)

    for task in (t for t in todo if t.kind == "settle"):
        fixture = by_id.get(task.match_id or "")
        if fixture is not None and fixture.finished:
            opened = index.open_forecasts.get(fixture.match_id, ())
            body = build_settlement(fixture, opened, settled_at=ctx.clock(), source=calendar.fixtures_ref)
            entries.append(("settlement", body))

    for task in (t for t in todo if t.kind == "fpl-deadline"):
        entries.append(_ep_next_entry(ctx, task, calendar, now))

    recorded_at = ctx.clock()
    kept, late = drop_late(entries, recorded_at=recorded_at)
    problems.extend(f"dropped {message}" for message in late)
    index = repo.append(kept, recorded_at=format_utc(recorded_at), expected_head_seq=index.head_seq)
    after = plan_work(calendar.fixtures, calendar.gameweeks, index, now=ctx.clock())
    return JobReport(len(kept), index.head_hash, index.head_seq, after, tuple(problems), odds_state)
