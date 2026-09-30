from __future__ import annotations

from dataclasses import replace
import importlib.util
import json
from pathlib import Path
from types import ModuleType

from app.services.power_engine import (
    CANONICAL_NFL_TEAMS,
    PowerEngineStore,
    PowerLineageRecord,
    PowerSnapshot,
    PowerTeamRating,
    build_preseason_regressed_root_snapshot,
    replay_frozen_weekly_power_transition_for_lineage,
    snapshot_hash,
)
from app.services.result_engine import ResultEngineStore, freeze_week_result_set
from result_engine_test_utils import make_accepted_result, make_identity


def _power_store(tmp_path: Path) -> PowerEngineStore:
    return PowerEngineStore(root_dir=tmp_path / "power-engine-root")


def _result_store(tmp_path: Path) -> ResultEngineStore:
    return ResultEngineStore(root_dir=tmp_path / "result-engine-root")


def _snapshot(*, season: int, through_week: int, snapshot_id: str, generated_at: str = "2026-09-10T00:00:00Z") -> PowerSnapshot:
    teams = tuple(
        PowerTeamRating(team_id=team, power=float(idx) / 5.0)
        for idx, team in enumerate(CANONICAL_NFL_TEAMS)
    )
    base = PowerSnapshot(
        snapshot_id=snapshot_id,
        snapshot_hash="",
        season=season,
        through_week=through_week,
        updater_version="sia_power_engine_2e4a_v1",
        methodology_hash="method-v1",
        source_snapshot_id=None,
        generated_at=generated_at,
        teams=teams,
    )
    return replace(base, snapshot_hash=snapshot_hash(base))


def _seed_active_lineage(store: PowerEngineStore, *, season: int, through_week: int = 0, snapshot_id: str = "power-root") -> tuple[PowerSnapshot, PowerLineageRecord]:
    snap = store.persist_snapshot(_snapshot(season=season, through_week=through_week, snapshot_id=snapshot_id))
    lineage = PowerLineageRecord(
        lineage_id=f"ln-{season}-wk{through_week}-seed",
        parent_lineage_id=None,
        root_snapshot_id=snap.snapshot_id,
        active_snapshot_id=snap.snapshot_id,
        season=season,
        through_week=through_week,
        status="ACTIVE",
        created_at="2026-09-10T00:00:00Z",
        superseded_at=None,
        superseded_by=None,
    )
    store.create_lineage(lineage, set_active=True)
    return snap, lineage


def _freeze_week(
    *,
    store: ResultEngineStore,
    season: int,
    week: int,
    games: list[tuple[str, str, str]],
) -> dict:
    expected = [
        make_identity(season=season, week=week, away_team=away, home_team=home, kickoff_utc=kickoff)
        for away, home, kickoff in games
    ]
    accepted = [
        make_accepted_result(
            season=season,
            week=week,
            away_team=away,
            home_team=home,
            kickoff_utc=kickoff,
            source_event_id=f"evt-{away}-{home}",
            away_score=17 + idx,
            home_score=24 + idx,
        )
        for idx, (away, home, kickoff) in enumerate(games)
    ]
    out = freeze_week_result_set(
        store=store,
        season=season,
        week=week,
        expected_events=expected,
        accepted_results=accepted,
    )
    assert out["status"] == "FROZEN"
    return out


def _terminal_map() -> dict[str, float]:
    return {team: float(idx) for idx, team in enumerate(CANONICAL_NFL_TEAMS)}


def _load_v2_lineage_script_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "implement_2026_power_v2_lineage.py"
    spec = importlib.util.spec_from_file_location("v2_lineage_script", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load implement_2026_power_v2_lineage.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_research_artifact(tmp_path: Path, *, shift: float = 0.0) -> Path:
    payload = {
        "phase6_2026_reconstruction_inputs": {
            "proposed_2025_terminal_table": [
                {"TEAM": team, "POWER": float(idx) + shift}
                for idx, team in enumerate(CANONICAL_NFL_TEAMS)
            ]
        }
    }
    path = tmp_path / "research-artifact.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_preseason_regressed_root_r_endpoints_and_r70() -> None:
    terminal = _terminal_map()
    mean = sum(terminal.values()) / float(len(terminal))

    root_zero = build_preseason_regressed_root_snapshot(
        prior_terminal_team_powers=terminal,
        target_season=2026,
        source_season=2025,
        source_snapshot_id="src",
        source_snapshot_hash="src-hash",
        regression_factor=0.0,
        generated_at="2026-09-01T00:00:00Z",
    )
    for team in root_zero.teams:
        assert team.power == mean

    root_full = build_preseason_regressed_root_snapshot(
        prior_terminal_team_powers=terminal,
        target_season=2026,
        source_season=2025,
        source_snapshot_id="src",
        source_snapshot_hash="src-hash",
        regression_factor=1.0,
        generated_at="2026-09-01T00:00:00Z",
    )
    for team in root_full.teams:
        assert team.power == terminal[team.team_id]

    root_r70 = build_preseason_regressed_root_snapshot(
        prior_terminal_team_powers=terminal,
        target_season=2026,
        source_season=2025,
        source_snapshot_id="src",
        source_snapshot_hash="src-hash",
        regression_factor=0.70,
        generated_at="2026-09-01T00:00:00Z",
    )
    first_team = root_r70.teams[0]
    expected_first = mean + 0.70 * (terminal[first_team.team_id] - mean)
    assert first_team.power == expected_first


def test_preseason_constructor_is_deterministic() -> None:
    terminal = _terminal_map()
    a = build_preseason_regressed_root_snapshot(
        prior_terminal_team_powers=terminal,
        target_season=2026,
        source_season=2025,
        source_snapshot_id="src",
        source_snapshot_hash="src-hash",
        regression_factor=0.70,
        generated_at="2026-09-01T00:00:00Z",
    )
    b = build_preseason_regressed_root_snapshot(
        prior_terminal_team_powers=terminal,
        target_season=2026,
        source_season=2025,
        source_snapshot_id="src",
        source_snapshot_hash="src-hash",
        regression_factor=0.70,
        generated_at="2026-09-01T00:00:00Z",
    )

    assert a.snapshot_id == b.snapshot_id
    assert a.snapshot_hash == b.snapshot_hash
    assert a.methodology_hash == b.methodology_hash


def test_branch_replay_does_not_change_active_pointer(tmp_path: Path) -> None:
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _, v1_lineage = _seed_active_lineage(power_store, season=2026, through_week=0, snapshot_id="power-root-v1")
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    root_v2 = build_preseason_regressed_root_snapshot(
        prior_terminal_team_powers=_terminal_map(),
        target_season=2026,
        source_season=2025,
        source_snapshot_id="power-2025-terminal-src",
        source_snapshot_hash="source-hash",
        regression_factor=0.70,
        generated_at="2026-09-01T00:00:00Z",
    )
    root_v2 = power_store.persist_snapshot(root_v2)

    v2_lineage = PowerLineageRecord(
        lineage_id="ln-2026-v2-wk0-test",
        parent_lineage_id=v1_lineage.lineage_id,
        root_snapshot_id=root_v2.snapshot_id,
        active_snapshot_id=root_v2.snapshot_id,
        season=2026,
        through_week=0,
        status="SUPERSEDED",
        created_at="2026-09-01T00:00:00Z",
        superseded_at="2026-09-01T00:00:00Z",
        superseded_by=v1_lineage.lineage_id,
    )
    power_store.create_lineage(v2_lineage, set_active=False)

    out = replay_frozen_weekly_power_transition_for_lineage(
        season=2026,
        week=1,
        parent_lineage_id=v2_lineage.lineage_id,
        prior_snapshot_id=root_v2.snapshot_id,
        root_snapshot_id=root_v2.snapshot_id,
        power_store=power_store,
        result_store=result_store,
        set_active=False,
    )

    assert out["status"] == "APPLIED"
    assert out["transition"]["parent_lineage_id"] == v2_lineage.lineage_id

    active_after = power_store.get_active_lineage(2026)
    assert active_after.lineage_id == v1_lineage.lineage_id


def test_v2_lineage_apply_is_idempotent_and_non_activating(tmp_path: Path, monkeypatch) -> None:
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _, active_lineage = _seed_active_lineage(power_store, season=2026, through_week=0, snapshot_id="power-root-v1")

    _freeze_week(
        store=result_store,
        season=2026,
        week=1,
        games=[("ARI", "ATL", "2026-09-10T00:15:00Z")],
    )
    _freeze_week(
        store=result_store,
        season=2026,
        week=2,
        games=[("BAL", "BUF", "2026-09-17T00:15:00Z")],
    )

    module = _load_v2_lineage_script_module()
    monkeypatch.setattr(module, "default_power_engine_store", lambda: power_store)
    monkeypatch.setattr(module, "default_result_engine_store", lambda: result_store)

    research_artifact = _write_research_artifact(tmp_path)

    run1 = module._create_v2_root_lineage(research_artifact, apply=True)
    run2 = module._create_v2_root_lineage(research_artifact, apply=True)

    assert run1["applied"] is True
    assert run2["applied"] is True

    assert run1["created"]["sourceSnapshot"]["snapshot_id"] == run2["created"]["sourceSnapshot"]["snapshot_id"]
    assert run1["created"]["sourceSnapshot"]["snapshot_hash"] == run2["created"]["sourceSnapshot"]["snapshot_hash"]
    assert run1["created"]["rootSnapshot"]["snapshot_id"] == run2["created"]["rootSnapshot"]["snapshot_id"]
    assert run1["created"]["rootSnapshot"]["snapshot_hash"] == run2["created"]["rootSnapshot"]["snapshot_hash"]
    assert run1["created"]["week1"]["transition"]["new_snapshot_id"] == run2["created"]["week1"]["transition"]["new_snapshot_id"]
    assert run1["created"]["week1"]["transition"]["new_snapshot_hash"] == run2["created"]["week1"]["transition"]["new_snapshot_hash"]
    assert run1["created"]["week2"]["transition"]["new_snapshot_id"] == run2["created"]["week2"]["transition"]["new_snapshot_id"]
    assert run1["created"]["week2"]["transition"]["new_snapshot_hash"] == run2["created"]["week2"]["transition"]["new_snapshot_hash"]

    assert run2["created"]["week1"]["status"] in {"APPLIED", "ALREADY_APPLIED"}
    assert run2["created"]["week2"]["status"] in {"APPLIED", "ALREADY_APPLIED"}

    active_after = power_store.get_active_lineage(2026)
    assert active_after.lineage_id == active_lineage.lineage_id
    assert run2["post"]["activeLineage"]["lineage_id"] == active_lineage.lineage_id


def test_v2_lineage_research_input_changes_root_identity(tmp_path: Path, monkeypatch) -> None:
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=0, snapshot_id="power-root-v1")

    _freeze_week(
        store=result_store,
        season=2026,
        week=1,
        games=[("ARI", "ATL", "2026-09-10T00:15:00Z")],
    )
    _freeze_week(
        store=result_store,
        season=2026,
        week=2,
        games=[("BAL", "BUF", "2026-09-17T00:15:00Z")],
    )

    module = _load_v2_lineage_script_module()
    monkeypatch.setattr(module, "default_power_engine_store", lambda: power_store)
    monkeypatch.setattr(module, "default_result_engine_store", lambda: result_store)

    artifact_a = _write_research_artifact(tmp_path / "a", shift=0.0)
    artifact_b = _write_research_artifact(tmp_path / "b", shift=0.5)

    out_a = module._create_v2_root_lineage(artifact_a, apply=False)
    out_b = module._create_v2_root_lineage(artifact_b, apply=False)

    assert out_a["v2RootPreview"]["snapshotId"] != out_b["v2RootPreview"]["snapshotId"]
    assert out_a["v2RootPreview"]["snapshotHash"] != out_b["v2RootPreview"]["snapshotHash"]
