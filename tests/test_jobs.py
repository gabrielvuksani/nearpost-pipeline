import hashlib
import json
from datetime import timedelta

import pytest

from nearpost.jobs.runner import RunFailedError, run
from nearpost.ledger.repo import LedgerRepo
from tests.factories import fpl_fixture
from tests.harness import KICKOFF, MATCH, World, context


def _forecasts(ctx):
    return [e.body for e in LedgerRepo(ctx.store).read_all() if e.kind == "forecast"]


def _status(ctx):
    return json.loads(ctx.store.get("state/status.json").data)


def test_a_tick_inside_the_t24h_window_records_every_model(tmp_path):
    world = World(now=KICKOFF - timedelta(hours=20))
    ctx = context(world, tmp_path)

    outcome = run("tick", ctx)

    bodies = _forecasts(ctx)
    assert sorted(b["model"] for b in bodies) == ["dixon-coles-v1", "elo-v1", "market-fdco-v1", "market-oddsapi-v1"]
    assert {b["horizon"] for b in bodies} == {"T-24h"}
    assert all(b["probs"] is not None and abs(sum(b["probs"]) - 1) < 1e-5 for b in bodies)
    odds = next(b for b in bodies if b["model"] == "market-oddsapi-v1")
    assert odds["meta"]["n_books"] == 2
    assert outcome.problems == ()
    status = _status(ctx)
    assert status["schema"] == 1
    assert "T-24h" not in [t.get("horizon") for t in status["tasks"]]
    assert status["odds_api"]["credits_remaining"] == 450
    assert status["last_success"]["tick"] == "2026-10-09T15:30:00Z"


def test_the_archived_snapshots_never_contain_the_api_key(tmp_path):
    world = World(now=KICKOFF - timedelta(hours=20))
    ctx = context(world, tmp_path)
    run("tick", ctx)
    for key in ctx.store.list_keys("snapshots/"):
        assert b"test-key-123" not in ctx.store.get(key).data


def test_a_second_tick_in_the_same_window_adds_nothing_and_spends_no_credit(tmp_path):
    world = World(now=KICKOFF - timedelta(hours=20))
    ctx = context(world, tmp_path)
    run("tick", ctx)
    world.requests.clear()
    world.now += timedelta(minutes=5)

    outcome = run("tick", ctx)

    assert outcome.appended == 0
    assert not [r for r in world.requests if "the-odds-api" in r]


def test_an_odds_api_outage_records_everything_else_and_fails_loudly(tmp_path):
    world = World(now=KICKOFF - timedelta(hours=20), odds_status=500)
    ctx = context(world, tmp_path)

    with pytest.raises(RunFailedError) as failure:
        run("tick", ctx)

    assert "odds-api" in "\n".join(failure.value.problems)
    models = sorted(b["model"] for b in _forecasts(ctx))
    assert models == ["dixon-coles-v1", "elo-v1", "market-fdco-v1"]
    [pending] = [t for t in _status(ctx)["tasks"] if t.get("horizon") == "T-24h"]
    assert pending["match_id"] == MATCH  # left pending, so the Worker retries it


def test_a_match_the_market_does_not_list_is_recorded_as_unavailable(tmp_path):
    world = World(now=KICKOFF - timedelta(hours=20), odds_events=[])
    ctx = context(world, tmp_path)
    run("tick", ctx)
    odds = next(b for b in _forecasts(ctx) if b["model"] == "market-oddsapi-v1")
    assert odds["probs"] is None
    assert odds["unavailable_reason"] == "The Odds API did not list this match"


def test_the_closing_capture_only_calls_the_market(tmp_path):
    world = World(now=KICKOFF - timedelta(minutes=10))
    ctx = context(world, tmp_path)
    run("tick", ctx)
    assert [(b["horizon"], b["model"]) for b in _forecasts(ctx)] == [("T-15m", "market-oddsapi-v1")]
    assert not [r for r in world.requests if "mmz4281" in r]  # no model fitting needed


def test_settlement_scores_all_forecasts_after_full_time(tmp_path):
    world = World(now=KICKOFF - timedelta(hours=20))
    ctx = context(world, tmp_path)
    run("tick", ctx)
    world.now = KICKOFF - timedelta(minutes=10)
    run("tick", ctx)

    world.now = KICKOFF + timedelta(hours=2, minutes=20)
    world.fixtures = [fpl_fixture(51, 6, "2026-10-10T11:30:00Z", 1, 6, finished=True, home_goals=2, away_goals=0)]
    run("tick", ctx)

    [settlement] = [e.body for e in LedgerRepo(ctx.store).read_all() if e.kind == "settlement"]
    assert (settlement["home_goals"], settlement["away_goals"], settlement["outcome"]) == (2, 0, "home")
    assert len(settlement["scores"]) == 5
    assert not [t for t in _status(ctx)["tasks"] if t["kind"] == "settle"]


def test_an_unfinished_match_stays_pending_for_settlement(tmp_path):
    world = World(now=KICKOFF - timedelta(hours=20))
    ctx = context(world, tmp_path)
    run("tick", ctx)
    world.now = KICKOFF + timedelta(hours=2, minutes=20)
    run("tick", ctx)
    assert [t["kind"] for t in _status(ctx)["tasks"]] == ["settle"]


def test_ep_next_is_frozen_into_the_ledger_before_the_deadline(tmp_path):
    world = World(now=KICKOFF - timedelta(hours=2), fixtures=[])  # GW6 deadline is 10:00, task due 09:00
    ctx = context(world, tmp_path)
    run("tick", ctx)
    [entry] = [e.body for e in LedgerRepo(ctx.store).read_all() if e.kind == "fpl-ep-next"]
    assert entry["gameweek"] == 6
    assert entry["n_players"] == 3
    table = ctx.store.get(entry["table"]["key"])
    assert hashlib.sha256(table.data).hexdigest() == entry["table"]["sha256"]
    assert entry["table"]["sha256"] != entry["source"]["sha256"]


def test_a_forecast_is_never_written_after_kickoff_even_if_the_run_is_late(tmp_path):
    world = World(now=KICKOFF + timedelta(minutes=1))
    ctx = context(world, tmp_path)
    run("tick", ctx)
    assert _forecasts(ctx) == []


def test_daily_benchmarks_settled_matches_verifies_the_chain_and_publishes_a_scoreboard(tmp_path):
    world = World(now=KICKOFF - timedelta(hours=20))
    ctx = context(world, tmp_path)
    run("tick", ctx)
    world.now = KICKOFF - timedelta(minutes=10)
    run("tick", ctx)
    world.now = KICKOFF + timedelta(hours=2, minutes=20)
    world.fixtures = [fpl_fixture(51, 6, "2026-10-10T11:30:00Z", 1, 6, finished=True, home_goals=2, away_goals=0)]
    run("tick", ctx)

    world.now = KICKOFF + timedelta(days=4)
    world.current_e0_rows = [
        "E0,10/10/2026,12:30,Arsenal,Chelsea,2,0,H,1.9,0.7,1.85,3.7,4.4,1.8,3.8,4.6,1.83,3.9,4.9,1.9,1.95"
    ]
    outcome = run("daily", ctx)

    kinds = [e.kind for e in LedgerRepo(ctx.store).read_all()]
    assert "benchmark" in kinds
    board = json.loads(ctx.store.get("derived/scoreboard.json").data)
    assert board["matches_settled"] == 1
    assert board["tracks"]["elo-v1"]["T-24h"]["vs_our_close"]["n"] == 1
    assert board["closes"]["football-data-avg"]["n"] == 1
    assert _status(ctx)["last_success"]["daily"] == "2026-10-14T11:30:00Z"
    assert outcome.head_hash == LedgerRepo(ctx.store).load_index().head_hash


def test_daily_refuses_to_continue_on_a_tampered_ledger(tmp_path):
    world = World(now=KICKOFF - timedelta(hours=20))
    ctx = context(world, tmp_path)
    run("tick", ctx)
    world.now = KICKOFF + timedelta(hours=2, minutes=20)
    world.fixtures = [fpl_fixture(51, 6, "2026-10-10T11:30:00Z", 1, 6, finished=True, home_goals=2, away_goals=0)]
    run("tick", ctx)  # settled, so daily would now append a benchmark
    key = "ledger/blocks/000000.json"
    block = json.loads(ctx.store.get(key).data)
    block["entries"][0]["body"]["probs"] = [0.9, 0.05, 0.05]
    ctx.store.put(key, json.dumps(block).encode())

    world.now = KICKOFF + timedelta(days=4)
    world.current_e0_rows = [
        "E0,10/10/2026,12:30,Arsenal,Chelsea,2,0,H,1.9,0.7,1.85,3.7,4.4,1.8,3.8,4.6,1.83,3.9,4.9,1.9,1.95"
    ]
    blocks_before = ctx.store.list_keys("ledger/blocks/")
    with pytest.raises(Exception, match="hash"):
        run("daily", ctx)
    assert ctx.store.list_keys("ledger/blocks/") == blocks_before  # verified before appending anything


def test_a_same_day_earlier_result_does_not_knock_out_the_baselines(tmp_path):
    early = fpl_fixture(50, 6, "2026-10-10T09:00:00Z", 9, 10, finished=True, home_goals=1, away_goals=1)
    world = World(now=KICKOFF - timedelta(minutes=50))  # T-1h window, after the 09:00 match finished
    world.fixtures = [early, fpl_fixture(51, 6, "2026-10-10T11:30:00Z", 1, 6)]
    ctx = context(world, tmp_path)

    outcome = run("tick", ctx)

    models = sorted(b["model"] for b in _forecasts(ctx) if b["horizon"] == "T-1h")
    assert models == ["dixon-coles-v1", "elo-v1", "market-fdco-v1", "market-oddsapi-v1"]
    assert outcome.problems == ()


def test_an_unparseable_odds_payload_is_recorded_once_instead_of_burning_credits_on_retries(tmp_path):
    world = World(now=KICKOFF - timedelta(hours=20))
    world.odds_events = [{"broken": True}]
    ctx = context(world, tmp_path)

    with pytest.raises(RunFailedError) as failure:
        run("tick", ctx)
    assert "odds-api" in "\n".join(failure.value.problems)
    odds = next(b for b in _forecasts(ctx) if b["model"] == "market-oddsapi-v1")
    assert odds["probs"] is None and "unparseable" in odds["unavailable_reason"]

    world.requests.clear()
    world.now += timedelta(minutes=30)
    run("tick", ctx)  # the retry the Worker would send
    assert not [r for r in world.requests if "the-odds-api" in r]
