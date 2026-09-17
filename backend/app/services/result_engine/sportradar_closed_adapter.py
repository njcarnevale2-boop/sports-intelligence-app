from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from .contracts import AcceptedFinalGameResult, RawResultObservation, ResultCorrectionCandidate, SourceEventBridgeRecord
from .engine import build_raw_observation
from .status import NormalizedResultStatus
from .validation import (
    accepted_result_payload_hash,
    deterministic_bridge_id,
    deterministic_result_id,
)
from .hashing import canonical_json, sha256_hex
from .persistence import ResultEngineStore

SPORTRADAR_CLOSED_POLICY_VERSION = "sportradar_closed_result_v1"
SPORTRADAR_NFL_SOURCE = "sportradar_nfl"


class SportradarAdapterError(ValueError):
    pass


@dataclass(frozen=True)
class SportradarChangeLogRef:
    source_event_id: str
    last_modified: str


@dataclass(frozen=True)
class SportradarResultEvidence:
    source_event_id: str
    season: int
    week: int
    kickoff_utc: str
    away_team: str
    home_team: str
    status: str
    away_score: int | None
    home_score: int | None
    observed_at_utc: str
    canonical_event_key: str
    sport: str = "nfl"
    etag: str | None = None
    x_generated_date: str | None = None
    last_modified: str | None = None
    change_log: SportradarChangeLogRef | None = None


@dataclass(frozen=True)
class SportradarTrustedIngestResult:
    status: str
    observation_id: str | None
    accepted: AcceptedFinalGameResult | None
    correction_candidate_id: str | None


def _parse_iso_utc(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise SportradarAdapterError(f"{field_name} must be a non-empty string")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SportradarAdapterError(f"Invalid {field_name}: {value}") from exc
    if parsed.tzinfo is None:
        raise SportradarAdapterError(f"{field_name} must include timezone information")
    return parsed.astimezone(timezone.utc)


def _to_iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_http_date(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise SportradarAdapterError(f"{field_name} must be a non-empty string")
    try:
        parsed = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError) as exc:
        raise SportradarAdapterError(f"Invalid {field_name}: {value}") from exc
    if parsed is None:
        raise SportradarAdapterError(f"Invalid {field_name}: {value}")
    if parsed.tzinfo is None:
        raise SportradarAdapterError(f"{field_name} must include timezone information")
    return parsed.astimezone(timezone.utc)


def _normalize_status(value: str) -> NormalizedResultStatus:
    token = str(value or "").strip().lower()
    mapping = {
        "scheduled": NormalizedResultStatus.SCHEDULED,
        "created": NormalizedResultStatus.SCHEDULED,
        "inprogress": NormalizedResultStatus.IN_PROGRESS,
        "live": NormalizedResultStatus.IN_PROGRESS,
        "halftime": NormalizedResultStatus.HALFTIME,
        "complete": NormalizedResultStatus.COMPLETED,
        "closed": NormalizedResultStatus.FINAL,
        "postponed": NormalizedResultStatus.POSTPONED,
        "suspended": NormalizedResultStatus.SUSPENDED,
        "cancelled": NormalizedResultStatus.CANCELLED,
        "delayed": NormalizedResultStatus.DELAYED,
    }
    out = mapping.get(token)
    if out is None:
        raise SportradarAdapterError(f"Unknown Sportradar status: {value}")
    return out


def _canonical_provider_payload(evidence: SportradarResultEvidence, normalized_status: NormalizedResultStatus) -> dict[str, Any]:
    return {
        "source_event_id": evidence.source_event_id,
        "season": int(evidence.season),
        "week": int(evidence.week),
        "kickoff_utc": evidence.kickoff_utc,
        "away_team": evidence.away_team,
        "home_team": evidence.home_team,
        "status": normalized_status.value,
        "away_score": evidence.away_score,
        "home_score": evidence.home_score,
        "sport": str(evidence.sport or "").strip().lower(),
    }


def _payload_digest(evidence: SportradarResultEvidence, normalized_status: NormalizedResultStatus) -> str:
    payload = _canonical_provider_payload(evidence, normalized_status)
    return sha256_hex(canonical_json(payload))


def resolve_provider_published_at_utc(evidence: SportradarResultEvidence) -> str:
    observed = _parse_iso_utc(evidence.observed_at_utc, "observed_at_utc")

    if evidence.change_log is not None:
        if evidence.change_log.source_event_id != evidence.source_event_id:
            raise SportradarAdapterError(
                "Daily Change Log identity mismatch: change_log.source_event_id does not match source_event_id"
            )
        published = _parse_iso_utc(evidence.change_log.last_modified, "change_log.last_modified")
    elif evidence.x_generated_date:
        published = _parse_http_date(evidence.x_generated_date, "x_generated_date")
    elif evidence.last_modified:
        published = _parse_http_date(evidence.last_modified, "last_modified")
    else:
        raise SportradarAdapterError("No provider publication timestamp available")

    if published > observed:
        raise SportradarAdapterError("provider_published_at_utc cannot be later than observed_at_utc")

    return _to_iso_z(published)


def derive_source_result_version(evidence: SportradarResultEvidence, normalized_status: NormalizedResultStatus) -> str:
    published = resolve_provider_published_at_utc(evidence)
    digest = _payload_digest(evidence, normalized_status)
    payload = {
        "version": "sr-result-v1",
        "etag": str(evidence.etag or ""),
        "provider_published_at_utc": published,
        "status": normalized_status.value,
        "away_score": evidence.away_score,
        "home_score": evidence.home_score,
        "payload_digest": digest,
    }
    return f"derived:sr-result-v1:{sha256_hex(canonical_json(payload))[:24]}"


def derive_source_observation_id(
    evidence: SportradarResultEvidence,
    normalized_status: NormalizedResultStatus,
    *,
    source_result_version: str,
    evidence_origin: str,
) -> str:
    published = resolve_provider_published_at_utc(evidence)
    payload = {
        "version": "sr-observation-v1",
        "source_event_id": evidence.source_event_id,
        "status": normalized_status.value,
        "away_score": evidence.away_score,
        "home_score": evidence.home_score,
        "provider_published_at_utc": published,
        "source_result_version": source_result_version,
        "evidence_origin": evidence_origin,
    }
    return f"derived:sr-observation-v1:{sha256_hex(canonical_json(payload))[:24]}"


def build_sportradar_raw_observation(
    evidence: SportradarResultEvidence,
    *,
    evidence_origin: str,
    source_label: str = SPORTRADAR_NFL_SOURCE,
) -> RawResultObservation:
    if str(evidence.sport or "").strip().lower() != "nfl":
        raise SportradarAdapterError("Only NFL evidence is supported by sportradar_closed_result_v1")

    normalized_status = _normalize_status(evidence.status)
    published_at = resolve_provider_published_at_utc(evidence)
    source_result_version = derive_source_result_version(evidence, normalized_status)
    source_observation_id = derive_source_observation_id(
        evidence,
        normalized_status,
        source_result_version=source_result_version,
        evidence_origin=evidence_origin,
    )

    return build_raw_observation(
        source=source_label,
        source_event_id=evidence.source_event_id,
        source_observation_id=source_observation_id,
        canonical_event_key=evidence.canonical_event_key,
        season=evidence.season,
        week=evidence.week,
        kickoff_utc=evidence.kickoff_utc,
        away_team=evidence.away_team,
        home_team=evidence.home_team,
        status=normalized_status,
        away_score=evidence.away_score,
        home_score=evidence.home_score,
        observed_at_utc=evidence.observed_at_utc,
        source_result_version=source_result_version,
        provider_published_at_utc=published_at,
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_bridge_record(observation: RawResultObservation) -> SourceEventBridgeRecord:
    draft = SourceEventBridgeRecord(
        bridge_id="",
        source=observation.source,
        source_event_id=observation.source_event_id,
        canonical_event_key=observation.canonical_event_key,
        created_at_utc=observation.observed_at_utc,
        first_observation_id=observation.observation_id,
    )
    return replace(draft, bridge_id=deterministic_bridge_id(draft))


def _build_correction_candidate(
    *,
    existing: AcceptedFinalGameResult,
    observation: RawResultObservation,
) -> ResultCorrectionCandidate:
    identity = {
        "canonical_event_key": existing.canonical_event_key,
        "existing_result_id": existing.result_id,
        "conflicting_observation_id": observation.observation_id,
        "source": observation.source,
        "source_event_id": observation.source_event_id,
        "away_score": observation.away_score,
        "home_score": observation.home_score,
        "reason_code": "FINAL_SCORE_CONFLICT",
    }
    candidate_id = f"corr-{sha256_hex(canonical_json(identity))[:24]}"
    return ResultCorrectionCandidate(
        candidate_id=candidate_id,
        canonical_event_key=existing.canonical_event_key,
        existing_result_id=existing.result_id,
        conflicting_observation_id=observation.observation_id,
        source=observation.source,
        source_event_id=observation.source_event_id,
        conflicting_away_score=observation.away_score,
        conflicting_home_score=observation.home_score,
        detected_at_utc=_utc_now_iso(),
        reason_code="FINAL_SCORE_CONFLICT",
    )


def _build_single_observation_accepted_result(observation: RawResultObservation) -> AcceptedFinalGameResult:
    if observation.away_score is None or observation.home_score is None:
        raise SportradarAdapterError("closed observations must include both scores")

    accepted_at = _utc_now_iso()
    draft = AcceptedFinalGameResult(
        result_id="",
        canonical_event_key=observation.canonical_event_key,
        season=observation.season,
        week=observation.week,
        kickoff_utc=observation.kickoff_utc,
        away_team=observation.away_team,
        home_team=observation.home_team,
        away_score=int(observation.away_score),
        home_score=int(observation.home_score),
        accepted_status=NormalizedResultStatus.FINAL,
        source=observation.source,
        source_event_id=observation.source_event_id,
        source_result_version=observation.source_result_version,
        first_observed_at_utc=observation.observed_at_utc,
        confirmed_at_utc=observation.observed_at_utc,
        accepted_at_utc=accepted_at,
        confirmation_count=2,
        observation_ids=(observation.observation_id, observation.observation_id),
        payload_hash="",
        acceptance_policy_version=SPORTRADAR_CLOSED_POLICY_VERSION,
        correction_of_result_id=None,
    )
    with_hash = replace(draft, payload_hash=accepted_result_payload_hash(draft))
    return replace(with_hash, result_id=deterministic_result_id(with_hash))


class SportradarClosedResultIngester:
    def __init__(self, *, store: ResultEngineStore | None = None) -> None:
        self.store = store or ResultEngineStore()

    def _has_ambiguous_source_event_bridge(self, observation: RawResultObservation) -> bool:
        bridges = self.store.list_source_event_bridges()
        conflicting = {
            bridge.source_event_id
            for bridge in bridges
            if bridge.source == SPORTRADAR_NFL_SOURCE
            and bridge.canonical_event_key == observation.canonical_event_key
            and bridge.source_event_id != observation.source_event_id
        }
        return len(conflicting) > 0

    def ingest_evidence(self, evidence: SportradarResultEvidence, *, evidence_origin: str) -> SportradarTrustedIngestResult:
        observation = build_sportradar_raw_observation(
            evidence,
            evidence_origin=evidence_origin,
            source_label=SPORTRADAR_NFL_SOURCE,
        )

        persisted_observation = self.store.persist_observation(observation)
        self.store.persist_source_event_bridge(_build_bridge_record(persisted_observation))

        if persisted_observation.status != NormalizedResultStatus.FINAL:
            return SportradarTrustedIngestResult(
                status="OBSERVED_NOT_FINAL",
                observation_id=persisted_observation.observation_id,
                accepted=None,
                correction_candidate_id=None,
            )

        if persisted_observation.away_score is None or persisted_observation.home_score is None:
            raise SportradarAdapterError("closed observations must include both scores")

        if self._has_ambiguous_source_event_bridge(persisted_observation):
            raise SportradarAdapterError(
                "Ambiguous postponed or replacement mapping for canonical_event_key; explicit bridge resolution required"
            )

        existing = self.store.get_accepted_result_for_event(persisted_observation.canonical_event_key)
        if existing is not None:
            same_scores = (
                int(existing.away_score) == int(persisted_observation.away_score)
                and int(existing.home_score) == int(persisted_observation.home_score)
            )
            same_source = (
                existing.source == persisted_observation.source
                and existing.source_event_id == persisted_observation.source_event_id
                and existing.source_result_version == persisted_observation.source_result_version
            )
            if same_scores and same_source:
                return SportradarTrustedIngestResult(
                    status="ALREADY_ACCEPTED",
                    observation_id=persisted_observation.observation_id,
                    accepted=existing,
                    correction_candidate_id=None,
                )

            candidate = self.store.persist_correction_candidate(
                _build_correction_candidate(existing=existing, observation=persisted_observation)
            )
            return SportradarTrustedIngestResult(
                status="CORRECTION_CANDIDATE",
                observation_id=persisted_observation.observation_id,
                accepted=existing,
                correction_candidate_id=candidate.candidate_id,
            )

        accepted = _build_single_observation_accepted_result(persisted_observation)
        persisted_result = self.store.persist_accepted_result(accepted)
        return SportradarTrustedIngestResult(
            status="ACCEPTED",
            observation_id=persisted_observation.observation_id,
            accepted=persisted_result,
            correction_candidate_id=None,
        )
