"""Elo baseline, salvaged from the old project's elo_core.py.

Kept deliberately plain: it is the yardstick the real engine must beat (ALIGNMENT §4.4),
so it is logged live from step 0 with fixed, published parameters.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from nearpost.domain import MatchResult
from nearpost.forecast import Forecast
from nearpost.models.errors import ModelInputError

MODEL_ID = "elo-v1"


@dataclass(frozen=True)
class EloParams:
    k: float = 20.0
    home_advantage: float = 60.0
    draw_base: float = 0.26
    draw_sensitivity: float = 0.06
    draw_min: float = 0.18
    draw_max: float = 0.34
    # A club first seen in the second tier starts below one first seen in the top flight.
    seed_by_division: Mapping[str, float] = field(default_factory=lambda: {"E0": 1500.0, "E1": 1350.0})

    def as_dict(self) -> dict[str, object]:
        return {
            "k": self.k,
            "home_advantage": self.home_advantage,
            "draw_base": self.draw_base,
            "draw_sensitivity": self.draw_sensitivity,
            "draw_min": self.draw_min,
            "draw_max": self.draw_max,
            "seed_by_division": dict(self.seed_by_division),
        }


def _expected(r_home: float, r_away: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-(r_home - r_away) / 400.0))


def _goal_margin_multiplier(goal_difference: int) -> float:
    margin = abs(goal_difference)
    if margin <= 1:
        return 1.0
    if margin == 2:
        return 1.15
    return min(1.5, 1.30 + 0.05 * (margin - 3))


def fit_elo(history: Iterable[MatchResult], params: EloParams) -> dict[str, float]:
    """Ratings after replaying results in the order given (callers pass them oldest first)."""
    ratings: dict[str, float] = {}
    for match in history:
        seed = params.seed_by_division.get(match.division, min(params.seed_by_division.values()))
        home = ratings.get(match.home, seed)
        away = ratings.get(match.away, seed)
        actual = 1.0 if match.home_goals > match.away_goals else 0.5 if match.home_goals == match.away_goals else 0.0
        delta = (
            params.k
            * _goal_margin_multiplier(match.home_goals - match.away_goals)
            * (actual - _expected(home + params.home_advantage, away))
        )
        ratings = {**ratings, match.home: home + delta, match.away: away - delta}
    return ratings


def predict_elo(ratings: Mapping[str, float], home: str, away: str, params: EloParams) -> Forecast:
    for team in (home, away):
        if team not in ratings:
            raise ModelInputError(f"elo has no rating for {team!r}")
    r_home = ratings[home] + params.home_advantage
    r_away = ratings[away]
    p_draw = params.draw_base + params.draw_sensitivity * math.exp(-abs(r_home - r_away) / 200.0)
    p_draw = max(params.draw_min, min(params.draw_max, p_draw))
    e_home = _expected(r_home, r_away)
    return Forecast(probs=(e_home * (1 - p_draw), p_draw, (1 - e_home) * (1 - p_draw)))
