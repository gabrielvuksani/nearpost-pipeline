from dataclasses import replace
from datetime import UTC, datetime, timedelta

from nearpost.domain import Fixture, Gameweek
from nearpost.horizons import HORIZONS, horizon_named
from nearpost.ledger.index import LedgerIndex, forecast_key
from nearpost.tasks import due, plan_work, task_to_status

KICKOFF = datetime(2026, 10, 10, 11, 30, tzinfo=UTC)
MATCH = "2026-27:arsenal-v-chelsea"
FIXTURE = Fixture(MATCH, "2026-27", 51, 6, KICKOFF, "arsenal", "chelsea", False, None, None)
GW6 = Gameweek(6, datetime(2026, 10, 10, 10, 0, tzinfo=UTC), False, False)
EMPTY = LedgerIndex()


def _done(index: LedgerIndex, horizon: str, models=None) -> LedgerIndex:
    names = models or horizon_named(horizon).models
    return replace(
        index, forecasts=index.forecasts | {forecast_key(MATCH, "2026-10-10T11:30:00Z", horizon, m) for m in names}
    )


def _captures(tasks):
    return [(t.horizon, t.due_at) for t in tasks if t.kind == "capture"]


def test_horizons_record_independent_models_three_times_and_the_market_close_once():
    assert [h.name for h in HORIZONS] == ["T-7d", "T-24h", "T-1h", "T-15m"]
    assert "elo-v1" in horizon_named("T-7d").models
    assert horizon_named("T-15m").models == ("market-oddsapi-v1",)


def test_a_future_fixture_has_one_pending_capture_per_horizon():
    work = plan_work([FIXTURE], [], EMPTY, now=datetime(2026, 10, 1, tzinfo=UTC))
    assert _captures(work.pending) == [
        ("T-7d", KICKOFF - timedelta(days=7)),
        ("T-24h", KICKOFF - timedelta(hours=24)),
        ("T-1h", KICKOFF - timedelta(hours=1)),
        ("T-15m", KICKOFF - timedelta(minutes=15)),
    ]
    assert due(work, datetime(2026, 10, 1, tzinfo=UTC)) == ()


def test_a_capture_is_due_from_its_window_start():
    now = KICKOFF - timedelta(days=7)
    work = plan_work([FIXTURE], [], EMPTY, now=now)
    assert [t.horizon for t in due(work, now)] == ["T-7d"]


def test_only_missing_models_are_requested():
    index = _done(EMPTY, "T-24h", models=("elo-v1",))
    now = KICKOFF - timedelta(hours=20)
    [task] = due(plan_work([FIXTURE], [], index, now=now), now)
    assert task.horizon == "T-24h"
    assert "elo-v1" not in task.models
    assert "dixon-coles-v1" in task.models


def test_completed_horizons_are_not_pending():
    index = _done(EMPTY, "T-7d")
    work = plan_work([FIXTURE], [], index, now=datetime(2026, 10, 4, tzinfo=UTC))
    assert "T-7d" not in [h for h, _ in _captures(work.pending)]


def test_a_rescheduled_match_is_a_new_meeting_with_fresh_captures():
    index = _done(_done(EMPTY, "T-7d"), "T-24h")  # recorded for the original 10 Oct kickoff
    moved = replace(FIXTURE, kickoff=datetime(2027, 1, 20, 19, 45, tzinfo=UTC))
    work = plan_work([moved], [], index, now=datetime(2027, 1, 1, tzinfo=UTC))
    assert [h for h, _ in _captures(work.pending)] == ["T-7d", "T-24h", "T-1h", "T-15m"]


def test_no_capture_is_ever_planned_at_or_after_kickoff():
    work = plan_work([FIXTURE], [], EMPTY, now=KICKOFF)
    assert _captures(work.pending) == []


def test_a_window_that_closed_undone_after_recording_began_is_missed():
    index = replace(EMPTY, genesis_at="2026-10-01T00:00:00Z")
    now = KICKOFF - timedelta(minutes=30)  # T-7d and T-24h have closed; T-1h stays open until T-15m
    assert [t.horizon for t in plan_work([FIXTURE], [], index, now=now).missed] == ["T-7d", "T-24h"]


def test_nothing_is_missed_before_the_ledger_began():
    index = replace(EMPTY, genesis_at="2026-10-10T10:45:00Z")  # after T-7d and T-24h closed
    work = plan_work([FIXTURE], [], index, now=KICKOFF - timedelta(minutes=30))
    assert [t.horizon for t in work.missed] == []


def test_an_empty_ledger_reports_nothing_missed():
    work = plan_work([FIXTURE], [], EMPTY, now=KICKOFF - timedelta(minutes=30))
    assert work.missed == ()


def test_missed_windows_age_out_after_seven_days():
    index = replace(EMPTY, genesis_at="2026-09-01T00:00:00Z")
    work = plan_work([FIXTURE], [], index, now=KICKOFF + timedelta(days=8))
    assert work.missed == ()


def test_a_forecast_match_is_settled_two_hours_fifteen_after_kickoff():
    index = _done(EMPTY, "T-24h")
    work = plan_work([FIXTURE], [], index, now=KICKOFF + timedelta(minutes=5))
    [settle] = [t for t in work.pending if t.kind == "settle"]
    assert settle.due_at == KICKOFF + timedelta(hours=2, minutes=15)


def test_matches_without_forecasts_or_already_settled_need_no_settlement():
    later = KICKOFF + timedelta(hours=3)
    assert [t for t in plan_work([FIXTURE], [], EMPTY, now=later).pending if t.kind == "settle"] == []
    settled = replace(_done(EMPTY, "T-24h"), settled=frozenset({MATCH}))
    assert [t for t in plan_work([FIXTURE], [], settled, now=later).pending if t.kind == "settle"] == []


def test_unscheduled_fixtures_are_ignored():
    unscheduled = replace(FIXTURE, kickoff=None)
    assert plan_work([unscheduled], [], EMPTY, now=datetime(2026, 10, 1, tzinfo=UTC)).pending == ()


def test_ep_next_is_captured_in_the_hour_before_the_deadline():
    work = plan_work([], [GW6], EMPTY, now=datetime(2026, 10, 1, tzinfo=UTC))
    [task] = work.pending
    assert (task.kind, task.gameweek, task.due_at) == ("fpl-deadline", 6, GW6.deadline - timedelta(hours=1))
    done = replace(EMPTY, fpl_ep_next=frozenset({6}))
    assert plan_work([], [GW6], done, now=datetime(2026, 10, 1, tzinfo=UTC)).pending == ()


def test_a_deadline_passed_without_ep_next_is_missed():
    index = replace(EMPTY, genesis_at="2026-10-01T00:00:00Z")
    work = plan_work([], [GW6], index, now=GW6.deadline + timedelta(minutes=1))
    assert [(t.kind, t.gameweek) for t in work.missed] == [("fpl-deadline", 6)]


def test_status_form_uses_z_timestamps_as_the_worker_contract_requires():
    work = plan_work([FIXTURE], [GW6], EMPTY, now=datetime(2026, 10, 1, tzinfo=UTC))
    capture = task_to_status(work.pending[0])
    assert capture == {
        "kind": "capture",
        "due_at": "2026-10-03T11:30:00Z",
        "match_id": MATCH,
        "horizon": "T-7d",
        "kickoff": "2026-10-10T11:30:00Z",
    }
    deadline = task_to_status(next(t for t in work.pending if t.kind == "fpl-deadline"))
    assert deadline == {"kind": "fpl-deadline", "due_at": "2026-10-10T09:00:00Z", "gameweek": 6}
