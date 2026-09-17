from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.services.result_engine import (
    CANONICAL_EVENT_KEY_POLICY_VERSION,
    KICKOFF_NORMALIZATION_POLICY_VERSION,
    NormalizedResultStatus,
    ResultEngineValidationError,
    build_canonical_event_identity,
    build_canonical_event_key,
    normalize_kickoff_utc,
    normalize_result_status,
    observation_source_evidence_hash,
    validate_observation_finality_for_acceptance,
    validate_raw_observation,
)
from app.services.result_engine.policy import DEFAULT_RESULT_ACCEPTANCE_POLICY

from result_engine_test_utils import make_observation


def test_canonical_identity_is_deterministic():
    a = build_canonical_event_identity(
        season=2026,
        week=1,
        kickoff_utc="2026-09-10T00:15:00Z",
        away_team="NE",
        home_team="SEA",
    )
    b = build_canonical_event_identity(
        season=2026,
        week=1,
        kickoff_utc="2026-09-09T19:15:00-05:00",
        away_team="NE",
        home_team="SEA",
    )

    assert a.canonical_event_key == b.canonical_event_key


def test_team_order_changes_canonical_identity():
    home_first = build_canonical_event_key(
        season=2026,
        week=1,
        kickoff_utc="2026-09-10T00:15:00Z",
        away_team="NE",
        home_team="SEA",
    )
    away_first = build_canonical_event_key(
        season=2026,
        week=1,
        kickoff_utc="2026-09-10T00:15:00Z",
        away_team="SEA",
        home_team="NE",
    )

    assert home_first != away_first


def test_kickoff_normalization_is_explicit_and_versioned():
    normalized = normalize_kickoff_utc("2026-09-09T20:15:00.999-04:00")

    assert normalized == "2026-09-10T00:15:00Z"
    assert KICKOFF_NORMALIZATION_POLICY_VERSION == "kickoff_utc_second_v1"


def test_rescheduled_kickoff_produces_distinct_canonical_key():
    base = build_canonical_event_key(
        season=2026,
        week=1,
        kickoff_utc="2026-09-10T00:15:00Z",
        away_team="NE",
        home_team="SEA",
    )
    moved = build_canonical_event_key(
        season=2026,
        week=1,
        kickoff_utc="2026-09-11T00:15:00Z",
        away_team="NE",
        home_team="SEA",
    )

    assert base == moved
    assert CANONICAL_EVENT_KEY_POLICY_VERSION == "stable_matchup_week_v1"


def test_malformed_kickoff_is_rejected():
    with pytest.raises(ValueError, match="Invalid kickoff_utc"):
        normalize_kickoff_utc("not-a-date")


def test_unknown_team_is_rejected():
    with pytest.raises(ValueError, match="Unknown team id"):
        build_canonical_event_identity(
            season=2026,
            week=1,
            kickoff_utc="2026-09-10T00:15:00Z",
            away_team="XXX",
            home_team="SEA",
        )


def test_home_equals_away_is_rejected():
    with pytest.raises(ValueError, match="cannot match"):
        build_canonical_event_identity(
            season=2026,
            week=1,
            kickoff_utc="2026-09-10T00:15:00Z",
            away_team="SEA",
            home_team="SEA",
        )


@pytest.mark.parametrize("bad_score", [-1, -10])
def test_negative_score_is_rejected(bad_score: int):
    obs = make_observation(home_score=bad_score)
    with pytest.raises(ResultEngineValidationError, match="home_score must be non-negative"):
        validate_raw_observation(obs)


@pytest.mark.parametrize("bad_score", [17.2, "17"])
def test_float_or_string_score_is_rejected(bad_score):
    obs = make_observation(away_score=bad_score)  # type: ignore[arg-type]
    with pytest.raises(ResultEngineValidationError, match="away_score must be an integer"):
        validate_raw_observation(obs)


def test_bool_score_is_rejected():
    obs = make_observation(away_score=True)  # type: ignore[arg-type]
    with pytest.raises(ResultEngineValidationError, match="away_score must be an integer"):
        validate_raw_observation(obs)


def test_scores_with_non_final_status_rejected_for_acceptance():
    obs = make_observation(status=NormalizedResultStatus.IN_PROGRESS)
    with pytest.raises(ResultEngineValidationError, match="Status is not final"):
        validate_observation_finality_for_acceptance(obs, policy=DEFAULT_RESULT_ACCEPTANCE_POLICY)


def test_explicit_final_with_valid_scores_is_eligible_for_acceptance():
    obs = make_observation(status=NormalizedResultStatus.FINAL, away_score=17, home_score=24)
    validate_observation_finality_for_acceptance(obs, policy=DEFAULT_RESULT_ACCEPTANCE_POLICY)


def test_observation_hash_and_id_are_deterministic():
    a = make_observation(observed_at_utc="2026-09-10T05:00:00Z")
    b = make_observation(observed_at_utc="2026-09-10T05:00:00Z")

    assert a.payload_hash == b.payload_hash
    assert a.observation_id == b.observation_id


def test_source_evidence_hash_ignores_local_observed_timestamp():
    a = make_observation(
        source_observation_id="prov-1",
        observed_at_utc="2026-09-10T05:00:00Z",
    )
    b = make_observation(
        source_observation_id="prov-1",
        observed_at_utc="2026-09-10T05:02:00Z",
    )

    assert a.source_evidence_hash == b.source_evidence_hash
    assert a.payload_hash != b.payload_hash
    assert a.observation_id == b.observation_id


def test_source_evidence_hash_changes_with_source_payload_fields():
    base = make_observation(source_observation_id="prov-1")
    changed_published = make_observation(source_observation_id="prov-1", provider_published_at_utc="2026-09-10T05:00:30Z")
    changed_version = make_observation(source_observation_id="prov-1", source_result_version="v2")
    changed_score = make_observation(source_observation_id="prov-1", home_score=27)
    changed_status = make_observation(source_observation_id="prov-1", status=NormalizedResultStatus.COMPLETED)
    changed_team = make_observation(source_observation_id="prov-1", away_team="BUF", home_team="MIA")
    changed_kickoff = make_observation(source_observation_id="prov-1", kickoff_utc="2026-09-11T00:15:00Z")
    changed_event = make_observation(source_observation_id="prov-1", source_event_id="evt-xyz")

    assert base.source_evidence_hash != changed_published.source_evidence_hash
    assert base.source_evidence_hash != changed_version.source_evidence_hash
    assert base.source_evidence_hash != changed_score.source_evidence_hash
    assert base.source_evidence_hash != changed_status.source_evidence_hash
    assert base.source_evidence_hash != changed_team.source_evidence_hash
    assert base.source_evidence_hash != changed_kickoff.source_evidence_hash
    assert base.source_evidence_hash != changed_event.source_evidence_hash


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("final", NormalizedResultStatus.FINAL),
        ("  completed ", NormalizedResultStatus.COMPLETED),
        ("postgame", NormalizedResultStatus.POSTGAME),
        ("in progress", NormalizedResultStatus.IN_PROGRESS),
        ("DELAYED", NormalizedResultStatus.DELAYED),
        ("garbage", NormalizedResultStatus.UNKNOWN),
    ],
)
def test_status_normalization_is_controlled(raw: str, expected: NormalizedResultStatus):
    assert normalize_result_status(raw) == expected


@pytest.mark.parametrize(
    "status",
    [
        NormalizedResultStatus.UNKNOWN,
        NormalizedResultStatus.POSTPONED,
        NormalizedResultStatus.SUSPENDED,
        NormalizedResultStatus.CANCELLED,
        NormalizedResultStatus.ABANDONED,
        NormalizedResultStatus.DELAYED,
        NormalizedResultStatus.IN_PROGRESS,
        NormalizedResultStatus.HALFTIME,
        NormalizedResultStatus.SCHEDULED,
    ],
)
def test_non_final_statuses_are_never_acceptance_eligible(status: NormalizedResultStatus):
    obs = make_observation(status=status, away_score=17, home_score=24)
    with pytest.raises(ResultEngineValidationError, match="Status is not final"):
        validate_observation_finality_for_acceptance(obs, policy=DEFAULT_RESULT_ACCEPTANCE_POLICY)


@pytest.mark.parametrize("bad_score", [True, False, 17.0, "17", -1])
def test_score_rejects_bool_float_string_negative(bad_score):
    obs = make_observation(home_score=bad_score)  # type: ignore[arg-type]
    with pytest.raises(ResultEngineValidationError):
        validate_raw_observation(obs)


@pytest.mark.parametrize("bad_score", [float("nan"), float("inf")])
def test_score_rejects_nan_and_infinity(bad_score: float):
    obs = make_observation(home_score=bad_score)  # type: ignore[arg-type]
    with pytest.raises(ResultEngineValidationError, match="must be an integer"):
        validate_raw_observation(obs)


def test_naive_and_invalid_timestamps_are_rejected():
    naive = make_observation(observed_at_utc="2026-09-10T05:00:00", provider_published_at_utc="2026-09-10T04:59:00Z")
    with pytest.raises(ResultEngineValidationError, match="timezone"):
        validate_raw_observation(naive)

    invalid = make_observation(observed_at_utc="bad-time", provider_published_at_utc="2026-09-10T04:59:00Z")
    with pytest.raises(ResultEngineValidationError, match="Invalid observed_at_utc"):
        validate_raw_observation(invalid)


def test_provider_published_after_observed_is_rejected():
    obs = make_observation(
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T05:00:01Z",
    )
    with pytest.raises(ResultEngineValidationError, match="cannot be after"):
        validate_raw_observation(obs)


def test_source_observation_id_is_required():
    obs = make_observation(source_observation_id="")
    with pytest.raises(ResultEngineValidationError, match="source_observation_id"):
        validate_raw_observation(obs)


def test_source_evidence_hash_function_matches_observation_value():
    observation = make_observation(source_observation_id="provider-observation-1")
    assert observation.source_evidence_hash == observation_source_evidence_hash(observation)


def test_conflicting_observation_identity_fails_validation():
    observation = make_observation()
    tampered = replace(observation, home_score=27)

    with pytest.raises(ResultEngineValidationError, match="source evidence hash mismatch|payload hash mismatch"):
        validate_raw_observation(tampered)
