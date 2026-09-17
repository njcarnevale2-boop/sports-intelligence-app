from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .hashing import canonical_json, sha256_hex
from .teams import normalize_team_id


KICKOFF_NORMALIZATION_POLICY_VERSION = "kickoff_utc_second_v1"
CANONICAL_EVENT_KEY_POLICY_VERSION = "stable_matchup_week_v1"


@dataclass(frozen=True)
class CanonicalEventIdentity:
    season: int
    week: int
    kickoff_utc: str
    away_team: str
    home_team: str
    canonical_event_key: str


def _validate_positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _parse_kickoff(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("kickoff_utc must be a non-empty string")
    text = value.strip().replace("Z", "+00:00")
    try:
        kickoff = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Invalid kickoff_utc: {value}") from exc
    if kickoff.tzinfo is None:
        raise ValueError("kickoff_utc must include timezone information")
    return kickoff.astimezone(timezone.utc)


def normalize_kickoff_utc(value: str) -> str:
    """Normalize kickoff into UTC second precision to absorb formatting/sub-second jitter.

    Policy:
    - parse an ISO timestamp with an explicit timezone,
    - convert to UTC,
    - drop microseconds,
    - emit RFC3339-like "YYYY-MM-DDTHH:MM:SSZ".

    This keeps distinct rescheduled times (different second-level instants) separate
    while treating equivalent representations of the same instant as identical.
    """

    kickoff = _parse_kickoff(value)
    kickoff = kickoff.replace(microsecond=0)
    return kickoff.isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_event_identity_payload(*, season: int, week: int, kickoff_utc: str, away_team: str, home_team: str) -> dict[str, Any]:
    # canonical_event_key is intentionally stable across kickoff reschedules.
    # kickoff_utc remains validated metadata for chronology and schedule audits.
    return {
        "season": season,
        "week": week,
        "away_team": away_team,
        "home_team": home_team,
        "canonical_event_key_policy": CANONICAL_EVENT_KEY_POLICY_VERSION,
    }


def build_canonical_event_key(*, season: int, week: int, kickoff_utc: str, away_team: str, home_team: str) -> str:
    payload = canonical_event_identity_payload(
        season=season,
        week=week,
        kickoff_utc=kickoff_utc,
        away_team=away_team,
        home_team=home_team,
    )
    return f"cev-{sha256_hex(canonical_json(payload))[:24]}"


def build_canonical_event_identity(*, season: int, week: int, kickoff_utc: str, away_team: str, home_team: str) -> CanonicalEventIdentity:
    normalized_season = _validate_positive_int(season, "season")
    normalized_week = _validate_positive_int(week, "week")
    normalized_kickoff = normalize_kickoff_utc(kickoff_utc)
    normalized_away = normalize_team_id(away_team)
    normalized_home = normalize_team_id(home_team)
    if normalized_away == normalized_home:
        raise ValueError("away_team and home_team cannot match")

    return CanonicalEventIdentity(
        season=normalized_season,
        week=normalized_week,
        kickoff_utc=normalized_kickoff,
        away_team=normalized_away,
        home_team=normalized_home,
        canonical_event_key=build_canonical_event_key(
            season=normalized_season,
            week=normalized_week,
            kickoff_utc=normalized_kickoff,
            away_team=normalized_away,
            home_team=normalized_home,
        ),
    )
