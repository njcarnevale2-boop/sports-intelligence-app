from __future__ import annotations

import json
import math
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import settings
from app.runtime_paths import runtime_paths
from app.services.result_engine import build_canonical_event_identity, normalize_kickoff_utc, normalize_team_id
from app.services.schedule_engine import ScheduleEngineStore, default_schedule_engine_store, load_active_schedule

from .hashing import canonical_json, sha256_hex
from .persistence import PowerEngineStore, default_power_engine_store
from .projection_generation import ProjectionLookupError, generate_projection_rows
from .weekly_transition import active_power_transition_observability

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None


_EVENT_ID_RE = re.compile(r"^(\d{4})_(\d{1,2})_")


class ProjectionPublicationError(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalScheduleEvent:
    event_id: str
    canonical_event_key: str
    season: int
    week: int
    kickoff_utc: str
    away_team: str
    home_team: str


@dataclass(frozen=True)
class ProjectionArtifactPointer:
    season: int
    week: int
    artifact_id: str
    artifact_hash: str
    power_snapshot_id: str
    power_snapshot_hash: str
    schedule_hash: str
    activated_at: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _projection_dirs(store: PowerEngineStore) -> tuple[Path, Path, Path, Path]:
    root = store.root_dir / "projections"
    artifacts = root / "artifacts"
    validations = root / "validations"
    active = root / "active"
    return root, artifacts, validations, active


def _projection_lock_path(store: PowerEngineStore, season: int, week: int) -> Path:
    return store.root_dir / "meta" / "locks" / f"projection-publication-{season}-{week}.lock"


@contextmanager
def _projection_lock(store: PowerEngineStore, *, season: int, week: int):
    lock_path = _projection_lock_path(store, season, week)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

        if hasattr(os, "O_DIRECTORY"):
            dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _read_json_file(path: Path, *, field_name: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProjectionPublicationError(f"Missing {field_name}: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectionPublicationError(f"Failed to read {field_name}: {path}") from exc
    if not isinstance(payload, dict):
        raise ProjectionPublicationError(f"Malformed {field_name}: expected JSON object")
    return payload


def _parse_gameday(value: Any) -> date:
    text = str(value or "").strip()
    if not text:
        raise ProjectionPublicationError("SCHEDULE_GAMEDAY_MISSING")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ProjectionPublicationError(f"SCHEDULE_GAMEDAY_INVALID: {text}") from exc


def _kickoff_matches_gameday(kickoff_utc: str, gameday: date) -> bool:
    kickoff = datetime.fromisoformat(kickoff_utc.replace("Z", "+00:00")).date()
    return kickoff == gameday or kickoff == (gameday + timedelta(days=1))


def _load_schedule_rows(*, season: int, week: int, schedule_context_path: Path) -> list[dict[str, Any]]:
    if not schedule_context_path.exists():
        raise ProjectionPublicationError("CANONICAL_SCHEDULE_MISSING")
    df = pd.read_csv(schedule_context_path)
    required = {"season", "week", "gameday", "away_team", "home_team"}
    if not required.issubset(set(df.columns)):
        raise ProjectionPublicationError("CANONICAL_SCHEDULE_SCHEMA_INVALID")

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        row_season = int(row.get("season"))
        row_week = int(row.get("week"))
        if row_season != season or row_week != week:
            continue
        event_id = str(row.get("event_id") or row.get("api_event_id") or "").strip()
        kickoff_raw = row.get("kickoff_utc") or row.get("commence_time") or ""
        kickoff_utc = normalize_kickoff_utc(str(kickoff_raw or ""))
        away = normalize_team_id(row.get("away_team"))
        home = normalize_team_id(row.get("home_team"))
        if not event_id:
            raise ProjectionPublicationError("CANONICAL_SCHEDULE_EVENT_ID_MISSING")
        if away == home:
            raise ProjectionPublicationError("CANONICAL_SCHEDULE_IDENTITY_INVALID")
        rows.append(
            {
                "event_id": event_id,
                "season": row_season,
                "week": row_week,
                "gameday": _parse_gameday(row.get("gameday")),
                "kickoff_utc": kickoff_utc,
                "away_team": away,
                "home_team": home,
            }
        )

    if not rows:
        raise ProjectionPublicationError("CANONICAL_SCHEDULE_MISSING")

    keys = [f"{r['event_id']}:{r['away_team']}@{r['home_team']}:{r['kickoff_utc']}" for r in rows]
    if len(keys) != len(set(keys)):
        raise ProjectionPublicationError("CANONICAL_SCHEDULE_DUPLICATE_EVENT")

    event_ids = [row["event_id"] for row in rows]
    if len(event_ids) != len(set(event_ids)):
        raise ProjectionPublicationError("CANONICAL_SCHEDULE_DUPLICATE_EVENT_ID")

    team_counts: dict[str, int] = {}
    for row in rows:
        team_counts[row["away_team"]] = team_counts.get(row["away_team"], 0) + 1
        team_counts[row["home_team"]] = team_counts.get(row["home_team"], 0) + 1
    duplicates = sorted(team for team, count in team_counts.items() if count > 1)
    if duplicates:
        raise ProjectionPublicationError("CANONICAL_SCHEDULE_DUPLICATE_TEAM")

    return rows


def _build_canonical_schedule(
    *,
    season: int,
    week: int,
    schedule_context_path: Path,
) -> dict[str, Any]:
    schedule_rows = _load_schedule_rows(season=season, week=week, schedule_context_path=schedule_context_path)

    events: list[CanonicalScheduleEvent] = []

    for schedule_row in schedule_rows:
        if not _kickoff_matches_gameday(schedule_row["kickoff_utc"], schedule_row["gameday"]):
            raise ProjectionPublicationError("CANONICAL_SCHEDULE_KICKOFF_MISMATCH")

        identity = build_canonical_event_identity(
            season=season,
            week=week,
            kickoff_utc=schedule_row["kickoff_utc"],
            away_team=schedule_row["away_team"],
            home_team=schedule_row["home_team"],
        )
        event_id = schedule_row["event_id"] or identity.canonical_event_key

        events.append(
            CanonicalScheduleEvent(
                event_id=event_id,
                canonical_event_key=identity.canonical_event_key,
                season=season,
                week=week,
                kickoff_utc=identity.kickoff_utc,
                away_team=identity.away_team,
                home_team=identity.home_team,
            )
        )

    event_ids = [event.event_id for event in events]
    if len(event_ids) != len(set(event_ids)):
        raise ProjectionPublicationError("CANONICAL_SCHEDULE_DUPLICATE_EVENT_ID")

    event_keys = [event.canonical_event_key for event in events]
    if len(event_keys) != len(set(event_keys)):
        raise ProjectionPublicationError("CANONICAL_SCHEDULE_DUPLICATE_EVENT")

    ordered = sorted(events, key=lambda item: (item.kickoff_utc, item.event_id))
    schedule_payload = {
        "season": season,
        "week": week,
        "events": [
            {
                "event_id": item.event_id,
                "canonical_event_key": item.canonical_event_key,
                "kickoff_utc": item.kickoff_utc,
                "away_team": item.away_team,
                "home_team": item.home_team,
            }
            for item in ordered
        ],
    }
    schedule_hash = sha256_hex(canonical_json(schedule_payload))

    return {
        "events": ordered,
        "expected_game_count": len(ordered),
        "schedule_hash": schedule_hash,
        "schedule_version": f"schedule-v1:{season}:{week}:{schedule_hash[:12]}",
    }


def _require_finite(value: Any, field_name: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ProjectionPublicationError(f"{field_name} must be numeric") from exc
    if not math.isfinite(numeric):
        raise ProjectionPublicationError(f"{field_name} must be finite")
    return numeric


def _projection_identity_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "season": int(artifact["season"]),
        "week": int(artifact["week"]),
        "power_snapshot_id": str(artifact["power_snapshot_id"]),
        "power_snapshot_hash": str(artifact["power_snapshot_hash"]),
        "power_through_week": int(artifact["power_through_week"]),
        "source_result_set_version": artifact.get("source_result_set_version"),
        "source_result_set_hash": artifact.get("source_result_set_hash"),
        "source_power_transition_id": artifact.get("source_power_transition_id"),
        "schedule_version": str(artifact["schedule_version"]),
        "schedule_hash": str(artifact["schedule_hash"]),
        "schedule_source_version": str(artifact["schedule_source_version"]),
        "model_version": str(artifact["model_version"]),
        "probability_version": str(artifact["probability_version"]),
        "methodology_hash": str(artifact["methodology_hash"]),
        "updater_version": str(artifact["updater_version"]),
        "expected_game_count": int(artifact["expected_game_count"]),
        "projected_game_count": int(artifact["projected_game_count"]),
        "coverage_hash": str(artifact["coverage_hash"]),
    }


def _projection_rows_for_hash(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        normalized = {
            "event_id": str(row["event_id"]),
            "season": int(row["season"]),
            "week": int(row["week"]),
            "kickoff_utc": str(row["kickoff_utc"]),
            "away_team": str(row["away_team"]),
            "home_team": str(row["home_team"]),
            "away_power": float(row["away_power"]),
            "home_power": float(row["home_power"]),
            "model_margin_home": float(row["model_margin_home"]),
            "canonical_event_key": str(row["canonical_event_key"]),
            "model_version": str(row["model_version"]),
            "probability_version": str(row["probability_version"]),
        }

        for key, value in row.items():
            if "probability" not in key:
                continue
            if key.endswith("_version"):
                continue
            if key in normalized:
                continue
            normalized[key] = None if value is None else float(value)

        out.append(normalized)

    return sorted(out, key=lambda item: (item["kickoff_utc"], item["event_id"]))


def _build_projection_artifact(
    *,
    season: int,
    week: int,
    active_snapshot: Any,
    source_lineage: dict[str, Any],
    schedule: dict[str, Any],
    projected_rows: list[dict[str, Any]],
    model_version: str,
    probability_version: str,
    parent_artifact_id: str | None,
    generated_at: str,
) -> dict[str, Any]:
    normalized_rows = _projection_rows_for_hash(projected_rows)
    coverage_payload = {
        "season": season,
        "week": week,
        "events": [
            {
                "event_id": row["event_id"],
                "canonical_event_key": row["canonical_event_key"],
                "away_team": row["away_team"],
                "home_team": row["home_team"],
                "kickoff_utc": row["kickoff_utc"],
            }
            for row in normalized_rows
        ],
    }
    coverage_hash = sha256_hex(canonical_json(coverage_payload))

    identity = {
        "season": season,
        "week": week,
        "power_snapshot_id": active_snapshot.snapshot_id,
        "power_snapshot_hash": active_snapshot.snapshot_hash,
        "power_through_week": active_snapshot.through_week,
        "source_result_set_version": source_lineage.get("sourceResultSetVersion"),
        "source_result_set_hash": source_lineage.get("sourceResultSetHash"),
        "source_power_transition_id": source_lineage.get("transitionId"),
        "schedule_version": schedule["schedule_version"],
        "schedule_hash": schedule["schedule_hash"],
        "schedule_source_version": schedule["schedule_source_version"],
        "model_version": model_version,
        "probability_version": probability_version,
        "methodology_hash": active_snapshot.methodology_hash,
        "updater_version": active_snapshot.updater_version,
        "expected_game_count": schedule["expected_game_count"],
        "projected_game_count": len(projected_rows),
        "coverage_hash": coverage_hash,
    }
    idempotency_key = sha256_hex(canonical_json(identity))
    artifact_id = f"proj-{idempotency_key[:16]}"

    deterministic_payload = {
        "identity": identity,
        "projections": normalized_rows,
    }
    artifact_hash = sha256_hex(canonical_json(deterministic_payload))
    payload_hash = sha256_hex(canonical_json({"artifact_id": artifact_id, "artifact_hash": artifact_hash, **deterministic_payload}))

    return {
        "artifact_id": artifact_id,
        "season": season,
        "week": week,
        "power_snapshot_id": active_snapshot.snapshot_id,
        "power_snapshot_hash": active_snapshot.snapshot_hash,
        "power_through_week": active_snapshot.through_week,
        "source_result_set_version": source_lineage.get("sourceResultSetVersion"),
        "source_result_set_hash": source_lineage.get("sourceResultSetHash"),
        "source_power_transition_id": source_lineage.get("transitionId"),
        "schedule_version": schedule["schedule_version"],
        "schedule_hash": schedule["schedule_hash"],
        "schedule_source_version": schedule["schedule_source_version"],
        "model_version": model_version,
        "probability_version": probability_version,
        "methodology_hash": active_snapshot.methodology_hash,
        "updater_version": active_snapshot.updater_version,
        "generated_at": generated_at,
        "expected_game_count": schedule["expected_game_count"],
        "projected_game_count": len(projected_rows),
        "coverage_hash": coverage_hash,
        "artifact_hash": artifact_hash,
        "status": "CANDIDATE",
        "parent_artifact_id": parent_artifact_id,
        "idempotency_key": idempotency_key,
        "payload_hash": payload_hash,
        "validation_report_id": f"val-{idempotency_key[:16]}",
        "storage_path": f"artifacts/{artifact_id}.json",
        "projection_rows": normalized_rows,
    }


def _artifact_path(store: PowerEngineStore, artifact_id: str) -> Path:
    _, artifacts_dir, _, _ = _projection_dirs(store)
    return artifacts_dir / f"{artifact_id}.json"


def _validation_path(store: PowerEngineStore, validation_id: str) -> Path:
    _, _, validations_dir, _ = _projection_dirs(store)
    return validations_dir / f"{validation_id}.json"


def _active_pointer_path(store: PowerEngineStore, season: int, week: int) -> Path:
    _, _, _, active_dir = _projection_dirs(store)
    return active_dir / f"active-{season}-{week}.json"


def _persist_projection_artifact(store: PowerEngineStore, artifact: dict[str, Any]) -> dict[str, Any]:
    path = _artifact_path(store, str(artifact["artifact_id"]))
    serialized = canonical_json(artifact)
    if path.exists():
        existing = _read_json_file(path, field_name="projection artifact")
        if (
            str(existing.get("artifact_hash")) == str(artifact.get("artifact_hash"))
            and str(existing.get("idempotency_key")) == str(artifact.get("idempotency_key"))
            and str(existing.get("payload_hash")) == str(artifact.get("payload_hash"))
        ):
            return existing
        if canonical_json(existing) != serialized:
            raise ProjectionPublicationError("ARTIFACT_ID_COLLISION")
        return existing

    _atomic_write_text(path, serialized)
    return artifact


def _load_projection_artifact(store: PowerEngineStore, artifact_id: str) -> dict[str, Any]:
    return _read_json_file(_artifact_path(store, artifact_id), field_name="projection artifact")


def _persist_projection_validation(store: PowerEngineStore, validation: dict[str, Any]) -> dict[str, Any]:
    path = _validation_path(store, str(validation["validation_id"]))
    serialized = canonical_json(validation)
    if path.exists():
        existing = _read_json_file(path, field_name="projection validation")
        if canonical_json(existing) != serialized:
            # Allow deterministic replay where only validation timestamp differs.
            existing_stable = dict(existing)
            existing_stable.pop("validated_at", None)
            candidate_stable = dict(validation)
            candidate_stable.pop("validated_at", None)
            if canonical_json(existing_stable) != canonical_json(candidate_stable):
                raise ProjectionPublicationError("VALIDATION_ID_COLLISION")
        return existing

    _atomic_write_text(path, serialized)
    return validation


def _load_projection_validation(store: PowerEngineStore, validation_id: str) -> dict[str, Any]:
    return _read_json_file(_validation_path(store, validation_id), field_name="projection validation")


def _read_active_projection_pointer(store: PowerEngineStore, season: int, week: int) -> ProjectionArtifactPointer | None:
    path = _active_pointer_path(store, season, week)
    if not path.exists():
        return None
    payload = _read_json_file(path, field_name="active projection pointer")
    return ProjectionArtifactPointer(
        season=int(payload["season"]),
        week=int(payload["week"]),
        artifact_id=str(payload["artifact_id"]),
        artifact_hash=str(payload["artifact_hash"]),
        power_snapshot_id=str(payload["power_snapshot_id"]),
        power_snapshot_hash=str(payload["power_snapshot_hash"]),
        schedule_hash=str(payload["schedule_hash"]),
        activated_at=str(payload["activated_at"]),
    )


def _persist_active_projection_pointer(store: PowerEngineStore, pointer: ProjectionArtifactPointer) -> None:
    payload = asdict(pointer)
    _atomic_write_text(_active_pointer_path(store, pointer.season, pointer.week), canonical_json(payload))


def _delete_active_projection_pointer(store: PowerEngineStore, season: int, week: int) -> None:
    path = _active_pointer_path(store, season, week)
    if path.exists():
        path.unlink()


def _validation_for_candidate(*, artifact: dict[str, Any], schedule_events: list[CanonicalScheduleEvent]) -> dict[str, Any]:
    checks: dict[str, bool] = {
        "season_match": int(artifact["season"]) == int(schedule_events[0].season),
        "week_match": int(artifact["week"]) == int(schedule_events[0].week),
        "power_through_week_match": int(artifact["power_through_week"]) == int(artifact["week"]) - 1,
        "projected_count_match": int(artifact["projected_game_count"]) == int(artifact["expected_game_count"]),
    }

    expected_map = {event.event_id: event for event in schedule_events}
    projected_rows: list[dict[str, Any]] = list(artifact["projection_rows"])

    projected_ids = [str(row["event_id"]) for row in projected_rows]
    checks["no_duplicate_projected_events"] = len(projected_ids) == len(set(projected_ids))

    expected_ids = set(expected_map.keys())
    projected_id_set = set(projected_ids)
    checks["no_missing_events"] = expected_ids.issubset(projected_id_set)
    checks["no_unexpected_events"] = projected_id_set.issubset(expected_ids)

    per_row_ok = True
    model_ok = True
    prob_ok = True
    for row in projected_rows:
        event = expected_map.get(str(row["event_id"]))
        if event is None:
            per_row_ok = False
            continue
        if str(row["away_team"]) != event.away_team:
            per_row_ok = False
        if str(row["home_team"]) != event.home_team:
            per_row_ok = False
        if str(row["kickoff_utc"]) != event.kickoff_utc:
            per_row_ok = False

        _require_finite(row.get("away_power"), "away_power")
        _require_finite(row.get("home_power"), "home_power")
        _require_finite(row.get("model_margin_home"), "model_margin_home")

        for key, value in row.items():
            if "probability" not in key:
                continue
            if key.endswith("_version"):
                continue
            if value is None:
                continue
            p = _require_finite(value, key)
            if p < 0.0 or p > 1.0:
                prob_ok = False

    checks["event_identity_match"] = per_row_ok
    checks["model_fields_valid"] = model_ok
    checks["probability_fields_valid"] = prob_ok

    deterministic_payload = {
        "identity": _projection_identity_payload(artifact),
        "projections": _projection_rows_for_hash(projected_rows),
    }
    checks["artifact_hash_valid"] = artifact["artifact_hash"] == sha256_hex(canonical_json(deterministic_payload))

    coverage_payload = {
        "season": int(artifact["season"]),
        "week": int(artifact["week"]),
        "events": [
            {
                "event_id": row["event_id"],
                "canonical_event_key": row["canonical_event_key"],
                "away_team": row["away_team"],
                "home_team": row["home_team"],
                "kickoff_utc": row["kickoff_utc"],
            }
            for row in projected_rows
        ],
    }
    checks["coverage_hash_valid"] = artifact["coverage_hash"] == sha256_hex(canonical_json(coverage_payload))
    checks["lineage_fields_present"] = bool(str(artifact.get("power_snapshot_id") or "").strip()) and bool(str(artifact.get("schedule_hash") or "").strip())

    status = "VALID" if all(checks.values()) else "INVALID"
    return {
        "validation_id": str(artifact["validation_report_id"]),
        "artifact_id": str(artifact["artifact_id"]),
        "season": int(artifact["season"]),
        "week": int(artifact["week"]),
        "status": status,
        "checks": checks,
        "validated_at": _utc_now_iso(),
    }


def _active_conflict_reason(existing_artifact: dict[str, Any], candidate: dict[str, Any]) -> str:
    if str(existing_artifact.get("power_snapshot_id")) != str(candidate.get("power_snapshot_id")):
        return "POWER_SNAPSHOT_CONFLICT"
    if str(existing_artifact.get("schedule_hash")) != str(candidate.get("schedule_hash")):
        return "SCHEDULE_HASH_CONFLICT"
    if str(existing_artifact.get("schedule_source_version")) != str(candidate.get("schedule_source_version")):
        return "SCHEDULE_SOURCE_VERSION_CONFLICT"
    if str(existing_artifact.get("model_version")) != str(candidate.get("model_version")):
        return "MODEL_VERSION_CONFLICT"
    if str(existing_artifact.get("probability_version")) != str(candidate.get("probability_version")):
        return "PROBABILITY_VERSION_CONFLICT"
    if str(existing_artifact.get("methodology_hash")) != str(candidate.get("methodology_hash")):
        return "METHODOLOGY_HASH_CONFLICT"
    if str(existing_artifact.get("updater_version")) != str(candidate.get("updater_version")):
        return "UPDATER_VERSION_CONFLICT"
    return "CONFLICTING_REPLAY"


def publish_weekly_projections(
    *,
    season: int,
    target_week: int,
    power_store: PowerEngineStore | None = None,
    schedule_store: ScheduleEngineStore | None = None,
    model_version: str | None = None,
    probability_version: str | None = None,
) -> dict[str, Any]:
    store = power_store or default_power_engine_store()
    authoritative_schedule_store = schedule_store or default_schedule_engine_store()

    if season <= 0:
        raise ProjectionPublicationError("SEASON_INVALID")
    if target_week <= 0:
        raise ProjectionPublicationError("WEEK_INVALID")

    active_lineage = store.get_active_lineage(season)
    active_snapshot = store.get_snapshot(active_lineage.active_snapshot_id)
    if active_snapshot.season != season:
        raise ProjectionPublicationError("POWER_SEASON_MISMATCH")
    if target_week != active_snapshot.through_week + 1:
        raise ProjectionPublicationError("TARGET_WEEK_NOT_NEXT")

    model_version_value = str(model_version or settings.DEFAULT_MODEL_VERSION)
    probability_version_value = str(probability_version or settings.DEFAULT_PROBABILITY_ENGINE_VERSION)

    source_lineage = active_power_transition_observability(power_store=store, season=season)
    try:
        persisted_schedule = load_active_schedule(season=season, week=target_week, store=authoritative_schedule_store)
    except Exception as exc:
        raise ProjectionPublicationError("ACTIVE_SCHEDULE_UNAVAILABLE") from exc
    schedule = {
        "events": [
            CanonicalScheduleEvent(
                event_id=event.source_event_id,
                canonical_event_key=event.canonical_event_key,
                season=event.season,
                week=event.week,
                kickoff_utc=event.kickoff_utc,
                away_team=event.away_team,
                home_team=event.home_team,
            )
            for event in persisted_schedule.events
        ],
        "expected_game_count": persisted_schedule.event_count,
        "schedule_hash": persisted_schedule.schedule_hash,
        "schedule_version": persisted_schedule.schedule_version,
        "schedule_source_version": persisted_schedule.source_version,
    }

    ratings_records = [{"team": team.team_id, "power_points": float(team.power)} for team in active_snapshot.teams]
    games = [
        {
            "api_event_id": event.event_id,
            "season": season,
            "week": target_week,
            "commence_time": event.kickoff_utc,
            "away_team": event.away_team,
            "home_team": event.home_team,
            "canonical_event_key": event.canonical_event_key,
        }
        for event in schedule["events"]
    ]

    try:
        generated_rows = generate_projection_rows(ratings_records=ratings_records, games=games)
    except ProjectionLookupError as exc:
        raise ProjectionPublicationError(str(exc)) from exc

    projected_rows: list[dict[str, Any]] = []
    for row in generated_rows:
        kickoff = normalize_kickoff_utc(str(row.get("commence_time") or ""))
        away = normalize_team_id(row.get("away_team"))
        home = normalize_team_id(row.get("home_team"))
        event_id = str(row.get("api_event_id") or "").strip()
        if not event_id:
            raise ProjectionPublicationError("PROJECTED_EVENT_ID_MISSING")
        identity = build_canonical_event_identity(
            season=season,
            week=target_week,
            kickoff_utc=kickoff,
            away_team=away,
            home_team=home,
        )
        projected = {
            "event_id": event_id,
            "season": season,
            "week": target_week,
            "kickoff_utc": identity.kickoff_utc,
            "away_team": identity.away_team,
            "home_team": identity.home_team,
            "away_power": _require_finite(row.get("away_power"), "away_power"),
            "home_power": _require_finite(row.get("home_power"), "home_power"),
            "model_margin_home": _require_finite(row.get("model_margin_home"), "model_margin_home"),
            "canonical_event_key": identity.canonical_event_key,
            "model_version": model_version_value,
            "probability_version": probability_version_value,
        }

        for key, value in row.items():
            if "probability" not in key:
                continue
            if key.endswith("_version"):
                continue
            if value is None:
                projected[key] = None
                continue
            p = _require_finite(value, key)
            if p < 0.0 or p > 1.0:
                raise ProjectionPublicationError("PROBABILITY_FIELD_INVALID")
            projected[key] = p

        projected_rows.append(projected)

    parent_pointer = _read_active_projection_pointer(store, season, target_week)
    parent_artifact_id = None if parent_pointer is None else parent_pointer.artifact_id
    candidate = _build_projection_artifact(
        season=season,
        week=target_week,
        active_snapshot=active_snapshot,
        source_lineage=source_lineage,
        schedule=schedule,
        projected_rows=projected_rows,
        model_version=model_version_value,
        probability_version=probability_version_value,
        parent_artifact_id=parent_artifact_id,
        generated_at=_utc_now_iso(),
    )

    persisted_candidate = _persist_projection_artifact(store, candidate)

    validation = _validation_for_candidate(artifact=persisted_candidate, schedule_events=schedule["events"])
    if validation["status"] != "VALID":
        raise ProjectionPublicationError("PROJECTION_VALIDATION_FAILED")
    persisted_validation = _persist_projection_validation(store, validation)

    with _projection_lock(store, season=season, week=target_week):
        active_pointer = _read_active_projection_pointer(store, season, target_week)
        if active_pointer is not None:
            active_artifact = _load_projection_artifact(store, active_pointer.artifact_id)
            if active_artifact.get("artifact_hash") != active_pointer.artifact_hash:
                raise ProjectionPublicationError("ACTIVE_POINTER_ARTIFACT_MISMATCH")

            if (
                str(active_artifact.get("idempotency_key")) == str(persisted_candidate.get("idempotency_key"))
                and str(active_artifact.get("artifact_hash")) == str(persisted_candidate.get("artifact_hash"))
            ):
                return {
                    "status": "ALREADY_ACTIVE",
                    "artifact": active_artifact,
                    "validation": _load_projection_validation(store, str(active_artifact["validation_report_id"])),
                    "active": asdict(active_pointer),
                }
            raise ProjectionPublicationError(_active_conflict_reason(active_artifact, persisted_candidate))

        previous_pointer = active_pointer
        new_pointer = ProjectionArtifactPointer(
            season=season,
            week=target_week,
            artifact_id=str(persisted_candidate["artifact_id"]),
            artifact_hash=str(persisted_candidate["artifact_hash"]),
            power_snapshot_id=str(persisted_candidate["power_snapshot_id"]),
            power_snapshot_hash=str(persisted_candidate["power_snapshot_hash"]),
            schedule_hash=str(persisted_candidate["schedule_hash"]),
            activated_at=_utc_now_iso(),
        )

        try:
            _persist_active_projection_pointer(store, new_pointer)
            readback = _read_active_projection_pointer(store, season, target_week)
            if readback is None:
                raise ProjectionPublicationError("ACTIVE_POINTER_READBACK_MISSING")
            if readback.artifact_id != new_pointer.artifact_id or readback.artifact_hash != new_pointer.artifact_hash:
                raise ProjectionPublicationError("ACTIVE_POINTER_READBACK_VERIFICATION_FAILED")
        except Exception:
            if previous_pointer is None:
                _delete_active_projection_pointer(store, season, target_week)
            else:
                _persist_active_projection_pointer(store, previous_pointer)
            raise

    return {
        "status": "APPLIED",
        "artifact": persisted_candidate,
        "validation": persisted_validation,
        "active": asdict(new_pointer),
    }


def active_projection_observability(
    *,
    season: int,
    week: int,
    power_store: PowerEngineStore | None = None,
) -> dict[str, Any]:
    store = power_store or default_power_engine_store()
    pointer = _read_active_projection_pointer(store, season, week)
    if pointer is None:
        return {
            "season": season,
            "week": week,
            "artifactId": None,
            "artifactHash": None,
            "status": None,
            "powerSnapshotId": None,
            "powerSnapshotHash": None,
            "powerThroughWeek": None,
            "sourceResultSetVersion": None,
            "sourceResultSetHash": None,
            "sourcePowerTransitionId": None,
            "scheduleVersion": None,
            "scheduleHash": None,
            "modelVersion": None,
            "probabilityVersion": None,
            "methodologyHash": None,
            "expectedGameCount": None,
            "projectedGameCount": None,
            "coverageHash": None,
            "validationStatus": None,
            "activatedAt": None,
            "isCurrentRelativeToPower": False,
        }

    artifact = _load_projection_artifact(store, pointer.artifact_id)
    validation = _load_projection_validation(store, str(artifact["validation_report_id"]))

    current = False
    try:
        active_snapshot = store.get_snapshot(store.get_active_lineage(season).active_snapshot_id)
        current = (
            active_snapshot.snapshot_id == str(artifact["power_snapshot_id"])
            and active_snapshot.snapshot_hash == str(artifact["power_snapshot_hash"])
            and int(active_snapshot.through_week) == int(week) - 1
        )
    except Exception:
        current = False

    return {
        "season": int(artifact["season"]),
        "week": int(artifact["week"]),
        "artifactId": str(artifact["artifact_id"]),
        "artifactHash": str(artifact["artifact_hash"]),
        "status": "ACTIVE",
        "powerSnapshotId": str(artifact["power_snapshot_id"]),
        "powerSnapshotHash": str(artifact["power_snapshot_hash"]),
        "powerThroughWeek": int(artifact["power_through_week"]),
        "sourceResultSetVersion": artifact.get("source_result_set_version"),
        "sourceResultSetHash": artifact.get("source_result_set_hash"),
        "sourcePowerTransitionId": artifact.get("source_power_transition_id"),
        "scheduleVersion": str(artifact["schedule_version"]),
        "scheduleHash": str(artifact["schedule_hash"]),
        "scheduleSourceVersion": str(artifact.get("schedule_source_version") or "") or None,
        "modelVersion": str(artifact["model_version"]),
        "probabilityVersion": str(artifact["probability_version"]),
        "methodologyHash": str(artifact["methodology_hash"]),
        "expectedGameCount": int(artifact["expected_game_count"]),
        "projectedGameCount": int(artifact["projected_game_count"]),
        "coverageHash": str(artifact["coverage_hash"]),
        "validationStatus": str(validation["status"]),
        "activatedAt": pointer.activated_at,
        "isCurrentRelativeToPower": current,
    }


def resolve_projection_readiness(
    *,
    season: int | None,
    week: int | None,
    power_store: PowerEngineStore | None = None,
    schedule_store: ScheduleEngineStore | None = None,
) -> dict[str, Any]:
    store = power_store or default_power_engine_store()
    authoritative_schedule_store = schedule_store or default_schedule_engine_store()

    base = {
        "projectionReadiness": "INVALID",
        "projectionReadinessReason": "CANONICAL_WEEK_INVALID",
        "projectionSeason": season,
        "projectionWeek": week,
        "projectionPowerThroughWeek": None,
        "projectionArtifactId": None,
        "projectionArtifactHash": None,
        "projectionScheduleVersion": None,
        "projectionScheduleHash": None,
        "projectionScheduleSourceVersion": None,
        "projectionValidationStatus": None,
        "projectionPowerSnapshotId": None,
        "projectionPowerSnapshotHash": None,
        "projectionActivatedAt": None,
        "expectedPowerThroughWeek": None if week is None else (int(week) - 1),
        "projectionExpectedGameCount": None,
        "projectionProjectedGameCount": None,
        "projectionRowCount": None,
    }

    if season is None or week is None:
        return base

    try:
        expected_season = int(season)
        expected_week = int(week)
    except (TypeError, ValueError):
        return base

    if expected_season <= 0 or expected_week <= 0:
        return base

    expected_power_through_week = expected_week - 1
    base["expectedPowerThroughWeek"] = expected_power_through_week

    try:
        pointer = _read_active_projection_pointer(store, expected_season, expected_week)
    except Exception:
        return {
            **base,
            "projectionReadiness": "INVALID",
            "projectionReadinessReason": "ACTIVE_POINTER_UNREADABLE",
        }

    if pointer is None:
        return {
            **base,
            "projectionReadiness": "MISSING",
            "projectionReadinessReason": "ACTIVE_POINTER_MISSING",
        }

    base.update(
        {
            "projectionSeason": int(pointer.season),
            "projectionWeek": int(pointer.week),
            "projectionArtifactId": str(pointer.artifact_id),
            "projectionArtifactHash": str(pointer.artifact_hash),
            "projectionPowerSnapshotId": str(pointer.power_snapshot_id),
            "projectionPowerSnapshotHash": str(pointer.power_snapshot_hash),
            "projectionScheduleHash": str(pointer.schedule_hash),
            "projectionActivatedAt": str(pointer.activated_at),
        }
    )

    try:
        artifact = _load_projection_artifact(store, pointer.artifact_id)
    except Exception:
        return {
            **base,
            "projectionReadiness": "INVALID",
            "projectionReadinessReason": "ACTIVE_ARTIFACT_UNREADABLE",
        }

    if str(artifact.get("artifact_id") or "") != str(pointer.artifact_id):
        return {
            **base,
            "projectionReadiness": "INVALID",
            "projectionReadinessReason": "POINTER_ARTIFACT_ID_MISMATCH",
        }

    if str(artifact.get("artifact_hash") or "") != str(pointer.artifact_hash):
        return {
            **base,
            "projectionReadiness": "INVALID",
            "projectionReadinessReason": "POINTER_ARTIFACT_HASH_MISMATCH",
        }

    validation_id = str(artifact.get("validation_report_id") or "").strip()
    if not validation_id:
        return {
            **base,
            "projectionReadiness": "INVALID",
            "projectionReadinessReason": "VALIDATION_POINTER_MISSING",
        }

    try:
        validation = _load_projection_validation(store, validation_id)
    except Exception:
        return {
            **base,
            "projectionReadiness": "INVALID",
            "projectionReadinessReason": "VALIDATION_UNREADABLE",
        }

    validation_status = str(validation.get("status") or "").upper()
    if validation_status != "VALID":
        return {
            **base,
            "projectionReadiness": "INVALID",
            "projectionReadinessReason": "VALIDATION_NOT_VALID",
            "projectionValidationStatus": validation_status or None,
        }

    if str(validation.get("artifact_id") or "") != str(pointer.artifact_id):
        return {
            **base,
            "projectionReadiness": "INVALID",
            "projectionReadinessReason": "VALIDATION_ARTIFACT_MISMATCH",
            "projectionValidationStatus": validation_status,
        }

    try:
        artifact_season = int(artifact.get("season"))
        artifact_week = int(artifact.get("week"))
        power_through_week = int(artifact.get("power_through_week"))
        expected_game_count = int(artifact.get("expected_game_count"))
        projected_game_count = int(artifact.get("projected_game_count"))
    except (TypeError, ValueError):
        return {
            **base,
            "projectionReadiness": "INVALID",
            "projectionReadinessReason": "ARTIFACT_LINEAGE_SCHEMA_INVALID",
            "projectionValidationStatus": validation_status,
        }

    projection_rows = artifact.get("projection_rows")
    if not isinstance(projection_rows, list):
        return {
            **base,
            "projectionReadiness": "INVALID",
            "projectionReadinessReason": "PROJECTION_ROWS_INVALID",
            "projectionValidationStatus": validation_status,
        }

    if not projection_rows:
        return {
            **base,
            "projectionReadiness": "INVALID",
            "projectionReadinessReason": "PROJECTION_ROWS_EMPTY",
            "projectionValidationStatus": validation_status,
        }

    row_count = len(projection_rows)
    if projected_game_count != row_count:
        return {
            **base,
            "projectionReadiness": "INVALID",
            "projectionReadinessReason": "PROJECTED_GAME_COUNT_MISMATCH",
            "projectionValidationStatus": validation_status,
            "projectionProjectedGameCount": projected_game_count,
            "projectionRowCount": row_count,
        }

    if expected_game_count != row_count:
        return {
            **base,
            "projectionReadiness": "INVALID",
            "projectionReadinessReason": "EXPECTED_GAME_COUNT_MISMATCH",
            "projectionValidationStatus": validation_status,
            "projectionExpectedGameCount": expected_game_count,
            "projectionRowCount": row_count,
        }

    schedule_version = str(artifact.get("schedule_version") or "").strip()
    schedule_hash = str(artifact.get("schedule_hash") or "").strip()
    schedule_source_version = str(artifact.get("schedule_source_version") or "").strip()
    if not schedule_version:
        return {
            **base,
            "projectionReadiness": "INVALID",
            "projectionReadinessReason": "SCHEDULE_VERSION_MISSING",
            "projectionValidationStatus": validation_status,
        }
    if not schedule_hash:
        return {
            **base,
            "projectionReadiness": "INVALID",
            "projectionReadinessReason": "SCHEDULE_HASH_MISSING",
            "projectionValidationStatus": validation_status,
        }
    if not schedule_source_version:
        return {
            **base,
            "projectionReadiness": "INVALID",
            "projectionReadinessReason": "SCHEDULE_SOURCE_VERSION_MISSING",
            "projectionValidationStatus": validation_status,
        }

    try:
        active_schedule = load_active_schedule(
            season=expected_season,
            week=expected_week,
            store=authoritative_schedule_store,
        )
    except Exception:
        return {
            **base,
            "projectionReadiness": "INVALID",
            "projectionReadinessReason": "ACTIVE_SCHEDULE_UNAVAILABLE",
            "projectionValidationStatus": validation_status,
        }

    base.update(
        {
            "projectionSeason": artifact_season,
            "projectionWeek": artifact_week,
            "projectionPowerThroughWeek": power_through_week,
            "projectionArtifactId": str(artifact.get("artifact_id") or pointer.artifact_id),
            "projectionArtifactHash": str(artifact.get("artifact_hash") or pointer.artifact_hash),
            "projectionScheduleVersion": str(artifact.get("schedule_version") or "") or None,
            "projectionScheduleHash": str(artifact.get("schedule_hash") or "") or None,
            "projectionScheduleSourceVersion": str(artifact.get("schedule_source_version") or "") or None,
            "projectionValidationStatus": validation_status,
            "projectionPowerSnapshotId": str(artifact.get("power_snapshot_id") or pointer.power_snapshot_id),
            "projectionPowerSnapshotHash": str(artifact.get("power_snapshot_hash") or pointer.power_snapshot_hash),
            "projectionExpectedGameCount": expected_game_count,
            "projectionProjectedGameCount": projected_game_count,
            "projectionRowCount": row_count,
        }
    )

    stale_reasons: list[str] = []
    if artifact_season != expected_season:
        stale_reasons.append("SEASON_MISMATCH")
    if artifact_week != expected_week:
        stale_reasons.append("WEEK_MISMATCH")
    if power_through_week != expected_power_through_week:
        stale_reasons.append("POWER_THROUGH_WEEK_MISMATCH")
    if schedule_version != str(active_schedule.schedule_version):
        stale_reasons.append("SCHEDULE_VERSION_MISMATCH")
    if schedule_hash != str(active_schedule.schedule_hash):
        stale_reasons.append("SCHEDULE_HASH_MISMATCH")
    if schedule_source_version != str(active_schedule.source_version):
        stale_reasons.append("SCHEDULE_SOURCE_VERSION_MISMATCH")
    if expected_game_count != int(active_schedule.event_count):
        stale_reasons.append("SCHEDULE_EVENT_COUNT_MISMATCH")

    if stale_reasons:
        return {
            **base,
            "projectionReadiness": "STALE",
            "projectionReadinessReason": "|".join(stale_reasons),
        }

    return {
        **base,
        "projectionReadiness": "CURRENT",
        "projectionReadinessReason": "LINEAGE_CURRENT",
    }


def load_active_projection_artifact_by_identity(
    *,
    season: int,
    week: int,
    artifact_id: str,
    artifact_hash: str,
    power_store: PowerEngineStore | None = None,
) -> dict[str, Any]:
    store = power_store or default_power_engine_store()

    pointer = _read_active_projection_pointer(store, season, week)
    if pointer is None:
        raise ProjectionPublicationError("ACTIVE_POINTER_MISSING")

    if str(pointer.artifact_id) != str(artifact_id):
        raise ProjectionPublicationError("ACTIVE_POINTER_ARTIFACT_ID_MISMATCH")
    if str(pointer.artifact_hash) != str(artifact_hash):
        raise ProjectionPublicationError("ACTIVE_POINTER_ARTIFACT_HASH_MISMATCH")

    artifact = _load_projection_artifact(store, str(artifact_id))
    if str(artifact.get("artifact_id") or "") != str(artifact_id):
        raise ProjectionPublicationError("ARTIFACT_ID_MISMATCH")
    if str(artifact.get("artifact_hash") or "") != str(artifact_hash):
        raise ProjectionPublicationError("ARTIFACT_HASH_MISMATCH")

    validation_id = str(artifact.get("validation_report_id") or "").strip()
    if not validation_id:
        raise ProjectionPublicationError("VALIDATION_POINTER_MISSING")

    validation = _load_projection_validation(store, validation_id)
    if str(validation.get("artifact_id") or "") != str(artifact_id):
        raise ProjectionPublicationError("VALIDATION_ARTIFACT_MISMATCH")
    if str(validation.get("status") or "").upper() != "VALID":
        raise ProjectionPublicationError("VALIDATION_NOT_VALID")

    return artifact


def list_projection_artifacts(
    *,
    season: int,
    week: int,
    power_store: PowerEngineStore | None = None,
) -> list[dict[str, Any]]:
    store = power_store or default_power_engine_store()
    _, artifacts_dir, _, _ = _projection_dirs(store)
    if not artifacts_dir.exists():
        return []

    out: list[dict[str, Any]] = []
    for path in sorted(artifacts_dir.glob("*.json")):
        payload = _read_json_file(path, field_name="projection artifact")
        if int(payload.get("season", -1)) != season:
            continue
        if int(payload.get("week", -1)) != week:
            continue
        out.append(payload)
    return out
