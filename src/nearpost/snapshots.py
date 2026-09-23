"""Fetch a source exactly once per use and keep the bytes we used, with when and where.

Every forecast references the snapshots it was built from by key and sha256, so any
ledger entry can be re-derived from archived inputs.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from nearpost.sources.errors import SourceError
from nearpost.store.base import BlobStore, PreconditionFailedError
from nearpost.timeutil import format_utc

USER_AGENT = "nearpost-recorder/0.1 (+https://github.com/gabrielvuksani/nearpost-pipeline)"
KEPT_HEADERS = (
    "content-type",
    "last-modified",
    "etag",
    "date",
    "x-requests-remaining",
    "x-requests-used",
    "x-requests-last",
)
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_RESPONSE_BYTES = 64 * 1024 * 1024  # FPL bootstrap-static is ~2 MB; anything near this is wrong


@dataclass(frozen=True)
class Snapshot:
    source: str
    url: str  # public form: never carries credentials
    fetched_at: datetime
    status: int
    headers: Mapping[str, str]
    body: bytes
    sha256: str


class ResponseTooLargeError(Exception):
    pass


class Fetcher:
    def __init__(
        self,
        client: httpx.Client,
        *,
        attempts: int = 3,
        max_bytes: int = MAX_RESPONSE_BYTES,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._attempts = attempts
        self._max_bytes = max_bytes
        self._clock = clock
        self._sleep = sleep

    def _read(self, url: str, params: Mapping[str, str] | None) -> tuple[int, dict[str, str], bytes]:
        with self._client.stream("GET", url, params=params, headers={"User-Agent": USER_AGENT}) as response:
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > self._max_bytes:
                    raise ResponseTooLargeError(f"response larger than {self._max_bytes} bytes")
                chunks.append(chunk)
            return response.status_code, dict(response.headers), b"".join(chunks)

    def get(
        self, source: str, url: str, *, params: Mapping[str, str] | None = None, public_url: str | None = None
    ) -> Snapshot:
        shown = public_url or url
        failure = ""
        for attempt in range(1, self._attempts + 1):
            try:
                status, headers, body = self._read(url, params)
            except ResponseTooLargeError as error:
                failure = str(error)
                break
            except httpx.HTTPError as error:
                # The exception text can embed the full request URL, credentials included.
                failure = type(error).__name__
            else:
                if status == 200:
                    return Snapshot(
                        source=source,
                        url=shown,
                        fetched_at=self._clock(),
                        status=200,
                        headers={k: headers[k] for k in KEPT_HEADERS if k in headers},
                        body=body,
                        sha256=hashlib.sha256(body).hexdigest(),
                    )
                failure = f"HTTP {status}: {body.decode('utf-8', 'replace')}"
                if status not in RETRYABLE_STATUS:
                    break
            if attempt < self._attempts:
                self._sleep(2.0**attempt)
        # Redact before truncating, so a secret straddling the cut can't leave a prefix behind.
        for value in (params or {}).values():
            failure = failure.replace(value, "***") if len(value) >= 8 else failure
        raise SourceError(f"{source} fetch failed ({shown}): {failure[:300]!r}") from None


def _extension(snapshot: Snapshot) -> str:
    content_type = snapshot.headers.get("content-type", "")
    if "json" in content_type:
        return "json"
    if "csv" in content_type or snapshot.url.endswith(".csv"):
        return "csv"
    return "bin"


def write_once(store: BlobStore, key: str, data: bytes, content_type: str, *, must_match: bool) -> None:
    """Create-only write, so archives stay compatible with an R2 bucket lock.

    Snapshot keys embed the content hash: an existing body at the key must be the same
    bytes, or something is badly wrong. A metadata sidecar may differ in harmless ways
    (a second fetch in the same second), and the first writer's description stands.
    """
    try:
        store.put(key, data, if_none_match=True, content_type=content_type)
    except PreconditionFailedError:
        if not must_match:
            return
        existing = store.get(key)
        if existing is None or existing.data != data:
            raise


def archive(store: BlobStore, snapshot: Snapshot) -> dict[str, str]:
    """Store the raw body (gzipped) plus a metadata sidecar. Returns the reference forecasts cite."""
    stamp = snapshot.fetched_at.astimezone(UTC)
    stem = f"snapshots/{snapshot.source}/{stamp:%Y/%m/%d}/{stamp:%H%M%S}Z-{snapshot.sha256[:12]}"
    key = f"{stem}.{_extension(snapshot)}.gz"
    write_once(store, key, gzip.compress(snapshot.body, mtime=0), "application/gzip", must_match=True)
    meta = {
        "source": snapshot.source,
        "url": snapshot.url,
        "fetched_at": format_utc(snapshot.fetched_at),
        "status": snapshot.status,
        "headers": dict(snapshot.headers),
        "sha256": snapshot.sha256,
        "bytes": len(snapshot.body),
    }
    meta_json = json.dumps(meta, indent=1, sort_keys=True).encode()
    write_once(store, f"{stem}.meta.json", meta_json, "application/json", must_match=False)
    return {"key": key, "sha256": snapshot.sha256}
