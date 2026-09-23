"""`state/status.json`: what the Cloudflare Worker reads. See docs/status-contract.md."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from nearpost.store.base import BlobStore
from nearpost.tasks import Plan, missed_to_status, task_to_status
from nearpost.timeutil import format_utc, parse_utc

STATUS_KEY = "state/status.json"
SCHEMA = 1
LOOKAHEAD = timedelta(days=8)  # the Worker only acts on due work; the whole season would be ~200 kB


def read_status(store: BlobStore) -> dict[str, Any] | None:
    blob = store.get(STATUS_KEY)
    if blob is None:
        return None
    try:
        status = json.loads(blob.data)
    except json.JSONDecodeError:
        return None
    return status if isinstance(status, dict) and status.get("schema") == SCHEMA else None


CREDITS_FRESH_FOR = timedelta(hours=24)


def previous_credits(status: dict[str, Any] | None, *, now: datetime) -> int | None:
    """The last credit count, if recent. An old count may predate the monthly reset, and
    trusting it would block captures that could have been made."""
    odds = (status or {}).get("odds_api") or {}
    observed = odds.get("observed_at")
    if observed is None or now - parse_utc(observed) > CREDITS_FRESH_FOR:
        return None
    return odds.get("credits_remaining")


def build_status(
    plan: Plan,
    *,
    now: datetime,
    previous: dict[str, Any] | None,
    succeeded: tuple[str, ...],
    odds_api: dict[str, Any] | None,
) -> dict[str, Any]:
    last_success = dict((previous or {}).get("last_success") or {})
    for mode in succeeded:
        last_success[mode] = format_utc(now)
    return {
        "schema": SCHEMA,
        "generated_at": format_utc(now),
        "last_success": last_success,
        "tasks": [task_to_status(t) for t in plan.pending if t.due_at <= now + LOOKAHEAD],
        "missed": [missed_to_status(t) for t in plan.missed],
        "odds_api": odds_api if odds_api is not None else (previous or {}).get("odds_api"),
    }


def carried_forward(previous: dict[str, Any] | None, *, now: datetime) -> dict[str, Any]:
    """After a crash: keep the last known tasks so the Worker can still see them go overdue,
    but record no new success."""
    base = previous or {"last_success": {}, "tasks": [], "missed": [], "odds_api": None}
    return {**base, "schema": SCHEMA, "generated_at": format_utc(now)}


def write_status(store: BlobStore, status: dict[str, Any]) -> None:
    store.put(STATUS_KEY, json.dumps(status, indent=1).encode())
