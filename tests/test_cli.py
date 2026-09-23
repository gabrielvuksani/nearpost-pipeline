from datetime import timedelta

from nearpost.cli import execute
from tests.harness import KICKOFF, World, context


class RecordingPinger:
    def __init__(self):
        self.calls = []

    def start(self):
        self.calls.append(("start", None))

    def success(self, body):
        self.calls.append(("success", body))

    def fail(self, body):
        self.calls.append(("fail", body))


def test_a_clean_run_pings_success_with_the_ledger_head_and_exits_zero(tmp_path):
    world = World(now=KICKOFF - timedelta(hours=20))
    pinger = RecordingPinger()
    summary = tmp_path / "summary.md"

    code = execute("tick", context(world, tmp_path / "store"), pinger, summary_path=summary)

    assert code == 0
    assert [c for c, _ in pinger.calls] == ["start", "success"]
    assert "head" in pinger.calls[1][1]
    assert "Ledger head" in summary.read_text()


def test_a_run_with_problems_pings_fail_with_them_and_exits_one(tmp_path):
    world = World(now=KICKOFF - timedelta(hours=20), odds_status=503)
    pinger = RecordingPinger()

    code = execute("tick", context(world, tmp_path, run_url="https://github.com/o/r/actions/runs/7"), pinger)

    assert code == 1
    kind, body = pinger.calls[-1]
    assert kind == "fail"
    assert "odds-api" in body
    assert "https://github.com/o/r/actions/runs/7" in body  # the alert links straight to the logs


def test_a_crash_pings_fail_with_the_error_and_exits_one(tmp_path):
    world = World(now=KICKOFF - timedelta(hours=20))
    world.handle = lambda request: __import__("httpx").Response(503)  # FPL itself is down
    pinger = RecordingPinger()

    code = execute("tick", context(world, tmp_path), pinger)

    assert code == 1
    kind, body = pinger.calls[-1]
    assert kind == "fail"
    assert "fpl-bootstrap" in body
