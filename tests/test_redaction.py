import logging
from datetime import timedelta

import pytest

from nearpost import cli
from nearpost.cli import configure_logging, execute
from nearpost.redaction import Redactor
from tests.harness import KICKOFF, World, context
from tests.test_cli import RecordingPinger

SECRET = "test-key-123"


@pytest.fixture
def restore_logging():
    factory = logging.getLogRecordFactory()
    levels = {name: logging.getLogger(name).level for name in ("httpx", "httpcore")}
    yield
    logging.setLogRecordFactory(factory)
    for name, level in levels.items():
        logging.getLogger(name).setLevel(level)


def test_redactor_replaces_every_secret_longest_first():
    redactor = Redactor(["abcdef", "abcdefgh", None, ""])
    assert redactor.clean("x abcdefgh y abcdef") == "x *** y ***"


def test_short_values_are_not_treated_as_secrets():
    assert Redactor(["eu"]).clean("regions=eu") == "regions=eu"


def test_a_full_run_at_info_level_never_logs_the_odds_api_key(tmp_path, caplog, restore_logging):
    configure_logging(Redactor([SECRET]))
    world = World(now=KICKOFF - timedelta(hours=20))
    with caplog.at_level(logging.INFO):
        execute("tick", context(world, tmp_path), RecordingPinger())
    assert "the-odds-api" in "".join(world.requests)  # the key really was used
    assert SECRET not in caplog.text


def test_any_log_record_carrying_a_secret_is_redacted(caplog, restore_logging):
    configure_logging(Redactor([SECRET]))
    with caplog.at_level(logging.INFO):
        logging.getLogger("some.library").info("calling https://x.test/?apiKey=%s", SECRET)
    assert SECRET not in caplog.text
    assert "apiKey=***" in caplog.text


def test_crash_reports_and_summaries_are_redacted(tmp_path, monkeypatch):
    def crash(mode, ctx):
        raise RuntimeError(f"boom while using {SECRET}")

    monkeypatch.setattr(cli, "run", crash)
    pinger = RecordingPinger()
    summary = tmp_path / "summary.md"
    ctx = context(World(now=KICKOFF), tmp_path / "store")

    assert execute("tick", ctx, pinger, summary_path=summary) == 1
    assert SECRET not in pinger.calls[-1][1]
    assert SECRET not in summary.read_text()
