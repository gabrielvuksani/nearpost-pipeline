from datetime import UTC, date, datetime, timedelta

import pytest

from nearpost.domain import Fixture, MarketQuote, MatchResult
from nearpost.forecast import Forecast
from nearpost.records.benchmarks import build_benchmark
from nearpost.records.forecasts import ModelSource, Skipped, Unavailable, build_forecasts, drop_late
from nearpost.records.settlements import build_settlement
from nearpost.tasks import Task

KICKOFF = datetime(2026, 10, 10, 11, 30, tzinfo=UTC)
FIXTURE = Fixture("2026-27:arsenal-v-chelsea", "2026-27", 51, 6, KICKOFF, "arsenal", "chelsea", False, None, None)
TASK = Task(
    "capture",
    KICKOFF - timedelta(hours=24),
    KICKOFF - timedelta(hours=1),
    FIXTURE.match_id,
    "T-24h",
    KICKOFF,
    6,
    ("elo-v1", "market-oddsapi-v1"),
)
NOW = KICKOFF - timedelta(hours=20)
REF = {"key": "snapshots/odds-api/2026/10/09/153000Z-abc.json.gz", "sha256": "ab" * 32}


def _sources(**overrides):
    sources = {
        "elo-v1": ModelSource("elo-v1", lambda f: Forecast((0.5, 0.3, 0.2)), inputs=(REF,), meta={"k": 20}),
        "market-oddsapi-v1": ModelSource(
            "market-oddsapi-v1", lambda f: Forecast((0.45, 0.28, 0.27), over_2_5=0.55, n_books=12), inputs=(REF,)
        ),
    }
    return {**sources, **overrides}


def test_each_missing_model_gets_one_forecast_entry():
    entries = build_forecasts([TASK], {FIXTURE.match_id: FIXTURE}, _sources(), now=NOW).entries
    assert [kind for kind, _ in entries] == ["forecast", "forecast"]
    elo = entries[0][1]
    assert elo["model"] == "elo-v1"
    assert elo["horizon"] == "T-24h"
    assert elo["probs"] == [0.5, 0.3, 0.2]
    assert elo["issued_at"] == "2026-10-09T15:30:00Z"
    assert elo["kickoff"] == "2026-10-10T11:30:00Z"
    assert elo["inputs"] == [REF]
    assert elo["meta"] == {"k": 20}
    assert elo["unavailable_reason"] is None
    market = entries[1][1]
    assert market["over_2_5"] == 0.55
    assert market["meta"] == {"n_books": 12}


def test_probabilities_are_rounded_so_hashes_are_stable():
    source = ModelSource("elo-v1", lambda f: Forecast((1 / 3, 1 / 3, 1 / 3)), inputs=())
    batch = build_forecasts([TASK], {FIXTURE.match_id: FIXTURE}, _sources(**{"elo-v1": source}), now=NOW)
    body = batch.entries[0][1]
    assert body["probs"] == [0.333333, 0.333333, 0.333333]


def test_an_unavailable_model_is_recorded_as_such_with_its_reason():
    down = ModelSource("market-oddsapi-v1", lambda f: Unavailable("The Odds API returned 401"), inputs=())
    batch = build_forecasts([TASK], {FIXTURE.match_id: FIXTURE}, _sources(**{"market-oddsapi-v1": down}), now=NOW)
    body = batch.entries[1][1]
    assert body["probs"] is None
    assert body["unavailable_reason"] == "The Odds API returned 401"


def test_a_model_without_a_source_this_run_is_skipped_and_left_pending():
    sources = _sources()
    del sources["market-oddsapi-v1"]
    batch = build_forecasts([TASK], {FIXTURE.match_id: FIXTURE}, sources, now=NOW)
    assert [body["model"] for _, body in batch.entries] == ["elo-v1"]
    assert batch.skipped == ("2026-27:arsenal-v-chelsea T-24h market-oddsapi-v1: no source this run",)


def test_a_skipped_prediction_writes_nothing_and_reports_why():
    failing = ModelSource("elo-v1", lambda f: Skipped("no rating for coventry-city"), inputs=())
    batch = build_forecasts([TASK], {FIXTURE.match_id: FIXTURE}, _sources(**{"elo-v1": failing}), now=NOW)
    assert [body["model"] for _, body in batch.entries] == ["market-oddsapi-v1"]
    assert batch.skipped == ("2026-27:arsenal-v-chelsea T-24h elo-v1: no rating for coventry-city",)


@pytest.mark.parametrize("late", [KICKOFF, KICKOFF + timedelta(seconds=1)])
def test_a_forecast_at_or_after_kickoff_is_skipped_not_written(late):
    batch = build_forecasts([TASK], {FIXTURE.match_id: FIXTURE}, _sources(), now=late)
    assert batch.entries == ()
    assert all("window closed" in s for s in batch.skipped)


def test_a_forecast_built_after_its_window_closed_is_skipped_so_the_label_stays_honest():
    after_window = TASK.window_end + timedelta(seconds=1)  # still before kickoff, but past T-24h's window
    batch = build_forecasts([TASK], {FIXTURE.match_id: FIXTURE}, _sources(), now=after_window)
    assert batch.entries == ()
    assert len(batch.skipped) == 2


def test_a_kickoff_moved_earlier_than_the_task_knew_is_caught_from_the_fresh_fixture():
    moved = Fixture(**{**FIXTURE.__dict__, "kickoff": NOW - timedelta(minutes=1)})
    batch = build_forecasts([TASK], {FIXTURE.match_id: moved}, _sources(), now=NOW)
    assert batch.entries == ()


def test_forecasts_that_would_land_after_kickoff_are_dropped_before_the_append():
    entries = build_forecasts([TASK], {FIXTURE.match_id: FIXTURE}, _sources(), now=NOW).entries
    kept, dropped = drop_late(entries, recorded_at=KICKOFF)
    assert kept == ()
    assert len(dropped) == 2
    kept, dropped = drop_late(entries, recorded_at=KICKOFF - timedelta(seconds=1))
    assert kept == entries and dropped == ()


OPEN = (
    {
        "hash": "h1",
        "model": "elo-v1",
        "horizon": "T-24h",
        "kickoff": "2026-10-10T11:30:00Z",
        "probs": [0.5, 0.3, 0.2],
        "over_2_5": None,
        "btts": None,
    },
    {
        "hash": "h2",
        "model": "dixon-coles-v1",
        "horizon": "T-24h",
        "kickoff": "2026-10-10T11:30:00Z",
        "probs": [0.2, 0.3, 0.5],
        "over_2_5": 0.6,
        "btts": 0.5,
    },
)


def test_settlement_scores_every_open_forecast_against_the_result():
    played = Fixture(**{**FIXTURE.__dict__, "finished": True, "home_goals": 2, "away_goals": 1})
    body = build_settlement(played, OPEN, settled_at=KICKOFF + timedelta(hours=3), source=REF)
    assert (body["home_goals"], body["away_goals"], body["outcome"]) == (2, 1, "home")
    elo, dc = body["scores"]
    assert elo["forecast"] == "h1"
    assert elo["rps"] == pytest.approx(0.145)
    assert elo["over_2_5"] is None
    assert dc["over_2_5"]["brier"] == pytest.approx(0.16)
    assert dc["btts"]["brier"] == pytest.approx(0.25)
    assert body["source"] == REF


def test_forecasts_for_a_kickoff_that_never_happened_are_voided_not_scored():
    stale = {**OPEN[0], "hash": "h0", "kickoff": "2026-08-30T14:00:00Z"}  # before a postponement
    played = Fixture(**{**FIXTURE.__dict__, "finished": True, "home_goals": 2, "away_goals": 1})
    body = build_settlement(played, (stale, *OPEN), settled_at=KICKOFF + timedelta(hours=3), source=REF)
    assert [s["forecast"] for s in body["scores"]] == ["h1", "h2"]
    assert body["void"] == [
        {
            "forecast": "h0",
            "model": "elo-v1",
            "horizon": "T-24h",
            "kickoff": "2026-08-30T14:00:00Z",
            "reason": "made for a kickoff that did not happen (moved to 2026-10-10T11:30:00Z)",
        }
    ]


def test_settling_an_unfinished_match_is_refused():
    with pytest.raises(ValueError, match="not finished"):
        build_settlement(FIXTURE, OPEN, settled_at=KICKOFF, source=REF)


def test_benchmark_scores_the_average_and_exchange_closing_lines():
    quote = MarketQuote(avg_1x2=(1.8, 3.8, 4.5), exchange_1x2=(1.85, 3.9, 4.8), avg_over_under_2_5=(1.9, 1.95))
    result = MatchResult("E0", date(2026, 10, 10), "arsenal", "chelsea", 0, 0)
    body = build_benchmark(FIXTURE.match_id, quote, result, source=REF)
    assert body["outcome"] == "draw"
    assert set(body["closes"]) == {"football-data-avg", "football-data-exchange"}
    avg = body["closes"]["football-data-avg"]
    assert sum(avg["probs"]) == pytest.approx(1.0, abs=1e-5)
    assert avg["scores"]["rps"] > 0
    assert 0 < avg["over_2_5"] < 1
    assert avg["over_2_5_scores"]["log_loss"] > 0


def test_benchmark_without_any_closing_line_is_none():
    result = MatchResult("E0", date(2026, 10, 10), "arsenal", "chelsea", 0, 0)
    assert build_benchmark(FIXTURE.match_id, MarketQuote(None, None, None), result, source=REF) is None
