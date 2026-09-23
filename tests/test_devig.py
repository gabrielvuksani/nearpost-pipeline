import penaltyblog as pb
import pytest

from nearpost.devig import proportional, shin


def test_shin_probabilities_sum_to_one():
    probs = shin((2.10, 3.40, 3.60))
    assert sum(probs) == pytest.approx(1.0, abs=1e-9)


def test_shin_matches_penaltyblog_reference_implementation():
    odds = [1.62, 4.10, 5.75]
    reference = pb.implied.calculate_implied(odds, method="shin").probabilities
    assert shin(tuple(odds)) == pytest.approx(tuple(reference), abs=1e-6)


def test_shin_shrinks_longshots_more_than_proportional():
    odds = (1.30, 5.50, 11.0)
    assert shin(odds)[2] < proportional(odds)[2]


def test_shin_on_a_fair_book_is_the_identity():
    odds = (2.0, 4.0, 4.0)
    assert shin(odds) == pytest.approx((0.5, 0.25, 0.25))


def test_proportional_handles_two_way_markets():
    over, under = proportional((1.90, 1.90))
    assert over == pytest.approx(0.5)
    assert under == pytest.approx(0.5)


@pytest.mark.parametrize("bad", [(1.0, 3.0, 3.0), (0.0, 2.0, 2.0), (float("nan"), 2.0, 2.0)])
def test_invalid_decimal_odds_are_rejected(bad):
    with pytest.raises(ValueError, match="decimal odds"):
        shin(bad)


def test_shin_needs_three_or_more_outcomes():
    with pytest.raises(ValueError, match="at least three"):
        shin((1.9, 1.9))
