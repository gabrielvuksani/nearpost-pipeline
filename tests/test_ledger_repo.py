import json

import pytest

from nearpost.ledger.chain import ChainError
from nearpost.ledger.repo import ConcurrentWriteError, LedgerRepo, forecast_key
from nearpost.store.local import LocalStore

T0 = "2026-10-03T11:30:00Z"
T1 = "2026-10-09T11:30:00Z"


KO = "2026-10-10T11:30:00Z"


def _forecast(match="2026-27:arsenal-v-chelsea", horizon="T-7d", model="elo-v1"):
    return ("forecast", {"match_id": match, "kickoff": KO, "horizon": horizon, "model": model})


@pytest.fixture
def store(tmp_path):
    return LocalStore(tmp_path)


def test_empty_ledger_has_no_head(store):
    index = LedgerRepo(store).load_index()
    assert index.last_block == -1
    assert index.head_seq == -1


def test_append_writes_one_immutable_block_and_updates_the_index(store):
    repo = LedgerRepo(store)
    index = repo.append([_forecast(), _forecast(model="dixon-coles-v1")], recorded_at=T0)

    assert store.list_keys("ledger/blocks/") == ["ledger/blocks/000000.json"]
    assert index.head_seq == 1
    assert forecast_key("2026-27:arsenal-v-chelsea", KO, "T-7d", "elo-v1") in index.forecasts
    assert LedgerRepo(store).load_index() == index


def test_appends_continue_the_same_chain_across_blocks(store):
    repo = LedgerRepo(store)
    repo.append([_forecast()], recorded_at=T0)
    repo.append([_forecast(horizon="T-24h")], recorded_at=T1)

    entries = repo.read_all()
    assert [e.seq for e in entries] == [0, 1]
    assert entries[1].prev_hash == entries[0].hash


def test_appending_nothing_writes_nothing(store):
    repo = LedgerRepo(store)
    repo.append([], recorded_at=T0)
    assert store.list_keys("ledger/") == []


def test_settlement_and_other_kinds_are_indexed(store):
    repo = LedgerRepo(store)
    index = repo.append(
        [
            ("settlement", {"match_id": "m1"}),
            ("benchmark", {"match_id": "m1"}),
            ("fpl-ep-next", {"gameweek": 6}),
            ("fpl-result", {"gameweek": 5}),
        ],
        recorded_at=T0,
    )
    assert index.settled == frozenset({"m1"})
    assert index.benchmarked == frozenset({"m1"})
    assert index.fpl_ep_next == frozenset({6})
    assert index.fpl_results == frozenset({5})


def test_index_heals_when_a_run_died_between_block_and_index_writes(store):
    repo = LedgerRepo(store)
    repo.append([_forecast()], recorded_at=T0)
    stale_index = store.get("ledger/index.json").data
    repo.append([_forecast(horizon="T-24h")], recorded_at=T1)
    store.put("ledger/index.json", stale_index)  # simulate the lost index write

    healed = LedgerRepo(store).load_index()
    assert healed.last_block == 1
    assert forecast_key("2026-27:arsenal-v-chelsea", KO, "T-24h", "elo-v1") in healed.forecasts


def test_a_competing_writer_that_took_the_block_number_first_is_refused(store):
    repo = LedgerRepo(store)
    repo.append([_forecast()], recorded_at=T0)

    class RacingStore:
        """Lets a competitor write block 1 after our read but before our write."""

        def __getattr__(self, name):
            return getattr(store, name)

        def put(self, key, data, **kwargs):
            if key == "ledger/blocks/000001.json" and store.get(key) is None:
                store.put(key, b'{"competitor": true}')
            return store.put(key, data, **kwargs)

    with pytest.raises(ConcurrentWriteError):
        LedgerRepo(RacingStore()).append([_forecast(horizon="T-24h")], recorded_at=T1)
    assert store.get("ledger/blocks/000001.json").data == b'{"competitor": true}'


def test_a_tampered_block_fails_verification(store):
    repo = LedgerRepo(store)
    repo.append([_forecast()], recorded_at=T0)
    repo.append([_forecast(horizon="T-24h")], recorded_at=T1)

    key = "ledger/blocks/000000.json"
    block = json.loads(store.get(key).data)
    block["entries"][0]["body"]["model"] = "someone-else"
    store.put(key, json.dumps(block).encode())

    with pytest.raises(ChainError):
        LedgerRepo(store).read_all()


def test_head_summary_exposes_the_public_anchor(store):
    repo = LedgerRepo(store)
    index = repo.append([_forecast()], recorded_at=T0)
    assert index.head_hash == repo.read_all()[-1].hash


def test_open_forecasts_hold_unsettled_probabilities_until_settlement(store):
    repo = LedgerRepo(store)
    body = {
        "match_id": "m1",
        "kickoff": KO,
        "horizon": "T-24h",
        "model": "elo-v1",
        "probs": [0.5, 0.3, 0.2],
        "over_2_5": None,
        "btts": None,
    }
    index = repo.append([("forecast", body)], recorded_at=T0)
    [open_forecast] = index.open_forecasts["m1"]
    assert open_forecast["probs"] == [0.5, 0.3, 0.2]
    assert open_forecast["kickoff"] == KO
    assert open_forecast["hash"] == repo.read_all()[0].hash

    index = repo.append([("settlement", {"match_id": "m1"})], recorded_at=T1)
    assert "m1" not in index.open_forecasts


def test_unavailable_forecasts_are_indexed_as_done_but_not_left_open(store):
    body = {"match_id": "m1", "kickoff": KO, "horizon": "T-7d", "model": "market-oddsapi-v1", "probs": None}
    index = LedgerRepo(store).append([("forecast", body)], recorded_at=T0)
    assert forecast_key("m1", KO, "T-7d", "market-oddsapi-v1") in index.forecasts
    assert "m1" not in index.open_forecasts


def test_genesis_time_is_the_first_entry_time(store):
    repo = LedgerRepo(store)
    repo.append([_forecast()], recorded_at=T0)
    index = repo.append([_forecast(horizon="T-24h")], recorded_at=T1)
    assert index.genesis_at == T0


def test_append_refuses_entries_planned_against_a_head_that_has_since_moved(store):
    repo = LedgerRepo(store)
    planned_from = repo.append([_forecast()], recorded_at=T0).head_seq
    repo.append([_forecast(horizon="T-24h")], recorded_at=T1)  # another writer got in first
    with pytest.raises(ConcurrentWriteError, match="head moved"):
        repo.append([("settlement", {"match_id": "m1"})], recorded_at=T1, expected_head_seq=planned_from)
    assert len(store.list_keys("ledger/blocks/")) == 2


def test_an_index_whose_head_disagrees_with_the_last_block_is_rejected(store):
    repo = LedgerRepo(store)
    repo.append([_forecast()], recorded_at=T0)
    index = json.loads(store.get("ledger/index.json").data)
    index["head_hash"] = "f" * 64
    store.put("ledger/index.json", json.dumps(index).encode())
    with pytest.raises(ChainError, match="index"):
        LedgerRepo(store).load_index()
