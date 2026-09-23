import gzip

import httpx
import pytest

from nearpost.snapshots import Fetcher
from nearpost.sources.client import SourceClient
from nearpost.sources.errors import SourceError
from nearpost.store.local import LocalStore
from tests.test_snapshots import NOW


def _client(tmp_path, handler):
    fetcher = Fetcher(httpx.Client(transport=httpx.MockTransport(handler)), clock=lambda: NOW, sleep=lambda s: None)
    return SourceClient(fetcher, LocalStore(tmp_path))


def test_fetch_archives_and_returns_the_reference(tmp_path):
    client = _client(
        tmp_path, lambda r: httpx.Response(200, content=b"[]", headers={"content-type": "application/json"})
    )
    snapshot, ref = client.fetch("fpl-fixtures", "https://example.test/fixtures/")
    assert snapshot.body == b"[]"
    assert ref["key"].startswith("snapshots/fpl-fixtures/2026/10/09/")


def test_past_season_files_are_downloaded_once_then_served_from_the_cache(tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=b"Div,HomeTeam\n", headers={"content-type": "text/csv"})

    client = _client(tmp_path, handler)
    body1, ref1 = client.football_data_season("2024-25", "E0", current=False)
    body2, ref2 = client.football_data_season("2024-25", "E0", current=False)
    assert body1 == body2 == b"Div,HomeTeam\n"
    assert ref1 == ref2
    assert ref1["key"] == "cache/football-data/2024-25/E0.csv.gz"
    assert calls == ["https://www.football-data.co.uk/mmz4281/2425/E0.csv"]
    assert gzip.decompress(LocalStore(tmp_path).get(ref1["key"]).data) == b"Div,HomeTeam\n"


def test_the_current_season_is_always_fetched_fresh_and_archived(tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=b"Div,HomeTeam\n", headers={"content-type": "text/csv"})

    client = _client(tmp_path, handler)
    _, ref = client.football_data_season("2026-27", "E0", current=True)
    client.football_data_season("2026-27", "E0", current=True)
    assert len(calls) == 2
    assert ref["key"].startswith("snapshots/fdco-E0-2026-27/")


def test_source_failures_propagate(tmp_path):
    client = _client(tmp_path, lambda r: httpx.Response(404))
    with pytest.raises(SourceError, match="404"):
        client.fetch("fpl-fixtures", "https://example.test/fixtures/")
