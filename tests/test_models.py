from datetime import date, timedelta

import pytest

from nearpost.domain import MatchResult
from nearpost.models.dixon_coles import DixonColesModel
from nearpost.models.elo import EloParams, fit_elo, predict_elo
from nearpost.models.errors import ModelInputError


def _season(rounds=12, start=date(2025, 8, 1)):
    """A small league where `strong` usually beats everyone and `weak` usually loses."""
    scorelines = {
        ("strong", "weak"): [(3, 0), (2, 1), (4, 1), (1, 1), (2, 0)],
        ("weak", "middle"): [(0, 1), (1, 2), (2, 2), (0, 2), (1, 0)],
        ("middle", "strong"): [(0, 2), (1, 3), (2, 2), (1, 2), (0, 1)],
        ("strong", "middle"): [(2, 1), (3, 1), (1, 0), (0, 0), (2, 2)],
        ("middle", "weak"): [(2, 0), (1, 1), (3, 2), (1, 0), (0, 1)],
        ("weak", "strong"): [(0, 2), (1, 3), (0, 1), (2, 2), (0, 3)],
    }
    results, day = [], start
    for r in range(rounds):
        for (home, away), scores in scorelines.items():
            hg, ag = scores[r % len(scores)]
            results.append(MatchResult("E0", day, home, away, hg, ag))
            day += timedelta(days=2)
    return results


def test_elo_ratings_rank_teams_by_results():
    ratings = fit_elo(_season(), EloParams())
    assert ratings["strong"] > ratings["middle"] > ratings["weak"]


def test_fit_elo_does_not_mutate_its_input_and_is_deterministic():
    history = _season()
    snapshot = list(history)
    assert fit_elo(history, EloParams()) == fit_elo(history, EloParams())
    assert history == snapshot


def test_elo_seeds_first_seen_second_division_clubs_lower():
    history = [MatchResult("E1", date(2025, 8, 1), "promoted", "other", 1, 1)]
    params = EloParams()
    ratings = fit_elo(history, params)
    # Elo is zero-sum, so two newly seeded clubs still average the E1 seed after playing.
    assert ratings["promoted"] + ratings["other"] == pytest.approx(2 * params.seed_by_division["E1"])
    assert ratings["promoted"] < params.seed_by_division["E0"]


def test_elo_prediction_is_a_probability_vector_favouring_the_stronger_side():
    ratings = fit_elo(_season(), EloParams())
    forecast = predict_elo(ratings, "strong", "weak", EloParams())
    assert sum(forecast.probs) == pytest.approx(1.0)
    assert forecast.probs[0] > forecast.probs[2]
    assert forecast.over_2_5 is None


def test_elo_refuses_teams_without_history():
    with pytest.raises(ModelInputError, match="ghost"):
        predict_elo({"strong": 1500.0}, "strong", "ghost", EloParams())


def test_dixon_coles_learns_team_strength_and_prices_goals_markets():
    model = DixonColesModel.fit(_season(), as_of=date(2026, 1, 1))
    forecast = model.predict("strong", "weak")
    assert sum(forecast.probs) == pytest.approx(1.0, abs=1e-6)
    assert forecast.probs[0] > 0.5
    assert 0.0 < forecast.over_2_5 < 1.0
    assert 0.0 < forecast.btts < 1.0


def test_dixon_coles_refuses_teams_without_history():
    model = DixonColesModel.fit(_season(), as_of=date(2026, 1, 1))
    with pytest.raises(ModelInputError, match="ghost"):
        model.predict("ghost", "weak")


def test_dixon_coles_refuses_training_data_from_the_future():
    with pytest.raises(ModelInputError, match="fall after"):
        DixonColesModel.fit(_season(), as_of=date(2025, 8, 5))


def test_dixon_coles_accepts_results_from_earlier_the_same_day():
    # training_set admits an FPL result that finished before the forecast on the same date;
    # the fit guard must agree, or every afternoon forecast after a lunchtime match is lost.
    history = [*_season(), MatchResult("E0", date(2026, 1, 10), "strong", "weak", 2, 0)]
    model = DixonColesModel.fit(history, as_of=date(2026, 1, 10))
    assert model.n_matches == len(history)


def test_dixon_coles_analytic_gradient_matches_finite_differences():
    import numpy as np
    from scipy.optimize import check_grad

    from nearpost.models.dixon_coles import likelihood

    nll, grad, size, _, _ = likelihood(_season(), as_of=date(2026, 1, 1), xi=0.0018)
    rng = np.random.default_rng(3)
    for _ in range(5):
        point = rng.normal(0, 0.3, size)
        point[-1] = rng.uniform(-0.2, 0.2)  # rho
        assert check_grad(nll, grad, point) < 1e-4 * max(1.0, float(np.linalg.norm(grad(point))))
