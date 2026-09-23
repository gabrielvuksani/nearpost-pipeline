"""The market's view as probabilities: de-vigged, averaged, never shown as prices."""

from __future__ import annotations

from collections.abc import Sequence
from statistics import fmean

from nearpost.devig import proportional, shin
from nearpost.domain import BookQuote, MarketQuote
from nearpost.forecast import Forecast

ODDS_API_MODEL_ID = "market-oddsapi-v1"  # consensus of books via The Odds API, Shin per book
FOOTBALL_DATA_MODEL_ID = "market-fdco-v1"  # football-data.co.uk fixtures.csv average line, Shin


def _mean_probs(rows: Sequence[tuple[float, ...]]) -> tuple[float, float, float]:
    means = [fmean(column) for column in zip(*rows, strict=True)]
    total = sum(means)
    return (means[0] / total, means[1] / total, means[2] / total)


def from_odds_api(books: Sequence[BookQuote]) -> Forecast | None:
    """Consensus of every book that priced the match: Shin per book, then the mean."""
    h2h = [shin(b.h2h) for b in books if b.h2h]
    if not h2h:
        return None
    overs = [proportional(b.over_under_2_5)[0] for b in books if b.over_under_2_5]
    return Forecast(probs=_mean_probs(h2h), over_2_5=fmean(overs) if overs else None, n_books=len(h2h))


def from_football_data(quote: MarketQuote) -> Forecast | None:
    """football-data.co.uk's average-of-books line (already a consensus price)."""
    if quote.avg_1x2 is None:
        return None
    probs = shin(quote.avg_1x2)
    over = proportional(quote.avg_over_under_2_5)[0] if quote.avg_over_under_2_5 else None
    return Forecast(probs=(probs[0], probs[1], probs[2]), over_2_5=over)
