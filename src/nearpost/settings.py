"""Runtime configuration, read once from the environment and validated up front."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class ConfigError(ValueError):
    pass


PRODUCTION_REQUIRED = (
    "ODDS_API_KEY",
    "HEALTHCHECKS_PING_KEY",
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
)


@dataclass(frozen=True)
class Settings:
    odds_api_key: str | None = None
    odds_regions: tuple[str, ...] = ("eu",)
    odds_markets: tuple[str, ...] = ("h2h", "totals")
    odds_credit_reserve: int = 30
    training_seasons: int = 5
    healthchecks_ping_key: str | None = None
    healthchecks_base_url: str = "https://hc-ping.com"
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket: str | None = None
    local_store: str = ".nearpost-data"
    run_url: str | None = None

    @property
    def secrets(self) -> tuple[str | None, ...]:
        return (self.odds_api_key, self.healthchecks_ping_key, self.r2_access_key_id, self.r2_secret_access_key)

    @property
    def uses_r2(self) -> bool:
        return self.r2_bucket is not None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        """In production (NEARPOST_ENV=production) every secret must be present: a missing one
        fails the run at start-up instead of silently disabling a source."""

        def value(name: str) -> str | None:
            text = env.get(name, "").strip()
            return text or None

        if value("NEARPOST_ENV") == "production":
            missing = [name for name in PRODUCTION_REQUIRED if value(name) is None]
            if missing:
                raise ConfigError(f"missing required environment variables: {', '.join(missing)}")

        run_url = None
        if value("GITHUB_RUN_ID"):
            run_url = f"{value('GITHUB_SERVER_URL')}/{value('GITHUB_REPOSITORY')}/actions/runs/{value('GITHUB_RUN_ID')}"

        return cls(
            odds_api_key=value("ODDS_API_KEY"),
            odds_regions=tuple((value("ODDS_API_REGIONS") or "eu").split(",")),
            odds_markets=tuple((value("ODDS_API_MARKETS") or "h2h,totals").split(",")),
            odds_credit_reserve=int(value("ODDS_API_CREDIT_RESERVE") or 30),
            training_seasons=int(value("NEARPOST_TRAINING_SEASONS") or 5),
            healthchecks_ping_key=value("HEALTHCHECKS_PING_KEY"),
            r2_account_id=value("R2_ACCOUNT_ID"),
            r2_access_key_id=value("R2_ACCESS_KEY_ID"),
            r2_secret_access_key=value("R2_SECRET_ACCESS_KEY"),
            r2_bucket=value("R2_BUCKET"),
            local_store=value("NEARPOST_LOCAL_STORE") or ".nearpost-data",
            run_url=run_url,
        )
