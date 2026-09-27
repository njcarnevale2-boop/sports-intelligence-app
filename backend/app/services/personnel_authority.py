from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from app.runtime_paths import runtime_paths


def _normalized_text(value: Any) -> str:
    return str(value or "").strip()


def _source_version() -> str:
    exports_root = runtime_paths.root / "data" / "exports"
    paths = [
        exports_root / "player_pregame_features.csv",
        exports_root / "player_pregame_history.csv",
    ]
    parts: list[str] = []
    for path in paths:
        if not path.exists():
            parts.append(f"{path.name}:missing")
            continue
        stat = path.stat()
        payload = f"{path.name}|{stat.st_size}|{int(stat.st_mtime_ns)}"
        parts.append(f"{path.name}:{sha256(payload.encode('utf-8')).hexdigest()}")
    return "|".join(parts)


def build_personnel_authority(
    *,
    season: int,
    week: int,
    event_id: str,
    canonical_event_key: str,
    away_team: str,
    home_team: str,
    away_expected_starting_qb: str | None,
    home_expected_starting_qb: str | None,
    away_qb_status: str,
    home_qb_status: str,
    away_qb_verified_at: str | None,
    home_qb_verified_at: str | None,
    away_qb_source: str | None,
    home_qb_source: str | None,
    personnel_verified_at: str | None,
    personnel_source_version: str,
    personnel_status: str,
    personnel_readiness_reason: str,
    personnel_numerically_adjusted: bool = False,
) -> dict[str, Any]:
    return {
        "season": int(season),
        "week": int(week),
        "eventId": _normalized_text(event_id),
        "canonicalEventKey": _normalized_text(canonical_event_key),
        "awayTeam": _normalized_text(away_team).upper(),
        "homeTeam": _normalized_text(home_team).upper(),
        "awayExpectedStartingQB": _normalized_text(away_expected_starting_qb) or None,
        "homeExpectedStartingQB": _normalized_text(home_expected_starting_qb) or None,
        "awayQBStatus": _normalized_text(away_qb_status).upper() or "UNAVAILABLE",
        "homeQBStatus": _normalized_text(home_qb_status).upper() or "UNAVAILABLE",
        "awayQBVerifiedAt": _normalized_text(away_qb_verified_at) or None,
        "homeQBVerifiedAt": _normalized_text(home_qb_verified_at) or None,
        "awayQBSource": _normalized_text(away_qb_source) or None,
        "homeQBSource": _normalized_text(home_qb_source) or None,
        "personnelVerifiedAt": _normalized_text(personnel_verified_at) or None,
        "personnelSourceVersion": _normalized_text(personnel_source_version) or _source_version(),
        "personnelReadiness": _normalized_text(personnel_status).upper() or "UNAVAILABLE",
        "personnelReadinessReason": _normalized_text(personnel_readiness_reason) or "QB_STATUS_UNVERIFIED",
        "personnelNumericallyAdjusted": bool(personnel_numerically_adjusted),
    }


def load_personnel_authority_lookup(*, season: int, week: int, schedule_events: list[dict[str, Any]] | list[Any]) -> dict[str, dict[str, Any]]:
    source_version = _source_version()
    lookup: dict[str, dict[str, Any]] = {}
    for event in schedule_events:
        if isinstance(event, dict):
            event_id = _normalized_text(event.get("source_event_id") or event.get("eventId") or event.get("event_id"))
            canonical_event_key = _normalized_text(event.get("canonical_event_key") or event.get("canonicalEventKey") or event_id)
            away_team = _normalized_text(event.get("away_team") or event.get("awayTeam"))
            home_team = _normalized_text(event.get("home_team") or event.get("homeTeam"))
        else:
            event_id = _normalized_text(getattr(event, "source_event_id", None) or getattr(event, "eventId", None) or getattr(event, "event_id", None))
            canonical_event_key = _normalized_text(getattr(event, "canonical_event_key", None) or getattr(event, "canonicalEventKey", None) or event_id)
            away_team = _normalized_text(getattr(event, "away_team", None) or getattr(event, "awayTeam", None))
            home_team = _normalized_text(getattr(event, "home_team", None) or getattr(event, "homeTeam", None))

        if not event_id:
            continue

        lookup[event_id] = build_personnel_authority(
            season=season,
            week=week,
            event_id=event_id,
            canonical_event_key=canonical_event_key,
            away_team=away_team,
            home_team=home_team,
            away_expected_starting_qb=None,
            home_expected_starting_qb=None,
            away_qb_status="UNAVAILABLE",
            home_qb_status="UNAVAILABLE",
            away_qb_verified_at=None,
            home_qb_verified_at=None,
            away_qb_source=None,
            home_qb_source=None,
            personnel_verified_at=None,
            personnel_source_version=source_version,
            personnel_status="UNAVAILABLE",
            personnel_readiness_reason="QB_STATUS_UNVERIFIED",
            personnel_numerically_adjusted=False,
        )

    return lookup
