"""The Odds API free tier (500 credits/month). Its terms allow in-app display of the data.

One `/odds` call returns every upcoming Premier League match and costs one credit per
region per market.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from nearpost.domain import BookQuote, OddsEvent
from nearpost.sources.errors import SchemaError
from nearpost.sources.prices import decimal_price
from nearpost.teams import UnknownTeamError, resolve_team
from nearpost.timeutil import parse_utc

API_BASE = "https://api.the-odds-api.com/v4"


@dataclass(frozen=True)
class OddsApiRequest:
    regions: tuple[str, ...] = ("eu",)
    markets: tuple[str, ...] = ("h2h", "totals")
    sport: str = "soccer_epl"

    @property
    def credit_cost(self) -> int:
        return len(self.regions) * len(self.markets)

    @property
    def url(self) -> str:
        return f"{API_BASE}/sports/{self.sport}/odds"

    def _public_params(self) -> dict[str, str]:
        return {
            "regions": ",".join(self.regions),
            "markets": ",".join(self.markets),
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }

    def params(self, *, api_key: str) -> dict[str, str]:
        return {"apiKey": api_key, **self._public_params()}

    @property
    def redacted_url(self) -> str:
        """What we archive with the snapshot: the request minus the key."""
        return f"{self.url}?{urlencode(self._public_params())}"


def credit_state(headers: Mapping[str, str]) -> dict[str, int] | None:
    """Credits from the usage headers, or None when they are absent or unreadable."""
    try:
        remaining, used = float(headers["x-requests-remaining"]), float(headers["x-requests-used"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(remaining) and math.isfinite(used)):
        return None
    return {"credits_remaining": int(remaining), "credits_used": int(used)}


def parse_odds(payload: bytes) -> list[OddsEvent]:
    try:
        events = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SchemaError(f"The Odds API returned invalid JSON: {error}") from error
    if not isinstance(events, list):
        raise SchemaError(f"The Odds API returned {type(events).__name__}, expected a list: {str(events)[:200]}")
    return [_event(e) for e in events]


def _event(raw: Mapping[str, Any]) -> OddsEvent:
    try:
        home_name, away_name = raw["home_team"], raw["away_team"]
        return OddsEvent(
            home=resolve_team(home_name),
            away=resolve_team(away_name),
            commence=parse_utc(raw["commence_time"]),
            books=tuple(_book(b, home_name, away_name) for b in raw["bookmakers"]),
        )
    except UnknownTeamError as error:
        raise SchemaError(str(error)) from error
    except (LookupError, TypeError, ValueError, AttributeError) as error:
        raise SchemaError(f"The Odds API event has an unexpected shape: {type(error).__name__}: {error}") from error


def _book(raw: Mapping[str, Any], home_name: str, away_name: str) -> BookQuote:
    markets = {m["key"]: m["outcomes"] for m in raw["markets"]}
    return BookQuote(
        key=raw["key"],
        last_update=raw.get("last_update"),
        h2h=_h2h(markets.get("h2h"), home_name, away_name),
        over_under_2_5=_totals(markets.get("totals")),
    )


def _h2h(outcomes: list[Mapping[str, Any]] | None, home_name: str, away_name: str):
    """(home, draw, away), or None if the book doesn't offer all three at valid prices."""
    if not outcomes:
        return None
    prices = {o["name"]: decimal_price(o.get("price")) for o in outcomes}
    trio = (prices.get(home_name), prices.get("Draw"), prices.get(away_name))
    return trio if all(p is not None for p in trio) else None


def _totals(outcomes: list[Mapping[str, Any]] | None):
    if not outcomes:
        return None
    at_line = {o["name"]: decimal_price(o.get("price")) for o in outcomes if o.get("point") == 2.5}
    pair = (at_line.get("Over"), at_line.get("Under"))
    return pair if all(p is not None for p in pair) else None
