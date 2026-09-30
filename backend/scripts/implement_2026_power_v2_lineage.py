from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app.services.power_engine import (
    PowerLineageRecord,
    PowerSnapshot,
    PowerTeamRating,
    active_power_transition_observability,
    build_preseason_regressed_root_snapshot,
    default_power_engine_store,
    list_power_weekly_transitions,
    replay_frozen_weekly_power_transition_for_lineage,
    snapshot_hash,
)
from app.services.power_engine.hashing import canonical_json, sha256_hex, snapshot_identity_payload
from app.services.power_engine.persistence import PowerEnginePersistenceError
from app.services.power_engine.projection_publication import active_projection_observability
from app.services.result_engine import ResultEngineStore, default_result_engine_store, load_frozen_week_result_set
from app.services.result_engine.teams import normalize_team_id


TARGET_SEASON = 2026
SOURCE_SEASON = 2025
REGRESSION_FACTOR = 0.70
RECONSTRUCTION_METHOD_VERSION = "sia_power_terminal_reconstruction_v1"
DETERMINISTIC_V2_GENERATED_AT = "2026-09-01T00:00:00Z"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_terminal_map(research_artifact_path: Path) -> tuple[dict[str, float], str, str]:
    payload = json.loads(research_artifact_path.read_text(encoding="utf-8"))
    table = payload.get("phase6_2026_reconstruction_inputs", {}).get("proposed_2025_terminal_table")
    if not isinstance(table, list) or not table:
        raise ValueError("research artifact missing phase6_2026_reconstruction_inputs.proposed_2025_terminal_table")

    powers: dict[str, float] = {}
    for row in table:
        team = normalize_team_id(str(row.get("TEAM") or "").strip())
        power = row.get("POWER")
        if not team:
            raise ValueError("invalid team row in research artifact")
        if team in powers:
            raise ValueError(f"duplicate team in research artifact table: {team}")
        powers[team] = float(power)

    artifact_hash = sha256_hex(canonical_json(payload))
    return powers, artifact_hash, str(research_artifact_path)


def _build_reconstructed_2025_terminal_snapshot(
    *,
    terminal_team_powers: dict[str, float],
    research_artifact_hash: str,
    generated_at: str,
) -> PowerSnapshot:
    methodology_payload = {
        "methodologyVersion": RECONSTRUCTION_METHOD_VERSION,
        "kind": "RESEARCH_DERIVED_2025_TERMINAL",
        "sourceSeason": SOURCE_SEASON,
        "sourceArtifactHash": research_artifact_hash,
        "selectedRegressionFactor": REGRESSION_FACTOR,
    }
    methodology_hash_value = sha256_hex(canonical_json(methodology_payload))
    teams = tuple(PowerTeamRating(team_id=team, power=float(power)) for team, power in sorted(terminal_team_powers.items()))

    provisional = PowerSnapshot(
        snapshot_id="",
        snapshot_hash="",
        season=SOURCE_SEASON,
        through_week=18,
        updater_version="sia_power_terminal_reconstruction_v1",
        methodology_hash=methodology_hash_value,
        source_snapshot_id=None,
        generated_at=generated_at,
        teams=teams,
    )
    provisional_hash = snapshot_hash(provisional)
    snapshot_id = f"power-2025-terminal-reconstructed-{provisional_hash[:12]}"
    snapshot = PowerSnapshot(
        snapshot_id=snapshot_id,
        snapshot_hash="",
        season=provisional.season,
        through_week=provisional.through_week,
        updater_version=provisional.updater_version,
        methodology_hash=provisional.methodology_hash,
        source_snapshot_id=provisional.source_snapshot_id,
        generated_at=provisional.generated_at,
        teams=provisional.teams,
    )
    final_hash = snapshot_hash(snapshot)
    return PowerSnapshot(
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=final_hash,
        season=snapshot.season,
        through_week=snapshot.through_week,
        updater_version=snapshot.updater_version,
        methodology_hash=snapshot.methodology_hash,
        source_snapshot_id=snapshot.source_snapshot_id,
        generated_at=snapshot.generated_at,
        teams=snapshot.teams,
    )


def _read_phase0_identities(*, allow_missing_active: bool = False) -> dict:
    store = default_power_engine_store()
    active_lineage = None
    active_snapshot = None
    try:
        active_lineage = store.get_active_lineage(TARGET_SEASON)
        active_snapshot = store.get_snapshot(active_lineage.active_snapshot_id)
    except PowerEnginePersistenceError:
        if not allow_missing_active:
            raise
    transitions = [asdict(item) for item in list_power_weekly_transitions(power_store=store, season=TARGET_SEASON)]

    snapshots = {snap.snapshot_id: snap for snap in store.list_snapshots(season=TARGET_SEASON)}
    week1 = next((asdict(snap) for snap in snapshots.values() if snap.through_week == 1), None)
    week2 = next((asdict(snap) for snap in snapshots.values() if snap.through_week == 2), None)
    week3 = next((asdict(snap) for snap in snapshots.values() if snap.through_week == 3), None)

    return {
        "activeLineage": None if active_lineage is None else asdict(active_lineage),
        "activeSnapshot": None if active_snapshot is None else asdict(active_snapshot),
        "week1Snapshot": week1,
        "week2Snapshot": week2,
        "week3Snapshot": week3,
        "powerObservability": None if active_lineage is None else active_power_transition_observability(power_store=store, season=TARGET_SEASON),
        "projectionWeek3": active_projection_observability(season=TARGET_SEASON, week=3, power_store=store),
        "transitions": transitions,
    }


def _is_bootstrap_safe_lineage_id(value: str) -> bool:
    return (
        value.startswith(f"ln-{TARGET_SEASON}-v2-wk0-")
        or value.startswith(f"ln-{TARGET_SEASON}-wk1-")
        or value.startswith(f"ln-{TARGET_SEASON}-wk2-")
    )


def _is_bootstrap_safe_snapshot_id(value: str) -> bool:
    return (
        value.startswith("power-2025-terminal-reconstructed-")
        or value.startswith(f"power-root-{TARGET_SEASON}-v2-")
        or value.startswith(f"power-{TARGET_SEASON}-wk1-")
        or value.startswith(f"power-{TARGET_SEASON}-wk2-")
    )


def _assert_bootstrap_store_safe(*, store) -> None:
    try:
        active = store.get_active_lineage(TARGET_SEASON)
        raise RuntimeError(f"BOOTSTRAP_REQUIRES_NO_ACTIVE_LINEAGE|found={active.lineage_id}")
    except PowerEnginePersistenceError:
        pass

    lineages = store.list_lineages(season=TARGET_SEASON)
    for lineage in lineages:
        if not _is_bootstrap_safe_lineage_id(lineage.lineage_id):
            raise RuntimeError(f"BOOTSTRAP_REQUIRES_EMPTY_OR_KNOWN_STORE|unexpected_lineage={lineage.lineage_id}")

    snapshots = [
        *store.list_snapshots(season=SOURCE_SEASON),
        *store.list_snapshots(season=TARGET_SEASON),
    ]
    for snapshot in snapshots:
        if not _is_bootstrap_safe_snapshot_id(snapshot.snapshot_id):
            raise RuntimeError(f"BOOTSTRAP_REQUIRES_EMPTY_OR_KNOWN_STORE|unexpected_snapshot={snapshot.snapshot_id}")

    transitions = list_power_weekly_transitions(power_store=store, season=TARGET_SEASON)
    for transition in transitions:
        if transition.week not in {1, 2}:
            raise RuntimeError(f"BOOTSTRAP_REQUIRES_EMPTY_OR_KNOWN_STORE|unexpected_transition_week={transition.week}")
        if not _is_bootstrap_safe_lineage_id(transition.parent_lineage_id):
            raise RuntimeError(
                f"BOOTSTRAP_REQUIRES_EMPTY_OR_KNOWN_STORE|unexpected_parent_lineage={transition.parent_lineage_id}"
            )


def _lineage_semantic_payload(lineage: PowerLineageRecord) -> dict:
    return {
        "lineage_id": lineage.lineage_id,
        "parent_lineage_id": lineage.parent_lineage_id,
        "root_snapshot_id": lineage.root_snapshot_id,
        "active_snapshot_id": lineage.active_snapshot_id,
        "season": int(lineage.season),
        "through_week": int(lineage.through_week),
        "status": lineage.status,
        "superseded_by": lineage.superseded_by,
    }


def _persist_snapshot_idempotent(*, store, snapshot: PowerSnapshot) -> PowerSnapshot:
    try:
        return store.persist_snapshot(snapshot)
    except PowerEnginePersistenceError as exc:
        if "snapshot_id collision with different content" not in str(exc):
            raise
        existing = store.get_snapshot(snapshot.snapshot_id)
        if canonical_json(snapshot_identity_payload(existing)) == canonical_json(snapshot_identity_payload(snapshot)):
            return existing
        raise


def _create_lineage_idempotent(*, store, lineage: PowerLineageRecord) -> PowerLineageRecord:
    try:
        return store.create_lineage(lineage, set_active=False)
    except PowerEnginePersistenceError as exc:
        if "lineage_id collision with different content" not in str(exc):
            raise
        existing = store.get_lineage(lineage.lineage_id)
        if canonical_json(_lineage_semantic_payload(existing)) == canonical_json(_lineage_semantic_payload(lineage)):
            return existing
        raise


def _create_v2_root_lineage(research_artifact_path: Path, *, apply: bool, bootstrap_empty_store: bool = False) -> dict:
    store = default_power_engine_store()
    result_store: ResultEngineStore = default_result_engine_store()
    deterministic_generated_at = DETERMINISTIC_V2_GENERATED_AT

    phase0 = _read_phase0_identities(allow_missing_active=bootstrap_empty_store)
    active_v1 = None if bootstrap_empty_store else store.get_active_lineage(TARGET_SEASON)

    terminal_map, research_hash, research_path = _load_terminal_map(research_artifact_path)
    source_snapshot = _build_reconstructed_2025_terminal_snapshot(
        terminal_team_powers=terminal_map,
        research_artifact_hash=research_hash,
        generated_at=deterministic_generated_at,
    )

    v2_root = build_preseason_regressed_root_snapshot(
        prior_terminal_team_powers=terminal_map,
        target_season=TARGET_SEASON,
        source_season=SOURCE_SEASON,
        source_snapshot_id=source_snapshot.snapshot_id,
        source_snapshot_hash=source_snapshot.snapshot_hash,
        regression_factor=REGRESSION_FACTOR,
        generated_at=deterministic_generated_at,
    )

    root_stddev = 0.0
    mean = sum(team.power for team in v2_root.teams) / float(len(v2_root.teams))
    root_stddev = (sum((team.power - mean) ** 2 for team in v2_root.teams) / float(len(v2_root.teams))) ** 0.5
    v2_lineage_id = f"ln-2026-v2-wk0-{v2_root.snapshot_hash[:12]}"
    if bootstrap_empty_store:
        v2_lineage = PowerLineageRecord(
            lineage_id=v2_lineage_id,
            parent_lineage_id=None,
            root_snapshot_id=v2_root.snapshot_id,
            active_snapshot_id=v2_root.snapshot_id,
            season=TARGET_SEASON,
            through_week=0,
            status="ACTIVE",
            created_at=deterministic_generated_at,
            superseded_at=None,
            superseded_by=None,
        )
    else:
        assert active_v1 is not None
        v2_lineage = PowerLineageRecord(
            lineage_id=v2_lineage_id,
            parent_lineage_id=active_v1.lineage_id,
            root_snapshot_id=v2_root.snapshot_id,
            active_snapshot_id=v2_root.snapshot_id,
            season=TARGET_SEASON,
            through_week=0,
            status="SUPERSEDED",
            created_at=deterministic_generated_at,
            superseded_at=deterministic_generated_at,
            superseded_by=active_v1.lineage_id,
        )

    freeze_wk1 = load_frozen_week_result_set(result_store, season=TARGET_SEASON, week=1)
    freeze_wk2 = load_frozen_week_result_set(result_store, season=TARGET_SEASON, week=2)
    preflight = {
        "week1FrozenResultSetPresent": freeze_wk1 is not None,
        "week2FrozenResultSetPresent": freeze_wk2 is not None,
    }

    out = {
        "phase0": phase0,
        "researchArtifactPath": research_path,
        "researchArtifactHash": research_hash,
        "v2RootPreview": {
            "snapshotId": v2_root.snapshot_id,
            "snapshotHash": v2_root.snapshot_hash,
            "methodologyHash": v2_root.methodology_hash,
            "sourceSnapshotId": v2_root.source_snapshot_id,
            "regressionFactor": REGRESSION_FACTOR,
            "rootStddev": root_stddev,
            "teamCount": len(v2_root.teams),
        },
        "preflight": preflight,
        "apply": apply,
        "bootstrapEmptyStore": bootstrap_empty_store,
        "applied": False,
    }

    if not apply:
        return out

    if freeze_wk1 is None:
        raise RuntimeError("Missing required frozen result set: weekly-result-set-2026-1")
    if freeze_wk2 is None:
        raise RuntimeError("Missing required frozen result set: weekly-result-set-2026-2")

    if bootstrap_empty_store:
        _assert_bootstrap_store_safe(store=store)

    persisted_source = _persist_snapshot_idempotent(store=store, snapshot=source_snapshot)
    persisted_root = _persist_snapshot_idempotent(store=store, snapshot=v2_root)
    created_lineage = _create_lineage_idempotent(store=store, lineage=v2_lineage)

    wk1 = replay_frozen_weekly_power_transition_for_lineage(
        season=TARGET_SEASON,
        week=1,
        parent_lineage_id=created_lineage.lineage_id,
        prior_snapshot_id=persisted_root.snapshot_id,
        root_snapshot_id=persisted_root.snapshot_id,
        power_store=store,
        result_store=result_store,
        set_active=False,
        superseded_by_lineage_id=created_lineage.lineage_id if bootstrap_empty_store else None,
    )
    wk1_lineage_id = wk1["transition"]["new_lineage_id"]
    wk1_snapshot_id = wk1["transition"]["new_snapshot_id"]

    wk2 = replay_frozen_weekly_power_transition_for_lineage(
        season=TARGET_SEASON,
        week=2,
        parent_lineage_id=wk1_lineage_id,
        prior_snapshot_id=wk1_snapshot_id,
        root_snapshot_id=persisted_root.snapshot_id,
        power_store=store,
        result_store=result_store,
        set_active=False,
        superseded_by_lineage_id=created_lineage.lineage_id if bootstrap_empty_store else None,
    )

    post = _read_phase0_identities(allow_missing_active=bootstrap_empty_store)
    out.update(
        {
            "applied": True,
            "created": {
                "sourceSnapshot": asdict(persisted_source),
                "rootSnapshot": asdict(persisted_root),
                "lineage": asdict(created_lineage),
                "week1": wk1,
                "week2": wk2,
            },
            "post": post,
            "invariants": {
                "ACTIVE_POWER_LINEAGE_CHANGED": (post["activeLineage"] or {}).get("lineage_id") != (phase0["activeLineage"] or {}).get("lineage_id"),
                "ACTIVE_PROJECTION_CHANGED": post["projectionWeek3"].get("artifactId") != phase0["projectionWeek3"].get("artifactId"),
                "V1_ARTIFACT_MUTATION": False,
            },
        }
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Implement immutable 2026 power v2 lineage.")
    parser.add_argument(
        "--research-artifact",
        required=True,
        help="Path to preseason initialization research artifact containing proposed_2025_terminal_table.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply runtime mutations. Omit for read-only proof/dry-run.",
    )
    parser.add_argument(
        "--bootstrap-empty-store",
        action="store_true",
        help="Fail-closed mode for bootstrapping an empty/known staging store without requiring an active v1 lineage.",
    )
    args = parser.parse_args()

    result = _create_v2_root_lineage(
        Path(args.research_artifact),
        apply=bool(args.apply),
        bootstrap_empty_store=bool(args.bootstrap_empty_store),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
