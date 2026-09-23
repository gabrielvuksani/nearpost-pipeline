from datetime import UTC, datetime

import pytest

from nearpost.sources.errors import SchemaError
from nearpost.sources.odds_api import OddsApiRequest, credit_state, parse_odds
from tests.factories import odds_event, odds_payload


def test_request_costs_one_credit_per_region_per_market():
    request = OddsApiRequest(regions=("uk", "eu"), markets=("h2h", "totals"))
    assert request.credit_cost == 4


def test_request_url_never_contains_the_key_but_params_do():
    request = OddsApiRequest(regions=("eu",), markets=("h2h", "totals"))
    assert request.url == "https://api.the-odds-api.com/v4/sports/soccer_epl/odds"
    params = request.params(api_key="SECRET")
    assert params["apiKey"] == "SECRET"
    assert params["regions"] == "eu"
    assert params["markets"] == "h2h,totals"
    assert params["oddsFormat"] == "decimal"
    assert "SECRET" not in request.redacted_url


def test_parse_odds_orders_h2h_prices_home_draw_away_by_team_name():
    event = odds_event("Chelsea", "Everton", "2026-10-03T14:00:00Z", [("pinnacle", (1.9, 3.6, 4.4), (1.85, 2.05))])
    # Real payloads don't promise outcome order, so shuffle it.
    event["bookmakers"][0]["markets"][0]["outcomes"].reverse()
    [parsed] = parse_odds(odds_payload(event))

    assert (parsed.home, parsed.away) == ("chelsea", "everton")
    assert parsed.commence == datetime(2026, 10, 3, 14, 0, tzinfo=UTC)
    book = parsed.books[0]
    assert book.key == "pinnacle"
    assert book.h2h == (1.9, 3.6, 4.4)
    assert book.over_under_2_5 == (1.85, 2.05)


def test_totals_at_other_lines_are_ignored():
    event = odds_event("Chelsea", "Everton", "2026-10-03T14:00:00Z", [("bk", None, (1.5, 2.6))])
    for outcome in event["bookmakers"][0]["markets"][0]["outcomes"]:
        outcome["point"] = 3.5
    [parsed] = parse_odds(odds_payload(event))
    assert parsed.books[0].over_under_2_5 is None
    assert parsed.books[0].h2h is None


def test_non_list_payload_is_a_schema_error():
    with pytest.raises(SchemaError):
        parse_odds(b'{"message": "Invalid api key"}')


def test_credit_state_reads_usage_headers():
    state = credit_state({"x-requests-remaining": "431", "x-requests-used": "69"})
    assert state == {"credits_remaining": 431, "credits_used": 69}
    assert credit_state({}) is None


@pytest.mark.parametrize("price", [1.0, 0.5, "x", None, float("inf")])
def test_an_invalid_price_drops_that_market_for_that_book_instead_of_crashing(price):
    event = odds_event("Chelsea", "Everton", "2026-10-03T14:00:00Z", [("bad", (1.9, 3.6, 4.4), None)])
    event["bookmakers"][0]["markets"][0]["outcomes"][0]["price"] = price
    [parsed] = parse_odds(odds_payload(event))
    assert parsed.books[0].h2h is None


def test_structurally_broken_events_are_schema_errors():
    event = odds_event("Chelsea", "Everton", "2026-10-03T14:00:00Z", [("bk", (1.9, 3.6, 4.4), None)])
    event["bookmakers"][0]["markets"] = "nonsense"
    with pytest.raises(SchemaError):
        parse_odds(odds_payload(event))


def test_unknown_team_names_are_schema_errors():
    event = odds_event("Chelsea", "Everton FC Legends", "2026-10-03T14:00:00Z", [])
    with pytest.raises(SchemaError, match="Everton FC Legends"):
        parse_odds(odds_payload(event))


@pytest.mark.parametrize("remaining", ["nan", "inf", "lots"])
def test_unreadable_credit_headers_are_treated_as_unknown(remaining):
    assert credit_state({"x-requests-remaining": remaining, "x-requests-used": "1"}) is None
