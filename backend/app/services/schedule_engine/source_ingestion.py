from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import threading
import uuid
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.result_engine import ResultEngineStore, default_result_engine_store, load_frozen_week_result_set
from app.services.result_engine.teams import normalize_team_id

from . import service as schedule_service
from .service import (
    CanonicalWeeklySchedule,
    ScheduleEngineError,
    ScheduleEngineStore,
    default_schedule_engine_store,
    load_canonical_weekly_schedule,
)

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_hex_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        with tmp.open("wb") as handle:
            handle.write(payload)
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


@contextmanager
def _file_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ScheduleSourceIngestionError(ValueError):
    pass


def list_power_weekly_transitions(*args, **kwargs):
    from app.services.power_engine.weekly_transition import list_power_weekly_transitions as _list_power_weekly_transitions

    return _list_power_weekly_transitions(*args, **kwargs)


def active_power_transition_observability(*args, **kwargs):
    from app.services.power_engine.weekly_transition import active_power_transition_observability as _active_power_transition_observability

    return _active_power_transition_observability(*args, **kwargs)


@dataclass(frozen=True)
class ScheduleSourceManifest:
    source: str
    dataset: str
    source_uri: str
    retrieved_at_utc: str
    release_tag: str
    release_id: str
    release_published_at: str | None
    release_updated_at: str | None
    target_commitish: str | None
    asset_name: str
    asset_id: str
    asset_updated_at: str | None
    asset_size_bytes_reported: int | None
    asset_digest_reported: str | None
    http_etag: str | None
    http_last_modified: str | None
    content_sha256_computed: str
    byte_count_downloaded: int
    parser_format: str
    schema_field_list: tuple[str, ...]
    schema_field_count: int
    row_count: int
    season_min: int | None
    season_max: int | None
    game_type_counts: dict[str, int]
    validation_status: str
    ingestion_run_id: str
    source_version: str


def _manifest_immutable_payload(manifest: ScheduleSourceManifest | dict[str, Any]) -> dict[str, Any]:
    payload = asdict(manifest) if isinstance(manifest, ScheduleSourceManifest) else dict(manifest)
    schema_field_list = payload.get("schema_field_list")
    if isinstance(schema_field_list, tuple):
        payload["schema_field_list"] = list(schema_field_list)
    return {
        key: payload.get(key)
        for key in (
            "source",
            "dataset",
            "source_uri",
            "release_tag",
            "release_id",
            "release_published_at",
            "release_updated_at",
            "target_commitish",
            "asset_name",
            "asset_id",
            "asset_updated_at",
            "asset_size_bytes_reported",
            "asset_digest_reported",
            "http_etag",
            "http_last_modified",
            "content_sha256_computed",
            "byte_count_downloaded",
            "parser_format",
            "schema_field_list",
            "schema_field_count",
            "row_count",
            "season_min",
            "season_max",
            "game_type_counts",
            "source_version",
        )
    }


@dataclass(frozen=True)
class ActiveSchedulePointer:
    season: int
    week: int
    schedule_version: str
    schedule_hash: str
    source_version: str
    source_content_sha256: str
    canonical_artifact_path: str
    activated_at: str


def _sources_root(store: ScheduleEngineStore) -> Path:
    return store.root_dir / "sources" / "nflverse"


def _source_locks_root(store: ScheduleEngineStore) -> Path:
    return store.root_dir / "sources" / "locks"


def _source_version_dir(store: ScheduleEngineStore, source_version: str) -> Path:
    return _sources_root(store) / source_version


def _source_manifest_path(store: ScheduleEngineStore, source_version: str) -> Path:
    return _source_version_dir(store, source_version) / "manifest.json"


def _source_bytes_path(store: ScheduleEngineStore, source_version: str) -> Path:
    return _source_version_dir(store, source_version) / "games.csv.gz"


def _canonical_versions_dir(store: ScheduleEngineStore, season: int, week: int) -> Path:
    return store.root_dir / "weeks" / str(season) / f"week-{week}"


def _canonical_version_path(store: ScheduleEngineStore, schedule: CanonicalWeeklySchedule) -> Path:
    return _canonical_versions_dir(store, schedule.season, schedule.week) / f"{schedule.schedule_version}.json"


def _active_pointer_path(store: ScheduleEngineStore, season: int, week: int) -> Path:
    return store.root_dir / "active" / str(season) / f"week-{week}.json"


def _active_pointer_lock_path(store: ScheduleEngineStore, season: int, week: int) -> Path:
    return store.root_dir / "locks" / f"active-schedule-{season}-{week}.lock"


def _source_version_formula(
    *,
    release_tag: str,
    release_id: str,
    asset_name: str,
    asset_id: str,
    asset_updated_at: str | None,
    content_sha256: str,
) -> str:
    updated = asset_updated_at or "unknown"
    return (
        "schedules|"
        f"{release_tag}|"
        f"{release_id}|"
        f"{asset_name}|"
        f"{asset_id}|"
        f"{updated}|"
        f"sha256={content_sha256}"
    )


def _read_json(path: Path, *, field_name: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScheduleSourceIngestionError(f"Missing {field_name}: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ScheduleSourceIngestionError(f"Failed to read {field_name}: {path}") from exc
    if not isinstance(payload, dict):
        raise ScheduleSourceIngestionError(f"Malformed {field_name}: expected JSON object")
    return payload


def _validate_and_parse_source_csv_gz(
    payload_bytes: bytes,
    *,
    asset_size_bytes_reported: int | None,
    asset_digest_reported: str | None,
) -> tuple[list[dict[str, Any]], tuple[str, ...], int, int | None, int | None, dict[str, int], str, int]:
    if not payload_bytes:
        raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_EMPTY_PAYLOAD")

    if asset_size_bytes_reported is not None and int(asset_size_bytes_reported) != len(payload_bytes):
        raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_SIZE_MISMATCH")

    if payload_bytes[:2] != b"\x1f\x8b":
        prefix = payload_bytes[:64].lstrip().lower()
        if prefix.startswith(b"<"):
            raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_HTML_RESPONSE")
        if prefix.startswith(b"{"):
            raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_JSON_RESPONSE")
        raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_GZIP_MAGIC_MISSING")

    content_sha256 = _sha256_hex_bytes(payload_bytes)

    if asset_digest_reported:
        normalized = asset_digest_reported.strip()
        if normalized.lower().startswith("sha256:"):
            normalized = normalized.split(":", 1)[1]
        if normalized and normalized.lower() != content_sha256.lower():
            raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_DIGEST_MISMATCH")

    try:
        decompressed = gzip.decompress(payload_bytes)
    except (OSError, EOFError) as exc:
        raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_GZIP_INVALID") from exc

    try:
        text = decompressed.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_DECODE_FAILED") from exc

    reader = csv.DictReader(text.splitlines())
    fieldnames = tuple(reader.fieldnames or ())
    if not fieldnames:
        raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_SCHEMA_MISSING")

    required = (
        "game_id",
        "season",
        "week",
        "game_type",
        "gameday",
        "gametime",
        "away_team",
        "home_team",
    )
    missing = [item for item in required if item not in fieldnames]
    if missing:
        raise ScheduleSourceIngestionError(f"SCHEDULE_SOURCE_SCHEMA_MISSING_FIELDS: {','.join(sorted(missing))}")

    rows: list[dict[str, Any]] = []
    game_ids: set[str] = set()
    game_type_counts: Counter[str] = Counter()
    season_min: int | None = None
    season_max: int | None = None

    for raw in reader:
        game_id = str(raw.get("game_id") or "").strip()
        if not game_id:
            raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_GAME_ID_MISSING")
        if game_id in game_ids:
            raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_DUPLICATE_GAME_ID")
        game_ids.add(game_id)

        try:
            season = int(str(raw.get("season") or "").strip())
            week = int(str(raw.get("week") or "").strip())
        except ValueError as exc:
            raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_SEASON_WEEK_INVALID") from exc
        if season <= 0 or week <= 0:
            raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_SEASON_WEEK_INVALID")

        game_type = str(raw.get("game_type") or "").strip()
        if not game_type:
            raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_GAME_TYPE_MISSING")

        gameday = str(raw.get("gameday") or "").strip()
        gametime = str(raw.get("gametime") or "").strip()
        away_team = str(raw.get("away_team") or "").strip()
        home_team = str(raw.get("home_team") or "").strip()

        game_type_counts[game_type] += 1
        season_min = season if season_min is None else min(season_min, season)
        season_max = season if season_max is None else max(season_max, season)

        rows.append(
            {
                "game_id": game_id,
                "season": season,
                "week": week,
                "game_type": game_type,
                "gameday": gameday,
                "gametime": gametime,
                "away_team": away_team,
                "home_team": home_team,
            }
        )

    if not rows:
        raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_EMPTY_ROWS")

    return (
        rows,
        fieldnames,
        len(rows),
        season_min,
        season_max,
        dict(sorted(game_type_counts.items())),
        content_sha256,
        len(payload_bytes),
    )


def _canonical_schedule_from_rows(
    *,
    season: int,
    week: int,
    rows: list[dict[str, Any]],
    source_version: str,
    source_content_sha256: str,
    source_manifest_identity: str,
    generated_at: str,
) -> CanonicalWeeklySchedule:
    events = schedule_service._materialize_events(rows=rows, season=season, week=week)
    schedule_hash = schedule_service._schedule_hash(events, season=season, week=week)
    schedule_version = f"canonical-schedule-v2:{season}:{week}:{schedule_hash[:12]}"

    base = CanonicalWeeklySchedule(
        schedule_version=schedule_version,
        schedule_hash=schedule_hash,
        season=season,
        week=week,
        event_count=len(events),
        source="nflverse",
        source_version=source_version,
        source_dataset_version="schedules",
        source_content_sha256=source_content_sha256,
        source_manifest_identity=source_manifest_identity,
        generated_at=generated_at,
        payload_hash="",
        events=events,
    )
    schedule = CanonicalWeeklySchedule(
        schedule_version=base.schedule_version,
        schedule_hash=base.schedule_hash,
        season=base.season,
        week=base.week,
        event_count=base.event_count,
        source=base.source,
        source_version=base.source_version,
        source_dataset_version=base.source_dataset_version,
        source_content_sha256=base.source_content_sha256,
        source_manifest_identity=base.source_manifest_identity,
        generated_at=base.generated_at,
        payload_hash=schedule_service._payload_hash(base),
        events=base.events,
    )
    schedule_service._validate_schedule(schedule)
    return schedule


def _week_required_field_missing_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    missing_gameday = 0
    missing_gametime = 0
    missing_away_team = 0
    missing_home_team = 0
    invalid_team_id = 0
    complete_source_rows = 0

    for row in rows:
        gameday = str(row.get("gameday") or "").strip()
        gametime = str(row.get("gametime") or "").strip()
        away_team = str(row.get("away_team") or "").strip()
        home_team = str(row.get("home_team") or "").strip()

        if not gameday:
            missing_gameday += 1
        if not gametime:
            missing_gametime += 1
        if not away_team:
            missing_away_team += 1
        if not home_team:
            missing_home_team += 1

        if not (gameday and gametime and away_team and home_team):
            continue

        try:
            normalize_team_id(away_team)
            normalize_team_id(home_team)
        except Exception:
            invalid_team_id += 1
            continue

        complete_source_rows += 1

    return {
        "missingGameday": missing_gameday,
        "missingGametime": missing_gametime,
        "missingAwayTeam": missing_away_team,
        "missingHomeTeam": missing_home_team,
        "invalidTeamId": invalid_team_id,
        "completeSourceRows": complete_source_rows,
    }


def _persist_manifest_and_source_bytes(
    *,
    store: ScheduleEngineStore,
    source_version: str,
    manifest: ScheduleSourceManifest,
    payload_bytes: bytes,
) -> dict[str, Any]:
    lock_path = _source_locks_root(store) / f"source-{hashlib.sha256(source_version.encode('utf-8')).hexdigest()[:16]}.lock"
    with _file_lock(lock_path):
        target_dir = _source_version_dir(store, source_version)
        manifest_path = _source_manifest_path(store, source_version)
        bytes_path = _source_bytes_path(store, source_version)
        target_dir.mkdir(parents=True, exist_ok=True)

        if manifest_path.exists() and bytes_path.exists():
            existing_manifest = _read_json(manifest_path, field_name="source manifest")
            existing_bytes = bytes_path.read_bytes()
            if existing_bytes != payload_bytes:
                raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_IMMUTABLE_CONFLICT")
            existing_immutable = _manifest_immutable_payload(existing_manifest)
            candidate_immutable = _manifest_immutable_payload(manifest)
            if _canonical_json(existing_immutable) != _canonical_json(candidate_immutable):
                raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_MANIFEST_CONFLICT")
            return {"status": "ALREADY_PERSISTED", "path": str(target_dir)}

        _atomic_write_bytes(bytes_path, payload_bytes)
        readback = bytes_path.read_bytes()
        if readback != payload_bytes:
            raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_READBACK_MISMATCH")
        if _sha256_hex_bytes(readback) != manifest.content_sha256_computed:
            raise ScheduleSourceIngestionError("SCHEDULE_SOURCE_READBACK_HASH_MISMATCH")

        _atomic_write_text(manifest_path, _canonical_json(asdict(manifest)))
        return {"status": "PERSISTED", "path": str(target_dir)}


def _persist_canonical_version(store: ScheduleEngineStore, schedule: CanonicalWeeklySchedule) -> dict[str, Any]:
    path = _canonical_version_path(store, schedule)
    payload = _canonical_json(asdict(schedule))
    if path.exists():
        existing = schedule_service._schedule_from_payload(_read_json(path, field_name="canonical weekly schedule"))
        if existing.schedule_hash == schedule.schedule_hash:
            return {"status": "ALREADY_PERSISTED", "path": str(path), "schedule": asdict(existing)}
        raise ScheduleSourceIngestionError("CANONICAL_IMMUTABLE_CONFLICT")

    _atomic_write_text(path, payload)
    readback = schedule_service._schedule_from_payload(_read_json(path, field_name="canonical weekly schedule"))
    if readback.schedule_hash != schedule.schedule_hash or readback.schedule_version != schedule.schedule_version:
        raise ScheduleSourceIngestionError("CANONICAL_READBACK_VERIFICATION_FAILED")
    return {"status": "PERSISTED", "path": str(path), "schedule": asdict(readback)}


def _read_active_pointer(store: ScheduleEngineStore, *, season: int, week: int) -> ActiveSchedulePointer | None:
    path = _active_pointer_path(store, season, week)
    if not path.exists():
        return None
    payload = _read_json(path, field_name="active schedule pointer")
    return ActiveSchedulePointer(
        season=int(payload["season"]),
        week=int(payload["week"]),
        schedule_version=str(payload["schedule_version"]),
        schedule_hash=str(payload["schedule_hash"]),
        source_version=str(payload["source_version"]),
        source_content_sha256=str(payload["source_content_sha256"]),
        canonical_artifact_path=str(payload["canonical_artifact_path"]),
        activated_at=str(payload["activated_at"]),
    )


def _validate_active_pointer_target(pointer: ActiveSchedulePointer, *, season: int, week: int) -> None:
    if pointer.season != season or pointer.week != week:
        raise ScheduleSourceIngestionError("ACTIVE_SCHEDULE_POINTER_IDENTITY_MISMATCH")


def _publish_active_pointer(store: ScheduleEngineStore, *, pointer: ActiveSchedulePointer) -> None:
    path = _active_pointer_path(store, pointer.season, pointer.week)
    _atomic_write_text(path, _canonical_json(asdict(pointer)))


def _load_versioned_schedule_by_identity(
    *,
    store: ScheduleEngineStore,
    season: int,
    week: int,
    schedule_version: str,
    schedule_hash: str,
) -> CanonicalWeeklySchedule:
    path = _canonical_versions_dir(store, season, week) / f"{schedule_version}.json"
    if not path.exists():
        raise ScheduleSourceIngestionError("ACTIVE_SCHEDULE_ARTIFACT_MISSING")
    schedule = schedule_service._schedule_from_payload(_read_json(path, field_name="canonical weekly schedule"))
    if schedule.season != season or schedule.week != week:
        raise ScheduleSourceIngestionError("ACTIVE_SCHEDULE_IDENTITY_MISMATCH")
    if schedule.schedule_version != schedule_version:
        raise ScheduleSourceIngestionError("ACTIVE_SCHEDULE_VERSION_MISMATCH")
    if schedule.schedule_hash != schedule_hash:
        raise ScheduleSourceIngestionError("ACTIVE_SCHEDULE_HASH_MISMATCH")
    return schedule


def load_active_schedule(*, season: int, week: int, store: ScheduleEngineStore | None = None) -> CanonicalWeeklySchedule:
    target_store = store or default_schedule_engine_store()
    pointer = _read_active_pointer(target_store, season=season, week=week)
    if pointer is None:
        raise ScheduleSourceIngestionError("ACTIVE_SCHEDULE_POINTER_MISSING")
    _validate_active_pointer_target(pointer, season=season, week=week)
    schedule = _load_versioned_schedule_by_identity(
        store=target_store,
        season=season,
        week=week,
        schedule_version=pointer.schedule_version,
        schedule_hash=pointer.schedule_hash,
    )
    if schedule.source_version != pointer.source_version:
        raise ScheduleSourceIngestionError("ACTIVE_SCHEDULE_SOURCE_VERSION_MISMATCH")
    if schedule.source_content_sha256 != pointer.source_content_sha256:
        raise ScheduleSourceIngestionError("ACTIVE_SCHEDULE_SOURCE_HASH_MISMATCH")
    return schedule


def load_active_schedule_by_identity(
    *,
    season: int,
    week: int,
    schedule_version: str,
    schedule_hash: str,
    store: ScheduleEngineStore | None = None,
) -> CanonicalWeeklySchedule:
    target_store = store or default_schedule_engine_store()
    schedule = _load_versioned_schedule_by_identity(
        store=target_store,
        season=season,
        week=week,
        schedule_version=schedule_version,
        schedule_hash=schedule_hash,
    )
    pointer = _read_active_pointer(target_store, season=season, week=week)
    if pointer is None:
        raise ScheduleSourceIngestionError("ACTIVE_SCHEDULE_POINTER_MISSING")
    _validate_active_pointer_target(pointer, season=season, week=week)
    if pointer.schedule_version != schedule_version or pointer.schedule_hash != schedule_hash:
        raise ScheduleSourceIngestionError("ACTIVE_SCHEDULE_POINTER_IDENTITY_MISMATCH")
    return schedule


def _week_consumed(
    *,
    season: int,
    week: int,
    result_store: ResultEngineStore,
    power_store: PowerEngineStore,
) -> tuple[bool, str | None]:
    frozen = load_frozen_week_result_set(result_store, season=season, week=week)
    if frozen is not None:
        return True, "FROZEN_RESULT_SET_EXISTS"

    transitions = list_power_weekly_transitions(power_store=power_store, season=season, week=week)
    if transitions:
        return True, "POWER_TRANSITION_EXISTS"

    # If there is no active lineage for this season yet, the week is not consumed.
    try:
        power_store.get_active_lineage(season)
    except Exception:
        return False, None

    try:
        obs = active_power_transition_observability(power_store=power_store, season=season)
    except Exception:
        # Fail closed when consumed-state observability cannot be trusted.
        return True, "CONSUMED_STATE_UNVERIFIED"

    if isinstance(obs, dict):
        through_week = obs.get("throughWeek")
        if isinstance(through_week, int) and through_week >= week:
            return True, "POWER_LINEAGE_ALREADY_THROUGH_WEEK"

    return False, None


def compare_candidate_to_legacy_seed(
    *,
    candidate: CanonicalWeeklySchedule,
    store: ScheduleEngineStore | None = None,
) -> dict[str, Any]:
    target_store = store or default_schedule_engine_store()
    legacy = load_canonical_weekly_schedule(season=candidate.season, week=candidate.week, store=target_store)
    if legacy is None:
        return {
            "status": "NO_LEGACY",
            "season": candidate.season,
            "week": candidate.week,
        }

    legacy_events = sorted(
        [
            {
                "source_event_id": event.source_event_id,
                "canonical_event_key": event.canonical_event_key,
                "game_type": event.game_type,
                "kickoff_utc": event.kickoff_utc,
                "away_team": event.away_team,
                "home_team": event.home_team,
            }
            for event in legacy.events
        ],
        key=lambda item: (item["kickoff_utc"], item["canonical_event_key"]),
    )
    candidate_events = sorted(
        [
            {
                "source_event_id": event.source_event_id,
                "canonical_event_key": event.canonical_event_key,
                "game_type": event.game_type,
                "kickoff_utc": event.kickoff_utc,
                "away_team": event.away_team,
                "home_team": event.home_team,
            }
            for event in candidate.events
        ],
        key=lambda item: (item["kickoff_utc"], item["canonical_event_key"]),
    )

    parity = (
        legacy.season == candidate.season
        and legacy.week == candidate.week
        and legacy.event_count == candidate.event_count
        and legacy.schedule_hash == candidate.schedule_hash
        and legacy_events == candidate_events
    )

    if parity:
        return {
            "status": "PARITY",
            "season": candidate.season,
            "week": candidate.week,
            "schedule_hash": candidate.schedule_hash,
        }

    return {
        "status": "DIFF",
        "season": candidate.season,
        "week": candidate.week,
        "legacy": {
            "event_count": legacy.event_count,
            "schedule_hash": legacy.schedule_hash,
            "events": legacy_events,
        },
        "candidate": {
            "event_count": candidate.event_count,
            "schedule_hash": candidate.schedule_hash,
            "events": candidate_events,
        },
    }


def ingest_nflverse_schedule_source_bytes(
    *,
    payload_bytes: bytes,
    source_uri: str,
    release_tag: str,
    release_id: str,
    release_published_at: str | None,
    release_updated_at: str | None,
    target_commitish: str | None,
    asset_name: str,
    asset_id: str,
    asset_updated_at: str | None,
    asset_size_bytes_reported: int | None,
    asset_digest_reported: str | None,
    http_etag: str | None,
    http_last_modified: str | None,
    store: ScheduleEngineStore | None = None,
    result_store: ResultEngineStore | None = None,
    power_store: PowerEngineStore | None = None,
    ingestion_run_id: str | None = None,
) -> dict[str, Any]:
    from app.services.power_engine.persistence import default_power_engine_store

    target_store = store or default_schedule_engine_store()
    target_result_store = result_store or default_result_engine_store()
    target_power_store = power_store or default_power_engine_store()

    (
        rows,
        schema_fields,
        row_count,
        season_min,
        season_max,
        game_type_counts,
        content_sha256,
        byte_count,
    ) = _validate_and_parse_source_csv_gz(
        payload_bytes,
        asset_size_bytes_reported=asset_size_bytes_reported,
        asset_digest_reported=asset_digest_reported,
    )

    source_version = _source_version_formula(
        release_tag=release_tag,
        release_id=release_id,
        asset_name=asset_name,
        asset_id=asset_id,
        asset_updated_at=asset_updated_at,
        content_sha256=content_sha256,
    )
    run_id = ingestion_run_id or f"ing-{uuid.uuid4().hex[:16]}"
    manifest_identity = hashlib.sha256(source_version.encode("utf-8")).hexdigest()[:16]
    manifest = ScheduleSourceManifest(
        source="nflverse",
        dataset="schedules",
        source_uri=source_uri,
        retrieved_at_utc=_utc_now_iso(),
        release_tag=release_tag,
        release_id=release_id,
        release_published_at=release_published_at,
        release_updated_at=release_updated_at,
        target_commitish=target_commitish,
        asset_name=asset_name,
        asset_id=asset_id,
        asset_updated_at=asset_updated_at,
        asset_size_bytes_reported=asset_size_bytes_reported,
        asset_digest_reported=asset_digest_reported,
        http_etag=http_etag,
        http_last_modified=http_last_modified,
        content_sha256_computed=content_sha256,
        byte_count_downloaded=byte_count,
        parser_format="csv.gz",
        schema_field_list=schema_fields,
        schema_field_count=len(schema_fields),
        row_count=row_count,
        season_min=season_min,
        season_max=season_max,
        game_type_counts=game_type_counts,
        validation_status="VALID",
        ingestion_run_id=run_id,
        source_version=source_version,
    )

    persisted_source = _persist_manifest_and_source_bytes(
        store=target_store,
        source_version=source_version,
        manifest=manifest,
        payload_bytes=payload_bytes,
    )

    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["season"], row["week"])].append(row)

    week_results: list[dict[str, Any]] = []
    legacy_parity: list[dict[str, Any]] = []

    for (season, week) in sorted(grouped.keys()):
        week_rows = grouped[(season, week)]
        with _file_lock(_active_pointer_lock_path(target_store, season, week)):
            missing_counts = _week_required_field_missing_counts(week_rows)
            if any(missing_counts[key] > 0 for key in ("missingGameday", "missingGametime", "missingAwayTeam", "missingHomeTeam", "invalidTeamId")):
                week_results.append(
                    {
                        "season": season,
                        "week": week,
                        "status": "CONFLICT_INCOMPLETE_WEEK",
                        "reason": "TARGET_WEEK_REQUIRED_FIELDS_MISSING",
                        "sourceRowCount": len(week_rows),
                        "completeSourceRowCount": int(missing_counts["completeSourceRows"]),
                        "canonicalEventCount": 0,
                        "missingRequiredFieldCounts": {
                            "missingGameday": int(missing_counts["missingGameday"]),
                            "missingGametime": int(missing_counts["missingGametime"]),
                            "missingAwayTeam": int(missing_counts["missingAwayTeam"]),
                            "missingHomeTeam": int(missing_counts["missingHomeTeam"]),
                            "invalidTeamId": int(missing_counts["invalidTeamId"]),
                        },
                    }
                )
                continue

            candidate = _canonical_schedule_from_rows(
                season=season,
                week=week,
                rows=week_rows,
                source_version=source_version,
                source_content_sha256=content_sha256,
                source_manifest_identity=manifest_identity,
                generated_at=_utc_now_iso(),
            )
            persisted_candidate = _persist_canonical_version(target_store, candidate)
            legacy_parity.append(compare_candidate_to_legacy_seed(candidate=candidate, store=target_store))

            active_pointer = _read_active_pointer(target_store, season=season, week=week)
            if active_pointer is None:
                _publish_active_pointer(
                    target_store,
                    pointer=ActiveSchedulePointer(
                        season=season,
                        week=week,
                        schedule_version=candidate.schedule_version,
                        schedule_hash=candidate.schedule_hash,
                        source_version=source_version,
                        source_content_sha256=content_sha256,
                        canonical_artifact_path=str(_canonical_version_path(target_store, candidate)),
                        activated_at=_utc_now_iso(),
                    ),
                )
                week_results.append(
                    {
                        "season": season,
                        "week": week,
                        "status": "PROMOTED_INITIAL",
                        "scheduleHash": candidate.schedule_hash,
                        "scheduleVersion": candidate.schedule_version,
                        "persistedCanonical": persisted_candidate["status"],
                    }
                )
                continue

            active = _load_versioned_schedule_by_identity(
                store=target_store,
                season=season,
                week=week,
                schedule_version=active_pointer.schedule_version,
                schedule_hash=active_pointer.schedule_hash,
            )
            if active.schedule_hash == candidate.schedule_hash:
                week_results.append(
                    {
                        "season": season,
                        "week": week,
                        "status": "UNCHANGED_CANONICAL",
                        "scheduleHash": candidate.schedule_hash,
                        "scheduleVersion": active.schedule_version,
                        "persistedCanonical": persisted_candidate["status"],
                    }
                )
                continue

            consumed, reason = _week_consumed(
                season=season,
                week=week,
                result_store=target_result_store,
                power_store=target_power_store,
            )
            if consumed:
                week_results.append(
                    {
                        "season": season,
                        "week": week,
                        "status": "CONFLICT_CONSUMED_WEEK",
                        "reason": reason,
                        "activeScheduleHash": active.schedule_hash,
                        "candidateScheduleHash": candidate.schedule_hash,
                        "persistedCanonical": persisted_candidate["status"],
                    }
                )
                continue

            _publish_active_pointer(
                target_store,
                pointer=ActiveSchedulePointer(
                    season=season,
                    week=week,
                    schedule_version=candidate.schedule_version,
                    schedule_hash=candidate.schedule_hash,
                    source_version=source_version,
                    source_content_sha256=content_sha256,
                    canonical_artifact_path=str(_canonical_version_path(target_store, candidate)),
                    activated_at=_utc_now_iso(),
                ),
            )
            week_results.append(
                {
                    "season": season,
                    "week": week,
                    "status": "PROMOTED_UPDATED",
                    "priorScheduleHash": active.schedule_hash,
                    "scheduleHash": candidate.schedule_hash,
                    "scheduleVersion": candidate.schedule_version,
                    "persistedCanonical": persisted_candidate["status"],
                }
            )

    return {
        "status": "INGESTED",
        "sourceVersion": source_version,
        "sourcePersisted": persisted_source["status"],
        "manifest": asdict(manifest),
        "weeks": week_results,
        "legacyParity": legacy_parity,
    }


def retrieve_nflverse_games_csv_gz_release_asset(
    *,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    try:
        import requests
    except Exception as exc:  # pragma: no cover
        raise ScheduleSourceIngestionError("REQUESTS_UNAVAILABLE") from exc

    release_url = "https://api.github.com/repos/nflverse/nflverse-data/releases/tags/schedules"
    release_response = requests.get(release_url, timeout=timeout_seconds)
    if release_response.status_code != 200:
        raise ScheduleSourceIngestionError("RELEASE_METADATA_HTTP_FAILURE")
    release_payload = release_response.json()
    if not isinstance(release_payload, dict):
        raise ScheduleSourceIngestionError("RELEASE_METADATA_INVALID")

    assets = release_payload.get("assets")
    if not isinstance(assets, list):
        raise ScheduleSourceIngestionError("RELEASE_ASSETS_MISSING")

    target_asset = None
    for asset in assets:
        if isinstance(asset, dict) and asset.get("name") == "games.csv.gz":
            target_asset = asset
            break
    if target_asset is None:
        raise ScheduleSourceIngestionError("RELEASE_GAMES_CSV_GZ_MISSING")

    source_uri = str(target_asset.get("browser_download_url") or "").strip()
    if not source_uri:
        raise ScheduleSourceIngestionError("RELEASE_ASSET_URI_MISSING")

    source_response = requests.get(source_uri, timeout=timeout_seconds)
    if source_response.status_code != 200:
        raise ScheduleSourceIngestionError("SOURCE_HTTP_FAILURE")

    return {
        "payload_bytes": source_response.content,
        "source_uri": source_uri,
        "release_tag": str(release_payload.get("tag_name") or "schedules"),
        "release_id": str(release_payload.get("id") or ""),
        "release_published_at": release_payload.get("published_at"),
        "release_updated_at": release_payload.get("updated_at"),
        "target_commitish": release_payload.get("target_commitish"),
        "asset_name": str(target_asset.get("name") or "games.csv.gz"),
        "asset_id": str(target_asset.get("id") or ""),
        "asset_updated_at": target_asset.get("updated_at"),
        "asset_size_bytes_reported": int(target_asset["size"]) if target_asset.get("size") is not None else None,
        "asset_digest_reported": target_asset.get("digest"),
        "http_etag": source_response.headers.get("ETag"),
        "http_last_modified": source_response.headers.get("Last-Modified"),
    }
