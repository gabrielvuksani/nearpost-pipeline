import pytest

from nearpost.devig import shin
from nearpost.domain import BookQuote, MarketQuote
from nearpost.market import from_football_data, from_odds_api


def _book(key, h2h=None, ou=None):
    return BookQuote(key=key, last_update=None, h2h=h2h, over_under_2_5=ou)


def test_odds_api_consensus_averages_shin_probabilities_across_books():
    books = (_book("a", (2.0, 3.4, 3.8)), _book("b", (2.1, 3.3, 3.6)))
    forecast = from_odds_api(books)
    expected = [(x + y) / 2 for x, y in zip(shin((2.0, 3.4, 3.8)), shin((2.1, 3.3, 3.6)), strict=True)]
    assert forecast.probs == pytest.approx(tuple(expected))
    assert sum(forecast.probs) == pytest.approx(1.0)
    assert forecast.n_books == 2


def test_books_without_a_market_are_skipped_for_that_market():
    books = (_book("a", (2.0, 3.4, 3.8)), _book("b", None, (1.9, 1.9)))
    forecast = from_odds_api(books)
    assert forecast.n_books == 1
    assert forecast.over_2_5 == pytest.approx(0.5)


def test_no_prices_means_no_market_forecast():
    assert from_odds_api((_book("a"),)) is None


def test_football_data_quote_uses_the_average_line():
    quote = MarketQuote(avg_1x2=(1.5, 4.2, 6.0), exchange_1x2=None, avg_over_under_2_5=(1.8, 2.0))
    forecast = from_football_data(quote)
    assert forecast.probs == pytest.approx(shin((1.5, 4.2, 6.0)))
    assert forecast.over_2_5 == pytest.approx((1 / 1.8) / (1 / 1.8 + 1 / 2.0))


def test_football_data_quote_without_average_prices_is_unavailable():
    assert from_football_data(MarketQuote(None, (1.5, 4.2, 6.0), None)) is None
