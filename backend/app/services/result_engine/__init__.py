from .completeness import WeekCompletenessResult, validate_week_completeness
from .contracts import (
    AcceptedFinalGameResult,
    RawResultObservation,
    ResultCorrectionCandidate,
    SourceEventBridgeRecord,
)
from .engine import ResultAcceptanceEngine, build_raw_observation
from .identity import (
    CANONICAL_EVENT_KEY_POLICY_VERSION,
    KICKOFF_NORMALIZATION_POLICY_VERSION,
    CanonicalEventIdentity,
    build_canonical_event_identity,
    build_canonical_event_key,
    normalize_kickoff_utc,
)
from .persistence import (
    ResultEnginePersistenceError,
    ResultEngineStore,
    default_result_engine_store,
)
from .policy import (
    DEFAULT_ACCEPTANCE_POLICY_VERSION,
    DEFAULT_MIN_CONFIRMATION_INTERVAL_SECONDS,
    DEFAULT_RESULT_ACCEPTANCE_POLICY,
    ResultAcceptancePolicy,
)
from .status import NormalizedResultStatus, normalize_result_status
from .teams import CANONICAL_NFL_TEAMS, normalize_team_id
from .validation import (
    ResultEngineValidationError,
    accepted_result_payload_hash,
    deterministic_observation_id,
    deterministic_result_id,
    observation_source_evidence_hash,
    observation_source_evidence_payload,
    observation_payload_hash,
    validate_accepted_result,
    validate_observation_finality_for_acceptance,
    validate_raw_observation,
)

__all__ = [
    "AcceptedFinalGameResult",
    "CANONICAL_EVENT_KEY_POLICY_VERSION",
    "CANONICAL_NFL_TEAMS",
    "CanonicalEventIdentity",
    "DEFAULT_ACCEPTANCE_POLICY_VERSION",
    "DEFAULT_MIN_CONFIRMATION_INTERVAL_SECONDS",
    "DEFAULT_RESULT_ACCEPTANCE_POLICY",
    "KICKOFF_NORMALIZATION_POLICY_VERSION",
    "NormalizedResultStatus",
    "RawResultObservation",
    "ResultAcceptanceEngine",
    "ResultAcceptancePolicy",
    "ResultCorrectionCandidate",
    "ResultEnginePersistenceError",
    "ResultEngineStore",
    "ResultEngineValidationError",
    "SourceEventBridgeRecord",
    "WeekCompletenessResult",
    "accepted_result_payload_hash",
    "build_canonical_event_identity",
    "build_canonical_event_key",
    "build_raw_observation",
    "default_result_engine_store",
    "deterministic_observation_id",
    "deterministic_result_id",
    "normalize_kickoff_utc",
    "normalize_result_status",
    "normalize_team_id",
    "observation_payload_hash",
    "observation_source_evidence_hash",
    "observation_source_evidence_payload",
    "validate_accepted_result",
    "validate_observation_finality_for_acceptance",
    "validate_raw_observation",
    "validate_week_completeness",
]
