import pytest

from nearpost.store.base import PreconditionFailedError
from nearpost.store.local import LocalStore


@pytest.fixture
def store(tmp_path):
    return LocalStore(tmp_path)


def test_missing_key_returns_none(store):
    assert store.get("nope.json") is None


def test_put_then_get_returns_bytes_and_etag(store):
    etag = store.put("a/b.json", b"{}")
    blob = store.get("a/b.json")
    assert blob.data == b"{}"
    assert blob.etag == etag


def test_if_none_match_refuses_to_overwrite(store):
    store.put("ledger/blocks/000000.json", b"first", if_none_match=True)
    with pytest.raises(PreconditionFailedError):
        store.put("ledger/blocks/000000.json", b"second", if_none_match=True)
    assert store.get("ledger/blocks/000000.json").data == b"first"


def test_if_match_rejects_a_stale_etag(store):
    first = store.put("ledger/index.json", b"v1")
    store.put("ledger/index.json", b"v2", if_match=first)
    with pytest.raises(PreconditionFailedError):
        store.put("ledger/index.json", b"v3", if_match=first)


def test_list_keys_is_sorted_and_respects_start_after(store):
    for n in (2, 0, 1):
        store.put(f"ledger/blocks/{n:06d}.json", b"x")
    store.put("ledger/index.json", b"x")
    assert store.list_keys("ledger/blocks/") == [
        "ledger/blocks/000000.json",
        "ledger/blocks/000001.json",
        "ledger/blocks/000002.json",
    ]
    assert store.list_keys("ledger/blocks/", start_after="ledger/blocks/000000.json") == [
        "ledger/blocks/000001.json",
        "ledger/blocks/000002.json",
    ]


def test_keys_cannot_escape_the_root(store):
    with pytest.raises(ValueError, match="key"):
        store.put("../outside.json", b"x")
