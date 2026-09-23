"""Keep configured secrets out of every log line, alert body and public job summary."""

from __future__ import annotations

import logging
from collections.abc import Iterable

MIN_SECRET_LENGTH = 6  # shorter values ("eu", "h2h") are configuration, not secrets
MASK = "***"


class Redactor:
    def __init__(self, secrets: Iterable[str | None]) -> None:
        values = {s for s in secrets if s and len(s) >= MIN_SECRET_LENGTH}
        self._secrets = sorted(values, key=len, reverse=True)  # longest first: no partial leftovers

    def clean(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, MASK)
        return text


def install_log_redaction(redactor: Redactor) -> None:
    """Redact at record creation, so it applies to every logger and every handler,
    including third-party libraries that log request URLs."""
    make_record = logging.getLogRecordFactory()

    def redacting_factory(*args, **kwargs) -> logging.LogRecord:
        record = make_record(*args, **kwargs)
        record.msg = redactor.clean(record.getMessage())
        record.args = None
        return record

    logging.setLogRecordFactory(redacting_factory)
