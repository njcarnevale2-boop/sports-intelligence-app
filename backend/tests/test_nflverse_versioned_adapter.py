from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.services.power_engine.trusted_result_mapper import accepted_result_to_final_game_result
from app.services.result_engine import build_canonical_event_identity
from app.services.result_engine.completeness import validate_week_completeness
from app.services.result_engine.persistence import ResultEngineStore
from app.services.result_engine.nflverse_versioned_adapter import (
    NFLVERSE_VERSIONED_RESULT_POLICY_VERSION,
    NflverseAdapterError,
    NflverseArtifactDescriptor,
    NflverseVersionedResultEvidence,
    NflverseVersionedResultIngester,
    build_nflverse_raw_observation,
)
from result_engine_test_utils import make_accepted_result


def _store(tmp_path: Path) -> ResultEngineStore:
    return ResultEngineStore(root_dir=tmp_path / "result-engine-root")


def _teams() -> list[tuple[str, str]]:
    return [
        ("ARI", "ATL"),
        ("BAL", "BUF"),
        ("CAR", "CHI"),
        ("CIN", "CLE"),
        ("DAL", "DEN"),
        ("DET", "GB"),
        ("HOU", "IND"),
        ("JAX", "KC"),
        ("LAC", "LAR"),
        ("LV", "MIA"),
        ("MIN", "NE"),
        ("NO", "NYG"),
        ("NYJ", "PHI"),
        ("PIT", "SEA"),
        ("SF", "TB"),
        ("TEN", "WAS"),
    ]


def _artifact(
    *,
    retrieved_at_utc: str = "2025-09-05T12:00:00Z",
    artifact_sha256: str = "a" * 64,
    release_version: str | None = "schedules-2025-09-05",
    source_locator: str = "https://github.com/nflverse/nflverse-data/releases/download/schedules/schedules.parquet",
) -> NflverseArtifactDescriptor:
    return NflverseArtifactDescriptor(
        provider="nflverse",
        dataset="schedules",
        source_locator=source_locator,
        artifact_sha256=artifact_sha256,
        retrieved_at_utc=retrieved_at_utc,
        release_version=release_version,
    )


def _evidence(
    *,
    idx: int = 0,
    artifact: NflverseArtifactDescriptor | None = None,
    away_score: int | None = 21,
    home_score: int | None = 17,
    retrieved_at_utc: str = "2025-09-05T12:00:00Z",
    season: int = 2025,
    week: int = 1,
) -> NflverseVersionedResultEvidence:
    away_team, home_team = _teams()[idx]
    identity = build_canonical_event_identity(
        season=season,
        week=week,
        kickoff_utc=f"2025-09-{5 + idx:02d}T00:15:00Z",
        away_team=away_team,
        home_team=home_team,
    )
    return NflverseVersionedResultEvidence(
        season=season,
        week=week,
        game_id=f"{season}_{week:02d}_{away_team}_{home_team}",
        kickoff_utc=identity.kickoff_utc,
        away_team=away_team,
        home_team=home_team,
        away_score=away_score,
        home_score=home_score,
        artifact=artifact or _artifact(retrieved_at_utc=retrieved_at_utc),
    )


def _synthetic_expected_events() -> tuple:
    events = []
    for idx, (away_team, home_team) in enumerate(_teams()):
        events.append(
            build_canonical_event_identity(
                season=2025,
                week=1,
                kickoff_utc=f"2025-09-{5 + idx:02d}T00:15:00Z",
                away_team=away_team,
                home_team=home_team,
            )
        )
    return tuple(events)


def test_deterministic_artifact_identity_and_normalization():
    raw_one = build_nflverse_raw_observation(_evidence(), evidence_origin="release_artifact")
    raw_two = build_nflverse_raw_observation(_evidence(), evidence_origin="release_artifact")

    assert raw_one.source == "nflverse"
    assert raw_one.source_event_id == "2025_01_ARI_ATL"
    assert raw_one.canonical_event_key == raw_two.canonical_event_key
    assert raw_one.source_result_version == raw_two.source_result_version
    assert raw_one.source_observation_id == raw_two.source_observation_id
    assert raw_one.away_score == 21
    assert raw_one.home_score == 17


def test_local_observed_at_does_not_create_new_source_evidence():
    one = build_nflverse_raw_observation(_evidence(retrieved_at_utc="2025-09-05T12:00:00Z"), evidence_origin="release_artifact")
    two = build_nflverse_raw_observation(_evidence(retrieved_at_utc="2025-09-05T13:30:00Z"), evidence_origin="release_artifact")

    assert one.source_result_version == two.source_result_version
    assert one.source_observation_id == two.source_observation_id
    assert one.source_evidence_hash == two.source_evidence_hash
    assert one.observation_id == two.observation_id
    assert one.payload_hash != two.payload_hash


def test_stable_game_identity():
    evidence = _evidence(idx=3)
    raw = build_nflverse_raw_observation(evidence, evidence_origin="release_artifact")
    expected = build_canonical_event_identity(
        season=2025,
        week=1,
        kickoff_utc="2025-09-08T00:15:00Z",
        away_team="CIN",
        home_team="CLE",
    )

    assert raw.canonical_event_key == expected.canonical_event_key
    assert raw.kickoff_utc == expected.kickoff_utc
    assert raw.away_team == expected.away_team
    assert raw.home_team == expected.home_team


def test_valid_completed_result_normalization(tmp_path: Path):
    ingester = NflverseVersionedResultIngester(store=_store(tmp_path))
    out = ingester.ingest_evidence(_evidence(), evidence_origin="release_artifact")

    assert out.status == "ACCEPTED"
    assert out.accepted is not None
    assert out.accepted.acceptance_policy_version == NFLVERSE_VERSIONED_RESULT_POLICY_VERSION
    assert out.accepted.accepted_status.value == "COMPLETED"
    assert out.artifact.provider == "nflverse"
    assert out.artifact.source_locator.startswith("https://github.com/nflverse/")


def test_missing_score_rejection():
    with pytest.raises(NflverseAdapterError, match="require both scores"):
        build_nflverse_raw_observation(_evidence(away_score=None), evidence_origin="release_artifact")


def test_malformed_score_rejection():
    with pytest.raises(NflverseAdapterError, match="must be non-negative"):
        build_nflverse_raw_observation(_evidence(home_score=-1), evidence_origin="release_artifact")


def test_malformed_artifact_hash_rejection():
    with pytest.raises(NflverseAdapterError, match="artifact_sha256"):
        build_nflverse_raw_observation(
            _evidence(artifact=_artifact(artifact_sha256="not-a-sha256")),
            evidence_origin="release_artifact",
        )


@pytest.mark.parametrize(
    "artifact_kwargs, match",
    [
        ({"provider": "other"}, "provider must be nflverse"),
        ({"dataset": ""}, "dataset must be a non-empty string"),
        ({"source_locator": ""}, "source_locator must be a non-empty string"),
        ({"retrieved_at_utc": "not-a-timestamp"}, "Invalid retrieved_at_utc"),
    ],
)
def test_incomplete_provenance_rejection(artifact_kwargs, match):
    kwargs = {
        "provider": "nflverse",
        "dataset": "schedules",
        "source_locator": "https://example.com/artifact.parquet",
        "artifact_sha256": "a" * 64,
        "retrieved_at_utc": "2025-09-05T12:00:00Z",
        "release_version": "schedules-2025-09-05",
    }
    kwargs.update(artifact_kwargs)
    with pytest.raises(NflverseAdapterError, match=match):
        build_nflverse_raw_observation(_evidence(artifact=NflverseArtifactDescriptor(**kwargs)), evidence_origin="release_artifact")


def test_duplicate_replay_idempotency(tmp_path: Path):
    ingester = NflverseVersionedResultIngester(store=_store(tmp_path))

    first = ingester.ingest_evidence(_evidence(retrieved_at_utc="2025-09-05T12:00:00Z"), evidence_origin="release_artifact")
    replay = ingester.ingest_evidence(_evidence(retrieved_at_utc="2025-09-05T13:30:00Z"), evidence_origin="release_artifact")

    assert first.status == "ACCEPTED"
    assert replay.status == "ALREADY_ACCEPTED"
    assert len(ingester.store.list_accepted_results()) == 1


def test_changed_score_and_artifact_correction_detection(tmp_path: Path):
    ingester = NflverseVersionedResultIngester(store=_store(tmp_path))

    first = ingester.ingest_evidence(_evidence(), evidence_origin="release_artifact")
    corrected_score = ingester.ingest_evidence(
        _evidence(home_score=18),
        evidence_origin="release_artifact",
    )
    corrected_artifact = ingester.ingest_evidence(
        _evidence(artifact=_artifact(artifact_sha256="b" * 64)),
        evidence_origin="release_artifact",
    )

    assert first.status == "ACCEPTED"
    assert corrected_score.status == "CORRECTION_CANDIDATE"
    assert corrected_score.correction_candidate_id is not None
    assert corrected_artifact.status == "CORRECTION_CANDIDATE"
    assert len(ingester.store.list_accepted_results()) == 1


def test_15_of_16_batch_blocks(tmp_path: Path):
    store = _store(tmp_path)
    ingester = NflverseVersionedResultIngester(store=store)
    expected_events = _synthetic_expected_events()

    for idx in range(15):
        out = ingester.ingest_evidence(_evidence(idx=idx), evidence_origin="release_artifact")
        assert out.status == "ACCEPTED"

    from app.services.result_engine.sportradar_batch_manifest import evaluate_trusted_result_batch

    evaluation = evaluate_trusted_result_batch(
        store=store,
        season=2025,
        week=1,
        expected_events=expected_events,
        policy_version=NFLVERSE_VERSIONED_RESULT_POLICY_VERSION,
    )

    assert evaluation.manifest.completeness.is_complete is False
    assert evaluation.is_handoff_eligible is False


def test_16_of_16_batch_succeeds(tmp_path: Path):
    store = _store(tmp_path)
    ingester = NflverseVersionedResultIngester(store=store)
    expected_events = _synthetic_expected_events()

    for idx in range(16):
        out = ingester.ingest_evidence(_evidence(idx=idx), evidence_origin="release_artifact")
        assert out.status == "ACCEPTED"

    from app.services.result_engine.sportradar_batch_manifest import evaluate_trusted_result_batch

    first = evaluate_trusted_result_batch(
        store=store,
        season=2025,
        week=1,
        expected_events=expected_events,
        policy_version=NFLVERSE_VERSIONED_RESULT_POLICY_VERSION,
    )
    second = evaluate_trusted_result_batch(
        store=store,
        season=2025,
        week=1,
        expected_events=expected_events,
        policy_version=NFLVERSE_VERSIONED_RESULT_POLICY_VERSION,
    )

    assert first.manifest.completeness.is_complete is True
    assert first.is_handoff_eligible is True
    assert first.manifest.manifest_id == second.manifest.manifest_id
    assert first.manifest.manifest_hash == second.manifest.manifest_hash


def test_duplicate_canonical_game_blocks():
    event = build_canonical_event_identity(
        season=2025,
        week=1,
        kickoff_utc="2025-09-05T00:15:00Z",
        away_team="ARI",
        home_team="ATL",
    )
    dup_one = make_accepted_result(
        season=2025,
        week=1,
        kickoff_utc=event.kickoff_utc,
        away_team=event.away_team,
        home_team=event.home_team,
        source="nflverse",
        source_event_id="2025_01_ARI_ATL",
        source_result_version="derived:first",
    )
    dup_two = make_accepted_result(
        season=2025,
        week=1,
        kickoff_utc=event.kickoff_utc,
        away_team=event.away_team,
        home_team=event.home_team,
        source="nflverse",
        source_event_id="2025_01_ARI_ATL_DUP",
        source_result_version="derived:second",
    )

    completeness = validate_week_completeness(
        season=2025,
        week=1,
        expected_events=[event],
        accepted_results=[dup_one, dup_two],
    )

    assert completeness.is_complete is False
    assert len(completeness.duplicate_event_keys) == 1


def test_unexpected_game_blocks():
    expected = build_canonical_event_identity(
        season=2025,
        week=1,
        kickoff_utc="2025-09-05T00:15:00Z",
        away_team="ARI",
        home_team="ATL",
    )
    unexpected = make_accepted_result(
        season=2025,
        week=1,
        kickoff_utc="2025-09-06T00:15:00Z",
        away_team="BAL",
        home_team="BUF",
        source="nflverse",
        source_event_id="2025_01_BAL_BUF",
        source_result_version="derived:unexpected",
    )

    completeness = validate_week_completeness(
        season=2025,
        week=1,
        expected_events=[expected],
        accepted_results=[unexpected],
    )

    assert completeness.is_complete is False
    assert len(completeness.unexpected_event_keys) == 1


def test_unresolved_correction_blocks_handoff(tmp_path: Path):
    store = _store(tmp_path)
    ingester = NflverseVersionedResultIngester(store=store)
    expected_events = [
        build_canonical_event_identity(
            season=2025,
            week=1,
            kickoff_utc="2025-09-05T00:15:00Z",
            away_team="ARI",
            home_team="ATL",
        )
    ]

    first = ingester.ingest_evidence(_evidence(), evidence_origin="release_artifact")
    assert first.status == "ACCEPTED"

    corrected = ingester.ingest_evidence(_evidence(home_score=18), evidence_origin="release_artifact")
    assert corrected.status == "CORRECTION_CANDIDATE"

    from app.services.result_engine.sportradar_batch_manifest import evaluate_trusted_result_batch

    evaluation = evaluate_trusted_result_batch(
        store=store,
        season=2025,
        week=1,
        expected_events=expected_events,
        policy_version=NFLVERSE_VERSIONED_RESULT_POLICY_VERSION,
    )

    assert evaluation.manifest.completeness.is_complete is True
    assert len(evaluation.manifest.unresolved_correction_candidate_ids) == 1
    assert evaluation.is_handoff_eligible is False


def test_mapper_remains_provider_agnostic():
    accepted = make_accepted_result(
        season=2025,
        week=1,
        away_team="ARI",
        home_team="ATL",
        source="nflverse",
        source_event_id="2025_01_ARI_ATL",
        source_result_version="derived:nflverse-versioned-result-v1:abc123",
    )

    out = accepted_result_to_final_game_result(accepted)

    assert out.season == accepted.season
    assert out.week == accepted.week
    assert out.game_id == accepted.canonical_event_key
    assert out.kickoff_utc == accepted.kickoff_utc
    assert out.home_team == accepted.home_team
    assert out.away_team == accepted.away_team
    assert out.home_score == accepted.home_score
    assert out.away_score == accepted.away_score
    assert out.source_result_version == accepted.source_result_version