"""UTC timestamps as the pipeline writes them: ISO-8601, second precision, `Z` suffix."""

from __future__ import annotations

from datetime import UTC, datetime


def format_utc(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("format_utc needs a timezone-aware datetime")
    return moment.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(text: str) -> datetime:
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError(f"timestamp {text!r} has no timezone")
    return moment.astimezone(UTC)


def season_of(moment: datetime) -> str:
    """The football season a moment belongs to, e.g. "2026-27". Seasons turn over on 1 July."""
    start = moment.year if moment.month >= 7 else moment.year - 1
    return f"{start}-{(start + 1) % 100:02d}"
