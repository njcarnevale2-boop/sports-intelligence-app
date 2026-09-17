from __future__ import annotations

import json
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.runtime_paths import runtime_paths

from .contracts import (
    FinalGameResult,
    PowerLineageRecord,
    PowerSnapshot,
    PowerTeamRating,
    PowerUpdateLedgerRecord,
    PowerUpdateResult,
)
from .hashing import (
    canonical_json,
    methodology_hash,
    sha256_hex,
    snapshot_hash,
    snapshot_identity_payload,
)
from .methodology import FROZEN_METHODOLOGY, UPDATER_VERSION
from .validation import (
    parse_kickoff_utc,
    validate_final_result,
    validate_snapshot,
)

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None


class PowerEnginePersistenceError(ValueError):
    pass


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_STATUS_ACTIVE = "ACTIVE"
_STATUS_SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class _ActiveLineagePointer:
    season: int
    lineage_id: str
    updated_at: str


def _validate_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PowerEnginePersistenceError(f"{field_name} must be a non-empty string")
    text = value.strip()
    if text in {".", ".."}:
        raise PowerEnginePersistenceError(f"{field_name} contains unsupported characters: {text}")
    if not _IDENTIFIER_RE.match(text):
        raise PowerEnginePersistenceError(f"{field_name} contains unsupported characters: {text}")
    return text


def _parse_iso_timestamp(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PowerEnginePersistenceError(f"{field_name} must be a non-empty string")
    text = value.strip().replace("Z", "+00:00")
    try:
        datetime.fromisoformat(text)
    except ValueError as exc:
        raise PowerEnginePersistenceError(f"Invalid {field_name}: {value}") from exc
    return value


def _read_json_file(path: Path, *, field_name: str) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PowerEnginePersistenceError(f"Failed to read {field_name}: {path}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PowerEnginePersistenceError(f"Corrupt JSON in {field_name}: {path}") from exc

    if not isinstance(payload, dict):
        raise PowerEnginePersistenceError(f"Malformed {field_name}: expected JSON object")
    return payload


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


def _snapshot_from_dict(payload: dict[str, Any]) -> PowerSnapshot:
    required = {
        "snapshot_id",
        "snapshot_hash",
        "season",
        "through_week",
        "updater_version",
        "methodology_hash",
        "source_snapshot_id",
        "generated_at",
        "teams",
    }
    missing = sorted(required - set(payload.keys()))
    if missing:
        raise PowerEnginePersistenceError(f"Malformed snapshot record missing fields: {missing}")

    teams_raw = payload.get("teams")
    if not isinstance(teams_raw, list):
        raise PowerEnginePersistenceError("Malformed snapshot record: teams must be a list")

    teams: list[PowerTeamRating] = []
    for index, item in enumerate(teams_raw):
        if not isinstance(item, dict):
            raise PowerEnginePersistenceError(f"Malformed snapshot team at index {index}: expected object")
        if "team_id" not in item or "power" not in item:
            raise PowerEnginePersistenceError(f"Malformed snapshot team at index {index}: missing team_id/power")
        teams.append(PowerTeamRating(team_id=item["team_id"], power=item["power"]))

    snapshot = PowerSnapshot(
        snapshot_id=payload["snapshot_id"],
        snapshot_hash=payload["snapshot_hash"],
        season=payload["season"],
        through_week=payload["through_week"],
        updater_version=payload["updater_version"],
        methodology_hash=payload["methodology_hash"],
        source_snapshot_id=payload["source_snapshot_id"],
        generated_at=payload["generated_at"],
        teams=tuple(teams),
    )
    try:
        _validate_identifier(snapshot.snapshot_id, "snapshot_id")
        _validate_identifier(snapshot.updater_version, "updater_version")
        _validate_identifier(snapshot.methodology_hash, "methodology_hash")
        _parse_iso_timestamp(snapshot.generated_at, "generated_at")
        validate_snapshot(snapshot)
        expected_hash = snapshot_hash(snapshot)
    except ValueError as exc:
        raise PowerEnginePersistenceError(str(exc)) from exc
    if snapshot.snapshot_hash != expected_hash:
        raise PowerEnginePersistenceError(
            f"Snapshot hash mismatch: provided={snapshot.snapshot_hash} expected={expected_hash}"
        )
    return snapshot


def _snapshot_canonical_file_payload(snapshot: PowerSnapshot) -> dict[str, Any]:
    # Keep generated_at in persisted record while preserving snapshot_hash identity semantics.
    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_hash": snapshot.snapshot_hash,
        "season": snapshot.season,
        "through_week": snapshot.through_week,
        "updater_version": snapshot.updater_version,
        "methodology_hash": snapshot.methodology_hash,
        "source_snapshot_id": snapshot.source_snapshot_id,
        "generated_at": snapshot.generated_at,
        "teams": [asdict(team) for team in snapshot.teams],
    }


def _ledger_payload_for_hash(record: PowerUpdateLedgerRecord) -> dict[str, Any]:
    return {
        "lineage_id": record.lineage_id,
        "snapshot_id_before": record.snapshot_id_before,
        "snapshot_id_after": record.snapshot_id_after,
        "season": record.season,
        "week": record.week,
        "game_id": record.game_id,
        "kickoff_utc": record.kickoff_utc,
        "home_team": record.home_team,
        "away_team": record.away_team,
        "home_score": record.home_score,
        "away_score": record.away_score,
        "actual_home_margin": record.actual_home_margin,
        "home_power_before": record.home_power_before,
        "away_power_before": record.away_power_before,
        "expected_home_margin": record.expected_home_margin,
        "raw_error": record.raw_error,
        "clipped_error": record.clipped_error,
        "k": record.k,
        "cap": record.cap,
        "game_shrink": record.game_shrink,
        "hfa": record.hfa,
        "home_adjustment": record.home_adjustment,
        "away_adjustment": record.away_adjustment,
        "home_power_after": record.home_power_after,
        "away_power_after": record.away_power_after,
        "updater_version": record.updater_version,
        "methodology_hash": record.methodology_hash,
        "source_result_version": record.source_result_version,
        "idempotency_key": record.idempotency_key,
    }


def _ledger_idempotency_payload(record: PowerUpdateLedgerRecord) -> dict[str, Any]:
    return {
        "lineage_id": record.lineage_id,
        "snapshot_id_before": record.snapshot_id_before,
        "season": record.season,
        "week": record.week,
        "game_id": record.game_id,
        "home_score": record.home_score,
        "away_score": record.away_score,
        "source_result_version": record.source_result_version,
        "updater_version": record.updater_version,
        "methodology_hash": record.methodology_hash,
    }


def build_ledger_idempotency_key(record: PowerUpdateLedgerRecord) -> str:
    return sha256_hex(canonical_json(_ledger_idempotency_payload(record)))


def _deterministic_update_id(idempotency_key: str) -> str:
    return f"upd-{sha256_hex(idempotency_key)[:16]}"


def build_ledger_payload_hash(record: PowerUpdateLedgerRecord) -> str:
    return sha256_hex(canonical_json(_ledger_payload_for_hash(record)))


def build_ledger_record(
    *,
    lineage_id: str,
    snapshot_before: PowerSnapshot,
    snapshot_after: PowerSnapshot,
    result: FinalGameResult,
    update: PowerUpdateResult,
    generated_at: str,
) -> PowerUpdateLedgerRecord:
    try:
        validate_snapshot(snapshot_before)
        validate_snapshot(snapshot_after)
        validate_final_result(result)
    except ValueError as exc:
        raise PowerEnginePersistenceError(str(exc)) from exc

    if update.game_id != result.game_id:
        raise PowerEnginePersistenceError("update.game_id must match result.game_id")

    base = PowerUpdateLedgerRecord(
        update_id="",
        lineage_id=_validate_identifier(lineage_id, "lineage_id"),
        snapshot_id_before=_validate_identifier(snapshot_before.snapshot_id, "snapshot_id_before"),
        snapshot_id_after=_validate_identifier(snapshot_after.snapshot_id, "snapshot_id_after"),
        season=result.season,
        week=result.week,
        game_id=update.game_id,
        kickoff_utc=result.kickoff_utc,
        home_team=update.home_team,
        away_team=update.away_team,
        home_score=update.home_score,
        away_score=update.away_score,
        actual_home_margin=update.actual_home_margin,
        home_power_before=update.home_power_before,
        away_power_before=update.away_power_before,
        expected_home_margin=update.expected_home_margin,
        raw_error=update.raw_error,
        clipped_error=update.clipped_error,
        k=update.k,
        cap=update.cap,
        game_shrink=update.game_shrink,
        hfa=update.hfa,
        home_adjustment=update.home_adjustment,
        away_adjustment=update.away_adjustment,
        home_power_after=update.home_power_after,
        away_power_after=update.away_power_after,
        updater_version=update.updater_version,
        methodology_hash=update.methodology_hash,
        source_result_version=result.source_result_version,
        generated_at=generated_at,
        idempotency_key="",
        payload_hash="",
    )

    idempotency_key = build_ledger_idempotency_key(base)
    update_id = _deterministic_update_id(idempotency_key)
    with_identity = PowerUpdateLedgerRecord(
        **{**asdict(base), "update_id": update_id, "idempotency_key": idempotency_key, "payload_hash": ""}
    )
    payload_hash = build_ledger_payload_hash(with_identity)

    return replace(with_identity, payload_hash=payload_hash)


def _validate_ledger_record(record: PowerUpdateLedgerRecord) -> None:
    _validate_identifier(record.update_id, "update_id")
    _validate_identifier(record.lineage_id, "lineage_id")
    _validate_identifier(record.snapshot_id_before, "snapshot_id_before")
    _validate_identifier(record.snapshot_id_after, "snapshot_id_after")
    _validate_identifier(record.game_id, "game_id")
    _validate_identifier(record.updater_version, "updater_version")
    _validate_identifier(record.methodology_hash, "methodology_hash")
    _validate_identifier(record.idempotency_key, "idempotency_key")
    _validate_identifier(record.payload_hash, "payload_hash")
    _parse_iso_timestamp(record.generated_at, "generated_at")

    # Reuse strict result validation for teams/scores/timestamp.
    try:
        validate_final_result(
            FinalGameResult(
                season=record.season,
                week=record.week,
                game_id=record.game_id,
                kickoff_utc=record.kickoff_utc,
                home_team=record.home_team,
                away_team=record.away_team,
                home_score=record.home_score,
                away_score=record.away_score,
                source_result_version=record.source_result_version,
            )
        )
    except ValueError as exc:
        raise PowerEnginePersistenceError(str(exc)) from exc

    expected_idempotency = build_ledger_idempotency_key(record)
    if record.idempotency_key != expected_idempotency:
        raise PowerEnginePersistenceError(
            f"Ledger idempotency mismatch: provided={record.idempotency_key} expected={expected_idempotency}"
        )

    expected_update_id = _deterministic_update_id(record.idempotency_key)
    if record.update_id != expected_update_id:
        raise PowerEnginePersistenceError(
            f"Ledger update_id mismatch: provided={record.update_id} expected={expected_update_id}"
        )

    expected_payload_hash = build_ledger_payload_hash(record)
    if record.payload_hash != expected_payload_hash:
        raise PowerEnginePersistenceError(
            f"Ledger payload hash mismatch: provided={record.payload_hash} expected={expected_payload_hash}"
        )


def _ledger_from_dict(payload: dict[str, Any]) -> PowerUpdateLedgerRecord:
    required = set(asdict(PowerUpdateLedgerRecord(
        update_id="",
        lineage_id="",
        snapshot_id_before="",
        snapshot_id_after="",
        season=0,
        week=0,
        game_id="",
        kickoff_utc="",
        home_team="",
        away_team="",
        home_score=0,
        away_score=0,
        actual_home_margin=0.0,
        home_power_before=0.0,
        away_power_before=0.0,
        expected_home_margin=0.0,
        raw_error=0.0,
        clipped_error=0.0,
        k=0.0,
        cap=0.0,
        game_shrink=0.0,
        hfa=0.0,
        home_adjustment=0.0,
        away_adjustment=0.0,
        home_power_after=0.0,
        away_power_after=0.0,
        updater_version="",
        methodology_hash="",
        source_result_version="",
        generated_at="",
        idempotency_key="",
        payload_hash="",
    )).keys())
    missing = sorted(required - set(payload.keys()))
    if missing:
        raise PowerEnginePersistenceError(f"Malformed ledger record missing fields: {missing}")

    record = PowerUpdateLedgerRecord(**payload)
    _validate_ledger_record(record)
    return record


def _lineage_from_dict(payload: dict[str, Any]) -> PowerLineageRecord:
    required = {
        "lineage_id",
        "parent_lineage_id",
        "root_snapshot_id",
        "active_snapshot_id",
        "season",
        "through_week",
        "status",
        "created_at",
        "superseded_at",
        "superseded_by",
    }
    missing = sorted(required - set(payload.keys()))
    if missing:
        raise PowerEnginePersistenceError(f"Malformed lineage record missing fields: {missing}")

    record = PowerLineageRecord(**payload)
    _validate_lineage_record(record)
    return record


def _active_pointer_from_dict(payload: dict[str, Any]) -> _ActiveLineagePointer:
    required = {"season", "lineage_id", "updated_at"}
    missing = sorted(required - set(payload.keys()))
    if missing:
        raise PowerEnginePersistenceError(f"Malformed active lineage pointer missing fields: {missing}")

    season = payload["season"]
    if isinstance(season, bool) or not isinstance(season, int) or season <= 0:
        raise PowerEnginePersistenceError("season must be a positive integer")

    lineage_id = _validate_identifier(payload["lineage_id"], "lineage_id")
    updated_at = _parse_iso_timestamp(payload["updated_at"], "updated_at")
    return _ActiveLineagePointer(season=season, lineage_id=lineage_id, updated_at=updated_at)


def _validate_lineage_record(record: PowerLineageRecord) -> None:
    _validate_identifier(record.lineage_id, "lineage_id")
    if record.parent_lineage_id is not None:
        _validate_identifier(record.parent_lineage_id, "parent_lineage_id")
    _validate_identifier(record.root_snapshot_id, "root_snapshot_id")
    _validate_identifier(record.active_snapshot_id, "active_snapshot_id")
    if isinstance(record.season, bool) or not isinstance(record.season, int) or record.season <= 0:
        raise PowerEnginePersistenceError("season must be a positive integer")
    if isinstance(record.through_week, bool) or not isinstance(record.through_week, int) or record.through_week < 0:
        raise PowerEnginePersistenceError("through_week must be a non-negative integer")
    if record.status not in {_STATUS_ACTIVE, _STATUS_SUPERSEDED}:
        raise PowerEnginePersistenceError(f"Invalid lineage status: {record.status}")
    _parse_iso_timestamp(record.created_at, "created_at")
    if record.status == _STATUS_ACTIVE:
        if record.superseded_at is not None or record.superseded_by is not None:
            raise PowerEnginePersistenceError("ACTIVE lineage cannot include supersession metadata")
        return

    if record.superseded_at is None or record.superseded_by is None:
        raise PowerEnginePersistenceError("SUPERSEDED lineage must include superseded_at and superseded_by")
    _parse_iso_timestamp(record.superseded_at, "superseded_at")
    _validate_identifier(record.superseded_by, "superseded_by")
    if record.superseded_by == record.lineage_id:
        raise PowerEnginePersistenceError("Lineage cannot supersede itself")


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


class PowerEngineStore:
    def __init__(
        self,
        *,
        root_dir: Path | None = None,
        snapshots_dir: Path | None = None,
        ledger_dir: Path | None = None,
        meta_dir: Path | None = None,
    ) -> None:
        root = Path(root_dir).resolve() if root_dir is not None else runtime_paths.power_engine_root.resolve()
        self._root_dir = root
        self._snapshots_dir = Path(snapshots_dir).resolve() if snapshots_dir is not None else root / "snapshots"
        self._ledger_dir = Path(ledger_dir).resolve() if ledger_dir is not None else root / "ledger"
        self._meta_dir = Path(meta_dir).resolve() if meta_dir is not None else root / "meta"

        self._lineages_dir = self._meta_dir / "lineages"
        self._active_lineage_dir = self._meta_dir / "active"
        self._snapshot_hash_index = self._meta_dir / "snapshot_hash_index.json"
        self._ledger_idempotency_index = self._meta_dir / "ledger_idempotency_index.json"
        self._lock_file = self._meta_dir / "power_engine.lock"

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def _ensure_dirs(self) -> None:
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)
        self._ledger_dir.mkdir(parents=True, exist_ok=True)
        self._lineages_dir.mkdir(parents=True, exist_ok=True)
        self._active_lineage_dir.mkdir(parents=True, exist_ok=True)

    def _snapshot_path(self, snapshot_id: str) -> Path:
        return self._snapshots_dir / f"{_validate_identifier(snapshot_id, 'snapshot_id')}.json"

    def _ledger_path(self, update_id: str) -> Path:
        return self._ledger_dir / f"{_validate_identifier(update_id, 'update_id')}.json"

    def _lineage_path(self, lineage_id: str) -> Path:
        return self._lineages_dir / f"{_validate_identifier(lineage_id, 'lineage_id')}.json"

    def _active_lineage_pointer_path(self, season: int) -> Path:
        if isinstance(season, bool) or not isinstance(season, int) or season <= 0:
            raise PowerEnginePersistenceError("season must be a positive integer")
        return self._active_lineage_dir / f"season-{season}.json"

    def _load_cached_index_or_none(self, path: Path) -> dict[str, str] | None:
        if not path.exists():
            return None

        try:
            payload = _read_json_file(path, field_name=str(path.name))
        except PowerEnginePersistenceError:
            return None

        out: dict[str, str] = {}
        for key, value in payload.items():
            if not isinstance(key, str) or not isinstance(value, str):
                return None
            out[key] = value
        return out

    def _collect_snapshots_locked(self) -> tuple[list[PowerSnapshot], dict[str, str], dict[str, PowerSnapshot]]:
        snapshots: list[PowerSnapshot] = []
        snapshots_by_id: dict[str, PowerSnapshot] = {}
        hash_to_id: dict[str, str] = {}

        if self._snapshots_dir.exists():
            for path in sorted(self._snapshots_dir.glob("*.json")):
                snapshot = _snapshot_from_dict(_read_json_file(path, field_name="snapshot"))
                expected_name = f"{snapshot.snapshot_id}.json"
                if path.name != expected_name:
                    raise PowerEnginePersistenceError(
                        f"Snapshot filename mismatch: path={path.name} snapshot_id={snapshot.snapshot_id}"
                    )
                if snapshot.snapshot_id in snapshots_by_id:
                    raise PowerEnginePersistenceError(f"Duplicate snapshot_id authority: {snapshot.snapshot_id}")
                other_id = hash_to_id.get(snapshot.snapshot_hash)
                if other_id is not None and other_id != snapshot.snapshot_id:
                    raise PowerEnginePersistenceError(
                        f"Duplicate snapshot authority for hash={snapshot.snapshot_hash}: ids={[other_id, snapshot.snapshot_id]}"
                    )
                snapshots.append(snapshot)
                snapshots_by_id[snapshot.snapshot_id] = snapshot
                hash_to_id[snapshot.snapshot_hash] = snapshot.snapshot_id

        cached = self._load_cached_index_or_none(self._snapshot_hash_index)
        if cached != hash_to_id:
            self._write_index(self._snapshot_hash_index, hash_to_id)

        return snapshots, hash_to_id, snapshots_by_id

    def _collect_ledger_locked(
        self,
    ) -> tuple[list[PowerUpdateLedgerRecord], dict[str, str], dict[str, PowerUpdateLedgerRecord]]:
        records: list[PowerUpdateLedgerRecord] = []
        records_by_id: dict[str, PowerUpdateLedgerRecord] = {}
        idem_to_id: dict[str, str] = {}

        if self._ledger_dir.exists():
            for path in sorted(self._ledger_dir.glob("*.json")):
                record = _ledger_from_dict(_read_json_file(path, field_name="ledger"))
                expected_name = f"{record.update_id}.json"
                if path.name != expected_name:
                    raise PowerEnginePersistenceError(
                        f"Ledger filename mismatch: path={path.name} update_id={record.update_id}"
                    )
                if record.update_id in records_by_id:
                    raise PowerEnginePersistenceError(f"Duplicate update_id authority: {record.update_id}")
                other_id = idem_to_id.get(record.idempotency_key)
                if other_id is not None and other_id != record.update_id:
                    raise PowerEnginePersistenceError(
                        f"Duplicate ledger authority for idempotency_key={record.idempotency_key}: update_ids={[other_id, record.update_id]}"
                    )
                records.append(record)
                records_by_id[record.update_id] = record
                idem_to_id[record.idempotency_key] = record.update_id

        cached = self._load_cached_index_or_none(self._ledger_idempotency_index)
        if cached != idem_to_id:
            self._write_index(self._ledger_idempotency_index, idem_to_id)

        return records, idem_to_id, records_by_id

    def _load_raw_lineages_locked(self) -> dict[str, PowerLineageRecord]:
        records: dict[str, PowerLineageRecord] = {}
        if not self._lineages_dir.exists():
            return records

        for path in sorted(self._lineages_dir.glob("*.json")):
            record = _lineage_from_dict(_read_json_file(path, field_name="lineage"))
            expected_name = f"{record.lineage_id}.json"
            if path.name != expected_name:
                raise PowerEnginePersistenceError(
                    f"Lineage filename mismatch: path={path.name} lineage_id={record.lineage_id}"
                )
            if record.lineage_id in records:
                raise PowerEnginePersistenceError(f"Duplicate lineage_id authority: {record.lineage_id}")
            records[record.lineage_id] = record

        for record in records.values():
            if record.superseded_by is None:
                continue
            successor = records.get(record.superseded_by)
            if successor is None:
                raise PowerEnginePersistenceError(
                    f"Lineage superseded_by references missing lineage: {record.superseded_by}"
                )
            if successor.season != record.season:
                raise PowerEnginePersistenceError(
                    f"Lineage superseded_by season mismatch: lineage={record.lineage_id} superseded_by={record.superseded_by}"
                )

        return records

    def _load_active_pointers_locked(self) -> dict[int, _ActiveLineagePointer]:
        pointers: dict[int, _ActiveLineagePointer] = {}
        if not self._active_lineage_dir.exists():
            return pointers

        for path in sorted(self._active_lineage_dir.glob("season-*.json")):
            pointer = _active_pointer_from_dict(_read_json_file(path, field_name="active lineage pointer"))
            expected_name = f"season-{pointer.season}.json"
            if path.name != expected_name:
                raise PowerEnginePersistenceError(
                    f"Active lineage pointer filename mismatch: path={path.name} season={pointer.season}"
                )
            if pointer.season in pointers:
                raise PowerEnginePersistenceError(f"Duplicate active lineage pointer authority for season {pointer.season}")
            pointers[pointer.season] = pointer

        return pointers

    def _collect_lineage_views_locked(
        self,
    ) -> tuple[list[PowerLineageRecord], dict[str, PowerLineageRecord], dict[int, _ActiveLineagePointer]]:
        records = self._load_raw_lineages_locked()
        pointers = self._load_active_pointers_locked()

        by_season: dict[int, list[PowerLineageRecord]] = {}
        for record in records.values():
            by_season.setdefault(record.season, []).append(record)

        for season, pointer in pointers.items():
            target = records.get(pointer.lineage_id)
            if target is None:
                raise PowerEnginePersistenceError(
                    f"Active lineage pointer references missing lineage: season={season} lineage_id={pointer.lineage_id}"
                )
            if target.season != season:
                raise PowerEnginePersistenceError(
                    f"Active lineage season mismatch for season {season}: lineage_id={pointer.lineage_id}"
                )

        normalized: dict[str, PowerLineageRecord] = {}
        for season, season_records in by_season.items():
            pointer = pointers.get(season)
            if pointer is None:
                active_ids = [record.lineage_id for record in season_records if record.status == _STATUS_ACTIVE]
                if len(active_ids) > 1:
                    raise PowerEnginePersistenceError(
                        f"Multiple ACTIVE lineage artifacts for season {season}: {sorted(active_ids)}"
                    )
                for record in season_records:
                    normalized[record.lineage_id] = record
                continue

            for record in season_records:
                if record.lineage_id == pointer.lineage_id:
                    normalized_record = replace(
                        record,
                        status=_STATUS_ACTIVE,
                        superseded_at=None,
                        superseded_by=None,
                    )
                else:
                    normalized_record = replace(
                        record,
                        status=_STATUS_SUPERSEDED,
                        superseded_at=record.superseded_at or pointer.updated_at,
                        superseded_by=record.superseded_by or pointer.lineage_id,
                    )
                _validate_lineage_record(normalized_record)
                normalized[record.lineage_id] = normalized_record

        return sorted(normalized.values(), key=lambda record: (record.season, record.lineage_id)), normalized, pointers

    def _active_lineage_ids_for_season_unlocked(self, season: int) -> list[str]:
        _, normalized, _ = self._collect_lineage_views_locked()
        return [
            record.lineage_id
            for record in normalized.values()
            if record.season == season and record.status == _STATUS_ACTIVE
        ]

    def _validate_or_rebuild_indexes_locked(self) -> tuple[dict[str, str], dict[str, str]]:
        self._ensure_dirs()
        _, snapshot_index, _ = self._collect_snapshots_locked()
        _, ledger_index, _ = self._collect_ledger_locked()
        return snapshot_index, ledger_index

    def _write_index(self, path: Path, payload: dict[str, Any]) -> None:
        _atomic_write_text(path, canonical_json(payload))

    def persist_snapshot(self, snapshot: PowerSnapshot) -> PowerSnapshot:
        try:
            validate_snapshot(snapshot)
        except ValueError as exc:
            raise PowerEnginePersistenceError(str(exc)) from exc
        _validate_identifier(snapshot.snapshot_id, "snapshot_id")
        _validate_identifier(snapshot.updater_version, "updater_version")
        _validate_identifier(snapshot.methodology_hash, "methodology_hash")
        _parse_iso_timestamp(snapshot.generated_at, "generated_at")

        expected_hash = snapshot_hash(snapshot)
        if snapshot.snapshot_hash != expected_hash:
            raise PowerEnginePersistenceError(
                f"Snapshot hash mismatch: provided={snapshot.snapshot_hash} expected={expected_hash}"
            )

        payload = _snapshot_canonical_file_payload(snapshot)
        canonical_text = canonical_json(payload)
        identity_text = canonical_json(snapshot_identity_payload(snapshot))
        path = self._snapshot_path(snapshot.snapshot_id)

        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            _, hash_index, snapshots_by_id = self._collect_snapshots_locked()

            existing = snapshots_by_id.get(snapshot.snapshot_id)
            if existing is not None:
                existing_text = canonical_json(_snapshot_canonical_file_payload(existing))
                if existing_text != canonical_text:
                    raise PowerEnginePersistenceError(
                        f"snapshot_id collision with different content: {snapshot.snapshot_id}"
                    )
                return existing

            existing_by_hash = hash_index.get(snapshot.snapshot_hash)
            if existing_by_hash:
                existing = snapshots_by_id[str(existing_by_hash)]
                if canonical_json(snapshot_identity_payload(existing)) != identity_text:
                    raise PowerEnginePersistenceError(
                        f"snapshot_hash collision with different content: {snapshot.snapshot_hash}"
                    )
                raise PowerEnginePersistenceError(
                    f"Duplicate snapshot authority is not allowed for hash={snapshot.snapshot_hash}: existing_snapshot_id={existing.snapshot_id} requested_snapshot_id={snapshot.snapshot_id}"
                )

            _atomic_write_text(path, canonical_text)
            hash_index[snapshot.snapshot_hash] = snapshot.snapshot_id
            self._write_index(self._snapshot_hash_index, hash_index)
            return snapshot

    def get_snapshot(self, snapshot_id: str) -> PowerSnapshot:
        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            _, _, snapshots_by_id = self._collect_snapshots_locked()
            snapshot = snapshots_by_id.get(_validate_identifier(snapshot_id, "snapshot_id"))
            if snapshot is None:
                raise PowerEnginePersistenceError(f"Snapshot not found: {snapshot_id}")
            return snapshot

    def list_snapshots(self, season: int | None = None) -> list[PowerSnapshot]:
        if season is not None and (isinstance(season, bool) or not isinstance(season, int) or season <= 0):
            raise PowerEnginePersistenceError("season must be a positive integer")

        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            snapshots, _, _ = self._collect_snapshots_locked()
            if season is None:
                return snapshots
            return [snapshot for snapshot in snapshots if snapshot.season == season]

    def persist_ledger_record(self, record: PowerUpdateLedgerRecord) -> PowerUpdateLedgerRecord:
        _validate_ledger_record(record)
        _parse_iso_timestamp(record.generated_at, "generated_at")
        payload = asdict(record)
        canonical_text = canonical_json(payload)
        path = self._ledger_path(record.update_id)

        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            _, idem_index, records_by_id = self._collect_ledger_locked()

            existing = records_by_id.get(record.update_id)
            if existing is not None:
                if canonical_json(asdict(existing)) != canonical_text:
                    raise PowerEnginePersistenceError(
                        f"update_id collision with different payload: {record.update_id}"
                    )
                return existing

            existing_update_id = idem_index.get(record.idempotency_key)
            if existing_update_id:
                existing = records_by_id[str(existing_update_id)]
                if existing.payload_hash != record.payload_hash:
                    raise PowerEnginePersistenceError(
                        f"idempotency key collision with different payload: {record.idempotency_key}"
                    )
                raise PowerEnginePersistenceError(
                    f"Duplicate ledger authority is not allowed for idempotency_key={record.idempotency_key}: existing_update_id={existing.update_id} requested_update_id={record.update_id}"
                )

            _atomic_write_text(path, canonical_text)
            idem_index[record.idempotency_key] = record.update_id
            self._write_index(self._ledger_idempotency_index, idem_index)
            return record

    def get_ledger_record(self, update_id: str) -> PowerUpdateLedgerRecord:
        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            _, _, records_by_id = self._collect_ledger_locked()
            record = records_by_id.get(_validate_identifier(update_id, "update_id"))
            if record is None:
                raise PowerEnginePersistenceError(f"Ledger record not found: {update_id}")
            return record

    def list_ledger(
        self,
        *,
        season: int | None = None,
        week: int | None = None,
        lineage_id: str | None = None,
    ) -> list[PowerUpdateLedgerRecord]:
        if season is not None and (isinstance(season, bool) or not isinstance(season, int) or season <= 0):
            raise PowerEnginePersistenceError("season must be a positive integer")
        if week is not None and (isinstance(week, bool) or not isinstance(week, int) or week <= 0):
            raise PowerEnginePersistenceError("week must be a positive integer")
        if lineage_id is not None:
            _validate_identifier(lineage_id, "lineage_id")

        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            records, _, _ = self._collect_ledger_locked()
            out: list[PowerUpdateLedgerRecord] = []
            for record in records:
                if season is not None and record.season != season:
                    continue
                if week is not None and record.week != week:
                    continue
                if lineage_id is not None and record.lineage_id != lineage_id:
                    continue
                out.append(record)
            return out

    def create_lineage(self, lineage: PowerLineageRecord, *, set_active: bool = False) -> PowerLineageRecord:
        _validate_lineage_record(lineage)
        path = self._lineage_path(lineage.lineage_id)
        canonical_text = canonical_json(asdict(lineage))

        with _file_lock(self._lock_file):
            self._ensure_dirs()

            active_ids = self._active_lineage_ids_for_season_unlocked(lineage.season)
            other_active_ids = [candidate for candidate in active_ids if candidate != lineage.lineage_id]
            if lineage.status == _STATUS_ACTIVE and other_active_ids and not set_active:
                raise PowerEnginePersistenceError(
                    f"Only one ACTIVE lineage is allowed per season {lineage.season}; existing={other_active_ids}"
                )

            if path.exists():
                existing = _lineage_from_dict(_read_json_file(path, field_name="lineage"))
                if canonical_json(asdict(existing)) != canonical_text:
                    raise PowerEnginePersistenceError(
                        f"lineage_id collision with different content: {lineage.lineage_id}"
                    )
                created = existing
            else:
                _atomic_write_text(path, canonical_text)
                created = lineage

            if set_active:
                self._set_active_lineage_locked(lineage_id=created.lineage_id, season=created.season)

            return created

    def _set_active_lineage_locked(self, *, lineage_id: str, season: int) -> None:
        raw_records = self._load_raw_lineages_locked()
        lineage = raw_records.get(_validate_identifier(lineage_id, "lineage_id"))
        if lineage is None:
            raise PowerEnginePersistenceError(f"Lineage not found: {lineage_id}")
        if lineage.season != season:
            raise PowerEnginePersistenceError("Lineage season does not match requested active season")

        pointer_path = self._active_lineage_pointer_path(season)
        previous_id = None
        if pointer_path.exists():
            pointer = _active_pointer_from_dict(_read_json_file(pointer_path, field_name="active lineage pointer"))
            previous_id = pointer.lineage_id
            if previous_id == lineage_id:
                return

        pointer_payload = {
            "season": season,
            "lineage_id": lineage_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_write_text(pointer_path, canonical_json(pointer_payload))

        if previous_id:
            old = raw_records.get(str(previous_id))
            if old is not None and old.lineage_id != lineage_id:
                superseded = PowerLineageRecord(
                    lineage_id=old.lineage_id,
                    parent_lineage_id=old.parent_lineage_id,
                    root_snapshot_id=old.root_snapshot_id,
                    active_snapshot_id=old.active_snapshot_id,
                    season=old.season,
                    through_week=old.through_week,
                    status=_STATUS_SUPERSEDED,
                    created_at=old.created_at,
                    superseded_at=pointer_payload["updated_at"],
                    superseded_by=lineage_id,
                )
                _atomic_write_text(self._lineage_path(old.lineage_id), canonical_json(asdict(superseded)))

    def set_active_lineage(self, *, lineage_id: str, season: int) -> None:
        with _file_lock(self._lock_file):
            self._ensure_dirs()
            self._set_active_lineage_locked(lineage_id=lineage_id, season=season)

    def get_active_lineage(self, season: int) -> PowerLineageRecord:
        with _file_lock(self._lock_file):
            _, normalized, pointers = self._collect_lineage_views_locked()
            pointer = pointers.get(season)
            if pointer is None:
                raise PowerEnginePersistenceError(f"No active lineage for season {season}")
            lineage = normalized.get(pointer.lineage_id)
            if lineage is None:
                raise PowerEnginePersistenceError(
                    f"Active lineage pointer references missing lineage: season={season} lineage_id={pointer.lineage_id}"
                )
            if lineage.season != season:
                raise PowerEnginePersistenceError(f"Active lineage season mismatch for season {season}")
            if lineage.status != _STATUS_ACTIVE:
                raise PowerEnginePersistenceError(f"Active lineage pointer references non-ACTIVE lineage: {pointer.lineage_id}")
            return lineage

    def get_lineage(self, lineage_id: str) -> PowerLineageRecord:
        with _file_lock(self._lock_file):
            _, normalized, _ = self._collect_lineage_views_locked()
            record = normalized.get(_validate_identifier(lineage_id, "lineage_id"))
            if record is None:
                raise PowerEnginePersistenceError(f"Lineage not found: {lineage_id}")
            return record

    def list_lineages(self, season: int | None = None) -> list[PowerLineageRecord]:
        if season is not None and (isinstance(season, bool) or not isinstance(season, int) or season <= 0):
            raise PowerEnginePersistenceError("season must be a positive integer")

        with _file_lock(self._lock_file):
            records, _, _ = self._collect_lineage_views_locked()
            if season is None:
                return records
            return [record for record in records if record.season == season]


def default_power_engine_store() -> PowerEngineStore:
    return PowerEngineStore()


def expected_methodology_hash() -> str:
    return methodology_hash(FROZEN_METHODOLOGY, UPDATER_VERSION)
