from __future__ import annotations

import os
import sys
from dataclasses import replace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.services.result_engine import ResultEnginePersistenceError
from app.services.result_engine.contracts import SourceEventBridgeRecord
from app.services.result_engine.validation import deterministic_bridge_id
from result_engine_test_utils import make_engine, make_identity, make_observation, make_store


def _bridge(*, source: str, source_event_id: str, canonical_event_key: str, first_observation_id: str = "obs-1") -> SourceEventBridgeRecord:
    draft = SourceEventBridgeRecord(
        bridge_id="",
        source=source,
        source_event_id=source_event_id,
        canonical_event_key=canonical_event_key,
        created_at_utc="2026-09-10T05:00:00Z",
        first_observation_id=first_observation_id,
    )
    return replace(draft, bridge_id=deterministic_bridge_id(draft))


def test_provider_a_event1_to_canonical_x_succeeds(tmp_path):
    store = make_store(tmp_path)
    identity = make_identity()
    record = _bridge(source="provider_a", source_event_id="event1", canonical_event_key=identity.canonical_event_key)

    persisted = store.persist_source_event_bridge(record)

    assert persisted.canonical_event_key == identity.canonical_event_key


def test_same_mapping_is_idempotent(tmp_path):
    store = make_store(tmp_path)
    identity = make_identity()
    one = _bridge(source="provider_a", source_event_id="event1", canonical_event_key=identity.canonical_event_key)
    two = _bridge(source="provider_a", source_event_id="event1", canonical_event_key=identity.canonical_event_key, first_observation_id="obs-2")

    first = store.persist_source_event_bridge(one)
    second = store.persist_source_event_bridge(two)

    assert first.bridge_id == second.bridge_id
    assert len(store.list_source_event_bridges()) == 1


def test_same_source_event_to_different_canonical_fails(tmp_path):
    store = make_store(tmp_path)
    x = make_identity().canonical_event_key
    y = make_identity(away_team="BUF", home_team="MIA").canonical_event_key

    store.persist_source_event_bridge(_bridge(source="provider_a", source_event_id="event1", canonical_event_key=x))

    with pytest.raises(ResultEnginePersistenceError, match="Source event bridge conflict"):
        store.persist_source_event_bridge(_bridge(source="provider_a", source_event_id="event1", canonical_event_key=y))


def test_provider_b_event77_to_same_canonical_is_allowed(tmp_path):
    store = make_store(tmp_path)
    identity = make_identity().canonical_event_key

    store.persist_source_event_bridge(_bridge(source="provider_a", source_event_id="event1", canonical_event_key=identity))
    store.persist_source_event_bridge(_bridge(source="provider_b", source_event_id="event77", canonical_event_key=identity))

    assert len(store.list_source_event_bridges()) == 2


@pytest.mark.parametrize("bad_source", ["", ".", "..", "provider/a"])
def test_malformed_source_fails(tmp_path, bad_source: str):
    store = make_store(tmp_path)
    identity = make_identity().canonical_event_key

    with pytest.raises(ResultEnginePersistenceError):
        store.persist_source_event_bridge(_bridge(source=bad_source, source_event_id="event1", canonical_event_key=identity))


@pytest.mark.parametrize("bad_source_event_id", ["", ".", "..", "../escape"])
def test_malformed_source_event_id_fails(tmp_path, bad_source_event_id: str):
    store = make_store(tmp_path)
    identity = make_identity().canonical_event_key

    with pytest.raises(ResultEnginePersistenceError):
        store.persist_source_event_bridge(_bridge(source="provider_a", source_event_id=bad_source_event_id, canonical_event_key=identity))


def test_ambiguous_mapping_state_on_disk_fails_closed(tmp_path):
    store = make_store(tmp_path)
    identity_x = make_identity().canonical_event_key
    identity_y = make_identity(away_team="BUF", home_team="MIA").canonical_event_key
    bridge = _bridge(source="provider_a", source_event_id="event1", canonical_event_key=identity_x)

    store.persist_source_event_bridge(bridge)

    # Inject a second bridge artifact with same source+event but conflicting canonical target.
    injected = replace(bridge, canonical_event_key=identity_y)
    injected_path = store._bridge_dir / "bridge-manual-conflict.json"
    injected_path.write_text(
        "{" +
        f'"bridge_id":"bridge-manual-conflict",' +
        f'"source":"{injected.source}",' +
        f'"source_event_id":"{injected.source_event_id}",' +
        f'"canonical_event_key":"{injected.canonical_event_key}",' +
        f'"created_at_utc":"{injected.created_at_utc}",' +
        f'"first_observation_id":"{injected.first_observation_id}"' +
        "}",
        encoding="utf-8",
    )

    with pytest.raises(ResultEnginePersistenceError, match="Bridge id mismatch|Ambiguous source-event bridge authority"):
        store.list_source_event_bridges()


def test_engine_ingest_creates_bridge_without_provider_calls(tmp_path):
    engine = make_engine(tmp_path, min_seconds=60)
    observation = make_observation(
        source="provider_a",
        source_event_id="event1",
        source_observation_id="provider-obs-1",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )

    result = engine.ingest_raw_observation(observation)
    bridge = engine.store.get_source_event_bridge(source="provider_a", source_event_id="event1")

    assert result["status"] in {"PENDING_CONFIRMATION", "OBSERVED_NOT_FINAL"}
    assert bridge is not None


def test_rescheduled_kickoff_keeps_same_canonical_bridge_identity(tmp_path):
    store = make_store(tmp_path)
    identity_a = make_identity(kickoff_utc="2026-09-10T00:15:00Z").canonical_event_key
    identity_b = make_identity(kickoff_utc="2026-09-11T00:15:00Z").canonical_event_key

    assert identity_a == identity_b
    record = _bridge(source="provider_a", source_event_id="event1", canonical_event_key=identity_a)
    persisted = store.persist_source_event_bridge(record)

    assert persisted.canonical_event_key == identity_b


def test_bridge_index_missing_stale_corrupt_rebuilds_from_authority(tmp_path):
    store = make_store(tmp_path)
    identity = make_identity().canonical_event_key
    store.persist_source_event_bridge(_bridge(source="provider_a", source_event_id="event1", canonical_event_key=identity))

    store._bridge_index.unlink()
    assert len(store.list_source_event_bridges()) == 1

    store._bridge_index.write_text('{"stale":"data"}', encoding="utf-8")
    assert len(store.list_source_event_bridges()) == 1

    store._bridge_index.write_text("{", encoding="utf-8")
    assert len(store.list_source_event_bridges()) == 1
