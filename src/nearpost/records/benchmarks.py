"""Benchmark entries: football-data.co.uk's closing lines, scored like any forecast.

They arrive days after the match (the CSV updates twice a week), so they are logged
separately from settlement, as an independent closing-line reference.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nearpost.devig import proportional, shin
from nearpost.domain import MarketQuote, MatchResult, Odds3
from nearpost.records.settlements import OUTCOME_NAMES, score_forecast
from nearpost.scoring import outcome_of


def _close(odds: Odds3, over_under: tuple[float, float] | None, result: MatchResult) -> dict[str, Any]:
    probs = [round(p, 6) for p in shin(odds)]
    over = round(proportional(over_under)[0], 6) if over_under else None
    scored = score_forecast(
        {"hash": None, "model": None, "horizon": None, "probs": probs, "over_2_5": over},
        result.home_goals,
        result.away_goals,
    )
    return {
        "probs": probs,
        "over_2_5": over,
        "scores": {k: scored[k] for k in ("rps", "log_loss", "brier")},
        "over_2_5_scores": scored["over_2_5"],
    }


def build_benchmark(
    match_id: str, quote: MarketQuote, result: MatchResult, *, source: Mapping[str, str]
) -> dict[str, Any] | None:
    closes: dict[str, Any] = {}
    if quote.avg_1x2:
        closes["football-data-avg"] = _close(quote.avg_1x2, quote.avg_over_under_2_5, result)
    if quote.exchange_1x2:
        closes["football-data-exchange"] = _close(quote.exchange_1x2, None, result)
    if not closes:
        return None
    return {
        "match_id": match_id,
        "home_goals": result.home_goals,
        "away_goals": result.away_goals,
        "outcome": OUTCOME_NAMES[outcome_of(result.home_goals, result.away_goals)],
        "source": dict(source),
        "closes": closes,
    }
