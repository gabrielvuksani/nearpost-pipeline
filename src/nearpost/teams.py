"""Canonical club identities across FPL, football-data.co.uk and The Odds API.

Salvaged from the old project's team_mapping.py (England section), minus its fuzzy
matcher: a name we don't know must fail loudly, because a silent near-match would
attach a forecast to the wrong club.
"""

from __future__ import annotations

import re
import unicodedata

# canonical slug -> every spelling seen in a source we join on
_ALIASES: dict[str, tuple[str, ...]] = {
    "arsenal": ("Arsenal", "Arsenal FC"),
    "aston-villa": ("Aston Villa", "Aston Villa FC"),
    "birmingham-city": ("Birmingham", "Birmingham City"),
    "blackburn-rovers": ("Blackburn", "Blackburn Rovers"),
    "bournemouth": ("Bournemouth", "AFC Bournemouth"),
    "brentford": ("Brentford", "Brentford FC"),
    "brighton": ("Brighton", "Brighton & Hove Albion", "Brighton and Hove Albion", "Brighton & HA"),
    "burnley": ("Burnley", "Burnley FC"),
    "cardiff-city": ("Cardiff", "Cardiff City"),
    "chelsea": ("Chelsea", "Chelsea FC"),
    "coventry-city": ("Coventry", "Coventry City"),
    "crystal-palace": ("Crystal Palace", "Crystal Palace FC"),
    "everton": ("Everton", "Everton FC"),
    "fulham": ("Fulham", "Fulham FC"),
    "hull-city": ("Hull", "Hull City"),
    "ipswich-town": ("Ipswich", "Ipswich Town"),
    "leeds-united": ("Leeds", "Leeds United"),
    "leicester-city": ("Leicester", "Leicester City"),
    "liverpool": ("Liverpool", "Liverpool FC"),
    "luton-town": ("Luton", "Luton Town"),
    "manchester-city": ("Man City", "Manchester City"),
    "manchester-united": ("Man United", "Man Utd", "Manchester United"),
    "middlesbrough": ("Middlesbrough",),
    "newcastle-united": ("Newcastle", "Newcastle United"),
    "norwich-city": ("Norwich", "Norwich City"),
    "nottingham-forest": ("Nott'm Forest", "Nottingham Forest"),
    "sheffield-united": ("Sheffield United", "Sheff Utd"),
    "southampton": ("Southampton",),
    "stoke-city": ("Stoke", "Stoke City"),
    "sunderland": ("Sunderland", "Sunderland AFC"),
    "swansea-city": ("Swansea", "Swansea City"),
    "tottenham-hotspur": ("Tottenham", "Tottenham Hotspur", "Spurs"),
    "watford": ("Watford",),
    "west-bromwich-albion": ("West Brom", "West Bromwich Albion"),
    "west-ham-united": ("West Ham", "West Ham United"),
    "wolverhampton-wanderers": ("Wolves", "Wolverhampton Wanderers"),
}


class UnknownTeamError(LookupError):
    pass


def _normalise(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    lowered = ascii_name.lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9 ]", "", lowered).split())


_BY_NORMALISED: dict[str, str] = {_normalise(alias): slug for slug, aliases in _ALIASES.items() for alias in aliases}


def slugify(name: str) -> str:
    return _normalise(name).replace(" ", "-")


def resolve_team(name: str) -> str:
    """Canonical slug for a club name from any joined source. Raises on unknown names."""
    try:
        return _BY_NORMALISED[_normalise(name)]
    except KeyError:
        raise UnknownTeamError(f"no canonical club for {name!r}; add it to teams._ALIASES") from None


def team_id(name: str) -> str:
    """Canonical slug where known, otherwise a stable slug.

    Only for historical training rows, where lower-league clubs we never join on appear.
    """
    try:
        return resolve_team(name)
    except UnknownTeamError:
        return slugify(name)
