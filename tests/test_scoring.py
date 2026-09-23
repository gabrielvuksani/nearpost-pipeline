import math

import pytest

from nearpost.scoring import Outcome, binary_scores, outcome_of, score_1x2


def test_outcome_of_goals():
    assert outcome_of(2, 1) is Outcome.HOME
    assert outcome_of(0, 0) is Outcome.DRAW
    assert outcome_of(1, 3) is Outcome.AWAY


def test_perfect_forecast_scores_zero():
    scores = score_1x2((1.0, 0.0, 0.0), Outcome.HOME)
    assert scores.rps == 0.0
    assert scores.brier == 0.0
    assert scores.log_loss == pytest.approx(0.0, abs=1e-12)


def test_known_values_for_a_home_win():
    probs = (0.5, 0.3, 0.2)
    scores = score_1x2(probs, Outcome.HOME)
    # RPS: cumulative (0.5, 0.8) vs (1, 1) -> (0.25 + 0.04) / 2
    assert scores.rps == pytest.approx(0.145)
    assert scores.brier == pytest.approx(0.25 + 0.09 + 0.04)
    assert scores.log_loss == pytest.approx(-math.log(0.5))


def test_rps_rewards_near_misses_in_order():
    # Both put 0.6 on the wrong side, but "draw-heavy" is closer to a home win.
    near = score_1x2((0.2, 0.6, 0.2), Outcome.HOME)
    far = score_1x2((0.2, 0.2, 0.6), Outcome.HOME)
    assert near.rps < far.rps


def test_zero_probability_on_the_outcome_is_clipped_not_infinite():
    scores = score_1x2((1.0, 0.0, 0.0), Outcome.AWAY)
    assert math.isfinite(scores.log_loss)
    assert scores.log_loss > 20


def test_probabilities_must_sum_to_one():
    with pytest.raises(ValueError, match="sum to 1"):
        score_1x2((0.5, 0.5, 0.5), Outcome.HOME)


def test_binary_scores_for_over_2_5():
    scores = binary_scores(0.6, happened=True)
    assert scores.brier == pytest.approx(0.16)
    assert scores.log_loss == pytest.approx(-math.log(0.6))
