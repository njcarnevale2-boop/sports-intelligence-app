from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.services.result_engine import ResultEnginePersistenceError
from app.services.result_engine.contracts import SourceEventBridgeRecord
from app.services.result_engine.validation import deterministic_bridge_id
from result_engine_test_utils import make_accepted_result, make_identity, make_observation, make_store


def _write_observation(store, observation, *, file_name: str | None = None):
    path = store._observations_dir / (file_name or f"{observation.observation_id}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(observation), sort_keys=True), encoding="utf-8")


def _write_accepted(store, accepted, *, file_name: str | None = None):
    path = store._accepted_dir / (file_name or f"{accepted.result_id}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(accepted), sort_keys=True), encoding="utf-8")


def _bridge(source: str, source_event_id: str, canonical_event_key: str, first_observation_id: str) -> SourceEventBridgeRecord:
    draft = SourceEventBridgeRecord(
        bridge_id="",
        source=source,
        source_event_id=source_event_id,
        canonical_event_key=canonical_event_key,
        created_at_utc="2026-09-10T05:00:00Z",
        first_observation_id=first_observation_id,
    )
    return replace(draft, bridge_id=deterministic_bridge_id(draft))


def test_same_observation_twice_produces_one_authority(tmp_path):
    store = make_store(tmp_path)
    obs = make_observation()

    first = store.persist_observation(obs)
    second = store.persist_observation(obs)

    assert first == second
    assert len(store.list_observations()) == 1


def test_same_observation_id_different_payload_fails(tmp_path):
    store = make_store(tmp_path)
    obs = make_observation()
    store.persist_observation(obs)

    conflict = replace(obs, payload_hash="0" * 64)
    with pytest.raises(ResultEnginePersistenceError):
        store.persist_observation(conflict)


def test_same_source_observation_replay_with_new_local_observed_time_is_idempotent(tmp_path):
    store = make_store(tmp_path)
    original = make_observation(
        source_observation_id="provider-1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )
    replay = make_observation(
        source_observation_id="provider-1",
        observed_at_utc="2026-09-10T05:02:00Z",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )

    first = store.persist_observation(original)
    second = store.persist_observation(replay)

    assert first.observation_id == second.observation_id
    assert first.observed_at_utc == "2026-09-10T05:00:00Z"
    assert len(store.list_observations()) == 1


def test_same_accepted_result_twice_produces_one_authority(tmp_path):
    store = make_store(tmp_path)
    accepted = make_accepted_result()

    first = store.persist_accepted_result(accepted)
    second = store.persist_accepted_result(accepted)

    assert first == second
    assert len(store.list_accepted_results()) == 1


def test_same_result_id_different_payload_fails(tmp_path):
    store = make_store(tmp_path)
    accepted = make_accepted_result()
    store.persist_accepted_result(accepted)

    conflict = replace(accepted, home_score=31)
    with pytest.raises(ResultEnginePersistenceError):
        store.persist_accepted_result(conflict)


def test_duplicate_valid_observation_artifacts_fail_closed(tmp_path):
    store = make_store(tmp_path)
    obs = make_observation()
    _write_observation(store, obs, file_name="one.json")
    _write_observation(store, obs, file_name="two.json")

    with pytest.raises(ResultEnginePersistenceError, match="filename mismatch|Duplicate observation authority"):
        store.list_observations()


def test_duplicate_valid_accepted_artifacts_fail_closed(tmp_path):
    store = make_store(tmp_path)
    a = make_accepted_result(source="provider_a", source_event_id="event1")
    b = make_accepted_result(source="provider_b", source_event_id="event9")
    _write_accepted(store, a)
    _write_accepted(store, b)

    with pytest.raises(ResultEnginePersistenceError, match="Duplicate accepted authority"):
        store.list_accepted_results()


def test_manual_second_valid_looking_accepted_authority_fails_closed(tmp_path):
    store = make_store(tmp_path)
    accepted = make_accepted_result(source="provider_a", source_event_id="event1")
    store.persist_accepted_result(accepted)

    forged = make_accepted_result(source="provider_b", source_event_id="event77")
    forged_payload = asdict(forged)
    forged_payload["canonical_event_key"] = accepted.canonical_event_key
    forged_path = store._accepted_dir / "res-manual-competing.json"
    forged_path.write_text(json.dumps(forged_payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(ResultEnginePersistenceError, match="filename mismatch|Duplicate accepted authority"):
        store.list_accepted_results()


def test_missing_indexes_are_rebuilt_safely(tmp_path):
    store = make_store(tmp_path)
    obs = make_observation()
    accepted = make_accepted_result()
    bridge = _bridge("provider_a", "event1", make_identity().canonical_event_key, obs.observation_id)

    store.persist_observation(obs)
    store.persist_accepted_result(accepted)
    store.persist_source_event_bridge(bridge)

    store._observation_id_index.unlink()
    store._accepted_event_index.unlink()
    store._bridge_index.unlink()

    assert len(store.list_observations()) == 1
    assert len(store.list_accepted_results()) == 1
    assert len(store.list_source_event_bridges()) == 1


def test_stale_indexes_are_rebuilt_from_authority(tmp_path):
    store = make_store(tmp_path)
    obs = make_observation()
    accepted = make_accepted_result()

    store.persist_observation(obs)
    store.persist_accepted_result(accepted)

    store._observation_id_index.write_text(json.dumps({"stale": "data"}), encoding="utf-8")
    store._accepted_event_index.write_text(json.dumps({"stale": "data"}), encoding="utf-8")

    assert len(store.list_observations()) == 1
    assert len(store.list_accepted_results()) == 1


def test_corrupt_indexes_are_rebuilt_from_authority(tmp_path):
    store = make_store(tmp_path)
    obs = make_observation()
    store.persist_observation(obs)

    store._observation_id_index.write_text("{", encoding="utf-8")

    assert len(store.list_observations()) == 1


def test_corrupt_authoritative_json_fails_closed(tmp_path):
    store = make_store(tmp_path)
    obs = make_observation()
    store.persist_observation(obs)

    path = store._observations_dir / f"{obs.observation_id}.json"
    path.write_text('{"bad":true}', encoding="utf-8")

    with pytest.raises(ResultEnginePersistenceError):
        store.list_observations()


def test_bad_payload_hash_fails_closed(tmp_path):
    store = make_store(tmp_path)
    obs = make_observation()
    bad = replace(obs, payload_hash="f" * 64)
    payload = asdict(bad)
    path = store._observations_dir / f"{bad.observation_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(ResultEnginePersistenceError, match="payload hash mismatch"):
        store.list_observations()


def test_truncated_authoritative_artifact_fails_closed(tmp_path):
    store = make_store(tmp_path)
    obs = make_observation()
    store.persist_observation(obs)

    path = store._observations_dir / f"{obs.observation_id}.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(ResultEnginePersistenceError, match="Corrupt JSON"):
        store.list_observations()


@pytest.mark.parametrize("bad_identifier", [".", "..", "../escape", "a/b", "a\\b", "/abs"])
def test_path_traversal_and_special_identifiers_fail(tmp_path, bad_identifier: str):
    store = make_store(tmp_path)

    with pytest.raises(ResultEnginePersistenceError, match="unsupported characters"):
        store._observation_path(bad_identifier)
    with pytest.raises(ResultEnginePersistenceError, match="unsupported characters"):
        store._accepted_path(bad_identifier)
    with pytest.raises(ResultEnginePersistenceError, match="unsupported characters"):
        store._bridge_path(bad_identifier)


def test_concurrent_identical_writes_create_one_authority(tmp_path):
    store = make_store(tmp_path)
    obs = make_observation()

    def worker():
        return store.persist_observation(obs)

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(lambda _: worker(), range(12)))

    assert all(row.observation_id == obs.observation_id for row in rows)
    assert len(store.list_observations()) == 1


def test_concurrent_conflicting_bridge_writes_allow_one_and_fail_one(tmp_path):
    store = make_store(tmp_path)
    identity_a = make_identity().canonical_event_key
    identity_b = make_identity(away_team="BUF", home_team="MIA").canonical_event_key
    bridge_a = _bridge("provider_a", "event1", identity_a, "obs-a")
    bridge_b = _bridge("provider_a", "event1", identity_b, "obs-b")

    outcomes: list[str] = []

    def worker(record):
        try:
            store.persist_source_event_bridge(record)
            outcomes.append("ok")
        except ResultEnginePersistenceError:
            outcomes.append("fail")

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker, [bridge_a, bridge_b]))

    assert outcomes.count("ok") == 1
    assert outcomes.count("fail") == 1
    assert len(store.list_source_event_bridges()) == 1


def test_conflicting_source_observation_authority_on_disk_fails_closed(tmp_path):
    store = make_store(tmp_path)
    one = make_observation(source_observation_id="provider-1", source_result_version="v1")
    two = make_observation(source_observation_id="provider-1", source_result_version="v2")

    _write_observation(store, one)
    _write_observation(store, two, file_name=f"{two.observation_id}.json")

    with pytest.raises(ResultEnginePersistenceError, match="Ambiguous source observation authority"):
        store.list_observations()


def test_correction_candidate_global_reads_still_validate_authority(tmp_path):
    store = make_store(tmp_path)
    accepted = make_accepted_result()
    store.persist_accepted_result(accepted)

    # Corrupt accepted authority; correction reads must still fail-closed.
    accepted_path = store._accepted_dir / f"{accepted.result_id}.json"
    accepted_path.write_text("{", encoding="utf-8")

    with pytest.raises(ResultEnginePersistenceError, match="Corrupt JSON"):
        store.list_correction_candidates()


def test_root_dir_temp_path_writes_only_beneath_tmp_path(tmp_path):
    store = make_store(tmp_path)
    obs = make_observation()
    store.persist_observation(obs)

    assert str(store.root_dir).startswith(str(tmp_path.resolve()))
    assert str(store.root_dir).startswith("/data") is False
    assert (store.root_dir / "observations" / f"{obs.observation_id}.json").exists()
