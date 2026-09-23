"""A folder that behaves like the R2 bucket, for tests and local dry runs."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from nearpost.store.base import Blob, PreconditionFailedError, validate_key


class LocalStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def _path(self, key: str) -> Path:
        return self._root / validate_key(key)

    def get(self, key: str) -> Blob | None:
        path = self._path(key)
        if not path.is_file():
            return None
        data = path.read_bytes()
        return Blob(data, hashlib.sha256(data).hexdigest())

    def put(
        self,
        key: str,
        data: bytes,
        *,
        if_none_match: bool = False,
        if_match: str | None = None,
        content_type: str = "application/json",
    ) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if if_none_match:
            try:
                with path.open("xb") as handle:
                    handle.write(data)
            except FileExistsError:
                raise PreconditionFailedError(key) from None
            return hashlib.sha256(data).hexdigest()
        if if_match is not None:
            current = self.get(key)
            if current is None or current.etag != if_match:
                raise PreconditionFailedError(key)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            handle.write(data)
        os.replace(handle.name, path)
        return hashlib.sha256(data).hexdigest()

    def list_keys(self, prefix: str, start_after: str | None = None) -> list[str]:
        if not self._root.exists():
            return []
        keys = (p.relative_to(self._root).as_posix() for p in self._root.rglob("*") if p.is_file())
        return sorted(k for k in keys if k.startswith(prefix) and (start_after is None or k > start_after))
