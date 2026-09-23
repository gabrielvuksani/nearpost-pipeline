"""The ledger in object storage: one immutable block object per run.

Blocks are created with `If-None-Match: *`, so no code path can overwrite one, and two
writers can never both claim the same block number. An R2 bucket lock on `ledger/blocks/`
extends that to anyone holding only the pipeline's object credentials (or a compromised
dependency running with them): they cannot delete or overwrite a block. It does not bind
the Cloudflare account owner, who can remove a lock rule; see README "What the ledger does
and doesn't prove".
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import reduce
from typing import Any

from nearpost.ledger.chain import (
    ChainError,
    Entry,
    entry_from_dict,
    entry_to_dict,
    link_entry,
    verify_chain,
)
from nearpost.ledger.index import (
    LedgerIndex,
    apply_entry,
    forecast_key,
    index_from_json,
    index_to_json,
)
from nearpost.store.base import BlobStore, PreconditionFailedError

__all__ = ["ConcurrentWriteError", "LedgerRepo", "forecast_key"]

BLOCK_PREFIX = "ledger/blocks/"
READ_WORKERS = 16  # block reads are independent GETs; verification happens after, in order
INDEX_KEY = "ledger/index.json"

PendingEntry = tuple[str, Mapping[str, Any]]


class ConcurrentWriteError(RuntimeError):
    pass


def block_key(number: int) -> str:
    return f"{BLOCK_PREFIX}{number:06d}.json"


def _block_number(key: str) -> int:
    return int(key.removeprefix(BLOCK_PREFIX).removesuffix(".json"))


class LedgerRepo:
    def __init__(self, store: BlobStore) -> None:
        self._store = store

    def _read_block(self, key: str) -> list[Entry]:
        blob = self._store.get(key)
        if blob is None:
            raise ChainError(f"block {key} vanished while reading")
        raw = json.loads(blob.data)
        if raw.get("block") != _block_number(key):
            raise ChainError(f"block {key} claims number {raw.get('block')}")
        return [entry_from_dict(e) for e in raw["entries"]]

    def _load(self) -> tuple[LedgerIndex, str | None]:
        """The index, healed by folding any blocks written after it."""
        blob = self._store.get(INDEX_KEY)
        index = index_from_json(blob.data) if blob else LedgerIndex()
        if index.last_block >= 0:
            # The index is a cache in an unlocked location: check its head against the block
            # it claims to summarise before chaining anything onto it.
            tail = self._read_block(block_key(index.last_block))[-1]
            if (tail.seq, tail.hash) != (index.head_seq, index.head_hash):
                raise ChainError(f"ledger index head does not match block {index.last_block}; rebuild the index")
        start_after = block_key(index.last_block) if index.last_block >= 0 else None
        for key in self._store.list_keys(BLOCK_PREFIX, start_after=start_after):
            number = _block_number(key)
            if number != index.last_block + 1:
                raise ChainError(f"expected block {index.last_block + 1}, found {key}")
            entries = self._read_block(key)
            verify_chain(entries, start_prev=index.head_hash, start_seq=index.head_seq + 1)
            index = reduce(apply_entry, entries, index)
            index = replace(index, last_block=number)
        return index, blob.etag if blob else None

    def load_index(self) -> LedgerIndex:
        return self._load()[0]

    def append(
        self, pending: Sequence[PendingEntry], *, recorded_at: str, expected_head_seq: int | None = None
    ) -> LedgerIndex:
        """Append one block. `expected_head_seq` is the head the entries were planned from: if
        another writer has moved the chain since, the entries may duplicate theirs, so refuse."""
        index, etag = self._load()
        if not pending:
            return index
        if expected_head_seq is not None and index.head_seq != expected_head_seq:
            raise ConcurrentWriteError(
                f"ledger head moved from seq {expected_head_seq} to {index.head_seq} since this run planned"
            )

        entries: list[Entry] = []
        head_seq, head_hash = index.head_seq, index.head_hash
        for kind, body in pending:
            entry = link_entry(head_seq, head_hash, kind, body, recorded_at)
            entries.append(entry)
            head_seq, head_hash = entry.seq, entry.hash

        number = index.last_block + 1
        block = {"block": number, "created_at": recorded_at, "entries": [entry_to_dict(e) for e in entries]}
        try:
            self._store.put(block_key(number), json.dumps(block, indent=1).encode(), if_none_match=True)
        except PreconditionFailedError as error:
            raise ConcurrentWriteError(f"block {number} was written by another run") from error

        updated = reduce(apply_entry, entries, index)
        updated = replace(updated, last_block=number)
        try:
            if etag is None:
                self._store.put(INDEX_KEY, index_to_json(updated), if_none_match=True)
            else:
                self._store.put(INDEX_KEY, index_to_json(updated), if_match=etag)
        except PreconditionFailedError as error:
            raise ConcurrentWriteError("ledger index changed during this run") from error
        return updated

    def read_all(self) -> list[Entry]:
        """Every entry from genesis, fully verified. Raises ChainError on any tampering."""
        keys = self._store.list_keys(BLOCK_PREFIX)
        for expected, key in enumerate(keys):
            if _block_number(key) != expected:
                raise ChainError(f"expected block {expected}, found {key}")
        with ThreadPoolExecutor(max_workers=READ_WORKERS) as pool:  # order-preserving
            blocks = list(pool.map(self._read_block, keys))
        entries = [entry for block in blocks for entry in block]
        verify_chain(entries)
        return entries
