from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.result_engine import (
    DEFAULT_RESULT_ACCEPTANCE_POLICY,
    AcceptedFinalGameResult,
    CanonicalEventIdentity,
    NormalizedResultStatus,
    ResultAcceptanceEngine,
    ResultAcceptancePolicy,
    ResultEngineStore,
    accepted_result_payload_hash,
    build_canonical_event_identity,
    build_raw_observation,
    deterministic_result_id,
)


def iso_at(offset_seconds: int = 0) -> str:
    base = datetime(2026, 9, 10, 0, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=offset_seconds)).isoformat().replace("+00:00", "Z")


def make_identity(
    *,
    season: int = 2026,
    week: int = 1,
    kickoff_utc: str = "2026-09-10T00:15:00Z",
    away_team: str = "NE",
    home_team: str = "SEA",
) -> CanonicalEventIdentity:
    return build_canonical_event_identity(
        season=season,
        week=week,
        kickoff_utc=kickoff_utc,
        away_team=away_team,
        home_team=home_team,
    )


def make_observation(
    *,
    source: str = "odds_api",
    source_event_id: str = "evt-001",
    source_observation_id: str = "obs-001",
    season: int = 2026,
    week: int = 1,
    kickoff_utc: str = "2026-09-10T00:15:00Z",
    away_team: str = "NE",
    home_team: str = "SEA",
    status: NormalizedResultStatus = NormalizedResultStatus.FINAL,
    away_score: int | None = 17,
    home_score: int | None = 24,
    observed_at_utc: str = "2026-09-10T05:00:00Z",
    source_result_version: str = "v1",
    provider_published_at_utc: str | None = "2026-09-10T04:59:50Z",
):
    identity = make_identity(
        season=season,
        week=week,
        kickoff_utc=kickoff_utc,
        away_team=away_team,
        home_team=home_team,
    )
    return build_raw_observation(
        source=source,
        source_event_id=source_event_id,
        source_observation_id=source_observation_id,
        canonical_event_key=identity.canonical_event_key,
        season=season,
        week=week,
        kickoff_utc=identity.kickoff_utc,
        away_team=away_team,
        home_team=home_team,
        status=status,
        away_score=away_score,
        home_score=home_score,
        observed_at_utc=observed_at_utc,
        source_result_version=source_result_version,
        provider_published_at_utc=provider_published_at_utc,
    )


def make_store(tmp_path: Path) -> ResultEngineStore:
    return ResultEngineStore(root_dir=tmp_path / "result-engine-root")


def make_policy(min_seconds: int = 60) -> ResultAcceptancePolicy:
    return ResultAcceptancePolicy(
        version=DEFAULT_RESULT_ACCEPTANCE_POLICY.version,
        min_confirmation_interval_seconds=min_seconds,
        final_statuses=DEFAULT_RESULT_ACCEPTANCE_POLICY.final_statuses,
    )


def make_accepted_result(
    *,
    season: int = 2026,
    week: int = 1,
    kickoff_utc: str = "2026-09-10T00:15:00Z",
    away_team: str = "NE",
    home_team: str = "SEA",
    away_score: int = 17,
    home_score: int = 24,
    source: str = "odds_api",
    source_event_id: str = "evt-001",
    source_result_version: str = "v1",
    first_observed_at_utc: str = "2026-09-10T05:00:00Z",
    confirmed_at_utc: str = "2026-09-10T05:02:00Z",
    accepted_at_utc: str = "2026-09-10T05:02:01Z",
    acceptance_policy_version: str = "single_source_two_observation_v1",
) -> AcceptedFinalGameResult:
    identity = make_identity(
        season=season,
        week=week,
        kickoff_utc=kickoff_utc,
        away_team=away_team,
        home_team=home_team,
    )
    draft = AcceptedFinalGameResult(
        result_id="",
        canonical_event_key=identity.canonical_event_key,
        season=season,
        week=week,
        kickoff_utc=identity.kickoff_utc,
        away_team=away_team,
        home_team=home_team,
        away_score=away_score,
        home_score=home_score,
        accepted_status=NormalizedResultStatus.FINAL,
        source=source,
        source_event_id=source_event_id,
        source_result_version=source_result_version,
        first_observed_at_utc=first_observed_at_utc,
        confirmed_at_utc=confirmed_at_utc,
        accepted_at_utc=accepted_at_utc,
        confirmation_count=2,
        observation_ids=("obs-a", "obs-b"),
        payload_hash="",
        acceptance_policy_version=acceptance_policy_version,
        correction_of_result_id=None,
    )
    with_hash = replace(draft, payload_hash=accepted_result_payload_hash(draft))
    return replace(with_hash, result_id=deterministic_result_id(with_hash))


def make_engine(tmp_path: Path, *, min_seconds: int = 60) -> ResultAcceptanceEngine:
    store = make_store(tmp_path)
    return ResultAcceptanceEngine(store=store, policy=make_policy(min_seconds))
