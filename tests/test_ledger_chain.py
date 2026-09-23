import dataclasses
import json

import pytest

from nearpost.ledger.chain import (
    GENESIS_HASH,
    ChainError,
    Entry,
    canonical_json,
    entry_from_dict,
    entry_to_dict,
    make_entry,
    verify_chain,
)

T0 = "2026-10-03T11:30:00Z"


def _chain(n: int) -> list[Entry]:
    entries: list[Entry] = []
    for i in range(n):
        previous = entries[-1] if entries else None
        entries.append(make_entry(previous, "forecast", {"i": i, "p": [0.5, 0.3, 0.2]}, T0))
    return entries


def test_canonical_json_is_key_order_independent_and_compact():
    assert canonical_json({"b": 1, "a": [1.5, "x"]}) == '{"a":[1.5,"x"],"b":1}'
    assert canonical_json({"a": [1.5, "x"], "b": 1}) == canonical_json({"b": 1, "a": [1.5, "x"]})


def test_canonical_json_refuses_nan():
    with pytest.raises(ValueError):
        canonical_json({"p": float("nan")})


def test_first_entry_links_to_genesis_and_later_entries_link_to_their_predecessor():
    first, second = _chain(2)
    assert (first.seq, first.prev_hash) == (0, GENESIS_HASH)
    assert (second.seq, second.prev_hash) == (1, first.hash)
    assert len(first.hash) == 64


def test_entry_body_is_a_fresh_copy_so_callers_cannot_mutate_the_record():
    entry = _chain(1)[0]
    entry.body["i"] = 99
    assert entry.body["i"] == 0


def test_a_valid_chain_verifies():
    verify_chain(_chain(5))


def test_editing_a_past_body_is_detected():
    entries = _chain(4)
    forged = dataclasses.replace(entries[1], body_json=canonical_json({"i": 1, "p": [0.9, 0.05, 0.05]}))
    with pytest.raises(ChainError, match="seq 1"):
        verify_chain([entries[0], forged, *entries[2:]])


def test_deleting_an_entry_is_detected():
    entries = _chain(4)
    with pytest.raises(ChainError, match="seq"):
        verify_chain([entries[0], *entries[2:]])


def test_rehashing_a_forged_entry_still_breaks_the_next_link():
    entries = _chain(3)
    forged = make_entry(entries[0], "forecast", {"i": 1, "p": [0.9, 0.05, 0.05]}, T0)
    with pytest.raises(ChainError, match="seq 2"):
        verify_chain([entries[0], forged, entries[2]])


def test_verification_can_start_mid_chain_from_a_trusted_head():
    entries = _chain(5)
    verify_chain(entries[3:], start_prev=entries[2].hash, start_seq=3)


def test_dict_round_trip_preserves_the_hash():
    entry = _chain(1)[0]
    as_json = json.dumps(entry_to_dict(entry))
    assert entry_from_dict(json.loads(as_json)) == entry


def test_entry_from_dict_rejects_missing_fields():
    with pytest.raises(ChainError, match="malformed"):
        entry_from_dict({"seq": 0, "kind": "forecast"})
