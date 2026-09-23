"""Assemble this run's forecasters from fitted models and captured market lines."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from nearpost.domain import Fixture, MarketQuote, MatchResult, OddsEvent
from nearpost.forecast import Forecast
from nearpost.market import FOOTBALL_DATA_MODEL_ID, ODDS_API_MODEL_ID, from_football_data, from_odds_api
from nearpost.models import dixon_coles, elo
from nearpost.models.errors import ModelInputError
from nearpost.records.forecasts import ModelSource, Skipped, Unavailable
from nearpost.tasks import Task

SAME_MEETING = timedelta(days=3)  # an event this close to the FPL kickoff is the same match
NEAR_KICKOFF_HORIZONS = frozenset({"T-1h", "T-15m"})

Ref = Mapping[str, str]


MODEL_FAILURES = (ModelInputError, ValueError)  # ValueError: numerical failures inside scipy or numpy


def _guarded(predict):
    def run(fixture: Fixture) -> Forecast | Skipped:
        try:
            return predict(fixture)
        except MODEL_FAILURES as error:
            return Skipped(str(error))

    return run


def independent_sources(
    history: Sequence[MatchResult], *, as_of: datetime, inputs: tuple[Ref, ...]
) -> tuple[dict[str, ModelSource], list[str]]:
    """Elo and Dixon-Coles fitted on results strictly before `as_of`. No odds, ever.

    Each model is built on its own, so one failing never takes the other down.
    """
    sources: dict[str, ModelSource] = {}
    problems: list[str] = []

    params = elo.EloParams()
    try:
        ratings = elo.fit_elo(history, params)
        sources[elo.MODEL_ID] = ModelSource(
            elo.MODEL_ID,
            _guarded(lambda f: elo.predict_elo(ratings, f.home, f.away, params)),
            inputs,
            {"params": params.as_dict(), "n_matches": len(history)},
        )
    except MODEL_FAILURES as error:
        problems.append(f"{elo.MODEL_ID} unavailable: {error}")

    try:
        fitted = dixon_coles.DixonColesModel.fit(history, as_of=as_of.date())
        sources[dixon_coles.MODEL_ID] = ModelSource(
            dixon_coles.MODEL_ID,
            _guarded(lambda f: fitted.predict(f.home, f.away)),
            inputs,
            {"xi": fitted.xi, "n_matches": fitted.n_matches},
        )
    except MODEL_FAILURES as error:
        problems.append(f"{dixon_coles.MODEL_ID} unavailable: {error}")

    return sources, problems


def odds_api_market(events: Sequence[OddsEvent], *, ref: Ref) -> ModelSource:
    def predict(fixture: Fixture) -> Forecast | Unavailable:
        assert fixture.kickoff is not None
        for event in events:
            if (event.home, event.away) == (fixture.home, fixture.away) and abs(
                event.commence - fixture.kickoff
            ) <= SAME_MEETING:
                forecast = from_odds_api(event.books)
                return forecast or Unavailable("The Odds API listed the match without 1X2 prices")
        return Unavailable("The Odds API did not list this match")

    return ModelSource(ODDS_API_MODEL_ID, predict, (ref,), {"devig": "shin", "consensus": "mean of books"})


def football_data_market(
    upcoming: Mapping[tuple[str, str], MarketQuote], *, ref: Ref, observed_at: str | None
) -> ModelSource:
    def predict(fixture: Fixture) -> Forecast | Unavailable:
        quote = upcoming.get((fixture.home, fixture.away))
        forecast = from_football_data(quote) if quote else None
        return forecast or Unavailable("football-data.co.uk fixtures.csv has no average price for this match")

    return ModelSource(FOOTBALL_DATA_MODEL_ID, predict, (ref,), {"prices_observed_at": observed_at})


def odds_budget_block(tasks: Sequence[Task], *, credits_remaining: int | None, reserve: int) -> str | None:
    """Why this run should not spend an Odds API credit, or None if it should."""
    wanting = [t for t in tasks if t.kind == "capture" and ODDS_API_MODEL_ID in t.models]
    if not wanting:
        return "no due capture needs The Odds API"
    if credits_remaining is None or credits_remaining >= reserve:
        return None
    if any(t.horizon in NEAR_KICKOFF_HORIZONS for t in wanting):
        return None
    return f"only {credits_remaining} credits left; the last {reserve} are kept for T-1h and T-15m captures"
