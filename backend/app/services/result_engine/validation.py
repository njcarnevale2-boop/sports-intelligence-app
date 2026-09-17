from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .contracts import AcceptedFinalGameResult, RawResultObservation, SourceEventBridgeRecord
from .hashing import canonical_json, sha256_hex
from .identity import build_canonical_event_identity, normalize_kickoff_utc
from .policy import ResultAcceptancePolicy
from .status import NormalizedResultStatus
from .teams import normalize_team_id

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


class ResultEngineValidationError(ValueError):
    pass


def _validate_identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResultEngineValidationError(f"{field_name} must be a non-empty string")
    text = value.strip()
    if text in {".", ".."}:
        raise ResultEngineValidationError(f"{field_name} contains unsupported characters: {text}")
    if not _IDENTIFIER_RE.match(text):
        raise ResultEngineValidationError(f"{field_name} contains unsupported characters: {text}")
    return text


def parse_iso_timestamp(value: Any, field_name: str) -> str:
    if value is None:
        raise ResultEngineValidationError(f"{field_name} is required")
    if not isinstance(value, str) or not value.strip():
        raise ResultEngineValidationError(f"{field_name} must be a non-empty string")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ResultEngineValidationError(f"Invalid {field_name}: {value}") from exc
    if parsed.tzinfo is None:
        raise ResultEngineValidationError(f"{field_name} must include timezone information")
    return value.strip()


def _parse_utc_timestamp(value: Any, field_name: str) -> datetime:
    normalized = parse_iso_timestamp(value, field_name)
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)


def _validate_positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ResultEngineValidationError(f"{field_name} must be a positive integer")
    return value


def _validate_non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResultEngineValidationError(f"{field_name} must be an integer")
    if value < 0:
        raise ResultEngineValidationError(f"{field_name} must be non-negative")
    return value


def observation_source_evidence_payload(observation: RawResultObservation) -> dict[str, Any]:
    return {
        "source": observation.source,
        "source_event_id": observation.source_event_id,
        "source_observation_id": observation.source_observation_id,
        "canonical_event_key": observation.canonical_event_key,
        "season": observation.season,
        "week": observation.week,
        "kickoff_utc": observation.kickoff_utc,
        "away_team": observation.away_team,
        "home_team": observation.home_team,
        "status": observation.status.value,
        "away_score": observation.away_score,
        "home_score": observation.home_score,
        "provider_published_at_utc": observation.provider_published_at_utc,
        "source_result_version": observation.source_result_version,
    }


def observation_source_evidence_hash(observation: RawResultObservation) -> str:
    return sha256_hex(canonical_json(observation_source_evidence_payload(observation)))


def observation_payload_for_hash(observation: RawResultObservation) -> dict[str, Any]:
    return {
        "source_evidence_hash": observation.source_evidence_hash,
        "observed_at_utc": observation.observed_at_utc,
    }


def observation_payload_hash(observation: RawResultObservation) -> str:
    return sha256_hex(canonical_json(observation_payload_for_hash(observation)))


def observation_identity_fields(observation: RawResultObservation) -> dict[str, Any]:
    return {
        "source": observation.source,
        "source_event_id": observation.source_event_id,
        "source_observation_id": observation.source_observation_id,
        "source_evidence_hash": observation.source_evidence_hash,
    }


def deterministic_observation_id(observation: RawResultObservation) -> str:
    return f"obs-{sha256_hex(canonical_json(observation_identity_fields(observation)))[:24]}"


def accepted_result_payload_for_hash(result: AcceptedFinalGameResult) -> dict[str, Any]:
    return {
        "canonical_event_key": result.canonical_event_key,
        "season": result.season,
        "week": result.week,
        "kickoff_utc": result.kickoff_utc,
        "away_team": result.away_team,
        "home_team": result.home_team,
        "away_score": result.away_score,
        "home_score": result.home_score,
        "accepted_status": result.accepted_status.value,
        "source": result.source,
        "source_event_id": result.source_event_id,
        "source_result_version": result.source_result_version,
        "first_observed_at_utc": result.first_observed_at_utc,
        "confirmed_at_utc": result.confirmed_at_utc,
        "accepted_at_utc": result.accepted_at_utc,
        "confirmation_count": result.confirmation_count,
        "observation_ids": list(result.observation_ids),
        "acceptance_policy_version": result.acceptance_policy_version,
        "correction_of_result_id": result.correction_of_result_id,
    }


def accepted_result_payload_hash(result: AcceptedFinalGameResult) -> str:
    return sha256_hex(canonical_json(accepted_result_payload_for_hash(result)))


def deterministic_result_id(result: AcceptedFinalGameResult) -> str:
    identity = {
        "canonical_event_key": result.canonical_event_key,
        "source": result.source,
        "source_event_id": result.source_event_id,
        "away_score": result.away_score,
        "home_score": result.home_score,
        "source_result_version": result.source_result_version,
        "acceptance_policy_version": result.acceptance_policy_version,
        "correction_of_result_id": result.correction_of_result_id,
    }
    return f"res-{sha256_hex(canonical_json(identity))[:24]}"


def deterministic_bridge_id(record: SourceEventBridgeRecord) -> str:
    identity = {"source": record.source, "source_event_id": record.source_event_id}
    return f"bridge-{sha256_hex(canonical_json(identity))[:24]}"


def validate_raw_observation(observation: RawResultObservation) -> RawResultObservation:
    source = _validate_identifier(observation.source, "source")
    source_event_id = _validate_identifier(observation.source_event_id, "source_event_id")
    source_observation_id = _validate_identifier(observation.source_observation_id, "source_observation_id")
    canonical_event_key = _validate_identifier(observation.canonical_event_key, "canonical_event_key")
    _validate_positive_int(observation.season, "season")
    _validate_positive_int(observation.week, "week")

    kickoff = normalize_kickoff_utc(observation.kickoff_utc)
    away = normalize_team_id(observation.away_team)
    home = normalize_team_id(observation.home_team)
    if away == home:
        raise ResultEngineValidationError("away_team and home_team cannot match")

    identity = build_canonical_event_identity(
        season=observation.season,
        week=observation.week,
        kickoff_utc=kickoff,
        away_team=away,
        home_team=home,
    )
    if identity.canonical_event_key != canonical_event_key:
        raise ResultEngineValidationError(
            "canonical_event_key does not match canonical identity fields"
        )

    if not isinstance(observation.status, NormalizedResultStatus):
        raise ResultEngineValidationError("status must be a NormalizedResultStatus")

    away_score = observation.away_score
    home_score = observation.home_score
    if away_score is not None:
        _validate_non_negative_int(away_score, "away_score")
    if home_score is not None:
        _validate_non_negative_int(home_score, "home_score")

    observed_at = _parse_utc_timestamp(observation.observed_at_utc, "observed_at_utc")
    now = datetime.now(timezone.utc)
    if observed_at > now:
        raise ResultEngineValidationError("observed_at_utc cannot be in the future")

    provider_published_at = None
    if observation.provider_published_at_utc is not None:
        provider_published_at = _parse_utc_timestamp(observation.provider_published_at_utc, "provider_published_at_utc")
        if provider_published_at > observed_at:
            raise ResultEngineValidationError("provider_published_at_utc cannot be after observed_at_utc")

    _ = (source, source_event_id, source_observation_id)
    _validate_identifier(observation.source_evidence_hash, "source_evidence_hash")
    _validate_identifier(observation.payload_hash, "payload_hash")
    _validate_identifier(observation.source_result_version, "source_result_version")

    expected_source_evidence_hash = observation_source_evidence_hash(observation)
    if observation.source_evidence_hash != expected_source_evidence_hash:
        raise ResultEngineValidationError(
            f"Observation source evidence hash mismatch: provided={observation.source_evidence_hash} expected={expected_source_evidence_hash}"
        )

    expected_payload_hash = observation_payload_hash(observation)
    if observation.payload_hash != expected_payload_hash:
        raise ResultEngineValidationError(
            f"Observation payload hash mismatch: provided={observation.payload_hash} expected={expected_payload_hash}"
        )

    expected_observation_id = deterministic_observation_id(observation)
    if observation.observation_id != expected_observation_id:
        raise ResultEngineValidationError(
            f"Observation id mismatch: provided={observation.observation_id} expected={expected_observation_id}"
        )

    return observation


def validate_observation_finality_for_acceptance(
    observation: RawResultObservation,
    *,
    policy: ResultAcceptancePolicy,
) -> None:
    if observation.status not in policy.final_statuses:
        raise ResultEngineValidationError(
            f"Status is not final for acceptance: {observation.status.value}"
        )
    if observation.away_score is None or observation.home_score is None:
        raise ResultEngineValidationError("Final observations require both scores")
    _validate_non_negative_int(observation.away_score, "away_score")
    _validate_non_negative_int(observation.home_score, "home_score")


def validate_accepted_result(result: AcceptedFinalGameResult) -> AcceptedFinalGameResult:
    _validate_identifier(result.result_id, "result_id")
    _validate_identifier(result.canonical_event_key, "canonical_event_key")
    _validate_positive_int(result.season, "season")
    _validate_positive_int(result.week, "week")
    kickoff = normalize_kickoff_utc(result.kickoff_utc)
    away = normalize_team_id(result.away_team)
    home = normalize_team_id(result.home_team)
    if away == home:
        raise ResultEngineValidationError("away_team and home_team cannot match")

    identity = build_canonical_event_identity(
        season=result.season,
        week=result.week,
        kickoff_utc=kickoff,
        away_team=away,
        home_team=home,
    )
    if identity.canonical_event_key != result.canonical_event_key:
        raise ResultEngineValidationError(
            "canonical_event_key does not match canonical identity fields"
        )

    if not isinstance(result.accepted_status, NormalizedResultStatus):
        raise ResultEngineValidationError("accepted_status must be a NormalizedResultStatus")

    _validate_non_negative_int(result.away_score, "away_score")
    _validate_non_negative_int(result.home_score, "home_score")

    _validate_identifier(result.source, "source")
    _validate_identifier(result.source_event_id, "source_event_id")
    _validate_identifier(result.source_result_version, "source_result_version")
    first_observed_at = _parse_utc_timestamp(result.first_observed_at_utc, "first_observed_at_utc")
    confirmed_at = _parse_utc_timestamp(result.confirmed_at_utc, "confirmed_at_utc")
    accepted_at = _parse_utc_timestamp(result.accepted_at_utc, "accepted_at_utc")
    if confirmed_at < first_observed_at:
        raise ResultEngineValidationError("confirmed_at_utc cannot be earlier than first_observed_at_utc")
    if accepted_at < confirmed_at:
        raise ResultEngineValidationError("accepted_at_utc cannot be earlier than confirmed_at_utc")

    if isinstance(result.confirmation_count, bool) or not isinstance(result.confirmation_count, int) or result.confirmation_count < 2:
        raise ResultEngineValidationError("confirmation_count must be an integer >= 2")

    if not isinstance(result.observation_ids, tuple) or len(result.observation_ids) < 2:
        raise ResultEngineValidationError("observation_ids must include at least two ids")
    for index, item in enumerate(result.observation_ids):
        _validate_identifier(item, f"observation_ids[{index}]")

    _validate_identifier(result.acceptance_policy_version, "acceptance_policy_version")
    _validate_identifier(result.payload_hash, "payload_hash")

    expected_payload_hash = accepted_result_payload_hash(result)
    if result.payload_hash != expected_payload_hash:
        raise ResultEngineValidationError(
            f"Accepted result payload hash mismatch: provided={result.payload_hash} expected={expected_payload_hash}"
        )

    expected_result_id = deterministic_result_id(result)
    if result.result_id != expected_result_id:
        raise ResultEngineValidationError(
            f"Accepted result id mismatch: provided={result.result_id} expected={expected_result_id}"
        )

    return result


def validate_source_event_bridge(record: SourceEventBridgeRecord) -> SourceEventBridgeRecord:
    _validate_identifier(record.bridge_id, "bridge_id")
    _validate_identifier(record.source, "source")
    _validate_identifier(record.source_event_id, "source_event_id")
    _validate_identifier(record.canonical_event_key, "canonical_event_key")
    _validate_identifier(record.first_observation_id, "first_observation_id")
    parse_iso_timestamp(record.created_at_utc, "created_at_utc")

    expected_bridge_id = deterministic_bridge_id(record)
    if record.bridge_id != expected_bridge_id:
        raise ResultEngineValidationError(
            f"Bridge id mismatch: provided={record.bridge_id} expected={expected_bridge_id}"
        )

    return record
