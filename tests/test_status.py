from datetime import UTC, datetime, timedelta

from nearpost.jobs.status import build_status, carried_forward
from nearpost.tasks import Plan, Task

NOW = datetime(2026, 9, 23, 3, 45, tzinfo=UTC)


def _task(days):
    return Task("capture", NOW + timedelta(days=days), NOW + timedelta(days=days, hours=1), "m", "T-7d", NOW)


def test_status_lists_only_work_due_within_the_lookahead_plus_anything_overdue():
    plan = Plan(pending=(_task(-1), _task(2), _task(7.9), _task(8.1), _task(200)), missed=())
    status = build_status(plan, now=NOW, previous=None, succeeded=("tick",), odds_api=None)
    assert [t["due_at"] for t in status["tasks"]] == [
        "2026-09-22T03:45:00Z",
        "2026-09-25T03:45:00Z",
        "2026-10-01T01:21:00Z",
    ]


def test_success_times_accumulate_and_failures_keep_the_previous_ones():
    previous = {"last_success": {"daily": "2026-09-22T06:00:00Z"}, "odds_api": {"credits_remaining": 400}}
    status = build_status(Plan((), ()), now=NOW, previous=previous, succeeded=(), odds_api=None)
    assert status["last_success"] == {"daily": "2026-09-22T06:00:00Z"}
    assert status["odds_api"] == {"credits_remaining": 400}


def test_a_crash_carries_the_last_tasks_forward_without_claiming_success():
    previous = {"schema": 1, "last_success": {}, "tasks": [{"kind": "settle"}], "missed": [], "odds_api": None}
    status = carried_forward(previous, now=NOW)
    assert status["tasks"] == [{"kind": "settle"}]
    assert status["generated_at"] == "2026-09-23T03:45:00Z"
    assert status["last_success"] == {}


def test_credit_counts_older_than_a_day_are_treated_as_unknown():
    from nearpost.jobs.status import previous_credits

    fresh = {"odds_api": {"credits_remaining": 20, "observed_at": "2026-09-22T12:00:00Z"}}
    stale = {"odds_api": {"credits_remaining": 20, "observed_at": "2026-09-20T12:00:00Z"}}
    assert previous_credits(fresh, now=NOW) == 20
    assert previous_credits(stale, now=NOW) is None
    assert previous_credits(None, now=NOW) is None
