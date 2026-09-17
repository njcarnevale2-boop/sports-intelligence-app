from __future__ import annotations

import os
from dataclasses import dataclass

from .status import NormalizedResultStatus


DEFAULT_ACCEPTANCE_POLICY_VERSION = "single_source_two_observation_v1"
DEFAULT_MIN_CONFIRMATION_INTERVAL_SECONDS = int(
    str(os.getenv("RESULT_ENGINE_MIN_CONFIRMATION_INTERVAL_SECONDS", "60") or "60").strip()
)


@dataclass(frozen=True)
class ResultAcceptancePolicy:
    version: str
    min_confirmation_interval_seconds: int
    final_statuses: frozenset[NormalizedResultStatus]


DEFAULT_RESULT_ACCEPTANCE_POLICY = ResultAcceptancePolicy(
    version=DEFAULT_ACCEPTANCE_POLICY_VERSION,
    min_confirmation_interval_seconds=max(1, DEFAULT_MIN_CONFIRMATION_INTERVAL_SECONDS),
    final_statuses=frozenset(
        {
            NormalizedResultStatus.FINAL,
            NormalizedResultStatus.COMPLETED,
            NormalizedResultStatus.POSTGAME,
        }
    ),
)
