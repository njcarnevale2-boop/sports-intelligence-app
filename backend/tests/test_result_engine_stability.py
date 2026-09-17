from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.services.result_engine import NormalizedResultStatus
from app.services.result_engine.engine import ResultEngineAcceptanceError
from result_engine_test_utils import make_engine, make_observation


def test_first_final_observation_is_not_accepted(tmp_path):
    engine = make_engine(tmp_path, min_seconds=60)
    first = make_observation(
        source_observation_id="provider-1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )

    outcome = engine.ingest_raw_observation(first)

    assert outcome["status"] == "PENDING_CONFIRMATION"
    assert outcome["accepted"] is None


def test_second_identical_final_before_interval_is_not_accepted(tmp_path):
    engine = make_engine(tmp_path, min_seconds=60)
    first = make_observation(
        source_observation_id="provider-1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )
    second = make_observation(
        source_observation_id="provider-2",
        observed_at_utc="2026-09-10T05:00:30Z",
        provider_published_at_utc="2026-09-10T05:00:20Z",
    )

    engine.ingest_raw_observation(first)
    outcome = engine.ingest_raw_observation(second)

    assert outcome["status"] == "PENDING_CONFIRMATION_INTERVAL"
    assert outcome["accepted"] is None


def test_second_identical_final_after_interval_is_accepted(tmp_path):
    engine = make_engine(tmp_path, min_seconds=60)
    first = make_observation(
        source_observation_id="provider-1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )
    second = make_observation(
        source_observation_id="provider-2",
        observed_at_utc="2026-09-10T05:01:05Z",
        provider_published_at_utc="2026-09-10T05:01:00Z",
    )

    engine.ingest_raw_observation(first)
    outcome = engine.ingest_raw_observation(second)

    assert outcome["status"] == "ACCEPTED"
    accepted = outcome["accepted"]
    assert accepted is not None
    assert accepted.away_score == 17
    assert accepted.home_score == 24
    assert accepted.confirmation_count == 2


def test_different_score_on_second_observation_is_not_accepted(tmp_path):
    engine = make_engine(tmp_path, min_seconds=60)
    first = make_observation(
        source_observation_id="provider-1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )
    second = make_observation(
        source_observation_id="provider-2",
        home_score=27,
        observed_at_utc="2026-09-10T05:01:30Z",
        provider_published_at_utc="2026-09-10T05:01:20Z",
    )

    engine.ingest_raw_observation(first)
    outcome = engine.ingest_raw_observation(second)

    assert outcome["status"] == "PENDING_CONFIRMATION"
    assert outcome["accepted"] is None


def test_different_canonical_identity_is_not_accepted(tmp_path):
    engine = make_engine(tmp_path, min_seconds=60)
    first = make_observation(
        source_observation_id="provider-1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )
    second = make_observation(
        kickoff_utc="2026-09-11T00:15:00Z",
        source_event_id="evt-002",
        source_observation_id="provider-2",
        observed_at_utc="2026-09-10T05:02:00Z",
        provider_published_at_utc="2026-09-10T05:01:55Z",
    )

    engine.ingest_raw_observation(first)
    outcome = engine.ingest_raw_observation(second)

    assert outcome["status"] == "PENDING_CONFIRMATION"
    assert outcome["accepted"] is None


def test_different_source_event_id_is_not_accepted_under_same_source_policy(tmp_path):
    engine = make_engine(tmp_path, min_seconds=60)
    first = make_observation(
        source_event_id="evt-001",
        source_observation_id="provider-1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )
    second = make_observation(
        source_event_id="evt-002",
        source_observation_id="provider-2",
        observed_at_utc="2026-09-10T05:02:00Z",
        provider_published_at_utc="2026-09-10T05:01:55Z",
    )

    engine.ingest_raw_observation(first)
    outcome = engine.ingest_raw_observation(second)

    assert outcome["status"] == "PENDING_CONFIRMATION"
    assert outcome["accepted"] is None


def test_non_final_second_observation_is_not_accepted(tmp_path):
    engine = make_engine(tmp_path, min_seconds=60)
    first = make_observation(
        status=NormalizedResultStatus.FINAL,
        source_observation_id="provider-1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )
    second = make_observation(
        status=NormalizedResultStatus.IN_PROGRESS,
        source_observation_id="provider-2",
        observed_at_utc="2026-09-10T05:02:00Z",
        provider_published_at_utc="2026-09-10T05:01:55Z",
    )

    engine.ingest_raw_observation(first)
    outcome = engine.ingest_raw_observation(second)

    assert outcome["status"] == "OBSERVED_NOT_FINAL"
    assert outcome["accepted"] is None


def test_accepted_result_replay_is_idempotent(tmp_path):
    engine = make_engine(tmp_path, min_seconds=60)
    first = make_observation(
        source_observation_id="provider-1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )
    second = make_observation(
        source_observation_id="provider-2",
        observed_at_utc="2026-09-10T05:02:00Z",
        provider_published_at_utc="2026-09-10T05:01:55Z",
    )

    engine.ingest_raw_observation(first)
    accepted = engine.ingest_raw_observation(second)
    replay = engine.ingest_raw_observation(second)

    assert accepted["status"] == "ACCEPTED"
    assert replay["status"] == "ALREADY_ACCEPTED"
    assert replay["accepted"].result_id == accepted["accepted"].result_id


def test_conflicting_final_after_acceptance_becomes_correction_candidate(tmp_path):
    engine = make_engine(tmp_path, min_seconds=60)
    first = make_observation(
        source_observation_id="provider-1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )
    second = make_observation(
        source_observation_id="provider-2",
        observed_at_utc="2026-09-10T05:02:00Z",
        provider_published_at_utc="2026-09-10T05:01:55Z",
    )
    conflict = make_observation(
        source_observation_id="provider-3",
        home_score=27,
        observed_at_utc="2026-09-10T05:04:00Z",
        provider_published_at_utc="2026-09-10T05:03:50Z",
    )

    engine.ingest_raw_observation(first)
    engine.ingest_raw_observation(second)
    outcome = engine.ingest_raw_observation(conflict)

    assert outcome["status"] == "CORRECTION_CANDIDATE"
    assert outcome["accepted"] is not None
    assert outcome["correctionCandidateId"]


def test_replay_same_provider_payload_with_new_local_observed_time_does_not_confirm(tmp_path):
    engine = make_engine(tmp_path, min_seconds=60)
    first = make_observation(
        source_observation_id="provider-1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )
    replay = make_observation(
        source_observation_id="provider-1",
        observed_at_utc="2026-09-10T05:02:00Z",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )

    first_outcome = engine.ingest_raw_observation(first)
    replay_outcome = engine.ingest_raw_observation(replay)

    assert first_outcome["status"] == "PENDING_CONFIRMATION"
    assert replay_outcome["status"] == "PENDING_CONFIRMATION"
    assert replay_outcome["accepted"] is None


def test_changing_source_result_version_only_does_not_confirm_without_new_source_observation(tmp_path):
    engine = make_engine(tmp_path, min_seconds=60)
    first = make_observation(
        source_observation_id="provider-1",
        source_result_version="scores-v1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )
    spoof = make_observation(
        source_observation_id="provider-1",
        source_result_version="scores-v2",
        observed_at_utc="2026-09-10T05:03:00Z",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )

    engine.ingest_raw_observation(first)
    with pytest.raises(ResultEngineAcceptanceError, match="Ambiguous source observation authority"):
        engine.ingest_raw_observation(spoof)


def test_genuine_second_source_observation_after_interval_is_accepted(tmp_path):
    engine = make_engine(tmp_path, min_seconds=60)
    a = make_observation(
        source_observation_id="provider-1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:00Z",
    )
    b = make_observation(
        source_observation_id="provider-2",
        observed_at_utc="2026-09-10T05:02:00Z",
        provider_published_at_utc="2026-09-10T05:01:05Z",
    )

    engine.ingest_raw_observation(a)
    outcome = engine.ingest_raw_observation(b)

    assert outcome["status"] == "ACCEPTED"


def test_interval_boundaries_use_provider_published_time(tmp_path):
    engine = make_engine(tmp_path, min_seconds=60)
    first = make_observation(
        source_observation_id="provider-1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:00Z",
    )
    almost = make_observation(
        source_observation_id="provider-2",
        observed_at_utc="2026-09-10T05:02:00Z",
        provider_published_at_utc="2026-09-10T04:59:59.999000Z",
    )

    engine.ingest_raw_observation(first)
    almost_outcome = engine.ingest_raw_observation(almost)
    assert almost_outcome["status"] == "PENDING_CONFIRMATION_INTERVAL"

    exact = make_observation(
        source_observation_id="provider-3",
        observed_at_utc="2026-09-10T05:03:00Z",
        provider_published_at_utc="2026-09-10T05:00:00Z",
    )
    exact_outcome = engine.ingest_raw_observation(exact)
    assert exact_outcome["status"] == "ACCEPTED"
