from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from .contracts import (
    AcceptedFinalGameResult,
    RawResultObservation,
    ResultCorrectionCandidate,
    SourceEventBridgeRecord,
)
from .hashing import canonical_json, sha256_hex
from .policy import DEFAULT_RESULT_ACCEPTANCE_POLICY, ResultAcceptancePolicy
from .persistence import ResultEnginePersistenceError, ResultEngineStore
from .validation import (
    ResultEngineValidationError,
    accepted_result_payload_hash,
    deterministic_bridge_id,
    deterministic_observation_id,
    deterministic_result_id,
    observation_source_evidence_hash,
    observation_payload_hash,
    validate_observation_finality_for_acceptance,
    validate_raw_observation,
)


class ResultEngineAcceptanceError(ValueError):
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _to_utc(value: str) -> datetime:
    return _parse_iso(value).astimezone(timezone.utc)


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


def build_raw_observation(
    *,
    source: str,
    source_event_id: str,
    source_observation_id: str,
    canonical_event_key: str,
    season: int,
    week: int,
    kickoff_utc: str,
    away_team: str,
    home_team: str,
    status: Any,
    away_score: int | None,
    home_score: int | None,
    observed_at_utc: str,
    source_result_version: str,
    provider_published_at_utc: str | None = None,
) -> RawResultObservation:
    from .status import normalize_result_status

    draft = RawResultObservation(
        observation_id="",
        source=str(source).strip(),
        source_event_id=str(source_event_id).strip(),
        source_observation_id=str(source_observation_id).strip(),
        canonical_event_key=str(canonical_event_key).strip(),
        season=season,
        week=week,
        kickoff_utc=kickoff_utc,
        away_team=away_team,
        home_team=home_team,
        status=normalize_result_status(status),
        away_score=away_score,
        home_score=home_score,
        observed_at_utc=observed_at_utc,
        provider_published_at_utc=provider_published_at_utc,
        source_evidence_hash="",
        payload_hash="",
        source_result_version=str(source_result_version).strip(),
    )
    with_source_evidence = replace(draft, source_evidence_hash=observation_source_evidence_hash(draft))
    with_hash = replace(with_source_evidence, payload_hash=observation_payload_hash(with_source_evidence))
    return replace(with_hash, observation_id=deterministic_observation_id(with_hash))


def _build_accepted_result(
    *,
    first: RawResultObservation,
    confirmed: RawResultObservation,
    policy: ResultAcceptancePolicy,
    accepted_at_utc: str,
) -> AcceptedFinalGameResult:
    if first.away_score is None or first.home_score is None:
        raise ResultEngineAcceptanceError("Final acceptance requires both scores")
    if confirmed.away_score is None or confirmed.home_score is None:
        raise ResultEngineAcceptanceError("Final acceptance requires both scores")

    draft = AcceptedFinalGameResult(
        result_id="",
        canonical_event_key=first.canonical_event_key,
        season=first.season,
        week=first.week,
        kickoff_utc=first.kickoff_utc,
        away_team=first.away_team,
        home_team=first.home_team,
        away_score=int(first.away_score),
        home_score=int(first.home_score),
        accepted_status=first.status,
        source=first.source,
        source_event_id=first.source_event_id,
        source_result_version=first.source_result_version,
        first_observed_at_utc=first.observed_at_utc,
        confirmed_at_utc=confirmed.observed_at_utc,
        accepted_at_utc=accepted_at_utc,
        confirmation_count=2,
        observation_ids=(first.observation_id, confirmed.observation_id),
        payload_hash="",
        acceptance_policy_version=policy.version,
        correction_of_result_id=None,
    )
    with_hash = replace(draft, payload_hash=accepted_result_payload_hash(draft))
    return replace(with_hash, result_id=deterministic_result_id(with_hash))


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


class ResultAcceptanceEngine:
    def __init__(
        self,
        *,
        store: ResultEngineStore | None = None,
        policy: ResultAcceptancePolicy = DEFAULT_RESULT_ACCEPTANCE_POLICY,
    ) -> None:
        self.store = store or ResultEngineStore()
        self.policy = policy

    def ingest_raw_observation(self, observation: RawResultObservation) -> dict[str, Any]:
        try:
            validated = validate_raw_observation(observation)
        except ResultEngineValidationError as exc:
            raise ResultEngineAcceptanceError(str(exc)) from exc

        try:
            persisted = self.store.persist_observation(validated)
        except ResultEnginePersistenceError as exc:
            raise ResultEngineAcceptanceError(str(exc)) from exc

        bridge = _build_bridge_record(persisted)
        try:
            self.store.persist_source_event_bridge(bridge)
        except ResultEnginePersistenceError as exc:
            raise ResultEngineAcceptanceError(str(exc)) from exc

        try:
            validate_observation_finality_for_acceptance(persisted, policy=self.policy)
        except ResultEngineValidationError:
            return {
                "status": "OBSERVED_NOT_FINAL",
                "observationId": persisted.observation_id,
                "accepted": None,
                "correctionCandidateId": None,
            }

        existing = self.store.get_accepted_result_for_event(persisted.canonical_event_key)
        if existing is not None:
            same_scores = (
                int(existing.away_score) == int(persisted.away_score)
                and int(existing.home_score) == int(persisted.home_score)
            )
            same_source = (
                existing.source == persisted.source
                and existing.source_event_id == persisted.source_event_id
                and existing.source_result_version == persisted.source_result_version
            )
            if same_scores and same_source:
                return {
                    "status": "ALREADY_ACCEPTED",
                    "observationId": persisted.observation_id,
                    "accepted": existing,
                    "correctionCandidateId": None,
                }

            candidate = _build_correction_candidate(existing=existing, observation=persisted)
            persisted_candidate = self.store.persist_correction_candidate(candidate)
            return {
                "status": "CORRECTION_CANDIDATE",
                "observationId": persisted.observation_id,
                "accepted": existing,
                "correctionCandidateId": persisted_candidate.candidate_id,
            }

        observations = self.store.list_observations_for_source_event(
            source=persisted.source,
            source_event_id=persisted.source_event_id,
            canonical_event_key=persisted.canonical_event_key,
        )

        candidates = [
            obs
            for obs in observations
            if obs.status in self.policy.final_statuses
            and obs.away_score == persisted.away_score
            and obs.home_score == persisted.home_score
            and obs.source_result_version == persisted.source_result_version
            and obs.provider_published_at_utc is not None
        ]

        # Independent evidence requires distinct provider/source observations.
        dedup_by_source_observation: dict[str, RawResultObservation] = {}
        for candidate in sorted(candidates, key=lambda item: item.provider_published_at_utc or ""):
            dedup_by_source_observation[candidate.source_observation_id] = candidate
        candidates = list(dedup_by_source_observation.values())

        if len(candidates) < 2:
            return {
                "status": "PENDING_CONFIRMATION",
                "observationId": persisted.observation_id,
                "accepted": None,
                "correctionCandidateId": None,
            }

        first = candidates[0]
        second = candidates[-1]
        if first.provider_published_at_utc is None or second.provider_published_at_utc is None:
            return {
                "status": "PENDING_TRUSTED_PROVENANCE",
                "observationId": persisted.observation_id,
                "accepted": None,
                "correctionCandidateId": None,
            }

        first_published = _to_utc(first.provider_published_at_utc)
        second_published = _to_utc(second.provider_published_at_utc)
        if second_published <= first_published:
            return {
                "status": "PENDING_TRUSTED_PROVENANCE",
                "observationId": persisted.observation_id,
                "accepted": None,
                "correctionCandidateId": None,
            }

        delta_seconds = (second_published - first_published).total_seconds()
        if delta_seconds < float(self.policy.min_confirmation_interval_seconds):
            return {
                "status": "PENDING_CONFIRMATION_INTERVAL",
                "observationId": persisted.observation_id,
                "accepted": None,
                "correctionCandidateId": None,
            }

        accepted = _build_accepted_result(
            first=first,
            confirmed=second,
            policy=self.policy,
            accepted_at_utc=_utc_now_iso(),
        )
        persisted_result = self.store.persist_accepted_result(accepted)
        return {
            "status": "ACCEPTED",
            "observationId": persisted.observation_id,
            "accepted": persisted_result,
            "correctionCandidateId": None,
        }
