from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import re
from typing import Any

from .contracts import AcceptedFinalGameResult, RawResultObservation, ResultCorrectionCandidate, SourceEventBridgeRecord
from .engine import build_raw_observation
from .hashing import canonical_json, sha256_hex
from .identity import build_canonical_event_identity
from .persistence import ResultEngineStore
from .status import NormalizedResultStatus
from .validation import accepted_result_payload_hash, deterministic_bridge_id, deterministic_result_id

NFLVERSE_VERSIONED_RESULT_POLICY_VERSION = "nflverse_versioned_result_v1"
NFLVERSE_VERSIONED_SOURCE = "nflverse"

_ARTIFACT_SHA256_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


class NflverseAdapterError(ValueError):
    pass


@dataclass(frozen=True)
class NflverseArtifactDescriptor:
    provider: str
    dataset: str
    source_locator: str
    artifact_sha256: str
    retrieved_at_utc: str
    release_version: str | None = None


@dataclass(frozen=True)
class NflverseVersionedResultEvidence:
    season: int
    week: int
    game_id: str
    kickoff_utc: str
    away_team: str
    home_team: str
    away_score: int | None
    home_score: int | None
    artifact: NflverseArtifactDescriptor


@dataclass(frozen=True)
class NflverseTrustedIngestResult:
    status: str
    observation_id: str | None
    accepted: AcceptedFinalGameResult | None
    correction_candidate_id: str | None
    artifact: NflverseArtifactDescriptor
    source_result_version: str | None


def _parse_iso_utc(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise NflverseAdapterError(f"{field_name} must be a non-empty string")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise NflverseAdapterError(f"Invalid {field_name}: {value}") from exc
    if parsed.tzinfo is None:
        raise NflverseAdapterError(f"{field_name} must include timezone information")
    return parsed.astimezone(timezone.utc)


def _to_iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NflverseAdapterError(f"{field_name} must be a non-empty string")
    text = value.strip()
    if text in {".", ".."}:
        raise NflverseAdapterError(f"{field_name} contains unsupported characters: {text}")
    if not _IDENTIFIER_RE.match(text):
        raise NflverseAdapterError(f"{field_name} contains unsupported characters: {text}")
    return text


def _validate_non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NflverseAdapterError(f"{field_name} must be an integer")
    if value < 0:
        raise NflverseAdapterError(f"{field_name} must be non-negative")
    return value


def _normalize_artifact_descriptor(descriptor: NflverseArtifactDescriptor) -> NflverseArtifactDescriptor:
    provider = _validate_identifier(descriptor.provider, "provider").lower()
    if provider != "nflverse":
        raise NflverseAdapterError("provider must be nflverse")

    dataset = _validate_identifier(descriptor.dataset, "dataset")
    source_locator = descriptor.source_locator.strip() if isinstance(descriptor.source_locator, str) else ""
    if not source_locator:
        raise NflverseAdapterError("source_locator must be a non-empty string")

    artifact_sha256 = descriptor.artifact_sha256.strip() if isinstance(descriptor.artifact_sha256, str) else ""
    if not _ARTIFACT_SHA256_RE.match(artifact_sha256):
        raise NflverseAdapterError("artifact_sha256 must be a 64-character hexadecimal SHA-256 digest")

    retrieved_at = _to_iso_z(_parse_iso_utc(descriptor.retrieved_at_utc, "retrieved_at_utc"))
    release_version = None
    if descriptor.release_version is not None:
        release_text = descriptor.release_version.strip()
        if not release_text:
            raise NflverseAdapterError("release_version must be a non-empty string when provided")
        release_version = release_text

    return NflverseArtifactDescriptor(
        provider=provider,
        dataset=dataset,
        source_locator=source_locator,
        artifact_sha256=artifact_sha256.lower(),
        retrieved_at_utc=retrieved_at,
        release_version=release_version,
    )


def _result_identity_payload(evidence: NflverseVersionedResultEvidence, artifact: NflverseArtifactDescriptor) -> dict[str, Any]:
    return {
        "version": "nflverse-versioned-result-v1",
        "provider": artifact.provider,
        "dataset": artifact.dataset,
        "release_version": artifact.release_version or "",
        "artifact_sha256": artifact.artifact_sha256,
        "result_state": "completed",
        "season": int(evidence.season),
        "week": int(evidence.week),
        "game_id": evidence.game_id,
        "kickoff_utc": evidence.kickoff_utc,
        "away_team": evidence.away_team,
        "home_team": evidence.home_team,
        "away_score": evidence.away_score,
        "home_score": evidence.home_score,
    }


def derive_source_result_version(evidence: NflverseVersionedResultEvidence, artifact: NflverseArtifactDescriptor) -> str:
    payload = _result_identity_payload(evidence, artifact)
    return f"derived:nflverse-versioned-result-v1:{sha256_hex(canonical_json(payload))[:24]}"


def derive_source_observation_id(
    evidence: NflverseVersionedResultEvidence,
    *,
    source_result_version: str,
) -> str:
    payload = {
        "version": "nflverse-versioned-observation-v1",
        "game_id": evidence.game_id,
        "source_result_version": source_result_version,
    }
    return f"derived:nflverse-versioned-observation-v1:{sha256_hex(canonical_json(payload))[:24]}"


def build_nflverse_raw_observation(
    evidence: NflverseVersionedResultEvidence,
    *,
    evidence_origin: str,
    source_label: str = NFLVERSE_VERSIONED_SOURCE,
) -> RawResultObservation:
    artifact = _normalize_artifact_descriptor(evidence.artifact)

    season = _validate_non_negative_int(evidence.season, "season")
    week = _validate_non_negative_int(evidence.week, "week")
    if evidence.away_score is None or evidence.home_score is None:
        raise NflverseAdapterError("completed nflverse rows require both scores")
    away_score = _validate_non_negative_int(evidence.away_score, "away_score")
    home_score = _validate_non_negative_int(evidence.home_score, "home_score")

    game_id = _validate_identifier(evidence.game_id, "game_id")
    canonical = build_canonical_event_identity(
        season=season,
        week=week,
        kickoff_utc=evidence.kickoff_utc,
        away_team=evidence.away_team,
        home_team=evidence.home_team,
    )

    source_result_version = derive_source_result_version(evidence, artifact)
    source_observation_id = derive_source_observation_id(evidence, source_result_version=source_result_version)

    return build_raw_observation(
        source=source_label,
        source_event_id=game_id,
        source_observation_id=source_observation_id,
        canonical_event_key=canonical.canonical_event_key,
        season=season,
        week=week,
        kickoff_utc=canonical.kickoff_utc,
        away_team=canonical.away_team,
        home_team=canonical.home_team,
        status=NormalizedResultStatus.COMPLETED,
        away_score=away_score,
        home_score=home_score,
        observed_at_utc=artifact.retrieved_at_utc,
        source_result_version=source_result_version,
        provider_published_at_utc=None,
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
        raise NflverseAdapterError("completed nflverse rows require both scores")

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
        accepted_status=NormalizedResultStatus.COMPLETED,
        source=observation.source,
        source_event_id=observation.source_event_id,
        source_result_version=observation.source_result_version,
        first_observed_at_utc=observation.observed_at_utc,
        confirmed_at_utc=observation.observed_at_utc,
        accepted_at_utc=accepted_at,
        confirmation_count=2,
        observation_ids=(observation.observation_id, observation.observation_id),
        payload_hash="",
        acceptance_policy_version=NFLVERSE_VERSIONED_RESULT_POLICY_VERSION,
        correction_of_result_id=None,
    )
    with_hash = replace(draft, payload_hash=accepted_result_payload_hash(draft))
    return replace(with_hash, result_id=deterministic_result_id(with_hash))


class NflverseVersionedResultIngester:
    def __init__(self, *, store: ResultEngineStore | None = None) -> None:
        self.store = store or ResultEngineStore()

    def ingest_evidence(
        self,
        evidence: NflverseVersionedResultEvidence,
        *,
        evidence_origin: str,
    ) -> NflverseTrustedIngestResult:
        artifact = _normalize_artifact_descriptor(evidence.artifact)
        observation = build_nflverse_raw_observation(
            NflverseVersionedResultEvidence(
                season=evidence.season,
                week=evidence.week,
                game_id=evidence.game_id,
                kickoff_utc=evidence.kickoff_utc,
                away_team=evidence.away_team,
                home_team=evidence.home_team,
                away_score=evidence.away_score,
                home_score=evidence.home_score,
                artifact=artifact,
            ),
            evidence_origin=evidence_origin,
        )

        persisted_observation = self.store.persist_observation(observation)
        self.store.persist_source_event_bridge(_build_bridge_record(persisted_observation))

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
                return NflverseTrustedIngestResult(
                    status="ALREADY_ACCEPTED",
                    observation_id=persisted_observation.observation_id,
                    accepted=existing,
                    correction_candidate_id=None,
                    artifact=artifact,
                    source_result_version=persisted_observation.source_result_version,
                )

            candidate = self.store.persist_correction_candidate(
                _build_correction_candidate(existing=existing, observation=persisted_observation)
            )
            return NflverseTrustedIngestResult(
                status="CORRECTION_CANDIDATE",
                observation_id=persisted_observation.observation_id,
                accepted=existing,
                correction_candidate_id=candidate.candidate_id,
                artifact=artifact,
                source_result_version=persisted_observation.source_result_version,
            )

        accepted = _build_single_observation_accepted_result(persisted_observation)
        persisted_result = self.store.persist_accepted_result(accepted)
        return NflverseTrustedIngestResult(
            status="ACCEPTED",
            observation_id=persisted_observation.observation_id,
            accepted=persisted_result,
            correction_candidate_id=None,
            artifact=artifact,
            source_result_version=persisted_observation.source_result_version,
        )