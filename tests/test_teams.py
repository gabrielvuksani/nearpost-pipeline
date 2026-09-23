import pytest

from nearpost.teams import UnknownTeamError, resolve_team, slugify

# Every name each source uses for the 2026/27 Premier League clubs.
FPL_2026_27 = [
    "Arsenal",
    "Aston Villa",
    "Bournemouth",
    "Brentford",
    "Brighton",
    "Chelsea",
    "Coventry City",
    "Crystal Palace",
    "Everton",
    "Fulham",
    "Hull City",
    "Ipswich Town",
    "Leeds",
    "Liverpool",
    "Man City",
    "Man Utd",
    "Newcastle",
    "Nott'm Forest",
    "Spurs",
    "Sunderland",
]
FOOTBALL_DATA_2026_27 = [
    "Arsenal",
    "Aston Villa",
    "Bournemouth",
    "Brentford",
    "Brighton",
    "Chelsea",
    "Coventry",
    "Crystal Palace",
    "Everton",
    "Fulham",
    "Hull",
    "Ipswich",
    "Leeds",
    "Liverpool",
    "Man City",
    "Man United",
    "Newcastle",
    "Nott'm Forest",
    "Tottenham",
    "Sunderland",
]
ODDS_API_2026_27 = [
    "Arsenal",
    "Aston Villa",
    "Bournemouth",
    "Brentford",
    "Brighton and Hove Albion",
    "Chelsea",
    "Coventry City",
    "Crystal Palace",
    "Everton",
    "Fulham",
    "Hull City",
    "Ipswich Town",
    "Leeds United",
    "Liverpool",
    "Manchester City",
    "Manchester United",
    "Newcastle United",
    "Nottingham Forest",
    "Tottenham Hotspur",
    "Sunderland",
]


def test_all_three_sources_resolve_to_the_same_twenty_clubs():
    fpl = [resolve_team(n) for n in FPL_2026_27]
    fd = [resolve_team(n) for n in FOOTBALL_DATA_2026_27]
    odds = [resolve_team(n) for n in ODDS_API_2026_27]
    assert fpl == fd == odds
    assert len(set(fpl)) == 20


def test_resolution_ignores_case_accents_and_punctuation():
    assert resolve_team("  MAN utd ") == "manchester-united"
    assert resolve_team("Nottm Forest") == "nottingham-forest"
    assert resolve_team("Brighton & Hove Albion") == "brighton"


def test_unknown_names_fail_loudly_instead_of_fuzzy_matching():
    with pytest.raises(UnknownTeamError, match="Manchester Rovers"):
        resolve_team("Manchester Rovers")


def test_slugify_is_stable_for_history_only_clubs():
    assert slugify("Sheffield Weds") == "sheffield-weds"
    assert slugify("Nott'm Forest") == "nottm-forest"
