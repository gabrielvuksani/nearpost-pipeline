"""Fetch-and-archive: every byte a run relies on is kept, and cited by reference."""

from __future__ import annotations

import contextlib
import gzip
import hashlib
from collections.abc import Mapping

from nearpost.snapshots import Fetcher, Snapshot, archive
from nearpost.sources.football_data import season_url
from nearpost.store.base import BlobStore, PreconditionFailedError

Ref = dict[str, str]


class SourceClient:
    def __init__(self, fetcher: Fetcher, store: BlobStore) -> None:
        self._fetcher = fetcher
        self._store = store

    def fetch(
        self, source: str, url: str, *, params: Mapping[str, str] | None = None, public_url: str | None = None
    ) -> tuple[Snapshot, Ref]:
        snapshot = self._fetcher.get(source, url, params=params, public_url=public_url)
        return snapshot, archive(self._store, snapshot)

    def peek(self, source: str, url: str) -> Snapshot:
        """Fetch without archiving: for reads that inform scheduling but are not evidence."""
        return self._fetcher.get(source, url)

    def keep(self, snapshot: Snapshot) -> Ref:
        """Archive a peeked snapshot once it becomes evidence for a ledger entry."""
        return archive(self._store, snapshot)

    def football_data_season(self, season: str, division: str, *, current: bool) -> tuple[bytes, Ref]:
        """A season CSV. Finished seasons never change, so they are downloaded once into a
        write-once cache; the current season is fetched fresh and archived every time."""
        url = season_url(season, division)
        if current:
            snapshot, ref = self.fetch(f"fdco-{division}-{season}", url)
            return snapshot.body, ref

        key = f"cache/football-data/{season}/{division}.csv.gz"
        cached = self._store.get(key)
        if cached is None:
            body = self._fetcher.get(f"fdco-{division}-{season}", url).body
            # Losing this race is fine: another run cached the same file first, and reading
            # theirs back below means both runs cite identical bytes.
            with contextlib.suppress(PreconditionFailedError):
                self._store.put(key, gzip.compress(body, mtime=0), if_none_match=True, content_type="application/gzip")
            cached = self._store.get(key)
            if cached is None:
                raise RuntimeError(f"cache write for {key} did not persist")
        body = gzip.decompress(cached.data)
        return body, {"key": key, "sha256": hashlib.sha256(body).hexdigest()}
