"""`nearpost tick | daily | verify | preview`"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx

from nearpost.health import Healthchecks
from nearpost.jobs.context import RunContext
from nearpost.jobs.preview import preview
from nearpost.jobs.runner import MODES, RunFailedError, RunOutcome, run
from nearpost.ledger.repo import LedgerRepo
from nearpost.redaction import Redactor, install_log_redaction
from nearpost.settings import Settings
from nearpost.snapshots import Fetcher
from nearpost.sources.client import SourceClient
from nearpost.store.base import BlobStore
from nearpost.store.local import LocalStore
from nearpost.store.r2 import R2Store, make_client

log = logging.getLogger("nearpost")


class Pinger(Protocol):
    def start(self) -> None: ...
    def success(self, body: str) -> None: ...
    def fail(self, body: str) -> None: ...


class _RedactingPinger:
    def __init__(self, inner: Pinger, redactor: Redactor) -> None:
        self._inner = inner
        self._redactor = redactor

    def start(self) -> None:
        self._inner.start()

    def success(self, body: str) -> None:
        self._inner.success(self._redactor.clean(body))

    def fail(self, body: str) -> None:
        self._inner.fail(self._redactor.clean(body))


def _describe(outcome: RunOutcome) -> str:
    return (
        f"{outcome.mode}: appended {outcome.appended} entries; ledger head seq {outcome.head_seq} {outcome.head_hash}"
    )


def _write_summary(path: Path | None, outcome: RunOutcome | None, lines: list[str]) -> None:
    """Publish the ledger head in the public job summary: a dated, third-party-hosted record
    of the chain's state. It is a weak anchor (the repo owner can delete runs, and GitHub
    keeps them at most 90 days), not a proof; see README."""
    if path is None:
        return
    text = ["## Nearpost recorder", *lines]
    if outcome is not None:
        text += [
            f"- Ledger head: seq `{outcome.head_seq}`, hash `{outcome.head_hash}`",
            f"- Appended: {outcome.appended}",
        ]
    with path.open("a") as handle:
        handle.write("\n".join(text) + "\n")


def configure_logging(redactor: Redactor) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs every request URL at INFO, query string included (The Odds API key is a
    # query parameter). Quiet it, and redact everything else that might carry a secret.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    install_log_redaction(redactor)


def execute(mode: str, ctx: RunContext, pinger: Pinger, *, summary_path: Path | None = None) -> int:
    redactor = Redactor(ctx.settings.secrets)
    run_link = f"\nrun: {ctx.settings.run_url}" if ctx.settings.run_url else ""
    pinger = _RedactingPinger(pinger, redactor)
    pinger.start()
    try:
        outcome = run(mode, ctx)
    except RunFailedError as failure:
        problems = "\n".join(f"- {p}" for p in failure.problems)
        log.error("%s finished with problems:\n%s", mode, problems)
        pinger.fail(f"{_describe(failure.outcome)}{run_link}\nPROBLEMS:\n{problems}")
        _write_summary(summary_path, failure.outcome, ["**Finished with problems:**", redactor.clean(problems)])
        return 1
    except Exception as error:
        log.exception("%s crashed", mode)
        detail = "".join(traceback.format_exception(error, limit=-8))
        pinger.fail(f"{mode} crashed: {type(error).__name__}: {error}{run_link}\n\n{detail}")
        _write_summary(summary_path, None, [redactor.clean(f"**Crashed:** {type(error).__name__}: {error}")])
        return 1
    log.info(_describe(outcome))
    pinger.success(_describe(outcome) + run_link)
    _write_summary(summary_path, outcome, ["All work due was done."])
    return 0


def build_store(settings: Settings) -> BlobStore:
    if settings.uses_r2:
        client = make_client(
            account_id=settings.r2_account_id or "",
            access_key_id=settings.r2_access_key_id or "",
            secret_access_key=settings.r2_secret_access_key or "",
        )
        return R2Store(client, settings.r2_bucket or "")
    return LocalStore(settings.local_store)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nearpost", description="Nearpost recording job")
    parser.add_argument("mode", choices=[*MODES, "verify", "preview"])
    args = parser.parse_args(argv)
    settings = Settings.from_env(os.environ)
    configure_logging(Redactor(settings.secrets))
    store = build_store(settings)
    # football-data.co.uk redirects www to its apex domain, so redirects must be followed.
    with httpx.Client(timeout=30.0, follow_redirects=True) as http:
        ctx = RunContext(store, SourceClient(Fetcher(http), store), lambda: datetime.now(UTC), settings)
        if args.mode == "verify":
            entries = LedgerRepo(store).read_all()
            print(f"verified {len(entries)} entries; head {entries[-1].hash if entries else 'empty'}")
            return 0
        if args.mode == "preview":
            print(preview(ctx))
            return 0
        pinger = Healthchecks(
            http, settings.healthchecks_ping_key, f"nearpost-{args.mode}", settings.healthchecks_base_url
        )
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        return execute(args.mode, ctx, pinger, summary_path=Path(summary) if summary else None)


if __name__ == "__main__":
    sys.exit(main())
