from __future__ import annotations

from dataclasses import dataclass

from .status import NormalizedResultStatus


@dataclass(frozen=True)
class RawResultObservation:
    observation_id: str
    source: str
    source_event_id: str
    source_observation_id: str
    canonical_event_key: str
    season: int
    week: int
    kickoff_utc: str
    away_team: str
    home_team: str
    status: NormalizedResultStatus
    away_score: int | None
    home_score: int | None
    observed_at_utc: str
    provider_published_at_utc: str | None
    source_evidence_hash: str
    payload_hash: str
    source_result_version: str


@dataclass(frozen=True)
class AcceptedFinalGameResult:
    result_id: str
    canonical_event_key: str
    season: int
    week: int
    kickoff_utc: str
    away_team: str
    home_team: str
    away_score: int
    home_score: int
    accepted_status: NormalizedResultStatus
    source: str
    source_event_id: str
    source_result_version: str
    first_observed_at_utc: str
    confirmed_at_utc: str
    accepted_at_utc: str
    confirmation_count: int
    observation_ids: tuple[str, ...]
    payload_hash: str
    acceptance_policy_version: str
    correction_of_result_id: str | None


@dataclass(frozen=True)
class SourceEventBridgeRecord:
    bridge_id: str
    source: str
    source_event_id: str
    canonical_event_key: str
    created_at_utc: str
    first_observation_id: str


@dataclass(frozen=True)
class ResultCorrectionCandidate:
    candidate_id: str
    canonical_event_key: str
    existing_result_id: str
    conflicting_observation_id: str
    source: str
    source_event_id: str
    conflicting_away_score: int | None
    conflicting_home_score: int | None
    detected_at_utc: str
    reason_code: str
