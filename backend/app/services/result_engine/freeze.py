from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .completeness import validate_week_completeness
from .contracts import AcceptedFinalGameResult
from .hashing import canonical_json, sha256_hex
from .identity import CanonicalEventIdentity
from .persistence import ResultEngineStore
from .status import NormalizedResultStatus, normalize_result_status
from .validation import ResultEngineValidationError, validate_accepted_result

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None


@dataclass(frozen=True)
class FrozenWeeklyResultSet:
    season: int
    week: int
    expected_game_count: int
    accepted_final_count: int
    expected_canonical_event_keys: tuple[str, ...]
    accepted_result_ids: tuple[str, ...]
    accepted_result_versions: tuple[str, ...]
    result_set_version: str
    result_set_hash: str
    frozen_at_utc: str
    accepted_results: tuple[AcceptedFinalGameResult, ...]


class FrozenWeeklyResultSetError(ValueError):
    pass


class FrozenWeeklyResultSetLockError(FrozenWeeklyResultSetError):
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _result_set_version(result_set_hash: str) -> str:
    return f"weekly-result-set-v1:{result_set_hash[:16]}"


def _sorted_expected_keys(expected_events: Iterable[CanonicalEventIdentity]) -> tuple[str, ...]:
    events = list(expected_events)
    keys = [event.canonical_event_key for event in events]
    if len(keys) != len(set(keys)):
        raise FrozenWeeklyResultSetError("Expected events contain duplicate canonical_event_key values")
    return tuple(sorted(keys))


def _canonical_accepted_summary(result: AcceptedFinalGameResult) -> dict[str, Any]:
    return {
        "result_id": result.result_id,
        "canonical_event_key": result.canonical_event_key,
        "season": result.season,
        "week": result.week,
        "kickoff_utc": result.kickoff_utc,
        "away_team": result.away_team,
        "home_team": result.home_team,
        "away_score": result.away_score,
        "home_score": result.home_score,
        "accepted_status": result.accepted_status.value,
        "source": result.source,
        "source_event_id": result.source_event_id,
        "source_result_version": result.source_result_version,
        "first_observed_at_utc": result.first_observed_at_utc,
        "confirmed_at_utc": result.confirmed_at_utc,
        "accepted_at_utc": result.accepted_at_utc,
        "confirmation_count": result.confirmation_count,
        "observation_ids": list(result.observation_ids),
        "acceptance_policy_version": result.acceptance_policy_version,
        "correction_of_result_id": result.correction_of_result_id,
    }


def _result_set_hash_for(
    *,
    season: int,
    week: int,
    expected_keys: Iterable[str],
    accepted_results: Iterable[AcceptedFinalGameResult],
) -> str:
    ordered_expected = tuple(sorted(expected_keys))
    ordered_acceptance = sorted(
        (_canonical_accepted_summary(result) for result in accepted_results),
        key=lambda item: (item["canonical_event_key"], item["result_id"]),
    )
    payload = {
        "season": season,
        "week": week,
        "expected_canonical_event_keys": list(ordered_expected),
        "accepted_results": ordered_acceptance,
    }
    return sha256_hex(canonical_json(payload))


def _status_reason_for(
    *,
    season: int,
    week: int,
    expected_events: list[CanonicalEventIdentity],
    accepted_results: list[AcceptedFinalGameResult],
) -> str | None:
    expected_keys = [event.canonical_event_key for event in expected_events]
    if len(expected_keys) != len(set(expected_keys)):
        return "DUPLICATE_EXPECTED_GAME"

    accepted_keys = [result.canonical_event_key for result in accepted_results]
    if len(accepted_keys) != len(set(accepted_keys)):
        by_key: dict[str, list[AcceptedFinalGameResult]] = {}
        for result in accepted_results:
            by_key.setdefault(result.canonical_event_key, []).append(result)
        for key, rows in by_key.items():
            if len(rows) > 1:
                signatures = {
                    (
                        row.canonical_event_key,
                        row.season,
                        row.week,
                        row.kickoff_utc,
                        row.away_team,
                        row.home_team,
                        row.away_score,
                        row.home_score,
                        row.accepted_status.value,
                    )
                    for row in rows
                }
                if len(signatures) > 1:
                    return "CONFLICTING_ACCEPTED_FINAL"
                return "DUPLICATE_ACCEPTED_FINAL"
        return "DUPLICATE_ACCEPTED_FINAL"

    expected_key_set = set(expected_keys)
    accepted_key_set = set(accepted_keys)
    if expected_key_set - accepted_key_set:
        return "MISSING_EXPECTED_GAME"
    if accepted_key_set - expected_key_set:
        return "UNEXPECTED_RESULT"

    for result in accepted_results:
        if result.season != season:
            return "SEASON_MISMATCH"
        if result.week != week:
            return "WEEK_MISMATCH"
        if result.accepted_status != NormalizedResultStatus.FINAL:
            return "NONFINAL_RESULT"
        try:
            validate_accepted_result(result)
        except ResultEngineValidationError:
            return "ACCEPTED_RESULT_VALIDATION_ERROR"

    completeness = validate_week_completeness(
        season=season,
        week=week,
        expected_events=expected_events,
        accepted_results=accepted_results,
    )
    if not completeness.is_complete:
        if completeness.missing_event_keys:
            return "MISSING_EXPECTED_GAME"
        if completeness.unexpected_event_keys:
            return "UNEXPECTED_RESULT"
        if completeness.duplicate_event_keys:
            return "DUPLICATE_ACCEPTED_FINAL"
        if completeness.identity_mismatch_event_keys:
            return "CONFLICTING_ACCEPTED_FINAL"
    return None


def _freeze_path(store: ResultEngineStore, season: int, week: int) -> Path:
    return store.root_dir / "frozen" / f"weekly-result-set-{season}-{week}.json"


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


def _freeze_lock_path(store: ResultEngineStore, season: int, week: int) -> Path:
    return store.root_dir / "locks" / f"weekly-freeze-{season}-{week}.lock"


@contextmanager
def _freeze_lock(store: ResultEngineStore, *, season: int, week: int):
    lock_path = _freeze_lock_path(store, season, week)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with lock_path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise FrozenWeeklyResultSetLockError(f"Unable to acquire freeze lock for {season}/{week}") from exc


def _load_frozen_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _normalize_frozen_payload(payload: dict[str, Any]) -> FrozenWeeklyResultSet:
    accepted_payload = payload.get("accepted_results", [])
    accepted: list[AcceptedFinalGameResult] = []
    for item in accepted_payload:
        materialized = dict(item)
        materialized["accepted_status"] = normalize_result_status(materialized.get("accepted_status"))
        if isinstance(materialized.get("observation_ids"), list):
            materialized["observation_ids"] = tuple(materialized["observation_ids"])
        result = AcceptedFinalGameResult(**materialized)
        accepted.append(validate_accepted_result(result))
    return FrozenWeeklyResultSet(
        season=int(payload["season"]),
        week=int(payload["week"]),
        expected_game_count=int(payload["expected_game_count"]),
        accepted_final_count=int(payload["accepted_final_count"]),
        expected_canonical_event_keys=tuple(payload.get("expected_canonical_event_keys", [])),
        accepted_result_ids=tuple(payload.get("accepted_result_ids", [])),
        accepted_result_versions=tuple(payload.get("accepted_result_versions", [])),
        result_set_version=str(payload["result_set_version"]),
        result_set_hash=str(payload["result_set_hash"]),
        frozen_at_utc=str(payload["frozen_at_utc"]),
        accepted_results=tuple(accepted),
    )


def load_frozen_week_result_set(store: ResultEngineStore, *, season: int, week: int) -> FrozenWeeklyResultSet | None:
    path = _freeze_path(store, season, week)
    payload = _load_frozen_payload(path)
    if payload is None:
        return None
    return _normalize_frozen_payload(payload)


def freeze_week_result_set(
    *,
    store: ResultEngineStore,
    season: int,
    week: int,
    expected_events: Iterable[CanonicalEventIdentity],
    accepted_results: Iterable[AcceptedFinalGameResult],
    require_unique_identity: bool = True,
) -> dict[str, Any]:
    expected_list = list(expected_events)
    accepted_list = list(accepted_results)
    expected_keys = _sorted_expected_keys(expected_list)

    for result in accepted_list:
        if result.season != season or result.week != week:
            return {
                "status": "NOT_READY",
                "reason": "SEASON_MISMATCH" if result.season != season else "WEEK_MISMATCH",
                "expectedGameCount": len(expected_keys),
                "acceptedFinalCount": len(accepted_list),
                "resultSetVersion": "",
                "resultSetHash": "",
                "frozenAt": None,
            }
        try:
            validate_accepted_result(result)
        except ResultEngineValidationError:
            return {
                "status": "NOT_READY",
                "reason": "ACCEPTED_RESULT_VALIDATION_ERROR",
                "expectedGameCount": len(expected_keys),
                "acceptedFinalCount": len(accepted_list),
                "resultSetVersion": "",
                "resultSetHash": "",
                "frozenAt": None,
            }
        if result.accepted_status != NormalizedResultStatus.FINAL:
            return {
                "status": "NOT_READY",
                "reason": "NONFINAL_RESULT",
                "expectedGameCount": len(expected_keys),
                "acceptedFinalCount": len(accepted_list),
                "resultSetVersion": "",
                "resultSetHash": "",
                "frozenAt": None,
            }

    try:
        with _freeze_lock(store, season=season, week=week):
            reason = _status_reason_for(
                season=season,
                week=week,
                expected_events=expected_list,
                accepted_results=accepted_list,
            )
            if reason is not None:
                existing = load_frozen_week_result_set(store, season=season, week=week)
                if existing is not None:
                    candidate_hash = _result_set_hash_for(
                        season=season,
                        week=week,
                        expected_keys=expected_keys,
                        accepted_results=accepted_list,
                    )
                    if existing.result_set_hash == candidate_hash:
                        return {
                            "status": "ALREADY_FROZEN",
                            "reason": "ALREADY_FROZEN",
                            "expectedGameCount": existing.expected_game_count,
                            "acceptedFinalCount": existing.accepted_final_count,
                            "resultSetVersion": existing.result_set_version,
                            "resultSetHash": existing.result_set_hash,
                            "frozenAt": existing.frozen_at_utc,
                        }
                    return {
                        "status": "NOT_READY",
                        "reason": "FROZEN_SET_CONFLICT",
                        "expectedGameCount": existing.expected_game_count,
                        "acceptedFinalCount": existing.accepted_final_count,
                        "resultSetVersion": existing.result_set_version,
                        "resultSetHash": existing.result_set_hash,
                        "frozenAt": existing.frozen_at_utc,
                    }
                return {
                    "status": "NOT_READY",
                    "reason": reason,
                    "expectedGameCount": len(expected_keys),
                    "acceptedFinalCount": len(accepted_list),
                    "resultSetVersion": "",
                    "resultSetHash": "",
                    "frozenAt": None,
                }

            if require_unique_identity and len({result.canonical_event_key for result in accepted_list}) != len(accepted_list):
                return {
                    "status": "NOT_READY",
                    "reason": "DUPLICATE_ACCEPTED_FINAL",
                    "expectedGameCount": len(expected_keys),
                    "acceptedFinalCount": len(accepted_list),
                    "resultSetVersion": "",
                    "resultSetHash": "",
                    "frozenAt": None,
                }

            result_hash = _result_set_hash_for(
                season=season,
                week=week,
                expected_keys=expected_keys,
                accepted_results=accepted_list,
            )
            result_version = _result_set_version(result_hash)
            frozen_at = _utc_now_iso()
            expected_ids = tuple(sorted(result.result_id for result in accepted_list))
            accepted_versions = tuple(sorted(result.source_result_version for result in accepted_list))

            existing = load_frozen_week_result_set(store, season=season, week=week)
            if existing is not None:
                candidate_hash = _result_set_hash_for(
                    season=season,
                    week=week,
                    expected_keys=expected_keys,
                    accepted_results=accepted_list,
                )
                if existing.result_set_hash == candidate_hash:
                    return {
                        "status": "ALREADY_FROZEN",
                        "reason": "ALREADY_FROZEN",
                        "expectedGameCount": existing.expected_game_count,
                        "acceptedFinalCount": existing.accepted_final_count,
                        "resultSetVersion": existing.result_set_version,
                        "resultSetHash": existing.result_set_hash,
                        "frozenAt": existing.frozen_at_utc,
                    }
                return {
                    "status": "NOT_READY",
                    "reason": "FROZEN_SET_CONFLICT",
                    "expectedGameCount": existing.expected_game_count,
                    "acceptedFinalCount": existing.accepted_final_count,
                    "resultSetVersion": existing.result_set_version,
                    "resultSetHash": existing.result_set_hash,
                    "frozenAt": existing.frozen_at_utc,
                }

            record = FrozenWeeklyResultSet(
                season=season,
                week=week,
                expected_game_count=len(expected_keys),
                accepted_final_count=len(accepted_list),
                expected_canonical_event_keys=expected_keys,
                accepted_result_ids=expected_ids,
                accepted_result_versions=accepted_versions,
                result_set_version=result_version,
                result_set_hash=result_hash,
                frozen_at_utc=frozen_at,
                accepted_results=tuple(sorted(accepted_list, key=lambda item: (item.canonical_event_key, item.result_id))),
            )

            path = _freeze_path(store, season, week)
            payload = asdict(record)
            payload["accepted_results"] = [asdict(item) for item in record.accepted_results]
            _atomic_write_text(path, canonical_json(payload))

            persisted = load_frozen_week_result_set(store, season=season, week=week)
            if persisted is None:
                raise FrozenWeeklyResultSetError("Freeze persistence verification failed")
            if persisted.result_set_hash != record.result_set_hash:
                raise FrozenWeeklyResultSetError("Freeze persistence verification hash mismatch")

            return {
                "status": "FROZEN",
                "expectedGameCount": record.expected_game_count,
                "acceptedFinalCount": record.accepted_final_count,
                "resultSetVersion": record.result_set_version,
                "resultSetHash": record.result_set_hash,
                "frozenAt": record.frozen_at_utc,
            }
    except FrozenWeeklyResultSetLockError:
        return {
            "status": "NOT_READY",
            "reason": "LOCK_ACQUISITION_FAILED",
            "expectedGameCount": len(expected_keys),
            "acceptedFinalCount": len(accepted_list),
            "resultSetVersion": "",
            "resultSetHash": "",
            "frozenAt": None,
        }
