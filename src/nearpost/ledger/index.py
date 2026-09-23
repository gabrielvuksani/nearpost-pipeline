"""A derived summary of the ledger, so each run need not read every block.

It is a cache: it can always be rebuilt by folding the blocks from the start. Beyond
"what has been done", it holds the working set of forecasts still awaiting a result,
which is all a settlement needs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any

from nearpost.ledger.chain import GENESIS_HASH, Entry

OpenForecast = dict[str, Any]  # hash, model, horizon, kickoff, probs, over_2_5, btts


def forecast_key(match_id: str, kickoff: str, horizon: str, model: str) -> str:
    """A meeting is a match at a specific kickoff: a rescheduled match is a new meeting."""
    return f"{match_id}|{kickoff}|{horizon}|{model}"


@dataclass(frozen=True)
class LedgerIndex:
    last_block: int = -1
    head_seq: int = -1
    head_hash: str = GENESIS_HASH
    genesis_at: str | None = None
    forecasts: frozenset[str] = field(default_factory=frozenset)
    settled: frozenset[str] = field(default_factory=frozenset)
    benchmarked: frozenset[str] = field(default_factory=frozenset)
    fpl_ep_next: frozenset[int] = field(default_factory=frozenset)
    fpl_results: frozenset[int] = field(default_factory=frozenset)
    # Treated as immutable: every change goes through `replace` with a new dict.
    open_forecasts: dict[str, tuple[OpenForecast, ...]] = field(default_factory=dict)

    def has_forecasts_for(self, match_id: str) -> bool:
        return any(key.startswith(f"{match_id}|") for key in self.forecasts)


def _open(entry: Entry, body: dict[str, Any]) -> OpenForecast:
    return {
        "hash": entry.hash,
        "model": body["model"],
        "horizon": body["horizon"],
        "kickoff": body["kickoff"],
        "probs": body["probs"],
        "over_2_5": body.get("over_2_5"),
        "btts": body.get("btts"),
    }


def apply_entry(index: LedgerIndex, entry: Entry) -> LedgerIndex:
    body = entry.body
    moved = replace(index, head_seq=entry.seq, head_hash=entry.hash, genesis_at=index.genesis_at or entry.recorded_at)
    match entry.kind:
        case "forecast":
            match_id = body["match_id"]
            key = forecast_key(match_id, body["kickoff"], body["horizon"], body["model"])
            opened = moved.open_forecasts
            if body.get("probs") is not None:
                opened = {**opened, match_id: (*opened.get(match_id, ()), _open(entry, body))}
            return replace(moved, forecasts=moved.forecasts | {key}, open_forecasts=opened)
        case "settlement":
            match_id = body["match_id"]
            remaining = {k: v for k, v in moved.open_forecasts.items() if k != match_id}
            return replace(moved, settled=moved.settled | {match_id}, open_forecasts=remaining)
        case "benchmark":
            return replace(moved, benchmarked=moved.benchmarked | {body["match_id"]})
        case "fpl-ep-next":
            return replace(moved, fpl_ep_next=moved.fpl_ep_next | {int(body["gameweek"])})
        case "fpl-result":
            return replace(moved, fpl_results=moved.fpl_results | {int(body["gameweek"])})
        case _:
            return moved


def index_to_json(index: LedgerIndex) -> bytes:
    return json.dumps(
        {
            "last_block": index.last_block,
            "head_seq": index.head_seq,
            "head_hash": index.head_hash,
            "genesis_at": index.genesis_at,
            "forecasts": sorted(index.forecasts),
            "settled": sorted(index.settled),
            "benchmarked": sorted(index.benchmarked),
            "fpl_ep_next": sorted(index.fpl_ep_next),
            "fpl_results": sorted(index.fpl_results),
            "open_forecasts": {k: list(v) for k, v in sorted(index.open_forecasts.items())},
        },
        indent=1,
    ).encode()


def index_from_json(data: bytes) -> LedgerIndex:
    raw: dict[str, Any] = json.loads(data)
    return LedgerIndex(
        last_block=int(raw["last_block"]),
        head_seq=int(raw["head_seq"]),
        head_hash=str(raw["head_hash"]),
        genesis_at=raw.get("genesis_at"),
        forecasts=frozenset(raw["forecasts"]),
        settled=frozenset(raw["settled"]),
        benchmarked=frozenset(raw["benchmarked"]),
        fpl_ep_next=frozenset(int(g) for g in raw["fpl_ep_next"]),
        fpl_results=frozenset(int(g) for g in raw["fpl_results"]),
        open_forecasts={k: tuple(v) for k, v in raw.get("open_forecasts", {}).items()},
    )
