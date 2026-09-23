import gzip
import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest

from nearpost.snapshots import Fetcher, archive
from nearpost.sources.errors import SourceError
from nearpost.store.local import LocalStore

NOW = datetime(2026, 10, 9, 15, 30, 5, tzinfo=UTC)


def _fetcher(handler, sleeps=None):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Fetcher(client, clock=lambda: NOW, sleep=(sleeps.append if sleeps is not None else lambda s: None))


def test_a_successful_fetch_captures_body_hash_time_and_useful_headers():
    def handler(request):
        return httpx.Response(
            200,
            content=b'{"ok": true}',
            headers={"content-type": "application/json", "last-modified": "Fri, 09 Oct 2026 13:00:00 GMT", "x": "y"},
        )

    snapshot = _fetcher(handler).get("fpl-fixtures", "https://example.test/api/fixtures/")
    assert snapshot.body == b'{"ok": true}'
    assert snapshot.sha256 == hashlib.sha256(b'{"ok": true}').hexdigest()
    assert snapshot.fetched_at == NOW
    assert snapshot.headers == {"content-type": "application/json", "last-modified": "Fri, 09 Oct 2026 13:00:00 GMT"}


def test_transient_failures_are_retried_with_backoff():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, content=b"ok")

    sleeps: list[float] = []
    assert _fetcher(handler, sleeps).get("x", "https://example.test/").body == b"ok"
    assert len(calls) == 3
    assert sleeps == [2.0, 4.0]


def test_client_errors_are_not_retried_and_raise_with_the_status():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, content=b'{"message": "bad key"}')

    with pytest.raises(SourceError, match="401"):
        _fetcher(handler).get("odds-api-epl", "https://example.test/odds")
    assert len(calls) == 1


def test_errors_never_leak_secret_query_parameters():
    def handler(request):
        raise httpx.ConnectError(f"could not reach {request.url}")

    with pytest.raises(SourceError) as caught:
        _fetcher(handler).get(
            "odds-api-epl",
            "https://example.test/odds",
            params={"apiKey": "TOPSECRET", "regions": "eu"},
            public_url="https://example.test/odds?regions=eu",
        )
    message = str(caught.value)
    assert "TOPSECRET" not in message
    assert "ConnectError" in message
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_snapshot_keeps_only_the_public_url():
    def handler(request):
        assert request.url.params["apiKey"] == "TOPSECRET"
        return httpx.Response(200, content=b"[]")

    snapshot = _fetcher(handler).get(
        "odds-api-epl",
        "https://example.test/odds",
        params={"apiKey": "TOPSECRET"},
        public_url="https://example.test/odds",
    )
    assert snapshot.url == "https://example.test/odds"


def test_archive_writes_gzipped_body_and_metadata_and_returns_a_reference(tmp_path):
    store = LocalStore(tmp_path)

    def handler(request):
        return httpx.Response(200, content=b"Div,HomeTeam\n", headers={"content-type": "text/csv"})

    snapshot = _fetcher(handler).get("fdco-fixtures", "https://example.test/fixtures.csv")
    ref = archive(store, snapshot)

    assert ref["key"] == f"snapshots/fdco-fixtures/2026/10/09/153005Z-{snapshot.sha256[:12]}.csv.gz"
    assert ref["sha256"] == snapshot.sha256
    assert gzip.decompress(store.get(ref["key"]).data) == b"Div,HomeTeam\n"
    meta = json.loads(store.get(ref["key"].replace(".csv.gz", ".meta.json")).data)
    assert meta["fetched_at"] == "2026-10-09T15:30:05Z"
    assert meta["url"] == "https://example.test/fixtures.csv"
    assert meta["status"] == 200


def test_an_error_body_echoing_the_key_is_scrubbed():
    def handler(request):
        return httpx.Response(401, content=b'{"message": "key TOPSECRET123 is invalid"}')

    with pytest.raises(SourceError) as caught:
        _fetcher(handler).get("odds-api-epl", "https://example.test/odds", params={"apiKey": "TOPSECRET123"})
    assert "TOPSECRET123" not in str(caught.value)
    assert "***" in str(caught.value)


def test_archiving_the_same_snapshot_twice_is_idempotent_and_never_overwrites(tmp_path):
    store = LocalStore(tmp_path)

    def handler(request):
        return httpx.Response(200, content=b"same bytes", headers={"content-type": "text/csv"})

    snapshot = _fetcher(handler).get("fdco-E0-2026-27", "https://example.test/E0.csv")
    original_put = store.put
    overwrites = []

    def guarded_put(key, data, **kwargs):
        if not kwargs.get("if_none_match") and store.get(key) is not None:
            overwrites.append(key)  # what an R2 bucket lock would reject
        return original_put(key, data, **kwargs)

    store.put = guarded_put
    assert archive(store, snapshot) == archive(store, snapshot)
    assert overwrites == []


def test_a_key_straddling_the_truncation_point_is_still_fully_redacted():
    key = "TOPSECRETKEY9876"
    body = ('{"message": "' + "x" * 175 + key + '"}').encode()  # key crosses the 200-char cut

    with pytest.raises(SourceError) as caught:
        _fetcher(lambda r: httpx.Response(401, content=body)).get(
            "odds-api-epl", "https://example.test/odds", params={"apiKey": key}
        )
    assert "TOPSEC" not in str(caught.value)


def test_oversized_responses_are_refused():
    huge = b"x" * (2 * 1024 * 1024)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=huge)))
    fetcher = Fetcher(client, clock=lambda: NOW, sleep=lambda s: None, max_bytes=1024 * 1024)
    with pytest.raises(SourceError, match="larger than"):
        fetcher.get("fpl-bootstrap", "https://example.test/big")
