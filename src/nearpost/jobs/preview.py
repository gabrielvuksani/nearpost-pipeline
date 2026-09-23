"""`preview`: fit the baselines on live data and print the next fixtures' forecasts.

Writes nothing to the ledger. A pre-flight check that team mapping, history and model
fitting all work on real inputs before the recorder goes live.
"""

from __future__ import annotations

from nearpost.forecast import Forecast
from nearpost.jobs.context import RunContext
from nearpost.jobs.modelling import independent_sources
from nearpost.jobs.tick import _history, read_calendar
from nearpost.models.history import training_set


def preview(ctx: RunContext, *, limit: int = 10) -> str:
    now = ctx.clock()
    calendar = read_calendar(ctx, now)
    results, _ = _history(ctx, now)
    history = training_set(results, calendar.fixtures, as_of=now)
    sources, problems = independent_sources(history, as_of=now, inputs=())
    upcoming = sorted(
        (f for f in calendar.fixtures if f.kickoff and f.kickoff > now and not f.finished),
        key=lambda f: f.kickoff,  # type: ignore[arg-type, return-value]
    )[:limit]

    lines = [f"trained on {len(history)} matches up to {now:%Y-%m-%d %H:%M}Z", *problems, ""]
    lines.append(f"{'kickoff (UTC)':<17} {'match':<44} {'model':<15} {'H':>6} {'D':>6} {'A':>6} {'O2.5':>6}")
    for fixture in upcoming:
        for model_id, source in sources.items():
            outcome = source.predict(fixture)
            name = f"{fixture.home} v {fixture.away}"
            if isinstance(outcome, Forecast):
                h, d, a = outcome.probs
                over = f"{outcome.over_2_5:6.3f}" if outcome.over_2_5 is not None else f"{'-':>6}"
                lines.append(
                    f"{fixture.kickoff:%Y-%m-%d %H:%M} {name:<44} {model_id:<15} {h:6.3f} {d:6.3f} {a:6.3f} {over}"
                )
            else:
                lines.append(f"{fixture.kickoff:%Y-%m-%d %H:%M} {name:<44} {model_id:<15} {outcome}")
    return "\n".join(lines)
