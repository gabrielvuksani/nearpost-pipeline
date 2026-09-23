from datetime import UTC, date, datetime, timedelta

import pytest

from nearpost.domain import BookQuote, Fixture, MarketQuote, OddsEvent
from nearpost.forecast import Forecast
from nearpost.jobs.modelling import (
    football_data_market,
    independent_sources,
    odds_api_market,
    odds_budget_block,
)
from nearpost.models.errors import ModelInputError
from nearpost.records.forecasts import Skipped, Unavailable
from nearpost.sources.football_data import parse_results
from nearpost.tasks import Task
from tests.factories import PL_TEAMS_FD, fd_season_csv, synthetic_season_rows

KICKOFF = datetime(2026, 10, 10, 11, 30, tzinfo=UTC)
FIXTURE = Fixture("2026-27:arsenal-v-chelsea", "2026-27", 51, 6, KICKOFF, "arsenal", "chelsea", False, None, None)
REF = {"key": "k", "sha256": "s"}


@pytest.fixture(scope="module")
def history():
    return parse_results(fd_season_csv(*synthetic_season_rows(PL_TEAMS_FD, date(2025, 8, 16))))


def test_independent_sources_forecast_known_clubs(history):
    sources, _ = independent_sources(history, as_of=KICKOFF - timedelta(days=1), inputs=(REF,))
    assert set(sources) == {"elo-v1", "dixon-coles-v1"}
    elo = sources["elo-v1"].predict(FIXTURE)
    dc = sources["dixon-coles-v1"].predict(FIXTURE)
    assert isinstance(elo, Forecast) and isinstance(dc, Forecast)
    assert dc.over_2_5 is not None
    assert sources["dixon-coles-v1"].meta["n_matches"] == len(history)
    assert sources["elo-v1"].inputs == (REF,)


def test_a_club_without_history_is_skipped_not_guessed(history):
    sources, _ = independent_sources(history, as_of=KICKOFF, inputs=())
    stranger = Fixture("x", "2026-27", 1, 6, KICKOFF, "arsenal", "wrexham", False, None, None)
    outcome = sources["elo-v1"].predict(stranger)
    assert isinstance(outcome, Skipped)
    assert "wrexham" in outcome.reason


def _event(commence=KICKOFF, h2h=(1.8, 3.8, 4.5)):
    return OddsEvent("arsenal", "chelsea", commence, (BookQuote("bk", None, h2h, (1.9, 1.95)),))


def test_odds_api_market_matches_the_event_for_the_fixture():
    outcome = odds_api_market([_event()], ref=REF).predict(FIXTURE)
    assert isinstance(outcome, Forecast)
    assert outcome.n_books == 1


def test_odds_api_market_without_the_event_is_unavailable():
    outcome = odds_api_market([], ref=REF).predict(FIXTURE)
    assert isinstance(outcome, Unavailable)


def test_an_event_days_away_from_the_kickoff_is_a_different_meeting():
    outcome = odds_api_market([_event(commence=KICKOFF + timedelta(days=4))], ref=REF).predict(FIXTURE)
    assert isinstance(outcome, Unavailable)


def test_odds_api_market_with_no_prices_is_unavailable():
    event = OddsEvent("arsenal", "chelsea", KICKOFF, (BookQuote("bk", None, None, None),))
    assert isinstance(odds_api_market([event], ref=REF).predict(FIXTURE), Unavailable)


def test_football_data_market_notes_when_its_prices_were_observed():
    quote = MarketQuote((1.8, 3.8, 4.5), None, (1.9, 1.95))
    source = football_data_market({("arsenal", "chelsea"): quote}, ref=REF, observed_at="Fri, 09 Oct 2026 13:00:00 GMT")
    assert isinstance(source.predict(FIXTURE), Forecast)
    assert source.meta == {"prices_observed_at": "Fri, 09 Oct 2026 13:00:00 GMT"}
    assert isinstance(football_data_market({}, ref=REF, observed_at=None).predict(FIXTURE), Unavailable)


def _capture(horizon):
    return Task("capture", KICKOFF, KICKOFF, FIXTURE.match_id, horizon, KICKOFF, 6, ("market-oddsapi-v1",))


def test_odds_budget_allows_calls_when_credits_are_healthy_or_unknown():
    assert odds_budget_block([_capture("T-7d")], credits_remaining=None, reserve=30) is None
    assert odds_budget_block([_capture("T-7d")], credits_remaining=200, reserve=30) is None


def test_odds_budget_protects_the_reserve_for_near_kickoff_captures():
    assert odds_budget_block([_capture("T-7d")], credits_remaining=10, reserve=30) is not None
    assert odds_budget_block([_capture("T-7d"), _capture("T-15m")], credits_remaining=10, reserve=30) is None


def test_no_call_is_needed_when_no_due_capture_wants_the_odds_api():
    task = Task("capture", KICKOFF, KICKOFF, FIXTURE.match_id, "T-24h", KICKOFF, 6, ("elo-v1",))
    assert odds_budget_block([task], credits_remaining=500, reserve=30) == "no due capture needs The Odds API"


def test_elo_survives_when_dixon_coles_cannot_fit(history, monkeypatch):
    from nearpost.models import dixon_coles

    def broken_fit(*args, **kwargs):
        raise ModelInputError("dixon-coles failed to converge")

    monkeypatch.setattr(dixon_coles.DixonColesModel, "fit", broken_fit)
    sources, problems = independent_sources(history, as_of=KICKOFF - timedelta(days=1), inputs=())
    assert set(sources) == {"elo-v1"}
    assert problems == ["dixon-coles-v1 unavailable: dixon-coles failed to converge"]
