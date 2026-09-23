"""Object storage the pipeline writes to: Cloudflare R2 in production, a folder locally."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class PreconditionFailedError(RuntimeError):
    """A conditional write lost: the object exists (if_none_match) or changed (if_match)."""


@dataclass(frozen=True)
class Blob:
    data: bytes
    etag: str


class BlobStore(Protocol):
    def get(self, key: str) -> Blob | None: ...

    def put(
        self,
        key: str,
        data: bytes,
        *,
        if_none_match: bool = False,
        if_match: str | None = None,
        content_type: str = "application/json",
    ) -> str:
        """Write an object and return its new etag."""
        ...

    def list_keys(self, prefix: str, start_after: str | None = None) -> list[str]:
        """Keys under a prefix in lexicographic order."""
        ...


def validate_key(key: str) -> str:
    parts = key.split("/")
    if not key or key.startswith("/") or "\\" in key or any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"invalid object key {key!r}")
    return key
