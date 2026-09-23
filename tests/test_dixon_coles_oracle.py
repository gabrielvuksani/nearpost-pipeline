"""Our Dixon-Coles must agree with penaltyblog's, which stays a dev-only reference so it
never runs inside the process that holds production secrets.

Agreement is approximate by design. On the live 2026-09-23 dataset (3,873 matches), our
analytic-gradient fit reached a lower negative log-likelihood than penaltyblog (3596.2571
vs 3596.2775; gradient norm 0.05 vs 2.4), i.e. penaltyblog stops slightly short of the
maximum. Probabilities differed by at most 0.0057 across 330 fixtures.
"""

from datetime import date

import penaltyblog as pb
import pytest

from nearpost.models.dixon_coles import DixonColesModel
from nearpost.sources.football_data import parse_results
from tests.factories import PL_TEAMS_FD, fd_season_csv, synthetic_season_rows

AS_OF = date(2026, 7, 1)


@pytest.fixture(scope="module")
def history():
    return parse_results(fd_season_csv(*synthetic_season_rows(PL_TEAMS_FD, date(2025, 8, 16), seed=11)))


@pytest.fixture(scope="module")
def ours(history):
    return DixonColesModel.fit(history, as_of=AS_OF)


@pytest.fixture(scope="module")
def reference(history):
    model = pb.models.DixonColesGoalModel(
        [r.home_goals for r in history],
        [r.away_goals for r in history],
        [r.home for r in history],
        [r.away for r in history],
        weights=pb.models.dixon_coles_weights([r.played_on for r in history], 0.0018, base_date=AS_OF),
    )
    model.fit()
    return model


@pytest.mark.parametrize(
    ("home", "away"),
    [("arsenal", "sunderland"), ("sunderland", "arsenal"), ("chelsea", "everton"), ("hull-city", "leeds-united")],
)
def test_probabilities_match_penaltyblog(ours, reference, home, away):
    mine = ours.predict(home, away)
    grid = reference.predict(home, away)
    assert mine.probs == pytest.approx(tuple(grid.home_draw_away), abs=2e-3)
    assert mine.over_2_5 == pytest.approx(grid.totals(2.5)[2], abs=2e-3)
    assert mine.btts == pytest.approx(grid.btts_yes, abs=2e-3)
