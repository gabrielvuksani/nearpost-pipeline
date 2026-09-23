"""Hash-chained ledger entries.

Each entry commits to its predecessor's hash, so editing, reordering or deleting any
past entry breaks every later link. The body is held as canonical JSON text, which
makes an Entry genuinely immutable: `.body` always hands back a fresh copy.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

GENESIS_HASH = "0" * 64


class ChainError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True)
class Entry:
    seq: int
    kind: str
    recorded_at: str
    prev_hash: str
    body_json: str
    hash: str

    @property
    def body(self) -> dict[str, Any]:
        return json.loads(self.body_json)


def _digest(seq: int, kind: str, recorded_at: str, prev_hash: str, body_json: str) -> str:
    material = canonical_json(
        {"seq": seq, "kind": kind, "recorded_at": recorded_at, "prev_hash": prev_hash, "body": json.loads(body_json)}
    )
    return hashlib.sha256(material.encode()).hexdigest()


def link_entry(head_seq: int, head_hash: str, kind: str, body: Mapping[str, Any], recorded_at: str) -> Entry:
    """The entry that follows a head identified by (seq, hash). Use (-1, GENESIS_HASH) to start."""
    seq = head_seq + 1
    body_json = canonical_json(body)
    return Entry(seq, kind, recorded_at, head_hash, body_json, _digest(seq, kind, recorded_at, head_hash, body_json))


def make_entry(previous: Entry | None, kind: str, body: Mapping[str, Any], recorded_at: str) -> Entry:
    if previous is None:
        return link_entry(-1, GENESIS_HASH, kind, body, recorded_at)
    return link_entry(previous.seq, previous.hash, kind, body, recorded_at)


def verify_chain(entries: Iterable[Entry], *, start_prev: str = GENESIS_HASH, start_seq: int = 0) -> None:
    expected_prev, expected_seq = start_prev, start_seq
    for entry in entries:
        if entry.seq != expected_seq:
            raise ChainError(f"expected seq {expected_seq}, found seq {entry.seq}: entries missing or reordered")
        if entry.prev_hash != expected_prev:
            raise ChainError(f"seq {entry.seq} does not link to its predecessor")
        recomputed = _digest(entry.seq, entry.kind, entry.recorded_at, entry.prev_hash, entry.body_json)
        if recomputed != entry.hash:
            raise ChainError(f"seq {entry.seq} content does not match its hash")
        expected_prev, expected_seq = entry.hash, entry.seq + 1


def entry_to_dict(entry: Entry) -> dict[str, Any]:
    return {
        "seq": entry.seq,
        "kind": entry.kind,
        "recorded_at": entry.recorded_at,
        "prev_hash": entry.prev_hash,
        "body": entry.body,
        "hash": entry.hash,
    }


def entry_from_dict(raw: Mapping[str, Any]) -> Entry:
    try:
        return Entry(
            seq=int(raw["seq"]),
            kind=str(raw["kind"]),
            recorded_at=str(raw["recorded_at"]),
            prev_hash=str(raw["prev_hash"]),
            body_json=canonical_json(raw["body"]),
            hash=str(raw["hash"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ChainError(f"malformed ledger entry: {error}") from error
