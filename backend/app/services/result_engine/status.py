from __future__ import annotations

from enum import Enum
from typing import Any


class NormalizedResultStatus(str, Enum):
    FINAL = "FINAL"
    COMPLETED = "COMPLETED"
    POSTGAME = "POSTGAME"
    IN_PROGRESS = "IN_PROGRESS"
    HALFTIME = "HALFTIME"
    SCHEDULED = "SCHEDULED"
    DELAYED = "DELAYED"
    POSTPONED = "POSTPONED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"
    ABANDONED = "ABANDONED"
    UNKNOWN = "UNKNOWN"


_STATUS_ALIASES = {
    "FINAL": NormalizedResultStatus.FINAL,
    "COMPLETE": NormalizedResultStatus.COMPLETED,
    "COMPLETED": NormalizedResultStatus.COMPLETED,
    "POST": NormalizedResultStatus.POSTGAME,
    "POSTGAME": NormalizedResultStatus.POSTGAME,
    "IN_PROGRESS": NormalizedResultStatus.IN_PROGRESS,
    "INPROGRESS": NormalizedResultStatus.IN_PROGRESS,
    "LIVE": NormalizedResultStatus.IN_PROGRESS,
    "HALFTIME": NormalizedResultStatus.HALFTIME,
    "SCHEDULED": NormalizedResultStatus.SCHEDULED,
    "DELAYED": NormalizedResultStatus.DELAYED,
    "POSTPONED": NormalizedResultStatus.POSTPONED,
    "SUSPENDED": NormalizedResultStatus.SUSPENDED,
    "CANCELLED": NormalizedResultStatus.CANCELLED,
    "ABANDONED": NormalizedResultStatus.ABANDONED,
    "UNKNOWN": NormalizedResultStatus.UNKNOWN,
}


def normalize_result_status(value: Any) -> NormalizedResultStatus:
    if isinstance(value, NormalizedResultStatus):
        return value
    token = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if token.startswith("NORMALIZEDRESULTSTATUS."):
        token = token.split(".", 1)[1]
    if not token:
        return NormalizedResultStatus.UNKNOWN
    return _STATUS_ALIASES.get(token, NormalizedResultStatus.UNKNOWN)
