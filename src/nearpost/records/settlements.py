"""Settlement entries: the result, and every open forecast for the match scored against it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from nearpost.domain import Fixture
from nearpost.ledger.index import OpenForecast
from nearpost.scoring import binary_scores, outcome_of, score_1x2
from nearpost.timeutil import format_utc

OUTCOME_NAMES = ("home", "draw", "away")


def _binary(probability: float | None, happened: bool) -> dict[str, float] | None:
    if probability is None:
        return None
    scores = binary_scores(probability, happened=happened)
    return {"log_loss": round(scores.log_loss, 6), "brier": round(scores.brier, 6)}


def score_forecast(forecast: OpenForecast, home_goals: int, away_goals: int) -> dict[str, Any]:
    scores = score_1x2(forecast["probs"], outcome_of(home_goals, away_goals))
    return {
        "forecast": forecast["hash"],
        "model": forecast["model"],
        "horizon": forecast["horizon"],
        "rps": round(scores.rps, 6),
        "log_loss": round(scores.log_loss, 6),
        "brier": round(scores.brier, 6),
        "over_2_5": _binary(forecast.get("over_2_5"), home_goals + away_goals > 2),
        "btts": _binary(forecast.get("btts"), home_goals > 0 and away_goals > 0),
    }


def build_settlement(
    fixture: Fixture, open_forecasts: Sequence[OpenForecast], *, settled_at: datetime, source: Mapping[str, str]
) -> dict[str, Any]:
    if not fixture.finished or fixture.home_goals is None or fixture.away_goals is None:
        raise ValueError(f"{fixture.match_id} is not finished; nothing to settle")
    hg, ag = fixture.home_goals, fixture.away_goals
    kickoff = format_utc(fixture.kickoff) if fixture.kickoff else None
    scored = [f for f in open_forecasts if f.get("kickoff") == kickoff]
    void = [
        {
            "forecast": f["hash"],
            "model": f["model"],
            "horizon": f["horizon"],
            "kickoff": f.get("kickoff"),
            "reason": f"made for a kickoff that did not happen (moved to {kickoff})",
        }
        for f in open_forecasts
        if f.get("kickoff") != kickoff
    ]
    return {
        "match_id": fixture.match_id,
        "home_goals": hg,
        "away_goals": ag,
        "outcome": OUTCOME_NAMES[outcome_of(hg, ag)],
        "settled_at": format_utc(settled_at),
        "source": dict(source),
        "scores": [score_forecast(f, hg, ag) for f in scored],
        "void": void,
    }
