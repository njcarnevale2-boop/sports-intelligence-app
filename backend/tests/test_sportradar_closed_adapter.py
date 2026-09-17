from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.services.result_engine import build_canonical_event_identity
from app.services.result_engine.persistence import ResultEngineStore
from app.services.result_engine.sportradar_closed_adapter import (
    SPORTRADAR_CLOSED_POLICY_VERSION,
    SPORTRADAR_NFL_SOURCE,
    SportradarAdapterError,
    SportradarChangeLogRef,
    SportradarClosedResultIngester,
    SportradarResultEvidence,
    build_sportradar_raw_observation,
)


def _store(tmp_path: Path) -> ResultEngineStore:
    return ResultEngineStore(root_dir=tmp_path / "result-engine-root")


def _identity(away: str = "ARI", home: str = "ATL"):
    return build_canonical_event_identity(
        season=2025,
        week=3,
        kickoff_utc="2025-09-20T00:15:00Z",
        away_team=away,
        home_team=home,
    )


def _evidence(
    *,
    event_id: str = "evt-a",
    status: str = "closed",
    away_score: int | None = 21,
    home_score: int | None = 24,
    observed_at: str = "2025-09-20T04:10:00Z",
    x_generated_date: str | None = "Sat, 20 Sep 2025 04:09:00 GMT",
    last_modified: str | None = None,
    change_log: SportradarChangeLogRef | None = None,
    away_team: str = "ARI",
    home_team: str = "ATL",
) -> SportradarResultEvidence:
    identity = _identity(away=away_team, home=home_team)
    return SportradarResultEvidence(
        source_event_id=event_id,
        season=2025,
        week=3,
        kickoff_utc=identity.kickoff_utc,
        away_team=away_team,
        home_team=home_team,
        status=status,
        away_score=away_score,
        home_score=home_score,
        observed_at_utc=observed_at,
        canonical_event_key=identity.canonical_event_key,
        etag='"etag-a"',
        x_generated_date=x_generated_date,
        last_modified=last_modified,
        change_log=change_log,
    )


def test_closed_happy_path_accepts_single_observation(tmp_path: Path):
    ingester = SportradarClosedResultIngester(store=_store(tmp_path))
    out = ingester.ingest_evidence(_evidence(status="closed"), evidence_origin="game_feed_direct")

    assert out.status == "ACCEPTED"
    assert out.accepted is not None
    assert out.accepted.acceptance_policy_version == SPORTRADAR_CLOSED_POLICY_VERSION
    assert out.accepted.source == SPORTRADAR_NFL_SOURCE


def test_complete_cannot_be_accepted(tmp_path: Path):
    ingester = SportradarClosedResultIngester(store=_store(tmp_path))
    out = ingester.ingest_evidence(_evidence(status="complete"), evidence_origin="game_feed_direct")

    assert out.status == "OBSERVED_NOT_FINAL"
    assert out.accepted is None
    assert len(ingester.store.list_accepted_results()) == 0


def test_unknown_state_fails_closed():
    with pytest.raises(SportradarAdapterError, match="Unknown Sportradar status"):
        build_sportradar_raw_observation(_evidence(status="mystery"), evidence_origin="game_feed_direct")


def test_duplicate_semantic_evidence_is_stable_even_if_observed_time_changes():
    evidence_one = _evidence(observed_at="2025-09-20T04:10:00Z")
    evidence_two = _evidence(observed_at="2025-09-20T04:20:00Z")

    one = build_sportradar_raw_observation(evidence_one, evidence_origin="game_feed_direct")
    two = build_sportradar_raw_observation(evidence_two, evidence_origin="game_feed_direct")

    assert one.source_observation_id == two.source_observation_id
    assert one.source_result_version == two.source_result_version
    assert one.source_evidence_hash == two.source_evidence_hash
    assert one.payload_hash != two.payload_hash


def test_provider_revision_change_produces_new_identity_version_and_evidence_hash():
    base = build_sportradar_raw_observation(_evidence(), evidence_origin="game_feed_direct")
    changed = build_sportradar_raw_observation(
        _evidence(
            observed_at="2025-09-20T04:15:00Z",
            change_log=SportradarChangeLogRef(source_event_id="evt-a", last_modified="2025-09-20T04:11:00Z"),
        ),
        evidence_origin="daily_change_log_reconciliation",
    )

    assert changed.source_result_version != base.source_result_version
    assert changed.source_observation_id != base.source_observation_id
    assert changed.source_evidence_hash != base.source_evidence_hash


def test_score_correction_creates_correction_candidate_not_replacement(tmp_path: Path):
    ingester = SportradarClosedResultIngester(store=_store(tmp_path))

    first = ingester.ingest_evidence(_evidence(status="closed", home_score=28, away_score=21), evidence_origin="game_feed_direct")
    corrected = ingester.ingest_evidence(
        _evidence(
            status="closed",
            home_score=27,
            away_score=21,
            observed_at="2025-09-20T04:20:00Z",
            change_log=SportradarChangeLogRef(source_event_id="evt-a", last_modified="2025-09-20T04:14:00Z"),
        ),
        evidence_origin="daily_change_log_reconciliation",
    )

    assert first.status == "ACCEPTED"
    assert corrected.status == "CORRECTION_CANDIDATE"
    assert corrected.correction_candidate_id is not None
    assert len(ingester.store.list_accepted_results()) == 1


def test_post_closed_change_evidence_routes_to_conflict_flow(tmp_path: Path):
    ingester = SportradarClosedResultIngester(store=_store(tmp_path))
    ingester.ingest_evidence(_evidence(status="closed", home_score=24, away_score=21), evidence_origin="game_feed_direct")

    changed_metadata = ingester.ingest_evidence(
        _evidence(
            status="closed",
            home_score=24,
            away_score=21,
            observed_at="2025-09-20T04:35:00Z",
            change_log=SportradarChangeLogRef(source_event_id="evt-a", last_modified="2025-09-20T04:30:00Z"),
        ),
        evidence_origin="daily_change_log_reconciliation",
    )

    assert changed_metadata.status == "CORRECTION_CANDIDATE"
    assert len(ingester.store.list_accepted_results()) == 1


def test_suspended_then_closed_lifecycle(tmp_path: Path):
    ingester = SportradarClosedResultIngester(store=_store(tmp_path))

    suspended = ingester.ingest_evidence(_evidence(status="suspended", home_score=None, away_score=None), evidence_origin="game_feed_direct")
    closed = ingester.ingest_evidence(
        _evidence(
            status="closed",
            home_score=17,
            away_score=14,
            observed_at="2025-09-20T04:15:00Z",
            change_log=SportradarChangeLogRef(source_event_id="evt-a", last_modified="2025-09-20T04:12:00Z"),
        ),
        evidence_origin="daily_change_log_reconciliation",
    )

    assert suspended.status == "OBSERVED_NOT_FINAL"
    assert closed.status == "ACCEPTED"


def test_postponed_is_not_acceptance_eligible(tmp_path: Path):
    ingester = SportradarClosedResultIngester(store=_store(tmp_path))
    out = ingester.ingest_evidence(_evidence(status="postponed", away_score=None, home_score=None), evidence_origin="game_feed_direct")
    assert out.status == "OBSERVED_NOT_FINAL"
    assert out.accepted is None


def test_postponed_replacement_event_id_ambiguity_fails_closed(tmp_path: Path):
    ingester = SportradarClosedResultIngester(store=_store(tmp_path))

    postponed = ingester.ingest_evidence(
        _evidence(event_id="evt-old", status="postponed", away_score=None, home_score=None),
        evidence_origin="game_feed_direct",
    )
    assert postponed.status == "OBSERVED_NOT_FINAL"

    with pytest.raises(SportradarAdapterError, match="Ambiguous postponed"):
        ingester.ingest_evidence(
            _evidence(
                event_id="evt-new",
                status="closed",
                home_score=31,
                away_score=17,
                observed_at="2025-09-20T04:45:00Z",
                change_log=SportradarChangeLogRef(source_event_id="evt-new", last_modified="2025-09-20T04:40:00Z"),
                x_generated_date=None,
            ),
            evidence_origin="daily_change_log_reconciliation",
        )


def test_home_away_mismatch_rejected_by_identity_validation():
    identity = _identity(away="ARI", home="ATL")
    evidence = SportradarResultEvidence(
        source_event_id="evt-a",
        season=2025,
        week=3,
        kickoff_utc=identity.kickoff_utc,
        away_team="ATL",
        home_team="ARI",
        status="closed",
        away_score=14,
        home_score=17,
        observed_at_utc="2025-09-20T04:10:00Z",
        canonical_event_key=identity.canonical_event_key,
        x_generated_date="Fri, 20 Sep 2030 04:09:00 GMT",
    )

    with pytest.raises(Exception):
        build_sportradar_raw_observation(evidence, evidence_origin="game_feed_direct")


def test_missing_score_rejected_for_closed(tmp_path: Path):
    ingester = SportradarClosedResultIngester(store=_store(tmp_path))
    with pytest.raises(SportradarAdapterError, match="closed observations must include both scores"):
        ingester.ingest_evidence(_evidence(status="closed", away_score=None), evidence_origin="game_feed_direct")


def test_no_provider_timestamp_rejected():
    with pytest.raises(SportradarAdapterError, match="No provider publication timestamp"):
        build_sportradar_raw_observation(
            _evidence(x_generated_date=None, last_modified=None, change_log=None),
            evidence_origin="game_feed_direct",
        )


def test_provider_timestamp_after_observed_rejected():
    with pytest.raises(SportradarAdapterError, match="cannot be later"):
        build_sportradar_raw_observation(
            _evidence(observed_at="2025-09-20T04:10:00Z", x_generated_date="Sat, 20 Sep 2025 04:12:00 GMT"),
            evidence_origin="game_feed_direct",
        )


def test_change_log_event_id_mismatch_rejected():
    with pytest.raises(SportradarAdapterError, match="identity mismatch"):
        build_sportradar_raw_observation(
            _evidence(change_log=SportradarChangeLogRef(source_event_id="evt-other", last_modified="2025-09-20T04:08:00Z")),
            evidence_origin="daily_change_log_reconciliation",
        )


def test_duplicate_semantic_replay_is_idempotent(tmp_path: Path):
    ingester = SportradarClosedResultIngester(store=_store(tmp_path))

    first = ingester.ingest_evidence(_evidence(observed_at="2025-09-20T04:10:00Z"), evidence_origin="game_feed_direct")
    replay = ingester.ingest_evidence(_evidence(observed_at="2025-09-20T04:15:00Z"), evidence_origin="game_feed_direct")

    assert first.status == "ACCEPTED"
    assert replay.status == "ALREADY_ACCEPTED"
    assert len(ingester.store.list_accepted_results()) == 1
