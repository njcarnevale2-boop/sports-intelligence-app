from __future__ import annotations

from typing import Any

from app.services.personnel_ingestion import (
    DEFAULT_PERSONNEL_SNAPSHOT_DIR,
    PersonnelSnapshot,
    build_starting_qb_evidence,
    load_latest_personnel_snapshot,
    normalize_team_id,
)


PERSONNEL_STATUSES = {"CURRENT", "STALE", "UNAVAILABLE", "CONFLICTED"}


def _normalized_text(value: Any) -> str:
    return str(value or "").strip()


def _current_snapshot_version(snapshot: PersonnelSnapshot | None) -> str:
    if snapshot is None:
        return "NO_SNAPSHOT"
    return f"{snapshot.personnel_snapshot_id}:{snapshot.personnel_snapshot_hash[:12]}"


def _is_snapshot_current(snapshot: PersonnelSnapshot, *, season: int, week: int) -> bool:
    return int(snapshot.season) == int(season) and int(snapshot.week) == int(week)


def _record_index(snapshot: PersonnelSnapshot) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in snapshot.records:
        key = (record.team, record.position)
        index.setdefault(key, []).append(record.to_canonical_dict())
    return index


def _starter_index(snapshot: PersonnelSnapshot) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for evidence in snapshot.starter_evidence:
        if evidence.role != "STARTING_QB":
            continue
        key = (evidence.team, evidence.effective_game)
        index.setdefault(key, []).append(evidence.to_canonical_dict())
    return index


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
    expected_starting_qb: str | None = None,
    expected_starting_qb_status: str | None = None,
    expected_starting_qb_source: str | None = None,
    expected_starting_qb_verified_at: str | None = None,
    qb_resolution_status: str | None = None,
    personnel_snapshot_id: str | None = None,
    personnel_snapshot_hash: str | None = None,
    personnel_source_timestamp: str | None = None,
    source_url: str | None = None,
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
        "personnelSourceVersion": _normalized_text(personnel_source_version) or _current_snapshot_version(None),
        "personnelReadiness": _normalized_text(personnel_status).upper() or "UNAVAILABLE",
        "personnelReadinessReason": _normalized_text(personnel_readiness_reason) or "QB_STATUS_UNVERIFIED",
        "expectedStartingQB": _normalized_text(expected_starting_qb) or None,
        "expectedStartingQBStatus": _normalized_text(expected_starting_qb_status).upper() or None,
        "expectedStartingQBSource": _normalized_text(expected_starting_qb_source) or None,
        "expectedStartingQBVerifiedAt": _normalized_text(expected_starting_qb_verified_at) or None,
        "qbResolutionStatus": _normalized_text(qb_resolution_status).upper() or None,
        "personnelSnapshotId": _normalized_text(personnel_snapshot_id) or None,
        "personnelSnapshotHash": _normalized_text(personnel_snapshot_hash) or None,
        "personnelSourceTimestamp": _normalized_text(personnel_source_timestamp) or None,
        "sourceUrl": _normalized_text(source_url) or None,
        "personnelNumericallyAdjusted": bool(personnel_numerically_adjusted),
    }


def _resolve_team_authority(
    *,
    season: int,
    week: int,
    schedule_event: dict[str, Any] | Any,
    snapshot: PersonnelSnapshot,
) -> dict[str, Any]:
    if isinstance(schedule_event, dict):
        event_id = _normalized_text(schedule_event.get("source_event_id") or schedule_event.get("eventId") or schedule_event.get("event_id"))
        canonical_event_key = _normalized_text(schedule_event.get("canonical_event_key") or schedule_event.get("canonicalEventKey") or event_id)
        away_team = normalize_team_id(schedule_event.get("away_team") or schedule_event.get("awayTeam"))
        home_team = normalize_team_id(schedule_event.get("home_team") or schedule_event.get("homeTeam"))
    else:
        event_id = _normalized_text(getattr(schedule_event, "source_event_id", None) or getattr(schedule_event, "eventId", None) or getattr(schedule_event, "event_id", None))
        canonical_event_key = _normalized_text(getattr(schedule_event, "canonical_event_key", None) or getattr(schedule_event, "canonicalEventKey", None) or event_id)
        away_team = normalize_team_id(getattr(schedule_event, "away_team", None) or getattr(schedule_event, "awayTeam", None))
        home_team = normalize_team_id(getattr(schedule_event, "home_team", None) or getattr(schedule_event, "homeTeam", None))

    if not event_id:
        return {}
    if not away_team or not home_team:
        authority = _build_unavailable_authority(
            season=season,
            week=week,
            event_id=event_id,
            canonical_event_key=canonical_event_key,
            away_team=away_team,
            home_team=home_team,
        )
        authority["personnelReadiness"] = "UNAVAILABLE"
        authority["personnelReadinessReason"] = "UNKNOWN_TEAM"
        authority["qbResolutionStatus"] = "UNVERIFIED"
        return authority

    snapshot_current = _is_snapshot_current(snapshot, season=season, week=week)
    if not snapshot_current:
        authority = _build_unavailable_authority(
            season=season,
            week=week,
            event_id=event_id,
            canonical_event_key=canonical_event_key,
            away_team=away_team,
            home_team=home_team,
        )
        authority["personnelReadiness"] = "STALE"
        authority["personnelReadinessReason"] = "PERSONNEL_SNAPSHOT_STALE"
        authority["qbResolutionStatus"] = "STALE"
        authority["personnelSourceVersion"] = _current_snapshot_version(snapshot)
        authority["personnelSnapshotId"] = snapshot.personnel_snapshot_id
        authority["personnelSnapshotHash"] = snapshot.personnel_snapshot_hash
        authority["personnelSourceTimestamp"] = snapshot.source_timestamp
        authority["sourceUrl"] = snapshot.source_url
        return authority

    team_event_key = canonical_event_key or event_id
    team_records = {
        side: [record for record in snapshot.records if record.team == side and record.position == "QB"]
        for side in {away_team, home_team}
    }
    starter_index = _starter_index(snapshot)

    def _team_resolution(team: str) -> dict[str, Any]:
        qb_records = team_records.get(team, [])
        starter_evidence = starter_index.get((team, team_event_key), [])
        if len(starter_evidence) > 1:
            return {
                "expected_starting_qb": None,
                "expected_starting_qb_status": "CONFLICTED",
                "expected_starting_qb_source": None,
                "expected_starting_qb_verified_at": None,
                "qb_resolution_status": "CONFLICTED",
                "reason": "QB_RESOLUTION_CONFLICTED",
            }

        if starter_evidence:
            evidence = starter_evidence[0]
            if evidence.get("verification_status") != "VERIFIED":
                return {
                    "expected_starting_qb": None,
                    "expected_starting_qb_status": "UNVERIFIED",
                    "expected_starting_qb_source": None,
                    "expected_starting_qb_verified_at": None,
                    "qb_resolution_status": "UNVERIFIED",
                    "reason": "QB_RESOLUTION_UNVERIFIED",
                }
            return {
                "expected_starting_qb": evidence.get("player"),
                "expected_starting_qb_status": "VERIFIED",
                "expected_starting_qb_source": evidence.get("source"),
                "expected_starting_qb_verified_at": evidence.get("retrieved_at"),
                "qb_resolution_status": "VERIFIED",
                "reason": "QB_RESOLUTION_VERIFIED",
            }

        if qb_records:
            game_statuses = {record.normalized_availability for record in qb_records}
            if len(game_statuses) > 1:
                return {
                    "expected_starting_qb": None,
                    "expected_starting_qb_status": "CONFLICTED",
                    "expected_starting_qb_source": None,
                    "expected_starting_qb_verified_at": None,
                    "qb_resolution_status": "CONFLICTED",
                    "reason": "QB_RESOLUTION_CONFLICTED",
                }
            # Injury report may establish status, not the starter.
            return {
                "expected_starting_qb": None,
                "expected_starting_qb_status": "UNVERIFIED",
                "expected_starting_qb_source": None,
                "expected_starting_qb_verified_at": None,
                "qb_resolution_status": "UNVERIFIED",
                "reason": "QB_RESOLUTION_UNVERIFIED",
            }

        return {
            "expected_starting_qb": None,
            "expected_starting_qb_status": "UNVERIFIED",
            "expected_starting_qb_source": None,
            "expected_starting_qb_verified_at": None,
            "qb_resolution_status": "UNVERIFIED",
            "reason": "QB_RESOLUTION_UNVERIFIED",
        }

    away_resolution = _team_resolution(away_team)
    home_resolution = _team_resolution(home_team)

    if away_resolution.get("qb_resolution_status") == "CONFLICTED" or home_resolution.get("qb_resolution_status") == "CONFLICTED":
        readiness = "CONFLICTED"
        readiness_reason = "QB_RESOLUTION_CONFLICTED"
    elif away_resolution.get("qb_resolution_status") == "VERIFIED" and home_resolution.get("qb_resolution_status") == "VERIFIED":
        readiness = "CURRENT"
        readiness_reason = "QB_STATUS_CURRENT"
    else:
        readiness = "UNAVAILABLE"
        readiness_reason = "QB_RESOLUTION_UNVERIFIED"

    return build_personnel_authority(
        season=season,
        week=week,
        event_id=event_id,
        canonical_event_key=canonical_event_key,
        away_team=away_team,
        home_team=home_team,
        away_expected_starting_qb=away_resolution.get("expected_starting_qb"),
        home_expected_starting_qb=home_resolution.get("expected_starting_qb"),
        away_qb_status=away_resolution.get("qb_resolution_status") or "UNAVAILABLE",
        home_qb_status=home_resolution.get("qb_resolution_status") or "UNAVAILABLE",
        away_qb_verified_at=away_resolution.get("expected_starting_qb_verified_at"),
        home_qb_verified_at=home_resolution.get("expected_starting_qb_verified_at"),
        away_qb_source=away_resolution.get("expected_starting_qb_source"),
        home_qb_source=home_resolution.get("expected_starting_qb_source"),
        personnel_verified_at=snapshot.created_at,
        personnel_source_version=_current_snapshot_version(snapshot),
        personnel_status=readiness,
        personnel_readiness_reason=readiness_reason,
        expected_starting_qb=None,
        expected_starting_qb_status=None,
        expected_starting_qb_source=None,
        expected_starting_qb_verified_at=None,
        qb_resolution_status=readiness,
        personnel_snapshot_id=snapshot.personnel_snapshot_id,
        personnel_snapshot_hash=snapshot.personnel_snapshot_hash,
        personnel_source_timestamp=snapshot.source_timestamp,
        source_url=snapshot.source_url,
        personnel_numerically_adjusted=False,
    )


def load_personnel_authority_lookup(*, season: int, week: int, schedule_events: list[dict[str, Any]] | list[Any], personnel_snapshot: PersonnelSnapshot | None = None, personnel_snapshot_root: Any | None = None) -> dict[str, dict[str, Any]]:
    snapshot = personnel_snapshot or load_latest_personnel_snapshot(season=season, week=week, store_root=personnel_snapshot_root or DEFAULT_PERSONNEL_SNAPSHOT_DIR)
    lookup: dict[str, dict[str, Any]] = {}
    for event in schedule_events:
        if isinstance(event, dict):
            event_id = _normalized_text(event.get("source_event_id") or event.get("eventId") or event.get("event_id"))
            canonical_event_key = _normalized_text(event.get("canonical_event_key") or event.get("canonicalEventKey") or event_id)
            away_team = normalize_team_id(event.get("away_team") or event.get("awayTeam"))
            home_team = normalize_team_id(event.get("home_team") or event.get("homeTeam"))
        else:
            event_id = _normalized_text(getattr(event, "source_event_id", None) or getattr(event, "eventId", None) or getattr(event, "event_id", None))
            canonical_event_key = _normalized_text(getattr(event, "canonical_event_key", None) or getattr(event, "canonicalEventKey", None) or event_id)
            away_team = normalize_team_id(getattr(event, "away_team", None) or getattr(event, "awayTeam", None))
            home_team = normalize_team_id(getattr(event, "home_team", None) or getattr(event, "homeTeam", None))

        if not event_id:
            continue

        if snapshot is None:
            lookup[event_id] = _build_unavailable_authority(
                season=season,
                week=week,
                event_id=event_id,
                canonical_event_key=canonical_event_key,
                away_team=away_team,
                home_team=home_team,
            )
            continue

        lookup[event_id] = _resolve_team_authority(
            season=season,
            week=week,
            schedule_event=event,
            snapshot=snapshot,
        )

    return lookup
