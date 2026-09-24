from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import app.services.power_engine.weekly_transition as weekly_transition_module
from app.services.power_engine import (
    CANONICAL_NFL_TEAMS,
    FROZEN_METHODOLOGY,
    UPDATER_VERSION,
    PowerEnginePersistenceError,
    PowerEngineStore,
    PowerLineageRecord,
    PowerSnapshot,
    PowerTeamRating,
    active_power_transition_observability,
    apply_frozen_weekly_power_transition,
    apply_single_game_update,
    apply_week_results,
    list_power_weekly_transitions,
    snapshot_hash,
)
from app.services.result_engine import ResultEngineStore, freeze_week_result_set, load_frozen_week_result_set
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
        updater_version=UPDATER_VERSION,
        methodology_hash=weekly_transition_module._expected_methodology_hash(methodology=FROZEN_METHODOLOGY, updater_version=UPDATER_VERSION),
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


def test_a_valid_week_n_transition(tmp_path: Path):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    root_snapshot, _ = _seed_active_lineage(power_store, season=2026, through_week=0, snapshot_id="power-root-2026")
    frozen = _freeze_week(
        store=result_store,
        season=2026,
        week=1,
        games=[("ARI", "ATL", "2026-09-10T00:15:00Z"), ("BAL", "BUF", "2026-09-11T00:15:00Z")],
    )

    out = apply_frozen_weekly_power_transition(
        season=2026,
        week=1,
        power_store=power_store,
        result_store=result_store,
    )

    assert out["status"] == "APPLIED"
    tr = out["transition"]
    assert tr["prior_snapshot_id"] == root_snapshot.snapshot_id
    assert tr["result_set_version"] == frozen["resultSetVersion"]
    assert tr["result_set_hash"] == frozen["resultSetHash"]
    active = power_store.get_active_lineage(2026)
    assert active.through_week == 1


def test_b_missing_frozen_result_set(tmp_path: Path):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026)

    with pytest.raises(ValueError, match="FROZEN_RESULT_SET_MISSING"):
        apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)


def test_c_missing_prior_snapshot(tmp_path: Path):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _, lineage = _seed_active_lineage(power_store, season=2026)
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    monkey = replace(lineage, active_snapshot_id="missing-snapshot")
    original = power_store.get_active_lineage

    def _bad_active(_season: int):
        return monkey

    power_store.get_active_lineage = _bad_active  # type: ignore[method-assign]

    with pytest.raises(ValueError):
        apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)

    power_store.get_active_lineage = original  # type: ignore[method-assign]


def test_d_wrong_prior_through_week(tmp_path: Path):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=1, snapshot_id="power-wk1")
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    with pytest.raises(ValueError, match="PRIOR_SNAPSHOT_THROUGH_WEEK_MISMATCH"):
        apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)


def test_e_wrong_season(tmp_path: Path):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026)
    _freeze_week(store=result_store, season=2027, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    with pytest.raises(ValueError, match="FROZEN_RESULT_SET_MISSING"):
        apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)


def test_f_result_set_lineage_mismatch(tmp_path: Path):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026)
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    with pytest.raises(ValueError, match="RESULT_SET_HASH_CONFLICT"):
        apply_frozen_weekly_power_transition(
            season=2026,
            week=1,
            power_store=power_store,
            result_store=result_store,
            expected_result_set_hash="deadbeef",
        )


def test_g_unknown_team_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026)
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    real_mapper = weekly_transition_module.accepted_result_to_final_game_result

    def _bad_mapper(accepted):
        base = real_mapper(accepted)
        return replace(base, home_team="XXX")

    monkeypatch.setattr(weekly_transition_module, "accepted_result_to_final_game_result", _bad_mapper)

    with pytest.raises(ValueError, match="RESULT_UNKNOWN_TEAM"):
        apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)


def test_h_incomplete_invalid_result_set_rejection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026)
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    frozen = load_frozen_week_result_set(result_store, season=2026, week=1)
    assert frozen is not None
    broken = replace(frozen, expected_game_count=frozen.expected_game_count + 1)
    monkeypatch.setattr(weekly_transition_module, "load_frozen_week_result_set", lambda *args, **kwargs: broken)

    with pytest.raises(ValueError, match="FROZEN_RESULT_SET_INCOMPLETE"):
        apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)


def test_i_deterministic_identical_transition(tmp_path: Path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    store_a = _power_store(root_a)
    res_a = _result_store(root_a)
    store_b = _power_store(root_b)
    res_b = _result_store(root_b)
    _seed_active_lineage(store_a, season=2026)
    _seed_active_lineage(store_b, season=2026)
    _freeze_week(store=res_a, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])
    _freeze_week(store=res_b, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    out_a = apply_frozen_weekly_power_transition(season=2026, week=1, power_store=store_a, result_store=res_a)
    out_b = apply_frozen_weekly_power_transition(season=2026, week=1, power_store=store_b, result_store=res_b)

    assert out_a["transition"]["new_snapshot_hash"] == out_b["transition"]["new_snapshot_hash"]
    assert out_a["transition"]["transition_id"] == out_b["transition"]["transition_id"]


def test_j_exact_replay_returns_already_applied(tmp_path: Path):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026)
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    first = apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)
    snapshots_before = len(power_store.list_snapshots(season=2026))
    second = apply_frozen_weekly_power_transition(
        season=2026,
        week=1,
        power_store=power_store,
        result_store=result_store,
        expected_prior_snapshot_id=first["transition"]["prior_snapshot_id"],
        expected_prior_snapshot_hash=first["transition"]["prior_snapshot_hash"],
    )
    snapshots_after = len(power_store.list_snapshots(season=2026))
    transitions = list_power_weekly_transitions(power_store=power_store, season=2026, week=1)

    assert first["status"] == "APPLIED"
    assert second["status"] == "ALREADY_APPLIED"
    assert first["transition"]["transition_id"] == second["transition"]["transition_id"]
    assert first["transition"]["prior_snapshot_id"] == second["transition"]["prior_snapshot_id"]
    assert first["transition"]["new_snapshot_id"] == second["transition"]["new_snapshot_id"]
    assert first["transition"]["new_snapshot_hash"] == second["transition"]["new_snapshot_hash"]
    assert len(transitions) == 1
    assert snapshots_after == snapshots_before


def test_k_same_week_cannot_be_applied_twice_from_week_n_snapshot(tmp_path: Path):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026)
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])
    _freeze_week(store=result_store, season=2026, week=2, games=[("BAL", "BUF", "2026-09-17T00:15:00Z")])

    apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)
    first = apply_frozen_weekly_power_transition(season=2026, week=2, power_store=power_store, result_store=result_store)
    active_before = power_store.get_active_lineage(2026)
    transition_count_before = len(list_power_weekly_transitions(power_store=power_store, season=2026, week=2))
    snapshot_count_before = len(power_store.list_snapshots(season=2026))
    active_snapshot_before = power_store.get_snapshot(active_before.active_snapshot_id)

    assert active_before.through_week == 2
    assert active_before.active_snapshot_id == first["transition"]["new_snapshot_id"]

    with pytest.raises(ValueError, match="PRIOR_SNAPSHOT_ID_CONFLICT"):
        apply_frozen_weekly_power_transition(
            season=2026,
            week=2,
            power_store=power_store,
            result_store=result_store,
            expected_prior_snapshot_id=active_before.active_snapshot_id,
        )

    active_after = power_store.get_active_lineage(2026)
    transition_count_after = len(list_power_weekly_transitions(power_store=power_store, season=2026, week=2))
    snapshot_count_after = len(power_store.list_snapshots(season=2026))
    active_snapshot_after = power_store.get_snapshot(active_after.active_snapshot_id)

    assert active_after.active_snapshot_id == active_before.active_snapshot_id
    assert active_after.through_week == active_before.through_week
    assert transition_count_after == transition_count_before
    assert snapshot_count_after == snapshot_count_before
    assert active_snapshot_after.snapshot_hash == active_snapshot_before.snapshot_hash


def test_l_conflicting_prior_snapshot(tmp_path: Path):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026)
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    applied = apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)

    with pytest.raises(ValueError, match="PRIOR_SNAPSHOT_ID_CONFLICT"):
        apply_frozen_weekly_power_transition(
            season=2026,
            week=1,
            power_store=power_store,
            result_store=result_store,
            expected_prior_snapshot_id="different-prior-snapshot",
        )

    with pytest.raises(ValueError, match="PRIOR_SNAPSHOT_HASH_CONFLICT"):
        apply_frozen_weekly_power_transition(
            season=2026,
            week=1,
            power_store=power_store,
            result_store=result_store,
            expected_prior_snapshot_id=applied["transition"]["prior_snapshot_id"],
            expected_prior_snapshot_hash="different-prior-hash",
        )


def test_m_conflicting_result_set_identity(tmp_path: Path):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026)
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    with pytest.raises(ValueError, match="RESULT_SET_VERSION_CONFLICT"):
        apply_frozen_weekly_power_transition(
            season=2026,
            week=1,
            power_store=power_store,
            result_store=result_store,
            expected_result_set_version="weekly-result-set-v1:incorrect",
        )


def test_n_conflicting_methodology(tmp_path: Path):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026)
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    with pytest.raises(ValueError, match="METHODOLOGY_HASH_CONFLICT"):
        apply_frozen_weekly_power_transition(
            season=2026,
            week=1,
            power_store=power_store,
            result_store=result_store,
            methodology_hash_value="f" * 64,
        )


def test_o_snapshot_identity_deterministic(tmp_path: Path):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026)
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    out = apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)
    rec = out["transition"]
    snap = power_store.get_snapshot(rec["new_snapshot_id"])

    assert snap.snapshot_hash == rec["new_snapshot_hash"]


def test_p_transition_identity_deterministic(tmp_path: Path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    power_left = _power_store(left)
    result_left = _result_store(left)
    power_right = _power_store(right)
    result_right = _result_store(right)
    _seed_active_lineage(power_left, season=2026)
    _seed_active_lineage(power_right, season=2026)
    _freeze_week(store=result_left, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])
    _freeze_week(store=result_right, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    out_left = apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_left, result_store=result_left)
    out_right = apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_right, result_store=result_right)

    assert out_left["transition"]["transition_id"] == out_right["transition"]["transition_id"]
    assert out_left["transition"]["idempotency_key"] == out_right["transition"]["idempotency_key"]


def test_q_timestamps_do_not_affect_deterministic_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_a = _power_store(tmp_path / "ta")
    result_a = _result_store(tmp_path / "ta")
    power_b = _power_store(tmp_path / "tb")
    result_b = _result_store(tmp_path / "tb")
    _seed_active_lineage(power_a, season=2026)
    _seed_active_lineage(power_b, season=2026)
    _freeze_week(store=result_a, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])
    _freeze_week(store=result_b, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    monkeypatch.setattr(weekly_transition_module, "_utc_now_iso", lambda: "2026-09-24T10:00:00Z")
    out_a = apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_a, result_store=result_a)
    monkeypatch.setattr(weekly_transition_module, "_utc_now_iso", lambda: "2026-09-24T11:00:00Z")
    out_b = apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_b, result_store=result_b)

    assert out_a["transition"]["transition_id"] == out_b["transition"]["transition_id"]
    assert out_a["transition"]["created_at"] != out_b["transition"]["created_at"]


def test_r_partial_snapshot_persistence_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026)
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])
    before = power_store.get_active_lineage(2026)

    def _boom_snapshot(snapshot):
        raise PowerEnginePersistenceError("snapshot write failed")

    monkeypatch.setattr(power_store, "persist_snapshot", _boom_snapshot)

    with pytest.raises(PowerEnginePersistenceError):
        apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)

    after = power_store.get_active_lineage(2026)
    assert after.lineage_id == before.lineage_id


def test_s_transition_record_persistence_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026)
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])
    before = power_store.get_active_lineage(2026)

    def _boom_transition(*args, **kwargs):
        raise OSError("transition staging failed")

    monkeypatch.setattr(weekly_transition_module, "_persist_transition_staged", _boom_transition)

    with pytest.raises(OSError):
        apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)

    after = power_store.get_active_lineage(2026)
    assert after.lineage_id == before.lineage_id


def test_t_active_pointer_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026)
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    before = power_store.get_active_lineage(2026)

    def _boom_create_lineage(*args, **kwargs):
        raise PowerEnginePersistenceError("active pointer failure")

    monkeypatch.setattr(power_store, "create_lineage", _boom_create_lineage)

    with pytest.raises(PowerEnginePersistenceError, match="active pointer failure"):
        apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)

    after = power_store.get_active_lineage(2026)
    assert after.lineage_id == before.lineage_id


def test_u_previous_active_snapshot_remains_authoritative_after_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    root, _ = _seed_active_lineage(power_store, season=2026)
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    monkeypatch.setattr(power_store, "create_lineage", lambda *args, **kwargs: (_ for _ in ()).throw(PowerEnginePersistenceError("boom")))

    with pytest.raises(PowerEnginePersistenceError):
        apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)

    active = power_store.get_active_lineage(2026)
    assert active.active_snapshot_id == root.snapshot_id


def test_v_restart_after_successful_transition(tmp_path: Path):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026)
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    first = apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)
    fresh_store = PowerEngineStore(root_dir=power_store.root_dir)
    fresh_result_store = ResultEngineStore(root_dir=result_store.root_dir)
    second = apply_frozen_weekly_power_transition(season=2026, week=1, power_store=fresh_store, result_store=fresh_result_store)

    assert first["status"] == "APPLIED"
    assert second["status"] == "ALREADY_APPLIED"
    assert first["transition"]["transition_id"] == second["transition"]["transition_id"]


def test_w_restart_after_interrupted_transition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026)
    _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])

    calls = {"count": 0}
    original_create = power_store.create_lineage

    def _fail_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PowerEnginePersistenceError("interrupted")
        return original_create(*args, **kwargs)

    monkeypatch.setattr(power_store, "create_lineage", _fail_once)

    with pytest.raises(PowerEnginePersistenceError):
        apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)

    monkeypatch.setattr(power_store, "create_lineage", original_create)
    out = apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)

    assert out["status"] in {"APPLIED", "ALREADY_APPLIED"}
    transitions = list_power_weekly_transitions(power_store=power_store, season=2026, week=1)
    assert len(transitions) == 1
    assert power_store.get_active_lineage(2026).through_week == 1


def test_x_same_week_games_use_frozen_preweek_ratings(tmp_path: Path):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    prior_snapshot, _ = _seed_active_lineage(power_store, season=2026)

    expected_events = [
        make_identity(season=2026, week=1, away_team="ARI", home_team="ATL", kickoff_utc="2026-09-10T00:15:00Z"),
        make_identity(season=2026, week=1, away_team="ATL", home_team="BUF", kickoff_utc="2026-09-11T00:15:00Z"),
    ]
    accepted = [
        make_accepted_result(season=2026, week=1, away_team="ARI", home_team="ATL", kickoff_utc="2026-09-10T00:15:00Z", away_score=14, home_score=35, source_event_id="evt-g1"),
        make_accepted_result(season=2026, week=1, away_team="ATL", home_team="BUF", kickoff_utc="2026-09-11T00:15:00Z", away_score=31, home_score=13, source_event_id="evt-g2"),
    ]
    frozen = freeze_week_result_set(
        store=result_store,
        season=2026,
        week=1,
        expected_events=expected_events,
        accepted_results=accepted,
    )
    assert frozen["status"] == "FROZEN"

    out = apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)
    produced = power_store.get_snapshot(out["transition"]["new_snapshot_id"])

    mapped = tuple(weekly_transition_module.accepted_result_to_final_game_result(item) for item in accepted)
    expected_batch = apply_week_results(
        snapshot=prior_snapshot,
        results=mapped,
        generated_at=load_frozen_week_result_set(result_store, season=2026, week=1).frozen_at_utc,
        updater_version=UPDATER_VERSION,
        methodology=FROZEN_METHODOLOGY,
    ).snapshot_after

    preweek = {t.team_id: float(t.power) for t in prior_snapshot.teams}
    seq = dict(preweek)
    for result in mapped:
        update = apply_single_game_update(
            home_power_before=seq[result.home_team],
            away_power_before=seq[result.away_team],
            result=result,
            methodology=FROZEN_METHODOLOGY,
            updater_version=UPDATER_VERSION,
        )
        seq[result.home_team] = update.home_power_after
        seq[result.away_team] = update.away_power_after

    produced_lookup = {team.team_id: float(team.power) for team in produced.teams}
    expected_lookup = {team.team_id: float(team.power) for team in expected_batch.teams}

    assert produced_lookup["ATL"] == pytest.approx(expected_lookup["ATL"], abs=1e-12)
    assert produced_lookup["ATL"] != pytest.approx(seq["ATL"], abs=1e-6)


def test_active_transition_observability_contains_lineage_fields(tmp_path: Path):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026)
    frozen = _freeze_week(store=result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-10T00:15:00Z")])
    applied = apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)

    obs = active_power_transition_observability(power_store=power_store, season=2026)
    assert obs["season"] == 2026
    assert obs["throughWeek"] == 1
    assert obs["activeSnapshotId"] == applied["transition"]["new_snapshot_id"]
    assert obs["sourceResultSetVersion"] == frozen["resultSetVersion"]
    assert obs["sourceResultSetHash"] == frozen["resultSetHash"]
    assert obs["transitionId"] == applied["transition"]["transition_id"]