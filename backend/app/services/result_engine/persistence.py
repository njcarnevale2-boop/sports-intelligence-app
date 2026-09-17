from __future__ import annotations

import json
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.runtime_paths import runtime_paths

from .contracts import (
    AcceptedFinalGameResult,
    RawResultObservation,
    ResultCorrectionCandidate,
    SourceEventBridgeRecord,
)
from .hashing import canonical_json
from .validation import (
    ResultEngineValidationError,
    validate_accepted_result,
    validate_raw_observation,
    validate_source_event_bridge,
)
from .status import normalize_result_status

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None


class ResultEnginePersistenceError(ValueError):
    pass


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


def _validate_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResultEnginePersistenceError(f"{field_name} must be a non-empty string")
    text = value.strip()
    if text in {".", ".."}:
        raise ResultEnginePersistenceError(f"{field_name} contains unsupported characters: {text}")
    if not _IDENTIFIER_RE.match(text):
        raise ResultEnginePersistenceError(f"{field_name} contains unsupported characters: {text}")
    return text


def _parse_iso_timestamp(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResultEnginePersistenceError(f"{field_name} must be a non-empty string")
    text = value.strip().replace("Z", "+00:00")
    try:
        datetime.fromisoformat(text)
    except ValueError as exc:
        raise ResultEnginePersistenceError(f"Invalid {field_name}: {value}") from exc
    return value


def _read_json_file(path: Path, *, field_name: str) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ResultEnginePersistenceError(f"Failed to read {field_name}: {path}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ResultEnginePersistenceError(f"Corrupt JSON in {field_name}: {path}") from exc

    if not isinstance(payload, dict):
        raise ResultEnginePersistenceError(f"Malformed {field_name}: expected JSON object")
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


def _observation_from_dict(payload: dict[str, Any]) -> RawResultObservation:
    materialized = dict(payload)
    materialized["status"] = normalize_result_status(materialized.get("status"))
    try:
        observation = RawResultObservation(**materialized)
    except TypeError as exc:
        raise ResultEnginePersistenceError(f"Malformed observation record: {exc}") from exc
    try:
        return validate_raw_observation(observation)
    except ResultEngineValidationError as exc:
        raise ResultEnginePersistenceError(str(exc)) from exc


def _accepted_from_dict(payload: dict[str, Any]) -> AcceptedFinalGameResult:
    materialized = dict(payload)
    materialized["accepted_status"] = normalize_result_status(materialized.get("accepted_status"))
    if isinstance(materialized.get("observation_ids"), list):
        materialized["observation_ids"] = tuple(materialized["observation_ids"])
    try:
        accepted = AcceptedFinalGameResult(**materialized)
    except TypeError as exc:
        raise ResultEnginePersistenceError(f"Malformed accepted result record: {exc}") from exc
    try:
        return validate_accepted_result(accepted)
    except ResultEngineValidationError as exc:
        raise ResultEnginePersistenceError(str(exc)) from exc


def _bridge_from_dict(payload: dict[str, Any]) -> SourceEventBridgeRecord:
    try:
        bridge = SourceEventBridgeRecord(**payload)
    except TypeError as exc:
        raise ResultEnginePersistenceError(f"Malformed identity bridge record: {exc}") from exc
    try:
        return validate_source_event_bridge(bridge)
    except ResultEngineValidationError as exc:
        raise ResultEnginePersistenceError(str(exc)) from exc


def _correction_candidate_from_dict(payload: dict[str, Any]) -> ResultCorrectionCandidate:
    required = {
        "candidate_id",
        "canonical_event_key",
        "existing_result_id",
        "conflicting_observation_id",
        "source",
        "source_event_id",
        "conflicting_away_score",
        "conflicting_home_score",
        "detected_at_utc",
        "reason_code",
    }
    missing = sorted(required - set(payload.keys()))
    if missing:
        raise ResultEnginePersistenceError(f"Malformed correction candidate missing fields: {missing}")

    candidate = ResultCorrectionCandidate(**payload)
    _validate_identifier(candidate.candidate_id, "candidate_id")
    _validate_identifier(candidate.canonical_event_key, "canonical_event_key")
    _validate_identifier(candidate.existing_result_id, "existing_result_id")
    _validate_identifier(candidate.conflicting_observation_id, "conflicting_observation_id")
    _validate_identifier(candidate.source, "source")
    _validate_identifier(candidate.source_event_id, "source_event_id")
    _parse_iso_timestamp(candidate.detected_at_utc, "detected_at_utc")
    _validate_identifier(candidate.reason_code, "reason_code")
    return candidate


class ResultEngineStore:
    def __init__(
        self,
        *,
        root_dir: Path | None = None,
    ) -> None:
        root = Path(root_dir).resolve() if root_dir is not None else runtime_paths.result_engine_root.resolve()
        self._root_dir = root
        self._observations_dir = root / "observations"
        self._accepted_dir = root / "accepted"
        self._identity_dir = root / "identity"
        self._corrections_dir = root / "corrections"
        self._meta_dir = root / "meta"
        self._locks_dir = root / "locks"

        self._bridge_dir = self._identity_dir / "source_event"
        self._observation_id_index = self._meta_dir / "observation_id_index.json"
        self._accepted_event_index = self._meta_dir / "accepted_event_index.json"
        self._bridge_index = self._meta_dir / "source_event_bridge_index.json"
        self._lock_file = self._locks_dir / "result_engine.lock"

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def _ensure_dirs(self) -> None:
        self._observations_dir.mkdir(parents=True, exist_ok=True)
        self._accepted_dir.mkdir(parents=True, exist_ok=True)
        self._bridge_dir.mkdir(parents=True, exist_ok=True)
        self._corrections_dir.mkdir(parents=True, exist_ok=True)
        self._meta_dir.mkdir(parents=True, exist_ok=True)
        self._locks_dir.mkdir(parents=True, exist_ok=True)

    def _observation_path(self, observation_id: str) -> Path:
        return self._observations_dir / f"{_validate_identifier(observation_id, 'observation_id')}.json"

    def _accepted_path(self, result_id: str) -> Path:
        return self._accepted_dir / f"{_validate_identifier(result_id, 'result_id')}.json"

    def _bridge_path(self, bridge_id: str) -> Path:
        return self._bridge_dir / f"{_validate_identifier(bridge_id, 'bridge_id')}.json"

    def _correction_path(self, candidate_id: str) -> Path:
        return self._corrections_dir / f"{_validate_identifier(candidate_id, 'candidate_id')}.json"

    def _load_cached_index_or_none(self, path: Path) -> dict[str, str] | None:
        if not path.exists():
            return None
        try:
            payload = _read_json_file(path, field_name=str(path.name))
        except ResultEnginePersistenceError:
            return None
        out: dict[str, str] = {}
        for key, value in payload.items():
            if not isinstance(key, str) or not isinstance(value, str):
                return None
            out[key] = value
        return out

    def _write_index(self, path: Path, payload: dict[str, Any]) -> None:
        _atomic_write_text(path, canonical_json(payload))

    def _collect_observations_locked(self) -> tuple[list[RawResultObservation], dict[str, str], dict[str, RawResultObservation]]:
        observations: list[RawResultObservation] = []
        by_id: dict[str, RawResultObservation] = {}
        id_index: dict[str, str] = {}
        source_observation_index: dict[str, str] = {}

        if self._observations_dir.exists():
            for path in sorted(self._observations_dir.glob("*.json")):
                observation = _observation_from_dict(_read_json_file(path, field_name="observation"))
                expected_name = f"{observation.observation_id}.json"
                if path.name != expected_name:
                    raise ResultEnginePersistenceError(
                        f"Observation filename mismatch: path={path.name} observation_id={observation.observation_id}"
                    )
                if observation.observation_id in by_id:
                    raise ResultEnginePersistenceError(
                        f"Duplicate observation authority: observation_id={observation.observation_id}"
                    )
                if observation.payload_hash in id_index and id_index[observation.payload_hash] != observation.observation_id:
                    raise ResultEnginePersistenceError(
                        f"Duplicate observation payload authority: payload_hash={observation.payload_hash}"
                    )

                source_observation_key = f"{observation.source}|{observation.source_event_id}|{observation.source_observation_id}"
                existing_source_evidence = source_observation_index.get(source_observation_key)
                if (
                    existing_source_evidence is not None
                    and existing_source_evidence != observation.source_evidence_hash
                ):
                    raise ResultEnginePersistenceError(
                        f"Ambiguous source observation authority for {source_observation_key}: source_evidence_hashes={[existing_source_evidence, observation.source_evidence_hash]}"
                    )
                observations.append(observation)
                by_id[observation.observation_id] = observation
                id_index[observation.observation_id] = observation.payload_hash
                source_observation_index[source_observation_key] = observation.source_evidence_hash

        cached = self._load_cached_index_or_none(self._observation_id_index)
        if cached != id_index:
            self._write_index(self._observation_id_index, id_index)

        return observations, id_index, by_id

    def _collect_accepted_locked(self) -> tuple[list[AcceptedFinalGameResult], dict[str, str], dict[str, AcceptedFinalGameResult]]:
        accepted: list[AcceptedFinalGameResult] = []
        by_id: dict[str, AcceptedFinalGameResult] = {}
        event_index: dict[str, str] = {}

        if self._accepted_dir.exists():
            for path in sorted(self._accepted_dir.glob("*.json")):
                result = _accepted_from_dict(_read_json_file(path, field_name="accepted result"))
                expected_name = f"{result.result_id}.json"
                if path.name != expected_name:
                    raise ResultEnginePersistenceError(
                        f"Accepted result filename mismatch: path={path.name} result_id={result.result_id}"
                    )
                if result.result_id in by_id:
                    raise ResultEnginePersistenceError(
                        f"Duplicate accepted result authority: result_id={result.result_id}"
                    )
                existing = event_index.get(result.canonical_event_key)
                if existing is not None and existing != result.result_id:
                    raise ResultEnginePersistenceError(
                        f"Duplicate accepted authority for canonical_event_key={result.canonical_event_key}: result_ids={[existing, result.result_id]}"
                    )
                accepted.append(result)
                by_id[result.result_id] = result
                event_index[result.canonical_event_key] = result.result_id

        cached = self._load_cached_index_or_none(self._accepted_event_index)
        if cached != event_index:
            self._write_index(self._accepted_event_index, event_index)

        return accepted, event_index, by_id

    def _collect_bridges_locked(self) -> tuple[list[SourceEventBridgeRecord], dict[str, str], dict[str, SourceEventBridgeRecord]]:
        bridges: list[SourceEventBridgeRecord] = []
        by_id: dict[str, SourceEventBridgeRecord] = {}
        source_event_index: dict[str, str] = {}

        if self._bridge_dir.exists():
            for path in sorted(self._bridge_dir.glob("*.json")):
                bridge = _bridge_from_dict(_read_json_file(path, field_name="identity bridge"))
                expected_name = f"{bridge.bridge_id}.json"
                if path.name != expected_name:
                    raise ResultEnginePersistenceError(
                        f"Bridge filename mismatch: path={path.name} bridge_id={bridge.bridge_id}"
                    )
                if bridge.bridge_id in by_id:
                    raise ResultEnginePersistenceError(
                        f"Duplicate bridge authority: bridge_id={bridge.bridge_id}"
                    )

                source_event_key = f"{bridge.source}|{bridge.source_event_id}"
                existing = source_event_index.get(source_event_key)
                if existing is not None and existing != bridge.canonical_event_key:
                    raise ResultEnginePersistenceError(
                        f"Ambiguous source-event bridge authority for {source_event_key}: canonical_event_keys={[existing, bridge.canonical_event_key]}"
                    )

                bridges.append(bridge)
                by_id[bridge.bridge_id] = bridge
                source_event_index[source_event_key] = bridge.canonical_event_key

        cached = self._load_cached_index_or_none(self._bridge_index)
        if cached != source_event_index:
            self._write_index(self._bridge_index, source_event_index)

        return bridges, source_event_index, by_id

    def _collect_corrections_locked(self) -> list[ResultCorrectionCandidate]:
        candidates: list[ResultCorrectionCandidate] = []
        if self._corrections_dir.exists():
            for path in sorted(self._corrections_dir.glob("*.json")):
                candidate = _correction_candidate_from_dict(_read_json_file(path, field_name="correction candidate"))
                expected_name = f"{candidate.candidate_id}.json"
                if path.name != expected_name:
                    raise ResultEnginePersistenceError(
                        f"Correction candidate filename mismatch: path={path.name} candidate_id={candidate.candidate_id}"
                    )
                candidates.append(candidate)
        return candidates

    def _validate_or_rebuild_indexes_locked(self) -> None:
        self._ensure_dirs()
        self._collect_observations_locked()
        self._collect_accepted_locked()
        self._collect_bridges_locked()

    def persist_observation(self, observation: RawResultObservation) -> RawResultObservation:
        try:
            validate_raw_observation(observation)
        except ResultEngineValidationError as exc:
            raise ResultEnginePersistenceError(str(exc)) from exc

        path = self._observation_path(observation.observation_id)
        text = canonical_json(asdict(observation))

        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            observations, _, by_id = self._collect_observations_locked()
            existing = by_id.get(observation.observation_id)
            if existing is not None:
                if canonical_json(asdict(existing)) != text:
                    if (
                        existing.source == observation.source
                        and existing.source_event_id == observation.source_event_id
                        and existing.source_observation_id == observation.source_observation_id
                        and existing.source_evidence_hash == observation.source_evidence_hash
                    ):
                        # Replay of the same provider/source observation with different
                        # local ingest metadata remains idempotent; preserve first write.
                        return existing
                    raise ResultEnginePersistenceError(
                        f"observation_id collision with different payload: {observation.observation_id}"
                    )
                return existing

            source_observation_key = f"{observation.source}|{observation.source_event_id}|{observation.source_observation_id}"
            existing_source = [
                item
                for item in observations
                if item.source == observation.source
                and item.source_event_id == observation.source_event_id
                and item.source_observation_id == observation.source_observation_id
            ]
            if existing_source:
                existing_source_evidence = existing_source[0].source_evidence_hash
                if existing_source_evidence != observation.source_evidence_hash:
                    raise ResultEnginePersistenceError(
                        f"Ambiguous source observation authority for {source_observation_key}: source_evidence_hashes={[existing_source_evidence, observation.source_evidence_hash]}"
                    )

            _atomic_write_text(path, text)
            self._collect_observations_locked()
            return observation

    def persist_accepted_result(self, result: AcceptedFinalGameResult) -> AcceptedFinalGameResult:
        try:
            validate_accepted_result(result)
        except ResultEngineValidationError as exc:
            raise ResultEnginePersistenceError(str(exc)) from exc

        path = self._accepted_path(result.result_id)
        text = canonical_json(asdict(result))

        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            _, event_index, by_id = self._collect_accepted_locked()

            existing = by_id.get(result.result_id)
            if existing is not None:
                if canonical_json(asdict(existing)) != text:
                    raise ResultEnginePersistenceError(
                        f"result_id collision with different payload: {result.result_id}"
                    )
                return existing

            existing_result_id = event_index.get(result.canonical_event_key)
            if existing_result_id and existing_result_id != result.result_id:
                raise ResultEnginePersistenceError(
                    f"Accepted result already exists for canonical_event_key={result.canonical_event_key}: existing_result_id={existing_result_id}"
                )

            _atomic_write_text(path, text)
            self._collect_accepted_locked()
            return result

    def persist_source_event_bridge(self, bridge: SourceEventBridgeRecord) -> SourceEventBridgeRecord:
        try:
            validate_source_event_bridge(bridge)
        except ResultEngineValidationError as exc:
            raise ResultEnginePersistenceError(str(exc)) from exc

        path = self._bridge_path(bridge.bridge_id)
        text = canonical_json(asdict(bridge))
        source_event_key = f"{bridge.source}|{bridge.source_event_id}"

        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            bridges, source_index, by_id = self._collect_bridges_locked()

            existing_canonical = source_index.get(source_event_key)
            if existing_canonical is not None and existing_canonical != bridge.canonical_event_key:
                raise ResultEnginePersistenceError(
                    f"Source event bridge conflict for {source_event_key}: existing={existing_canonical} requested={bridge.canonical_event_key}"
                )

            if existing_canonical == bridge.canonical_event_key:
                matches = [
                    record
                    for record in bridges
                    if record.source == bridge.source and record.source_event_id == bridge.source_event_id
                ]
                if len(matches) != 1:
                    raise ResultEnginePersistenceError(
                        f"Ambiguous source-event bridge authority for {source_event_key}"
                    )
                return matches[0]

            existing = by_id.get(bridge.bridge_id)
            if existing is not None:
                if canonical_json(asdict(existing)) != text:
                    raise ResultEnginePersistenceError(
                        f"bridge_id collision with different payload: {bridge.bridge_id}"
                    )
                return existing

            _atomic_write_text(path, text)
            self._collect_bridges_locked()
            return bridge

    def persist_correction_candidate(self, candidate: ResultCorrectionCandidate) -> ResultCorrectionCandidate:
        _correction_candidate_from_dict(asdict(candidate))
        path = self._correction_path(candidate.candidate_id)
        text = canonical_json(asdict(candidate))

        with _file_lock(self._lock_file):
            self._ensure_dirs()
            if path.exists():
                existing = _correction_candidate_from_dict(_read_json_file(path, field_name="correction candidate"))
                if canonical_json(asdict(existing)) != text:
                    raise ResultEnginePersistenceError(
                        f"candidate_id collision with different payload: {candidate.candidate_id}"
                    )
                return existing
            _atomic_write_text(path, text)
            return candidate

    def get_observation(self, observation_id: str) -> RawResultObservation:
        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            _, _, by_id = self._collect_observations_locked()
            observation = by_id.get(_validate_identifier(observation_id, "observation_id"))
            if observation is None:
                raise ResultEnginePersistenceError(f"Observation not found: {observation_id}")
            return observation

    def list_observations(self) -> list[RawResultObservation]:
        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            observations, _, _ = self._collect_observations_locked()
            return observations

    def list_observations_for_source_event(
        self,
        *,
        source: str,
        source_event_id: str,
        canonical_event_key: str | None = None,
    ) -> list[RawResultObservation]:
        source_value = _validate_identifier(source, "source")
        source_event_value = _validate_identifier(source_event_id, "source_event_id")
        if canonical_event_key is not None:
            _validate_identifier(canonical_event_key, "canonical_event_key")

        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            observations, _, _ = self._collect_observations_locked()
            out = [
                observation
                for observation in observations
                if observation.source == source_value
                and observation.source_event_id == source_event_value
                and (canonical_event_key is None or observation.canonical_event_key == canonical_event_key)
            ]
            out.sort(key=lambda item: item.observed_at_utc)
            return out

    def get_accepted_result_for_event(self, canonical_event_key: str) -> AcceptedFinalGameResult | None:
        _validate_identifier(canonical_event_key, "canonical_event_key")
        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            _, event_index, by_id = self._collect_accepted_locked()
            result_id = event_index.get(canonical_event_key)
            if result_id is None:
                return None
            return by_id.get(result_id)

    def get_accepted_result(self, result_id: str) -> AcceptedFinalGameResult:
        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            _, _, by_id = self._collect_accepted_locked()
            accepted = by_id.get(_validate_identifier(result_id, "result_id"))
            if accepted is None:
                raise ResultEnginePersistenceError(f"Accepted result not found: {result_id}")
            return accepted

    def list_accepted_results(self, *, season: int | None = None, week: int | None = None) -> list[AcceptedFinalGameResult]:
        if season is not None and (isinstance(season, bool) or not isinstance(season, int) or season <= 0):
            raise ResultEnginePersistenceError("season must be a positive integer")
        if week is not None and (isinstance(week, bool) or not isinstance(week, int) or week <= 0):
            raise ResultEnginePersistenceError("week must be a positive integer")

        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            accepted, _, _ = self._collect_accepted_locked()
            out: list[AcceptedFinalGameResult] = []
            for result in accepted:
                if season is not None and result.season != season:
                    continue
                if week is not None and result.week != week:
                    continue
                out.append(result)
            return out

    def list_source_event_bridges(self) -> list[SourceEventBridgeRecord]:
        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            bridges, _, _ = self._collect_bridges_locked()
            return bridges

    def get_source_event_bridge(self, *, source: str, source_event_id: str) -> SourceEventBridgeRecord | None:
        source_value = _validate_identifier(source, "source")
        source_event_value = _validate_identifier(source_event_id, "source_event_id")
        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            bridges, _, _ = self._collect_bridges_locked()
            matches = [
                bridge
                for bridge in bridges
                if bridge.source == source_value and bridge.source_event_id == source_event_value
            ]
            if not matches:
                return None
            if len(matches) > 1:
                raise ResultEnginePersistenceError(
                    f"Ambiguous source-event bridge authority for {source_value}|{source_event_value}"
                )
            return matches[0]

    def list_correction_candidates(self) -> list[ResultCorrectionCandidate]:
        with _file_lock(self._lock_file):
            self._validate_or_rebuild_indexes_locked()
            return self._collect_corrections_locked()


def default_result_engine_store() -> ResultEngineStore:
    return ResultEngineStore()
