from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.result_engine import ResultEngineStore, default_result_engine_store, load_frozen_week_result_set

from .contracts import FinalGameResult, PowerLineageRecord, PowerSnapshot
from .hashing import canonical_json, sha256_hex
from .methodology import FROZEN_METHODOLOGY, UPDATER_VERSION, FrozenMethodology
from .persistence import (
    PowerEnginePersistenceError,
    PowerEngineStore,
    build_ledger_record,
    default_power_engine_store,
)
from .trusted_result_mapper import accepted_result_to_final_game_result
from .updater import apply_week_results

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None


class PowerWeeklyTransitionError(ValueError):
    pass


@dataclass(frozen=True)
class PowerWeeklyTransitionRecord:
    transition_id: str
    season: int
    week: int
    prior_snapshot_id: str
    prior_snapshot_hash: str
    new_snapshot_id: str
    new_snapshot_hash: str
    result_set_version: str
    result_set_hash: str
    methodology_hash: str
    updater_version: str
    game_count_expected: int
    game_count_applied: int
    applied_game_ids_sorted: tuple[str, ...]
    applied_event_identity_hash: str
    transition_status: str
    parent_lineage_id: str
    new_lineage_id: str
    idempotency_key: str
    payload_hash: str
    created_at: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso_timestamp(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PowerWeeklyTransitionError(f"{field_name} must be a non-empty string")
    text = value.strip().replace("Z", "+00:00")
    try:
        datetime.fromisoformat(text)
    except ValueError as exc:
        raise PowerWeeklyTransitionError(f"Invalid {field_name}: {value}") from exc
    return value


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
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


def _transition_dirs(store: PowerEngineStore) -> tuple[Path, Path]:
    transitions_dir = store.root_dir / "meta" / "transitions"
    staged_dir = transitions_dir / "staged"
    return transitions_dir, staged_dir


def _transition_lock_path(store: PowerEngineStore, season: int, week: int) -> Path:
    return store.root_dir / "meta" / "locks" / f"weekly-transition-{season}-{week}.lock"


@contextmanager
def _transition_lock(store: PowerEngineStore, *, season: int, week: int):
    lock_path = _transition_lock_path(store, season, week)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_json_file(path: Path, *, field_name: str) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PowerWeeklyTransitionError(f"Failed to read {field_name}: {path}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PowerWeeklyTransitionError(f"Corrupt JSON in {field_name}: {path}") from exc
    if not isinstance(payload, dict):
        raise PowerWeeklyTransitionError(f"Malformed {field_name}: expected JSON object")
    return payload


def _normalize_transition(payload: dict[str, Any]) -> PowerWeeklyTransitionRecord:
    required = set(PowerWeeklyTransitionRecord.__dataclass_fields__.keys())
    missing = sorted(required - set(payload.keys()))
    if missing:
        raise PowerWeeklyTransitionError(f"Malformed transition record missing fields: {missing}")
    rec = PowerWeeklyTransitionRecord(
        transition_id=str(payload["transition_id"]),
        season=int(payload["season"]),
        week=int(payload["week"]),
        prior_snapshot_id=str(payload["prior_snapshot_id"]),
        prior_snapshot_hash=str(payload["prior_snapshot_hash"]),
        new_snapshot_id=str(payload["new_snapshot_id"]),
        new_snapshot_hash=str(payload["new_snapshot_hash"]),
        result_set_version=str(payload["result_set_version"]),
        result_set_hash=str(payload["result_set_hash"]),
        methodology_hash=str(payload["methodology_hash"]),
        updater_version=str(payload["updater_version"]),
        game_count_expected=int(payload["game_count_expected"]),
        game_count_applied=int(payload["game_count_applied"]),
        applied_game_ids_sorted=tuple(str(item) for item in payload["applied_game_ids_sorted"]),
        applied_event_identity_hash=str(payload["applied_event_identity_hash"]),
        transition_status=str(payload["transition_status"]),
        parent_lineage_id=str(payload["parent_lineage_id"]),
        new_lineage_id=str(payload["new_lineage_id"]),
        idempotency_key=str(payload["idempotency_key"]),
        payload_hash=str(payload["payload_hash"]),
        created_at=str(payload["created_at"]),
    )
    _parse_iso_timestamp(rec.created_at, "created_at")
    return rec


def _transition_identity_payload(
    *,
    season: int,
    week: int,
    parent_lineage_id: str,
    prior_snapshot_id: str,
    prior_snapshot_hash: str,
    result_set_version: str,
    result_set_hash: str,
    methodology_hash: str,
    updater_version: str,
) -> dict[str, Any]:
    return {
        "season": int(season),
        "week": int(week),
        "parentLineageId": str(parent_lineage_id),
        "priorSnapshotId": str(prior_snapshot_id),
        "priorSnapshotHash": str(prior_snapshot_hash),
        "resultSetVersion": str(result_set_version),
        "resultSetHash": str(result_set_hash),
        "methodologyHash": str(methodology_hash),
        "updaterVersion": str(updater_version),
    }


def _build_transition_idempotency_key(identity_payload: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(identity_payload))


def _build_transition_id(idempotency_key: str) -> str:
    return f"powtr-{idempotency_key[:16]}"


def _transition_payload_for_hash(record: PowerWeeklyTransitionRecord) -> dict[str, Any]:
    return {
        "transition_id": record.transition_id,
        "season": record.season,
        "week": record.week,
        "prior_snapshot_id": record.prior_snapshot_id,
        "prior_snapshot_hash": record.prior_snapshot_hash,
        "new_snapshot_id": record.new_snapshot_id,
        "new_snapshot_hash": record.new_snapshot_hash,
        "result_set_version": record.result_set_version,
        "result_set_hash": record.result_set_hash,
        "methodology_hash": record.methodology_hash,
        "updater_version": record.updater_version,
        "game_count_expected": record.game_count_expected,
        "game_count_applied": record.game_count_applied,
        "applied_game_ids_sorted": list(record.applied_game_ids_sorted),
        "applied_event_identity_hash": record.applied_event_identity_hash,
        "transition_status": record.transition_status,
        "parent_lineage_id": record.parent_lineage_id,
        "new_lineage_id": record.new_lineage_id,
        "idempotency_key": record.idempotency_key,
    }


def _build_transition_payload_hash(record: PowerWeeklyTransitionRecord) -> str:
    return sha256_hex(canonical_json(_transition_payload_for_hash(record)))


def _transition_record_from(
    *,
    season: int,
    week: int,
    prior_snapshot: PowerSnapshot,
    new_snapshot: PowerSnapshot,
    result_set_version: str,
    result_set_hash: str,
    methodology_hash: str,
    updater_version: str,
    game_ids_sorted: tuple[str, ...],
    parent_lineage_id: str,
    new_lineage_id: str,
    created_at: str,
) -> PowerWeeklyTransitionRecord:
    identity_payload = _transition_identity_payload(
        season=season,
        week=week,
        parent_lineage_id=parent_lineage_id,
        prior_snapshot_id=prior_snapshot.snapshot_id,
        prior_snapshot_hash=prior_snapshot.snapshot_hash,
        result_set_version=result_set_version,
        result_set_hash=result_set_hash,
        methodology_hash=methodology_hash,
        updater_version=updater_version,
    )
    idempotency_key = _build_transition_idempotency_key(identity_payload)
    transition_id = _build_transition_id(idempotency_key)
    event_identity_hash = sha256_hex(canonical_json({"gameIds": list(game_ids_sorted)}))

    base = PowerWeeklyTransitionRecord(
        transition_id=transition_id,
        season=int(season),
        week=int(week),
        prior_snapshot_id=prior_snapshot.snapshot_id,
        prior_snapshot_hash=prior_snapshot.snapshot_hash,
        new_snapshot_id=new_snapshot.snapshot_id,
        new_snapshot_hash=new_snapshot.snapshot_hash,
        result_set_version=result_set_version,
        result_set_hash=result_set_hash,
        methodology_hash=methodology_hash,
        updater_version=updater_version,
        game_count_expected=len(game_ids_sorted),
        game_count_applied=len(game_ids_sorted),
        applied_game_ids_sorted=game_ids_sorted,
        applied_event_identity_hash=event_identity_hash,
        transition_status="APPLIED",
        parent_lineage_id=parent_lineage_id,
        new_lineage_id=new_lineage_id,
        idempotency_key=idempotency_key,
        payload_hash="",
        created_at=created_at,
    )
    payload_hash = _build_transition_payload_hash(base)
    return PowerWeeklyTransitionRecord(**{**asdict(base), "payload_hash": payload_hash})


def _load_transition_records(store: PowerEngineStore) -> tuple[dict[str, PowerWeeklyTransitionRecord], dict[str, PowerWeeklyTransitionRecord]]:
    transitions_dir, staged_dir = _transition_dirs(store)
    transitions: dict[str, PowerWeeklyTransitionRecord] = {}
    staged: dict[str, PowerWeeklyTransitionRecord] = {}

    if transitions_dir.exists():
        for path in sorted(transitions_dir.glob("*.json")):
            rec = _normalize_transition(_read_json_file(path, field_name="power transition"))
            transitions[rec.transition_id] = rec

    if staged_dir.exists():
        for path in sorted(staged_dir.glob("*.json")):
            rec = _normalize_transition(_read_json_file(path, field_name="staged power transition"))
            staged[rec.transition_id] = rec

    return transitions, staged


def _persist_transition_staged(store: PowerEngineStore, record: PowerWeeklyTransitionRecord) -> None:
    _, staged_dir = _transition_dirs(store)
    path = staged_dir / f"{record.transition_id}.json"
    _atomic_write_text(path, canonical_json(asdict(record)))


def _persist_transition_applied(store: PowerEngineStore, record: PowerWeeklyTransitionRecord) -> None:
    transitions_dir, staged_dir = _transition_dirs(store)
    transitions_dir.mkdir(parents=True, exist_ok=True)
    applied_path = transitions_dir / f"{record.transition_id}.json"
    _atomic_write_text(applied_path, canonical_json(asdict(record)))

    staged_path = staged_dir / f"{record.transition_id}.json"
    if staged_path.exists():
        try:
            staged_path.unlink()
        except OSError:
            pass


def _existing_transition_conflict(
    *,
    records: dict[str, PowerWeeklyTransitionRecord],
    season: int,
    week: int,
    parent_lineage_id: str,
    expected_idempotency_key: str,
) -> PowerWeeklyTransitionRecord | None:
    for rec in records.values():
        if rec.season != season or rec.week != week:
            continue
        if rec.parent_lineage_id != parent_lineage_id:
            continue
        if rec.idempotency_key != expected_idempotency_key:
            return rec
    return None


def _expected_methodology_hash(*, methodology: FrozenMethodology, updater_version: str) -> str:
    from .hashing import methodology_hash as _methodology_hash

    return _methodology_hash(methodology, updater_version)


def _derive_new_lineage_id(
    *,
    season: int,
    week: int,
    new_snapshot_hash: str,
    parent_lineage_id: str,
) -> str:
    seed = sha256_hex(
        canonical_json(
            {
                "season": season,
                "week": week,
                "newSnapshotHash": new_snapshot_hash,
                "parentLineageId": parent_lineage_id,
            }
        )
    )
    return f"ln-{season}-wk{week}-{seed[:12]}"


def _build_lineage_record(
    *,
    previous_active: PowerLineageRecord,
    new_snapshot: PowerSnapshot,
    season: int,
    week: int,
    created_at: str,
) -> PowerLineageRecord:
    lineage_id = _derive_new_lineage_id(
        season=season,
        week=week,
        new_snapshot_hash=new_snapshot.snapshot_hash,
        parent_lineage_id=previous_active.lineage_id,
    )
    return PowerLineageRecord(
        lineage_id=lineage_id,
        parent_lineage_id=previous_active.lineage_id,
        root_snapshot_id=previous_active.root_snapshot_id,
        active_snapshot_id=new_snapshot.snapshot_id,
        season=season,
        through_week=week,
        status="ACTIVE",
        created_at=created_at,
        superseded_at=None,
        superseded_by=None,
    )


def _validate_frozen_results_inputs(
    *,
    season: int,
    week: int,
    frozen: Any,
) -> None:
    if frozen is None:
        raise PowerWeeklyTransitionError("FROZEN_RESULT_SET_MISSING")
    if int(frozen.season) != season:
        raise PowerWeeklyTransitionError("FROZEN_RESULT_SET_SEASON_MISMATCH")
    if int(frozen.week) != week:
        raise PowerWeeklyTransitionError("FROZEN_RESULT_SET_WEEK_MISMATCH")
    if not str(frozen.result_set_version or "").strip():
        raise PowerWeeklyTransitionError("FROZEN_RESULT_SET_VERSION_MISSING")
    if not str(frozen.result_set_hash or "").strip():
        raise PowerWeeklyTransitionError("FROZEN_RESULT_SET_HASH_MISSING")
    if int(frozen.expected_game_count) <= 0:
        raise PowerWeeklyTransitionError("FROZEN_RESULT_SET_EXPECTED_COUNT_INVALID")
    if int(frozen.accepted_final_count) != int(frozen.expected_game_count):
        raise PowerWeeklyTransitionError("FROZEN_RESULT_SET_INCOMPLETE")
    if len(frozen.accepted_results) != int(frozen.expected_game_count):
        raise PowerWeeklyTransitionError("FROZEN_RESULT_SET_ACCEPTED_COUNT_MISMATCH")


def _validate_prior_snapshot(*, season: int, week: int, snapshot: PowerSnapshot) -> None:
    if snapshot.season != season:
        raise PowerWeeklyTransitionError("PRIOR_SNAPSHOT_SEASON_MISMATCH")
    expected_prior_week = week - 1
    if snapshot.through_week != expected_prior_week:
        raise PowerWeeklyTransitionError("PRIOR_SNAPSHOT_THROUGH_WEEK_MISMATCH")


def _map_and_validate_week_results(
    *,
    season: int,
    week: int,
    frozen: Any,
    prior_snapshot: PowerSnapshot,
) -> tuple[tuple[FinalGameResult, ...], tuple[str, ...]]:
    prior_teams = {team.team_id for team in prior_snapshot.teams}
    mapped: list[FinalGameResult] = []
    game_ids: list[str] = []

    for accepted in frozen.accepted_results:
        result = accepted_result_to_final_game_result(accepted)
        if result.season != season:
            raise PowerWeeklyTransitionError("RESULT_SEASON_MISMATCH")
        if result.week != week:
            raise PowerWeeklyTransitionError("RESULT_WEEK_MISMATCH")
        if result.home_team not in prior_teams or result.away_team not in prior_teams:
            raise PowerWeeklyTransitionError("RESULT_UNKNOWN_TEAM")
        if result.home_team == result.away_team:
            raise PowerWeeklyTransitionError("RESULT_IDENTITY_INVALID")
        mapped.append(result)
        game_ids.append(result.game_id)

    if len(game_ids) != len(set(game_ids)):
        raise PowerWeeklyTransitionError("DUPLICATE_EVENT_IDENTITY")

    sorted_ids = tuple(sorted(game_ids))
    if len(sorted_ids) != int(frozen.expected_game_count):
        raise PowerWeeklyTransitionError("FROZEN_RESULT_SET_INCOMPLETE")
    return tuple(mapped), sorted_ids


def _persist_week_ledger(
    *,
    store: PowerEngineStore,
    lineage_id: str,
    snapshot_before: PowerSnapshot,
    snapshot_after: PowerSnapshot,
    results: tuple[FinalGameResult, ...],
    updates: tuple[Any, ...],
    generated_at: str,
) -> None:
    by_game = {result.game_id: result for result in results}
    for update in updates:
        result = by_game.get(update.game_id)
        if result is None:
            raise PowerWeeklyTransitionError("LEDGER_RESULT_ALIGNMENT_FAILED")
        ledger = build_ledger_record(
            lineage_id=lineage_id,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after,
            result=result,
            update=update,
            generated_at=generated_at,
        )
        store.persist_ledger_record(ledger)


def apply_frozen_weekly_power_transition(
    *,
    season: int,
    week: int,
    power_store: PowerEngineStore | None = None,
    result_store: ResultEngineStore | None = None,
    updater_version: str = UPDATER_VERSION,
    methodology: FrozenMethodology = FROZEN_METHODOLOGY,
    methodology_hash_value: str | None = None,
    expected_result_set_version: str | None = None,
    expected_result_set_hash: str | None = None,
    expected_prior_snapshot_id: str | None = None,
    expected_prior_snapshot_hash: str | None = None,
) -> dict[str, Any]:
    store = power_store or default_power_engine_store()
    frozen_store = result_store or default_result_engine_store()

    if week <= 0:
        raise PowerWeeklyTransitionError("WEEK_INVALID")
    if season <= 0:
        raise PowerWeeklyTransitionError("SEASON_INVALID")

    expected_mh = methodology_hash_value or _expected_methodology_hash(methodology=methodology, updater_version=updater_version)
    created_at = _utc_now_iso()

    with _transition_lock(store, season=season, week=week):
        frozen = load_frozen_week_result_set(frozen_store, season=season, week=week)
        _validate_frozen_results_inputs(season=season, week=week, frozen=frozen)

        if expected_result_set_version and expected_result_set_version != frozen.result_set_version:
            raise PowerWeeklyTransitionError("RESULT_SET_VERSION_CONFLICT")
        if expected_result_set_hash and expected_result_set_hash != frozen.result_set_hash:
            raise PowerWeeklyTransitionError("RESULT_SET_HASH_CONFLICT")

        applied, staged = _load_transition_records(store)
        season_week_applied = [
            rec
            for rec in applied.values()
            if rec.season == season and rec.week == week
        ]
        matching_result_identity = [
            rec
            for rec in season_week_applied
            if rec.result_set_version == frozen.result_set_version
            and rec.result_set_hash == frozen.result_set_hash
        ]
        if matching_result_identity:
            rec = sorted(matching_result_identity, key=lambda item: item.transition_id)[0]
            if expected_prior_snapshot_id and expected_prior_snapshot_id != rec.prior_snapshot_id:
                raise PowerWeeklyTransitionError("PRIOR_SNAPSHOT_ID_CONFLICT")
            if expected_prior_snapshot_hash and expected_prior_snapshot_hash != rec.prior_snapshot_hash:
                raise PowerWeeklyTransitionError("PRIOR_SNAPSHOT_HASH_CONFLICT")
            if expected_mh != rec.methodology_hash:
                raise PowerWeeklyTransitionError("METHODOLOGY_HASH_CONFLICT")
            if updater_version != rec.updater_version:
                raise PowerWeeklyTransitionError("UPDATER_VERSION_CONFLICT")

            replay_prior_snapshot = store.get_snapshot(rec.prior_snapshot_id)
            _validate_prior_snapshot(season=season, week=week, snapshot=replay_prior_snapshot)
            if replay_prior_snapshot.snapshot_hash != rec.prior_snapshot_hash:
                raise PowerWeeklyTransitionError("PRIOR_SNAPSHOT_HASH_CONFLICT")

            return {
                "status": "ALREADY_APPLIED",
                "transition": asdict(rec),
                "season": season,
                "week": week,
            }
        if season_week_applied:
            raise PowerWeeklyTransitionError("CONFLICTING_REPLAY")

        active_lineage = store.get_active_lineage(season)
        prior_snapshot = store.get_snapshot(active_lineage.active_snapshot_id)
        _validate_prior_snapshot(season=season, week=week, snapshot=prior_snapshot)

        if expected_prior_snapshot_id and expected_prior_snapshot_id != prior_snapshot.snapshot_id:
            raise PowerWeeklyTransitionError("PRIOR_SNAPSHOT_ID_CONFLICT")
        if expected_prior_snapshot_hash and expected_prior_snapshot_hash != prior_snapshot.snapshot_hash:
            raise PowerWeeklyTransitionError("PRIOR_SNAPSHOT_HASH_CONFLICT")

        results, sorted_game_ids = _map_and_validate_week_results(
            season=season,
            week=week,
            frozen=frozen,
            prior_snapshot=prior_snapshot,
        )

        week_update = apply_week_results(
            snapshot=prior_snapshot,
            results=results,
            generated_at=frozen.frozen_at_utc,
            updater_version=updater_version,
            methodology=methodology,
        )
        new_snapshot = week_update.snapshot_after
        if new_snapshot.through_week != week:
            raise PowerWeeklyTransitionError("NEW_SNAPSHOT_THROUGH_WEEK_MISMATCH")
        if new_snapshot.methodology_hash != expected_mh:
            raise PowerWeeklyTransitionError("METHODOLOGY_HASH_CONFLICT")
        if new_snapshot.updater_version != updater_version:
            raise PowerWeeklyTransitionError("UPDATER_VERSION_CONFLICT")

        candidate_lineage = _build_lineage_record(
            previous_active=active_lineage,
            new_snapshot=new_snapshot,
            season=season,
            week=week,
            created_at=created_at,
        )
        transition = _transition_record_from(
            season=season,
            week=week,
            prior_snapshot=prior_snapshot,
            new_snapshot=new_snapshot,
            result_set_version=frozen.result_set_version,
            result_set_hash=frozen.result_set_hash,
            methodology_hash=expected_mh,
            updater_version=updater_version,
            game_ids_sorted=sorted_game_ids,
            parent_lineage_id=active_lineage.lineage_id,
            new_lineage_id=candidate_lineage.lineage_id,
            created_at=created_at,
        )

        conflict = _existing_transition_conflict(
            records={**applied, **staged},
            season=season,
            week=week,
            parent_lineage_id=active_lineage.lineage_id,
            expected_idempotency_key=transition.idempotency_key,
        )
        if conflict is not None:
            raise PowerWeeklyTransitionError("CONFLICTING_REPLAY")

        existing_staged = staged.get(transition.transition_id)
        if existing_staged is not None and existing_staged.payload_hash != transition.payload_hash:
            raise PowerWeeklyTransitionError("CONFLICTING_REPLAY")

        store.persist_snapshot(new_snapshot)
        _persist_week_ledger(
            store=store,
            lineage_id=transition.new_lineage_id,
            snapshot_before=prior_snapshot,
            snapshot_after=new_snapshot,
            results=results,
            updates=week_update.updates,
            generated_at=frozen.frozen_at_utc,
        )

        if existing_staged is None:
            _persist_transition_staged(store, transition)

        store.create_lineage(candidate_lineage, set_active=True)
        _persist_transition_applied(store, transition)

        return {
            "status": "APPLIED",
            "transition": asdict(transition),
            "season": season,
            "week": week,
        }


def replay_frozen_weekly_power_transition_for_lineage(
    *,
    season: int,
    week: int,
    parent_lineage_id: str,
    prior_snapshot_id: str,
    root_snapshot_id: str,
    power_store: PowerEngineStore | None = None,
    result_store: ResultEngineStore | None = None,
    updater_version: str = UPDATER_VERSION,
    methodology: FrozenMethodology = FROZEN_METHODOLOGY,
    methodology_hash_value: str | None = None,
    expected_result_set_version: str | None = None,
    expected_result_set_hash: str | None = None,
    set_active: bool = False,
) -> dict[str, Any]:
    store = power_store or default_power_engine_store()
    frozen_store = result_store or default_result_engine_store()

    if week <= 0:
        raise PowerWeeklyTransitionError("WEEK_INVALID")
    if season <= 0:
        raise PowerWeeklyTransitionError("SEASON_INVALID")

    expected_mh = methodology_hash_value or _expected_methodology_hash(methodology=methodology, updater_version=updater_version)
    created_at = _utc_now_iso()

    with _transition_lock(store, season=season, week=week):
        frozen = load_frozen_week_result_set(frozen_store, season=season, week=week)
        _validate_frozen_results_inputs(season=season, week=week, frozen=frozen)

        if expected_result_set_version and expected_result_set_version != frozen.result_set_version:
            raise PowerWeeklyTransitionError("RESULT_SET_VERSION_CONFLICT")
        if expected_result_set_hash and expected_result_set_hash != frozen.result_set_hash:
            raise PowerWeeklyTransitionError("RESULT_SET_HASH_CONFLICT")

        parent_lineage = store.get_lineage(parent_lineage_id)
        if parent_lineage.season != season:
            raise PowerWeeklyTransitionError("LINEAGE_SEASON_MISMATCH")
        if parent_lineage.active_snapshot_id != prior_snapshot_id:
            raise PowerWeeklyTransitionError("LINEAGE_PRIOR_SNAPSHOT_MISMATCH")

        prior_snapshot = store.get_snapshot(prior_snapshot_id)
        if prior_snapshot.season != season:
            raise PowerWeeklyTransitionError("PRIOR_SNAPSHOT_SEASON_MISMATCH")
        _validate_prior_snapshot(season=season, week=week, snapshot=prior_snapshot)

        applied, staged = _load_transition_records(store)
        season_week_applied = [
            rec
            for rec in applied.values()
            if rec.season == season and rec.week == week and rec.parent_lineage_id == parent_lineage.lineage_id
        ]
        matching_result_identity = [
            rec
            for rec in season_week_applied
            if rec.result_set_version == frozen.result_set_version
            and rec.result_set_hash == frozen.result_set_hash
            and rec.methodology_hash == expected_mh
            and rec.updater_version == updater_version
            and rec.prior_snapshot_id == prior_snapshot.snapshot_id
            and rec.prior_snapshot_hash == prior_snapshot.snapshot_hash
        ]
        if matching_result_identity:
            rec = sorted(matching_result_identity, key=lambda item: item.transition_id)[0]
            return {
                "status": "ALREADY_APPLIED",
                "transition": asdict(rec),
                "season": season,
                "week": week,
            }

        results, sorted_game_ids = _map_and_validate_week_results(
            season=season,
            week=week,
            frozen=frozen,
            prior_snapshot=prior_snapshot,
        )

        week_update = apply_week_results(
            snapshot=prior_snapshot,
            results=results,
            generated_at=frozen.frozen_at_utc,
            updater_version=updater_version,
            methodology=methodology,
        )
        new_snapshot = week_update.snapshot_after
        if new_snapshot.through_week != week:
            raise PowerWeeklyTransitionError("NEW_SNAPSHOT_THROUGH_WEEK_MISMATCH")
        if new_snapshot.methodology_hash != expected_mh:
            raise PowerWeeklyTransitionError("METHODOLOGY_HASH_CONFLICT")
        if new_snapshot.updater_version != updater_version:
            raise PowerWeeklyTransitionError("UPDATER_VERSION_CONFLICT")

        new_lineage_id = _derive_new_lineage_id(
            season=season,
            week=week,
            new_snapshot_hash=new_snapshot.snapshot_hash,
            parent_lineage_id=parent_lineage.lineage_id,
        )

        transition = _transition_record_from(
            season=season,
            week=week,
            prior_snapshot=prior_snapshot,
            new_snapshot=new_snapshot,
            result_set_version=frozen.result_set_version,
            result_set_hash=frozen.result_set_hash,
            methodology_hash=expected_mh,
            updater_version=updater_version,
            game_ids_sorted=sorted_game_ids,
            parent_lineage_id=parent_lineage.lineage_id,
            new_lineage_id=new_lineage_id,
            created_at=created_at,
        )

        conflict = _existing_transition_conflict(
            records={**applied, **staged},
            season=season,
            week=week,
            parent_lineage_id=parent_lineage.lineage_id,
            expected_idempotency_key=transition.idempotency_key,
        )
        if conflict is not None:
            raise PowerWeeklyTransitionError("CONFLICTING_REPLAY")

        existing_staged = staged.get(transition.transition_id)
        if existing_staged is not None and existing_staged.payload_hash != transition.payload_hash:
            raise PowerWeeklyTransitionError("CONFLICTING_REPLAY")

        active_lineage_id = None
        if not set_active:
            active_lineage_id = store.get_active_lineage(season).lineage_id

        candidate_lineage = PowerLineageRecord(
            lineage_id=new_lineage_id,
            parent_lineage_id=parent_lineage.lineage_id,
            root_snapshot_id=root_snapshot_id,
            active_snapshot_id=new_snapshot.snapshot_id,
            season=season,
            through_week=week,
            status="ACTIVE" if set_active else "SUPERSEDED",
            created_at=created_at,
            superseded_at=None if set_active else created_at,
            superseded_by=None if set_active else active_lineage_id,
        )

        store.persist_snapshot(new_snapshot)
        _persist_week_ledger(
            store=store,
            lineage_id=transition.new_lineage_id,
            snapshot_before=prior_snapshot,
            snapshot_after=new_snapshot,
            results=results,
            updates=week_update.updates,
            generated_at=frozen.frozen_at_utc,
        )

        if existing_staged is None:
            _persist_transition_staged(store, transition)

        store.create_lineage(candidate_lineage, set_active=set_active)
        _persist_transition_applied(store, transition)

        return {
            "status": "APPLIED",
            "transition": asdict(transition),
            "season": season,
            "week": week,
        }


def list_power_weekly_transitions(
    *,
    power_store: PowerEngineStore | None = None,
    season: int | None = None,
    week: int | None = None,
) -> list[PowerWeeklyTransitionRecord]:
    store = power_store or default_power_engine_store()
    applied, _ = _load_transition_records(store)
    records = sorted(applied.values(), key=lambda rec: (rec.season, rec.week, rec.transition_id))
    out: list[PowerWeeklyTransitionRecord] = []
    for rec in records:
        if season is not None and rec.season != season:
            continue
        if week is not None and rec.week != week:
            continue
        out.append(rec)
    return out


def active_power_transition_observability(
    *,
    power_store: PowerEngineStore | None = None,
    season: int,
) -> dict[str, Any]:
    store = power_store or default_power_engine_store()
    active_lineage = store.get_active_lineage(season)
    active_snapshot = store.get_snapshot(active_lineage.active_snapshot_id)
    transitions = list_power_weekly_transitions(power_store=store, season=season)
    linked = next((rec for rec in reversed(transitions) if rec.new_snapshot_id == active_snapshot.snapshot_id), None)

    return {
        "season": active_snapshot.season,
        "throughWeek": active_snapshot.through_week,
        "activeSnapshotId": active_snapshot.snapshot_id,
        "activeSnapshotHash": active_snapshot.snapshot_hash,
        "priorSnapshotId": None if linked is None else linked.prior_snapshot_id,
        "sourceResultSetVersion": None if linked is None else linked.result_set_version,
        "sourceResultSetHash": None if linked is None else linked.result_set_hash,
        "methodologyHash": active_snapshot.methodology_hash,
        "updaterVersion": active_snapshot.updater_version,
        "transitionId": None if linked is None else linked.transition_id,
        "transitionStatus": None if linked is None else linked.transition_status,
        "lineageId": active_lineage.lineage_id,
    }