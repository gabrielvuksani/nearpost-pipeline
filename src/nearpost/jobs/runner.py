"""Run a mode, always leave an honest status behind, and fail loudly on any problem."""

from __future__ import annotations

from dataclasses import dataclass

from nearpost.jobs.context import JobReport, RunContext
from nearpost.jobs.daily import run_daily
from nearpost.jobs.status import build_status, carried_forward, previous_credits, read_status, write_status
from nearpost.jobs.tick import run_tick

MODES = ("tick", "daily")


@dataclass(frozen=True)
class RunOutcome:
    mode: str
    appended: int
    head_hash: str
    head_seq: int
    problems: tuple[str, ...]


class RunFailedError(RuntimeError):
    def __init__(self, outcome: RunOutcome) -> None:
        super().__init__(f"{outcome.mode} finished with {len(outcome.problems)} problem(s)")
        self.outcome = outcome
        self.problems = outcome.problems


def run(mode: str, ctx: RunContext) -> RunOutcome:
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
    previous = read_status(ctx.store)
    credits = previous_credits(previous, now=ctx.clock())
    try:
        report: JobReport = run_daily(ctx, credits=credits) if mode == "daily" else run_tick(ctx, credits=credits)
    except Exception:
        write_status(ctx.store, carried_forward(previous, now=ctx.clock()))
        raise

    succeeded = () if report.problems else (("daily", "tick") if mode == "daily" else ("tick",))
    status = build_status(
        report.plan,  # type: ignore[arg-type]
        now=ctx.clock(),
        previous=previous,
        succeeded=succeeded,
        odds_api=report.odds_api,
    )
    write_status(ctx.store, status)
    outcome = RunOutcome(mode, report.appended, report.head_hash, report.head_seq, report.problems)
    if report.problems:
        raise RunFailedError(outcome)
    return outcome
