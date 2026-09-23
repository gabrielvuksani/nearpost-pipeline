import pytest

from nearpost.settings import ConfigError, Settings

PRODUCTION = {
    "NEARPOST_ENV": "production",
    "ODDS_API_KEY": "k",
    "HEALTHCHECKS_PING_KEY": "p",
    "R2_ACCOUNT_ID": "a",
    "R2_ACCESS_KEY_ID": "i",
    "R2_SECRET_ACCESS_KEY": "s",
    "R2_BUCKET": "nearpost-recorder",
}


def test_local_defaults_need_no_secrets():
    settings = Settings.from_env({})
    assert settings.odds_api_key is None
    assert not settings.uses_r2
    assert settings.odds_regions == ("eu",)
    assert settings.odds_markets == ("h2h", "totals")


def test_production_fails_fast_naming_every_missing_secret_but_not_its_value():
    env = {**PRODUCTION, "ODDS_API_KEY": "", "R2_BUCKET": "  "}
    with pytest.raises(ConfigError) as error:
        Settings.from_env(env)
    assert "ODDS_API_KEY" in str(error.value)
    assert "R2_BUCKET" in str(error.value)


def test_production_with_everything_uses_r2_and_links_the_run():
    env = {**PRODUCTION, "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "42"}
    settings = Settings.from_env(env)
    assert settings.uses_r2
    assert settings.run_url == "https://github.com/o/r/actions/runs/42"
