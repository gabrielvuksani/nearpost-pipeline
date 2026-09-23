"""When forecasts are recorded, and by which models.

Each horizon owns a window running from its offset before kickoff up to the next
horizon's offset (the last one closes at kickoff). A forecast recorded in its window
carries that horizon's label; one never recorded is a visible miss.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from nearpost.market import FOOTBALL_DATA_MODEL_ID, ODDS_API_MODEL_ID
from nearpost.models.dixon_coles import MODEL_ID as DIXON_COLES
from nearpost.models.elo import MODEL_ID as ELO

INDEPENDENT_MODELS = (ELO, DIXON_COLES)


@dataclass(frozen=True)
class Horizon:
    name: str
    offset: timedelta
    models: tuple[str, ...]


HORIZONS: tuple[Horizon, ...] = (
    # fixtures.csv only lists the coming round, so its line starts at T-24h.
    Horizon("T-7d", timedelta(days=7), (*INDEPENDENT_MODELS, ODDS_API_MODEL_ID)),
    Horizon("T-24h", timedelta(hours=24), (*INDEPENDENT_MODELS, ODDS_API_MODEL_ID, FOOTBALL_DATA_MODEL_ID)),
    Horizon("T-1h", timedelta(hours=1), (*INDEPENDENT_MODELS, ODDS_API_MODEL_ID, FOOTBALL_DATA_MODEL_ID)),
    # Our own closing line: the market as near kickoff as a runner can reliably reach.
    Horizon("T-15m", timedelta(minutes=15), (ODDS_API_MODEL_ID,)),
)


def horizon_named(name: str) -> Horizon:
    for horizon in HORIZONS:
        if horizon.name == name:
            return horizon
    raise KeyError(f"unknown horizon {name!r}")


def window(horizon: Horizon, kickoff: datetime) -> tuple[datetime, datetime]:
    """[start, end) during which this horizon's forecast may be recorded."""
    position = HORIZONS.index(horizon)
    end_offset = HORIZONS[position + 1].offset if position + 1 < len(HORIZONS) else timedelta(0)
    return kickoff - horizon.offset, kickoff - end_offset
