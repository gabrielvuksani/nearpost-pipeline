"""healthchecks.io dead-man switch. Each mode reports to its own check, auto-created by slug.

A ping that fails is logged, never raised: the missing ping is itself what makes
healthchecks.io raise the alarm.
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)
MAX_BODY = 100_000  # healthchecks.io keeps the first 100 kB of a ping body


class Healthchecks:
    def __init__(
        self, client: httpx.Client, ping_key: str | None, slug: str, base_url: str = "https://hc-ping.com"
    ) -> None:
        self._client = client
        self._key = ping_key
        self._slug = slug
        self._base = base_url.rstrip("/")

    def _ping(self, suffix: str, body: str = "") -> None:
        if not self._key:
            log.warning("healthchecks disabled (no HEALTHCHECKS_PING_KEY); would have sent %s%s", self._slug, suffix)
            return
        url = f"{self._base}/{self._key}/{self._slug}{suffix}"
        try:
            response = self._client.post(url, params={"create": "1"}, content=body.encode()[:MAX_BODY], timeout=10)
            if response.status_code >= 300:
                log.error("healthchecks ping failed: %s%s answered HTTP %s", self._slug, suffix, response.status_code)
        except httpx.HTTPError as error:
            log.error("healthchecks ping failed: %s%s: %s", self._slug, suffix, type(error).__name__)

    def start(self) -> None:
        self._ping("/start")

    def success(self, body: str) -> None:
        self._ping("", body)

    def fail(self, body: str) -> None:
        self._ping("/fail", body)
