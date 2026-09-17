from __future__ import annotations

import os
import sys
from pathlib import Path

from app.services.result_engine import build_canonical_event_identity

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.services.result_engine.completeness import validate_week_completeness
from app.services.result_engine.sportradar_batch_manifest import evaluate_trusted_result_batch
from app.services.result_engine.sportradar_closed_adapter import (
    SPORTRADAR_CLOSED_POLICY_VERSION,
    SportradarChangeLogRef,
    SportradarClosedResultIngester,
    SportradarResultEvidence,
)
from app.services.result_engine.persistence import ResultEngineStore
from result_engine_test_utils import make_accepted_result


def _store(tmp_path: Path) -> ResultEngineStore:
    return ResultEngineStore(root_dir=tmp_path / "result-engine-root")


def _event(index: int):
    teams = [
        ("ARI", "ATL"), ("BAL", "BUF"), ("CAR", "CHI"), ("CIN", "CLE"),
        ("DAL", "DEN"), ("DET", "GB"), ("HOU", "IND"), ("JAX", "KC"),
        ("LAC", "LAR"), ("LV", "MIA"), ("MIN", "NE"), ("NO", "NYG"),
        ("NYJ", "PHI"), ("PIT", "SEA"), ("SF", "TB"), ("TEN", "WAS"),
    ]
    away, home = teams[index]
    day = 1 + index
    kickoff = f"2025-10-{day:02d}T00:15:00Z"
    return build_canonical_event_identity(
        season=2025,
        week=3,
        kickoff_utc=kickoff,
        away_team=away,
        home_team=home,
    )


def _evidence_from_event(event_id: str, idx: int) -> SportradarResultEvidence:
    event = _event(idx)
    return SportradarResultEvidence(
        source_event_id=event_id,
        season=2025,
        week=3,
        kickoff_utc=event.kickoff_utc,
        away_team=event.away_team,
        home_team=event.home_team,
        status="closed",
        away_score=10 + idx,
        home_score=13 + idx,
        observed_at_utc=f"2025-10-{1 + idx:02d}T04:10:00Z",
        canonical_event_key=event.canonical_event_key,
        x_generated_date=f"Wed, {1 + idx:02d} Oct 2025 04:09:00 GMT",
    )


def test_16_of_16_completeness_success_and_manifest_replay_stable(tmp_path: Path):
    store = _store(tmp_path)
    ingester = SportradarClosedResultIngester(store=store)
    expected_events = tuple(_event(i) for i in range(16))

    for i in range(16):
        out = ingester.ingest_evidence(_evidence_from_event(f"evt-{i}", i), evidence_origin="game_feed_direct")
        assert out.status == "ACCEPTED"

    first = evaluate_trusted_result_batch(
        store=store,
        season=2025,
        week=3,
        expected_events=expected_events,
        policy_version=SPORTRADAR_CLOSED_POLICY_VERSION,
    )
    second = evaluate_trusted_result_batch(
        store=store,
        season=2025,
        week=3,
        expected_events=expected_events,
        policy_version=SPORTRADAR_CLOSED_POLICY_VERSION,
    )

    assert first.manifest.completeness.is_complete is True
    assert first.is_handoff_eligible is True
    assert first.manifest.manifest_id == second.manifest.manifest_id
    assert first.manifest.manifest_hash == second.manifest.manifest_hash


def test_15_of_16_completeness_rejected(tmp_path: Path):
    store = _store(tmp_path)
    ingester = SportradarClosedResultIngester(store=store)
    expected_events = tuple(_event(i) for i in range(16))

    for i in range(15):
        out = ingester.ingest_evidence(_evidence_from_event(f"evt-{i}", i), evidence_origin="game_feed_direct")
        assert out.status == "ACCEPTED"

    evaluation = evaluate_trusted_result_batch(
        store=store,
        season=2025,
        week=3,
        expected_events=expected_events,
        policy_version=SPORTRADAR_CLOSED_POLICY_VERSION,
    )

    assert evaluation.manifest.completeness.is_complete is False
    assert evaluation.is_handoff_eligible is False


def test_duplicate_canonical_game_rejected_by_completeness_validator():
    event = _event(0)
    dup = make_accepted_result(
        season=2025,
        week=3,
        kickoff_utc=event.kickoff_utc,
        away_team=event.away_team,
        home_team=event.home_team,
        source="sportradar_nfl",
        source_event_id="evt-a",
        source_result_version="derived:one",
    )
    dup_two = make_accepted_result(
        season=2025,
        week=3,
        kickoff_utc=event.kickoff_utc,
        away_team=event.away_team,
        home_team=event.home_team,
        source="sportradar_nfl",
        source_event_id="evt-b",
        source_result_version="derived:two",
    )

    completeness = validate_week_completeness(
        season=2025,
        week=3,
        expected_events=[event],
        accepted_results=[dup, dup_two],
    )

    assert completeness.is_complete is False
    assert len(completeness.duplicate_event_keys) == 1


def test_unresolved_correction_blocks_handoff_eligibility(tmp_path: Path):
    store = _store(tmp_path)
    ingester = SportradarClosedResultIngester(store=store)
    expected_events = [_event(0)]

    first = ingester.ingest_evidence(_evidence_from_event("evt-0", 0), evidence_origin="game_feed_direct")
    assert first.status == "ACCEPTED"

    corrected = _evidence_from_event("evt-0", 0)
    corrected = SportradarResultEvidence(
        **{
            **corrected.__dict__,
            "home_score": corrected.home_score - 1,
            "observed_at_utc": "2025-10-01T04:30:00Z",
            "change_log": SportradarChangeLogRef(source_event_id="evt-0", last_modified="2025-10-01T04:20:00Z"),
            "x_generated_date": None,
        }
    )
    out = ingester.ingest_evidence(corrected, evidence_origin="daily_change_log_reconciliation")
    assert out.status == "CORRECTION_CANDIDATE"

    evaluation = evaluate_trusted_result_batch(
        store=store,
        season=2025,
        week=3,
        expected_events=expected_events,
        policy_version=SPORTRADAR_CLOSED_POLICY_VERSION,
    )
    assert evaluation.manifest.completeness.is_complete is True
    assert len(evaluation.manifest.unresolved_correction_candidate_ids) == 1
    assert evaluation.is_handoff_eligible is False
