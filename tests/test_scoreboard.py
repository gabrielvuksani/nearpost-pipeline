import pytest

from nearpost.ledger.chain import make_entry
from nearpost.scoreboard import build_scoreboard

T = "2026-10-11T00:00:00Z"


def _entries(specs):
    entries, previous = [], None
    for kind, body in specs:
        previous = make_entry(previous, kind, body, T)
        entries.append(previous)
    return entries


def _score(model, horizon, rps, log_loss=1.0, brier=0.5):
    return {"forecast": "h", "model": model, "horizon": horizon, "rps": rps, "log_loss": log_loss, "brier": brier}


def test_scoreboard_averages_each_model_and_horizon():
    entries = _entries(
        [
            ("settlement", {"match_id": "m1", "scores": [_score("elo-v1", "T-24h", 0.2)]}),
            ("settlement", {"match_id": "m2", "scores": [_score("elo-v1", "T-24h", 0.4)]}),
        ]
    )
    board = build_scoreboard(entries, generated_at=T)
    row = board["tracks"]["elo-v1"]["T-24h"]
    assert row["n"] == 2
    assert row["rps"] == pytest.approx(0.3)


def test_scoreboard_pairs_models_with_our_closing_line_match_by_match():
    entries = _entries(
        [
            (
                "settlement",
                {
                    "match_id": "m1",
                    "scores": [
                        _score("elo-v1", "T-24h", 0.25, log_loss=1.1),
                        _score("market-oddsapi-v1", "T-15m", 0.20, log_loss=1.0),
                    ],
                },
            ),
            ("settlement", {"match_id": "m2", "scores": [_score("elo-v1", "T-24h", 0.1)]}),
        ]
    )
    board = build_scoreboard(entries, generated_at=T)
    versus = board["tracks"]["elo-v1"]["T-24h"]["vs_our_close"]
    assert versus["n"] == 1  # m2 had no closing capture, so it can't be paired
    assert versus["rps"] == pytest.approx(0.05)
    assert versus["log_loss"] == pytest.approx(0.1)


def test_scoreboard_pairs_with_football_data_closing_lines_from_benchmarks():
    entries = _entries(
        [
            ("settlement", {"match_id": "m1", "scores": [_score("elo-v1", "T-24h", 0.25)]}),
            (
                "benchmark",
                {
                    "match_id": "m1",
                    "closes": {"football-data-avg": {"scores": {"rps": 0.15, "log_loss": 0.9, "brier": 0.4}}},
                },
            ),
        ]
    )
    board = build_scoreboard(entries, generated_at=T)
    assert board["tracks"]["elo-v1"]["T-24h"]["vs_football_data_close"]["rps"] == pytest.approx(0.10)
    assert board["closes"]["football-data-avg"]["n"] == 1


def test_empty_ledger_gives_an_empty_scoreboard():
    board = build_scoreboard([], generated_at=T)
    assert board == {"generated_at": T, "matches_settled": 0, "tracks": {}, "closes": {}}
