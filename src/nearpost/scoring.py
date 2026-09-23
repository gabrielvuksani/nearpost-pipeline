"""Proper scoring rules for settled forecasts. Lower is better for all of them."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum

_EPSILON = 1e-15  # log loss clip, so a confident miss is huge but finite


class Outcome(IntEnum):
    HOME = 0
    DRAW = 1
    AWAY = 2


def outcome_of(home_goals: int, away_goals: int) -> Outcome:
    if home_goals > away_goals:
        return Outcome.HOME
    if home_goals == away_goals:
        return Outcome.DRAW
    return Outcome.AWAY


@dataclass(frozen=True)
class Scores:
    rps: float
    log_loss: float
    brier: float


@dataclass(frozen=True)
class BinaryScores:
    log_loss: float
    brier: float


def score_1x2(probs: Sequence[float], outcome: Outcome) -> Scores:
    """RPS (normalised by K-1), natural-log loss, and multiclass Brier (range 0-2)."""
    if len(probs) != 3 or abs(sum(probs) - 1.0) > 1e-5:  # stored probabilities are rounded to 6 dp
        raise ValueError(f"1X2 probabilities must be three values that sum to 1, got {probs}")
    actual = [1.0 if i == outcome else 0.0 for i in range(3)]
    cumulative_gap = [sum(probs[: k + 1]) - sum(actual[: k + 1]) for k in range(2)]
    return Scores(
        rps=sum(g * g for g in cumulative_gap) / 2,
        log_loss=-math.log(max(probs[outcome], _EPSILON)),
        brier=sum((p - a) ** 2 for p, a in zip(probs, actual, strict=True)),
    )


def binary_scores(probability: float, *, happened: bool) -> BinaryScores:
    if not 0.0 <= probability <= 1.0:
        raise ValueError(f"probability must be within [0, 1], got {probability}")
    p_actual = probability if happened else 1.0 - probability
    return BinaryScores(
        log_loss=-math.log(max(p_actual, _EPSILON)),
        brier=(probability - (1.0 if happened else 0.0)) ** 2,
    )
