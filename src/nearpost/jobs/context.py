from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from nearpost.settings import Settings
from nearpost.sources.client import SourceClient
from nearpost.store.base import BlobStore


@dataclass(frozen=True)
class RunContext:
    store: BlobStore
    client: SourceClient
    clock: Callable[[], datetime]
    settings: Settings


@dataclass(frozen=True)
class JobReport:
    """What a job did. `problems` non-empty means the run must be reported as failed."""

    appended: int
    head_hash: str
    head_seq: int
    plan: object  # nearpost.tasks.Plan, after this run's entries
    problems: tuple[str, ...]
    odds_api: dict | None = None
