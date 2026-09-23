"""`daily`: refresh slow sources, add closing-line benchmarks and FPL results, verify the whole
chain, publish the scoreboard, then do any due tick work."""

from __future__ import annotations

import json
from dataclasses import replace

from nearpost.jobs.context import JobReport, RunContext
from nearpost.jobs.tick import RECOVERABLE, Calendar, read_calendar, run_tick
from nearpost.ledger.chain import ChainError
from nearpost.ledger.index import LedgerIndex
from nearpost.ledger.repo import LedgerRepo, PendingEntry
from nearpost.records.benchmarks import build_benchmark
from nearpost.scoreboard import build_scoreboard
from nearpost.sources import fpl
from nearpost.sources.football_data import FIXTURES_URL, parse_closing, parse_results
from nearpost.timeutil import format_utc, season_of

SCOREBOARD_KEY = "derived/scoreboard.json"


def _benchmarks(ctx: RunContext, calendar: Calendar, index: LedgerIndex) -> list[PendingEntry]:
    waiting = sorted(index.settled - index.benchmarked)
    if not waiting:
        return []
    body, ref = ctx.client.football_data_season(season_of(ctx.clock()), "E0", current=True)
    closing = parse_closing(body)
    results = {(r.home, r.away): r for r in parse_results(body)}
    by_id = {f.match_id: f for f in calendar.fixtures}
    entries: list[PendingEntry] = []
    for match_id in waiting:
        fixture = by_id.get(match_id)
        if fixture is None:
            continue
        teams = (fixture.home, fixture.away)
        if teams in closing and teams in results:
            benchmark = build_benchmark(match_id, closing[teams], results[teams], source=ref)
            if benchmark is not None:
                entries.append(("benchmark", benchmark))
    return entries


def _fpl_results(ctx: RunContext, calendar: Calendar, index: LedgerIndex) -> list[PendingEntry]:
    entries: list[PendingEntry] = []
    for gameweek in calendar.gameweeks:
        gw = gameweek.gameweek
        if gameweek.data_checked and gw in index.fpl_ep_next and gw not in index.fpl_results:
            _, ref = ctx.client.fetch("fpl-live", fpl.live_url(gw))
            entries.append(("fpl-result", {"gameweek": gw, "captured_at": format_utc(ctx.clock()), "source": ref}))
    return entries


def run_daily(ctx: RunContext, *, credits: int | None) -> JobReport:
    now = ctx.clock()
    calendar = read_calendar(ctx, now)
    ctx.client.keep(calendar.bootstrap)
    repo = LedgerRepo(ctx.store)
    index = repo.load_index()
    # Verify the whole chain from genesis before adding anything to it.
    chain = repo.read_all()
    if chain and chain[-1].hash != index.head_hash:
        raise ChainError("ledger index head disagrees with the verified chain")
    problems: list[str] = []
    entries: list[PendingEntry] = []

    try:
        ctx.client.fetch("fdco-fixtures", FIXTURES_URL)
    except RECOVERABLE as error:
        problems.append(f"football-data fixtures.csv snapshot failed: {error}")
    for collect, label in ((_benchmarks, "closing-line benchmarks"), (_fpl_results, "FPL results")):
        try:
            entries.extend(collect(ctx, calendar, index))
        except RECOVERABLE as error:
            problems.append(f"{label} unavailable: {error}")

    repo.append(entries, recorded_at=format_utc(ctx.clock()), expected_head_seq=index.head_seq)
    board = build_scoreboard(repo.read_all(), generated_at=format_utc(ctx.clock()))
    ctx.store.put(SCOREBOARD_KEY, json.dumps(board, indent=1).encode())

    tick = run_tick(ctx, credits=credits, calendar=calendar)
    return replace(tick, appended=tick.appended + len(entries), problems=(*problems, *tick.problems))
