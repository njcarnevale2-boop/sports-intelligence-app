from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .completeness import WeekCompletenessResult, validate_week_completeness
from .contracts import AcceptedFinalGameResult
from .hashing import canonical_json, sha256_hex
from .identity import CanonicalEventIdentity
from .persistence import ResultEnginePersistenceError, ResultEngineStore


@dataclass(frozen=True)
class TrustedResultBatchManifest:
    manifest_id: str
    manifest_hash: str
    season: int
    week: int
    policy_version: str
    expected_canonical_event_keys: tuple[str, ...]
    accepted_result_ids: tuple[str, ...]
    accepted_result_versions: tuple[str, ...]
    unresolved_correction_candidate_ids: tuple[str, ...]
    completeness: WeekCompletenessResult
    created_at_utc: str


@dataclass(frozen=True)
class TrustedResultBatchEvaluation:
    manifest: TrustedResultBatchManifest
    is_handoff_eligible: bool


class TrustedResultBatchManifestError(ValueError):
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_manifest_payload(manifest: TrustedResultBatchManifest) -> dict:
    return {
        "season": manifest.season,
        "week": manifest.week,
        "policy_version": manifest.policy_version,
        "expected_canonical_event_keys": list(manifest.expected_canonical_event_keys),
        "accepted_result_ids": list(manifest.accepted_result_ids),
        "accepted_result_versions": list(manifest.accepted_result_versions),
        "unresolved_correction_candidate_ids": list(manifest.unresolved_correction_candidate_ids),
        "completeness": asdict(manifest.completeness),
    }


def _manifest_hash(manifest: TrustedResultBatchManifest) -> str:
    return sha256_hex(canonical_json(_canonical_manifest_payload(manifest)))


def _manifest_id(manifest_hash: str) -> str:
    return f"trb-{manifest_hash[:24]}"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


class TrustedResultBatchManifestStore:
    def __init__(self, *, store: ResultEngineStore) -> None:
        self._store = store
        self._manifests_dir = store.root_dir / "manifests"

    def persist(self, manifest: TrustedResultBatchManifest) -> TrustedResultBatchManifest:
        payload = asdict(manifest)
        serialized = canonical_json(payload)
        path = self._manifests_dir / f"{manifest.manifest_id}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if canonical_json(existing) != serialized:
                raise TrustedResultBatchManifestError(
                    f"Manifest collision with different payload: {manifest.manifest_id}"
                )
            return manifest
        _atomic_write_text(path, serialized)
        return manifest


def evaluate_trusted_result_batch(
    *,
    store: ResultEngineStore,
    season: int,
    week: int,
    expected_events: Iterable[CanonicalEventIdentity],
    policy_version: str,
) -> TrustedResultBatchEvaluation:
    expected_list = list(expected_events)
    accepted_results = store.list_accepted_results(season=season, week=week)
    completeness = validate_week_completeness(
        season=season,
        week=week,
        expected_events=expected_list,
        accepted_results=accepted_results,
    )

    expected_keys = tuple(sorted(event.canonical_event_key for event in expected_list))
    accepted_sorted = sorted(
        accepted_results,
        key=lambda item: (item.canonical_event_key, item.result_id),
    )
    accepted_ids = tuple(item.result_id for item in accepted_sorted)
    accepted_versions = tuple(item.source_result_version for item in accepted_sorted)

    unresolved = sorted(
        {
            candidate.candidate_id
            for candidate in store.list_correction_candidates()
            if candidate.canonical_event_key in set(expected_keys)
        }
    )

    draft = TrustedResultBatchManifest(
        manifest_id="",
        manifest_hash="",
        season=season,
        week=week,
        policy_version=policy_version,
        expected_canonical_event_keys=expected_keys,
        accepted_result_ids=accepted_ids,
        accepted_result_versions=accepted_versions,
        unresolved_correction_candidate_ids=tuple(unresolved),
        completeness=completeness,
        created_at_utc=_utc_now_iso(),
    )
    manifest_hash = _manifest_hash(draft)
    manifest_id = _manifest_id(manifest_hash)
    manifest = TrustedResultBatchManifest(
        manifest_id=manifest_id,
        manifest_hash=manifest_hash,
        season=draft.season,
        week=draft.week,
        policy_version=draft.policy_version,
        expected_canonical_event_keys=draft.expected_canonical_event_keys,
        accepted_result_ids=draft.accepted_result_ids,
        accepted_result_versions=draft.accepted_result_versions,
        unresolved_correction_candidate_ids=draft.unresolved_correction_candidate_ids,
        completeness=draft.completeness,
        created_at_utc=draft.created_at_utc,
    )

    store_wrapper = TrustedResultBatchManifestStore(store=store)
    persisted_manifest = store_wrapper.persist(manifest)

    return TrustedResultBatchEvaluation(
        manifest=persisted_manifest,
        is_handoff_eligible=bool(completeness.is_complete and not unresolved),
    )
