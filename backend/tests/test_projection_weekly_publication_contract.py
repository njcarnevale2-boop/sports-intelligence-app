from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import threading

import duckdb
import pandas as pd
import pytest

import app.services.power_engine.projection_publication as publication_module
import app.services.schedule_engine.service as schedule_module
from app.services.power_engine import (
    CANONICAL_NFL_TEAMS,
    PowerEngineStore,
    PowerLineageRecord,
    PowerSnapshot,
    PowerTeamRating,
    active_projection_observability,
    apply_frozen_weekly_power_transition,
    list_projection_artifacts,
    publish_weekly_projections,
    snapshot_hash,
)
from app.services.result_engine import ResultEngineStore, freeze_week_result_set
from app.services.schedule_engine import ScheduleEngineStore, load_canonical_weekly_schedule, materialize_canonical_weekly_schedule
from result_engine_test_utils import make_accepted_result, make_identity


def _power_store(tmp_path: Path) -> PowerEngineStore:
    return PowerEngineStore(root_dir=tmp_path / "power-root")


def _result_store(tmp_path: Path) -> ResultEngineStore:
    return ResultEngineStore(root_dir=tmp_path / "result-root")


def _schedule_path(tmp_path: Path) -> Path:
    return tmp_path / "schedule_context_latest.csv"


def _schedule_store(tmp_path: Path) -> ScheduleEngineStore:
    return ScheduleEngineStore(root_dir=tmp_path / "schedule-engine-root")


def _schedule_duckdb_path(tmp_path: Path) -> Path:
    return tmp_path / "schedule-source.duckdb"


def _projection_path(tmp_path: Path) -> Path:
    return tmp_path / "current_game_projections.csv"


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_schedule_source(tmp_path: Path, rows: list[dict]) -> Path:
    path = _schedule_duckdb_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = duckdb.connect(str(path))
    con.execute(
        """
        CREATE TABLE schedules (
            game_id VARCHAR,
            season INTEGER,
            week INTEGER,
            gameday VARCHAR,
            gametime VARCHAR,
            away_team VARCHAR,
            home_team VARCHAR
        )
        """
    )
    for row in rows:
        con.execute(
            "INSERT INTO schedules VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                row["game_id"],
                row["season"],
                row["week"],
                row["gameday"],
                row["gametime"],
                row["away_team"],
                row["home_team"],
            ],
        )
    con.close()
    return path


def _read_schedule_source_rows(tmp_path: Path) -> list[dict]:
    con = duckdb.connect(str(_schedule_duckdb_path(tmp_path)), read_only=True)
    try:
        rows = con.execute(
            "SELECT game_id, season, week, gameday, gametime, away_team, home_team FROM schedules ORDER BY gameday, gametime, game_id"
        ).fetchdf()
    finally:
        con.close()
    return rows.to_dict(orient="records")


def _rewrite_schedule_source_rows(tmp_path: Path, rows: list[dict]) -> Path:
    return _write_schedule_source(tmp_path, rows)


def _snapshot(*, season: int, through_week: int, snapshot_id: str, power_shift: float = 0.0) -> PowerSnapshot:
    teams = tuple(
        PowerTeamRating(team_id=team, power=float(idx) / 5.0 + power_shift)
        for idx, team in enumerate(CANONICAL_NFL_TEAMS)
    )
    base = PowerSnapshot(
        snapshot_id=snapshot_id,
        snapshot_hash="",
        season=season,
        through_week=through_week,
        updater_version="power-updater-v1",
        methodology_hash="method-v1",
        source_snapshot_id=None,
        generated_at="2026-09-10T00:00:00Z",
        teams=teams,
    )
    return replace(base, snapshot_hash=snapshot_hash(base))


def _seed_active_lineage(
    store: PowerEngineStore,
    *,
    season: int,
    through_week: int,
    snapshot_id: str,
    lineage_id: str,
    power_shift: float = 0.0,
) -> PowerSnapshot:
    snap = store.persist_snapshot(_snapshot(season=season, through_week=through_week, snapshot_id=snapshot_id, power_shift=power_shift))
    lineage = PowerLineageRecord(
        lineage_id=lineage_id,
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
    return snap


def _write_valid_week3_schedule(tmp_path: Path, *, season: int = 2026, week: int = 3) -> tuple[Path, Path]:
    if week == 3:
        schedule_rows = [
            {
                "game_id": f"{season}_{week:02d}_ARI_ATL",
                "season": season,
                "week": week,
                "gameday": "2026-09-24",
                "gametime": "20:20",
                "away_team": "ARI",
                "home_team": "ATL",
            },
            {
                "game_id": f"{season}_{week:02d}_BAL_BUF",
                "season": season,
                "week": week,
                "gameday": "2026-09-27",
                "gametime": "13:00",
                "away_team": "BAL",
                "home_team": "BUF",
            },
        ]
        projection_rows = [
            {
                "api_event_id": f"{season}_{week}_ARI_ATL",
                "commence_time": "2026-09-25T00:20:00+00:00",
                "away_team": "ARI",
                "home_team": "ATL",
            },
            {
                "api_event_id": f"{season}_{week}_BAL_BUF",
                "commence_time": "2026-09-27T17:00:00+00:00",
                "away_team": "BAL",
                "home_team": "BUF",
            },
        ]
    else:
        schedule_rows = [
            {
                "game_id": f"{season}_{week:02d}_CAR_CHI",
                "season": season,
                "week": week,
                "gameday": "2026-10-01",
                "gametime": "20:20",
                "away_team": "CAR",
                "home_team": "CHI",
            },
            {
                "game_id": f"{season}_{week:02d}_CIN_CLE",
                "season": season,
                "week": week,
                "gameday": "2026-10-04",
                "gametime": "13:00",
                "away_team": "CIN",
                "home_team": "CLE",
            },
        ]
        projection_rows = [
            {
                "api_event_id": f"{season}_{week}_CAR_CHI",
                "commence_time": "2026-10-02T00:20:00+00:00",
                "away_team": "CAR",
                "home_team": "CHI",
            },
            {
                "api_event_id": f"{season}_{week}_CIN_CLE",
                "commence_time": "2026-10-04T17:00:00+00:00",
                "away_team": "CIN",
                "home_team": "CLE",
            },
        ]
    schedule_path = _write_schedule_source(tmp_path, schedule_rows)
    projection_path = _projection_path(tmp_path)
    _write_csv(projection_path, projection_rows)
    return schedule_path, projection_path


def _materialize_schedule(tmp_path: Path, *, season: int, week: int) -> dict:
    return materialize_canonical_weekly_schedule(
        season=season,
        week=week,
        store=_schedule_store(tmp_path),
        duckdb_path=_schedule_duckdb_path(tmp_path),
    )


def _publish(
    *,
    tmp_path: Path,
    power_store: PowerEngineStore,
    season: int,
    target_week: int,
    model_version: str | None = None,
    probability_version: str | None = None,
):
    schedule_store = _schedule_store(tmp_path)
    try:
        active_lineage = power_store.get_active_lineage(season)
        active_snapshot = power_store.get_snapshot(active_lineage.active_snapshot_id)
    except Exception:
        active_snapshot = None

    if (
        active_snapshot is not None
        and active_snapshot.season == season
        and active_snapshot.through_week + 1 == target_week
        and load_canonical_weekly_schedule(season=season, week=target_week, store=schedule_store) is None
        and _schedule_duckdb_path(tmp_path).exists()
    ):
        materialize_canonical_weekly_schedule(
            season=season,
            week=target_week,
            store=schedule_store,
            duckdb_path=_schedule_duckdb_path(tmp_path),
        )
    return publish_weekly_projections(
        season=season,
        target_week=target_week,
        power_store=power_store,
        schedule_store=schedule_store,
        model_version=model_version,
        probability_version=probability_version,
    )


def _write_conflicting_legacy_projection_csv(tmp_path: Path) -> Path:
    projection_path = _projection_path(tmp_path)
    _write_csv(
        projection_path,
        [
            {
                "api_event_id": "bogus_evt_1",
                "commence_time": "2030-01-01T00:00:00+00:00",
                "away_team": "NYJ",
                "home_team": "NE",
                "away_power": 999.0,
                "home_power": -999.0,
                "model_margin_home": -123.45,
            },
            {
                "api_event_id": "bogus_evt_2",
                "commence_time": "2030-01-02T00:00:00+00:00",
                "away_team": "KC",
                "home_team": "LAR",
                "away_power": 555.0,
                "home_power": -555.0,
                "model_margin_home": 42.0,
            },
        ],
    )
    return projection_path


def _freeze_week_result_set(result_store: ResultEngineStore, *, season: int, week: int, games: list[tuple[str, str, str]]) -> None:
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
            source_event_id=f"evt-{week}-{idx}",
            away_score=17 + idx,
            home_score=24 + idx,
        )
        for idx, (away, home, kickoff) in enumerate(games)
    ]
    out = freeze_week_result_set(
        store=result_store,
        season=season,
        week=week,
        expected_events=expected,
        accepted_results=accepted,
    )
    assert out["status"] == "FROZEN"


def test_a_valid_week_n_plus_one_generation_publication(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(
        power_store,
        season=2026,
        through_week=2,
        snapshot_id="power-2026-wk2",
        lineage_id="ln-2026-wk2",
    )
    _write_valid_week3_schedule(tmp_path)

    out = _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)

    assert out["status"] == "APPLIED"
    assert out["artifact"]["season"] == 2026
    assert out["artifact"]["week"] == 3
    assert out["artifact"]["projected_game_count"] == out["artifact"]["expected_game_count"]


def test_b_missing_active_power_snapshot(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _write_valid_week3_schedule(tmp_path)

    with pytest.raises(ValueError):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)


def test_c_wrong_power_season(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2025, through_week=2, snapshot_id="power-2025-wk2", lineage_id="ln-2025-wk2")
    _write_valid_week3_schedule(tmp_path)

    with pytest.raises(ValueError):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)


def test_d_power_through_week_mismatch(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=1, snapshot_id="power-2026-wk1", lineage_id="ln-2026-wk1")
    _write_valid_week3_schedule(tmp_path)

    with pytest.raises(ValueError, match="TARGET_WEEK_NOT_NEXT"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)


def test_e_target_week_not_n_plus_one(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    with pytest.raises(ValueError, match="TARGET_WEEK_NOT_NEXT"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=2)

    with pytest.raises(ValueError, match="TARGET_WEEK_NOT_NEXT"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=4)


def test_f_missing_canonical_schedule(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")

    with pytest.raises(ValueError, match="CANONICAL_SCHEDULE_MISSING"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)


def test_g_duplicate_canonical_event(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    rows = _read_schedule_source_rows(tmp_path)
    duplicate = dict(rows[0])
    duplicate["game_id"] = "2026_03_DUP_ATL_GB"
    rows.append(duplicate)
    _rewrite_schedule_source_rows(tmp_path, rows)

    with pytest.raises(ValueError, match="SCHEDULE_DUPLICATE_CANONICAL_EVENT_KEY"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)


def test_h_missing_canonical_event(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    original = publication_module.generate_projection_rows

    def _missing_one(**kwargs):
        rows = original(**kwargs)
        return rows[:1]

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(publication_module, "generate_projection_rows", _missing_one)

    try:
        with pytest.raises(ValueError, match="PROJECTION_VALIDATION_FAILED"):
            _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)
    finally:
        monkeypatch.undo()


def test_i_unexpected_projected_event(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    original = publication_module.generate_projection_rows

    def _extra_row(**kwargs):
        rows = original(**kwargs)
        extra = dict(rows[0])
        extra["api_event_id"] = "2026_3_EXTRA_EVENT"
        extra["away_team"] = "KC"
        extra["home_team"] = "LAR"
        extra["commence_time"] = "2026-09-28T01:20:00+00:00"
        rows.append(extra)
        return rows

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(publication_module, "generate_projection_rows", _extra_row)

    try:
        with pytest.raises(ValueError, match="PROJECTION_VALIDATION_FAILED"):
            _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)
    finally:
        monkeypatch.undo()


def test_j_unknown_team(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    rows = _read_schedule_source_rows(tmp_path)
    rows[0]["away_team"] = "XYZ"
    _rewrite_schedule_source_rows(tmp_path, rows)

    with pytest.raises(ValueError):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)


def test_k_duplicate_projected_event(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    original = publication_module.generate_projection_rows

    def _duplicate_row(**kwargs):
        rows = original(**kwargs)
        rows[1]["api_event_id"] = rows[0]["api_event_id"]
        return rows

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(publication_module, "generate_projection_rows", _duplicate_row)

    try:
        with pytest.raises(ValueError, match="PROJECTION_VALIDATION_FAILED"):
            _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)
    finally:
        monkeypatch.undo()


def test_l_team_event_identity_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    original = publication_module.generate_projection_rows

    def _bad_generate(**kwargs):
        rows = original(**kwargs)
        rows[0]["home_team"] = "BUF"
        return rows

    monkeypatch.setattr(publication_module, "generate_projection_rows", _bad_generate)

    with pytest.raises(ValueError, match="PROJECTION_VALIDATION_FAILED"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)


def test_m_kickoff_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    original = publication_module.generate_projection_rows

    def _bad_generate(**kwargs):
        rows = original(**kwargs)
        rows[0]["commence_time"] = "2026-09-26T00:20:00+00:00"
        return rows

    monkeypatch.setattr(publication_module, "generate_projection_rows", _bad_generate)

    with pytest.raises(ValueError, match="PROJECTION_VALIDATION_FAILED"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)


def test_n_invalid_non_finite_model_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    original = publication_module.generate_projection_rows

    def _bad_generate(**kwargs):
        rows = original(**kwargs)
        rows[0]["model_margin_home"] = float("nan")
        return rows

    monkeypatch.setattr(publication_module, "generate_projection_rows", _bad_generate)

    with pytest.raises(ValueError, match="model_margin_home"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)


def test_o_invalid_probability_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    original = publication_module.generate_projection_rows

    def _bad_generate(**kwargs):
        rows = original(**kwargs)
        rows[0]["home_win_probability"] = 2.0
        return rows

    monkeypatch.setattr(publication_module, "generate_projection_rows", _bad_generate)

    with pytest.raises(ValueError, match="PROBABILITY_FIELD_INVALID"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)


def test_p_deterministic_identical_artifact(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    power_a = _power_store(a)
    power_b = _power_store(b)
    _seed_active_lineage(power_a, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _seed_active_lineage(power_b, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(a)
    _write_valid_week3_schedule(b)

    out_a = _publish(tmp_path=a, power_store=power_a, season=2026, target_week=3)
    out_b = _publish(tmp_path=b, power_store=power_b, season=2026, target_week=3)

    assert out_a["artifact"]["artifact_id"] == out_b["artifact"]["artifact_id"]
    assert out_a["artifact"]["artifact_hash"] == out_b["artifact"]["artifact_hash"]
    assert out_a["artifact"]["idempotency_key"] == out_b["artifact"]["idempotency_key"]


def test_q_timestamps_do_not_affect_artifact_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    a = tmp_path / "a"
    b = tmp_path / "b"
    power_a = _power_store(a)
    power_b = _power_store(b)
    _seed_active_lineage(power_a, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _seed_active_lineage(power_b, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(a)
    _write_valid_week3_schedule(b)

    monkeypatch.setattr(publication_module, "_utc_now_iso", lambda: "2026-09-24T10:00:00Z")
    out_a = _publish(tmp_path=a, power_store=power_a, season=2026, target_week=3)
    monkeypatch.setattr(publication_module, "_utc_now_iso", lambda: "2026-09-24T11:00:00Z")
    out_b = _publish(tmp_path=b, power_store=power_b, season=2026, target_week=3)

    assert out_a["artifact"]["artifact_id"] == out_b["artifact"]["artifact_id"]
    assert out_a["artifact"]["artifact_hash"] == out_b["artifact"]["artifact_hash"]
    assert out_a["artifact"]["generated_at"] != out_b["artifact"]["generated_at"]


def test_r_exact_replay_already_active(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    first = _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)
    second = _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)

    assert first["status"] == "APPLIED"
    assert second["status"] == "ALREADY_ACTIVE"
    assert first["artifact"]["artifact_id"] == second["artifact"]["artifact_id"]


def test_s_conflicting_power_snapshot(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2-a", lineage_id="ln-2026-wk2-a")
    _write_valid_week3_schedule(tmp_path)
    _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)

    newer = power_store.persist_snapshot(_snapshot(season=2026, through_week=2, snapshot_id="power-2026-wk2-b", power_shift=1.0))
    lineage = PowerLineageRecord(
        lineage_id="ln-2026-wk2-b",
        parent_lineage_id="ln-2026-wk2-a",
        root_snapshot_id=newer.snapshot_id,
        active_snapshot_id=newer.snapshot_id,
        season=2026,
        through_week=2,
        status="ACTIVE",
        created_at="2026-09-20T00:00:00Z",
        superseded_at=None,
        superseded_by=None,
    )
    power_store.create_lineage(lineage, set_active=True)

    with pytest.raises(ValueError, match="POWER_SNAPSHOT_CONFLICT"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)


def test_t_conflicting_schedule_hash(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)
    _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)

    conflict_root = tmp_path / "conflict"
    conflict_store = _schedule_store(conflict_root)
    _write_valid_week3_schedule(conflict_root)
    rows = _read_schedule_source_rows(conflict_root)
    rows[0]["gametime"] = "21:20"
    _rewrite_schedule_source_rows(conflict_root, rows)
    materialize_canonical_weekly_schedule(
        season=2026,
        week=3,
        store=conflict_store,
        duckdb_path=_schedule_duckdb_path(conflict_root),
    )

    with pytest.raises(ValueError, match="SCHEDULE_HASH_CONFLICT"):
        publish_weekly_projections(
            season=2026,
            target_week=3,
            power_store=power_store,
            schedule_store=conflict_store,
        )


def test_u_conflicting_model_version(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)
    _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3, model_version="model-v1")

    with pytest.raises(ValueError, match="MODEL_VERSION_CONFLICT"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3, model_version="model-v2")


def test_v_conflicting_probability_version(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)
    _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3, probability_version="prob-v1")

    with pytest.raises(ValueError, match="PROBABILITY_VERSION_CONFLICT"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3, probability_version="prob-v2")


def test_w_candidate_persistence_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    monkeypatch.setattr(publication_module, "_persist_projection_artifact", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("candidate fail")))

    with pytest.raises(OSError, match="candidate fail"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)


def test_x_validation_persistence_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    monkeypatch.setattr(publication_module, "_persist_projection_validation", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("validation fail")))

    with pytest.raises(OSError, match="validation fail"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)

    obs = active_projection_observability(power_store=power_store, season=2026, week=3)
    assert obs["artifactId"] is None


def test_y_active_pointer_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    monkeypatch.setattr(publication_module, "_persist_active_projection_pointer", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("pointer fail")))

    with pytest.raises(OSError, match="pointer fail"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)

    obs = active_projection_observability(power_store=power_store, season=2026, week=3)
    assert obs["artifactId"] is None


def test_z_previous_active_remains_authoritative_after_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    first = _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)
    active_before = active_projection_observability(power_store=power_store, season=2026, week=3)

    week3_snapshot = power_store.persist_snapshot(
        _snapshot(season=2026, through_week=3, snapshot_id="power-2026-wk3")
    )
    week3_lineage = PowerLineageRecord(
        lineage_id="ln-2026-wk3",
        parent_lineage_id="ln-2026-wk2",
        root_snapshot_id=week3_snapshot.snapshot_id,
        active_snapshot_id=week3_snapshot.snapshot_id,
        season=2026,
        through_week=3,
        status="ACTIVE",
        created_at="2026-09-30T00:00:00Z",
        superseded_at=None,
        superseded_by=None,
    )
    power_store.create_lineage(week3_lineage, set_active=True)
    _write_valid_week3_schedule(tmp_path, week=4)

    monkeypatch.setattr(publication_module, "_persist_active_projection_pointer", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("pointer fail")))

    with pytest.raises(OSError, match="pointer fail"):
        _publish(
            tmp_path=tmp_path,
            power_store=power_store,
            season=2026,
            target_week=4,
            model_version="model-v-next",
        )

    active_after = active_projection_observability(power_store=power_store, season=2026, week=3)
    assert active_after["artifactId"] == active_before["artifactId"]
    assert active_after["artifactHash"] == active_before["artifactHash"]
    assert first["artifact"]["artifact_id"] == active_after["artifactId"]


def test_aa_restart_after_successful_publication(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    first = _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)
    fresh_store = PowerEngineStore(root_dir=power_store.root_dir)
    second = _publish(tmp_path=tmp_path, power_store=fresh_store, season=2026, target_week=3)

    assert first["status"] == "APPLIED"
    assert second["status"] == "ALREADY_ACTIVE"
    assert first["artifact"]["artifact_id"] == second["artifact"]["artifact_id"]


def test_ab_restart_after_interrupted_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    calls = {"count": 0}
    original = publication_module._persist_active_projection_pointer

    def _fail_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("interrupted")
        return original(*args, **kwargs)

    monkeypatch.setattr(publication_module, "_persist_active_projection_pointer", _fail_once)

    with pytest.raises(OSError, match="interrupted"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)

    fresh_store = PowerEngineStore(root_dir=power_store.root_dir)
    out = _publish(tmp_path=tmp_path, power_store=fresh_store, season=2026, target_week=3)

    assert out["status"] in {"APPLIED", "ALREADY_ACTIVE"}
    assert len(list_projection_artifacts(power_store=fresh_store, season=2026, week=3)) == 1


def test_ac_one_projection_per_canonical_matchup(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    out = _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)
    event_ids = [row["event_id"] for row in out["artifact"]["projection_rows"]]

    assert len(event_ids) == len(set(event_ids))
    assert len(event_ids) == out["artifact"]["expected_game_count"]


def test_ad_exact_canonical_coverage(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    out = _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)

    schedule_rows = _read_schedule_source_rows(tmp_path)
    expected_event_ids = {str(row["game_id"]) for row in schedule_rows}
    produced_event_ids = {str(row["event_id"]) for row in out["artifact"]["projection_rows"]}
    assert produced_event_ids == expected_event_ids


def test_ai_publication_succeeds_without_legacy_csv(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)
    projection_path = _projection_path(tmp_path)
    projection_path.unlink()

    out = _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)

    assert out["status"] == "APPLIED"


def test_aj_conflicting_legacy_csv_has_zero_effect(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    power_a = _power_store(a)
    power_b = _power_store(b)
    _seed_active_lineage(power_a, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _seed_active_lineage(power_b, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(a)
    _write_valid_week3_schedule(b)
    _projection_path(a).unlink()
    _write_conflicting_legacy_projection_csv(b)

    out_a = _publish(tmp_path=a, power_store=power_a, season=2026, target_week=3)
    out_b = _publish(tmp_path=b, power_store=power_b, season=2026, target_week=3)

    assert out_a["artifact"]["schedule_hash"] == out_b["artifact"]["schedule_hash"]
    assert out_a["artifact"]["artifact_id"] == out_b["artifact"]["artifact_id"]
    assert out_a["artifact"]["coverage_hash"] == out_b["artifact"]["coverage_hash"]
    assert out_a["artifact"]["projection_rows"] == out_b["artifact"]["projection_rows"]


def test_ac_legacy_csv_deletion_or_change_does_not_change_output(tmp_path: Path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    power_left = _power_store(left)
    power_right = _power_store(right)
    _seed_active_lineage(power_left, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _seed_active_lineage(power_right, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(left)
    _write_valid_week3_schedule(right)
    _projection_path(left).unlink()
    _write_conflicting_legacy_projection_csv(right)

    out_left = _publish(tmp_path=left, power_store=power_left, season=2026, target_week=3)
    out_right = _publish(tmp_path=right, power_store=power_right, season=2026, target_week=3)

    assert out_left["artifact"]["artifact_id"] == out_right["artifact"]["artifact_id"]
    assert out_left["artifact"]["coverage_hash"] == out_right["artifact"]["coverage_hash"]
    assert out_left["artifact"]["projection_rows"] == out_right["artifact"]["projection_rows"]


def test_ak_missing_canonical_schedule_fails_even_if_legacy_exists(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_conflicting_legacy_projection_csv(tmp_path)

    with pytest.raises(ValueError, match="CANONICAL_SCHEDULE_MISSING"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)


def test_al_canonical_schedule_event_ids_are_preserved(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    out = _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)
    expected_ids = {str(row["game_id"]) for row in _read_schedule_source_rows(tmp_path)}
    produced_ids = {str(row["event_id"]) for row in out["artifact"]["projection_rows"]}

    assert produced_ids == expected_ids


def test_am_schedule_row_reordering_does_not_change_schedule_hash(tmp_path: Path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    power_left = _power_store(left)
    power_right = _power_store(right)
    _seed_active_lineage(power_left, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _seed_active_lineage(power_right, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(left)
    _write_valid_week3_schedule(right)

    reordered = list(reversed(_read_schedule_source_rows(right)))
    _rewrite_schedule_source_rows(right, reordered)

    out_left = _publish(tmp_path=left, power_store=power_left, season=2026, target_week=3)
    out_right = _publish(tmp_path=right, power_store=power_right, season=2026, target_week=3)

    assert out_left["artifact"]["schedule_hash"] == out_right["artifact"]["schedule_hash"]


def test_an_irrelevant_schedule_metadata_does_not_change_identity(tmp_path: Path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    power_left = _power_store(left)
    power_right = _power_store(right)
    _seed_active_lineage(power_left, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _seed_active_lineage(power_right, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(left)
    _write_valid_week3_schedule(right)

    out_left = _publish(tmp_path=left, power_store=power_left, season=2026, target_week=3)
    out_right = _publish(tmp_path=right, power_store=power_right, season=2026, target_week=3)

    assert out_left["artifact"]["schedule_hash"] == out_right["artifact"]["schedule_hash"]
    assert out_left["artifact"]["artifact_id"] == out_right["artifact"]["artifact_id"]


def test_ae_all_games_use_same_authoritative_power_snapshot(tmp_path: Path):
    power_store = _power_store(tmp_path)
    source_snapshot = _seed_active_lineage(
        power_store,
        season=2026,
        through_week=2,
        snapshot_id="power-2026-wk2",
        lineage_id="ln-2026-wk2",
    )
    _write_valid_week3_schedule(tmp_path)

    out = _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)
    source_lookup = {team.team_id: float(team.power) for team in source_snapshot.teams}

    for row in out["artifact"]["projection_rows"]:
        assert row["away_power"] == pytest.approx(source_lookup[row["away_team"]])
        assert row["home_power"] == pytest.approx(source_lookup[row["home_team"]])


def test_af_source_result_power_lineage_carried_into_artifact(tmp_path: Path):
    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(
        power_store,
        season=2026,
        through_week=0,
        snapshot_id="power-root-2026",
        lineage_id="ln-2026-root",
    )
    _freeze_week_result_set(result_store, season=2026, week=1, games=[("ARI", "ATL", "2026-09-11T00:20:00Z")])
    _freeze_week_result_set(result_store, season=2026, week=2, games=[("BAL", "BUF", "2026-09-18T00:20:00Z")])
    t1 = apply_frozen_weekly_power_transition(season=2026, week=1, power_store=power_store, result_store=result_store)
    t2 = apply_frozen_weekly_power_transition(season=2026, week=2, power_store=power_store, result_store=result_store)
    _write_valid_week3_schedule(tmp_path)

    out = _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)

    assert out["artifact"]["source_result_set_version"] == t2["transition"]["result_set_version"]
    assert out["artifact"]["source_result_set_hash"] == t2["transition"]["result_set_hash"]
    assert out["artifact"]["source_power_transition_id"] == t2["transition"]["transition_id"]


def test_ag_active_pointer_readback_verifies_identity(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    out = _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)
    obs = active_projection_observability(power_store=power_store, season=2026, week=3)

    assert out["active"]["artifact_id"] == out["artifact"]["artifact_id"]
    assert out["active"]["artifact_hash"] == out["artifact"]["artifact_hash"]
    assert obs["artifactId"] == out["artifact"]["artifact_id"]
    assert obs["artifactHash"] == out["artifact"]["artifact_hash"]


def test_ah_stale_older_power_cannot_publish_newer_target_week(tmp_path: Path):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=1, snapshot_id="power-2026-wk1", lineage_id="ln-2026-wk1")
    _write_valid_week3_schedule(tmp_path)

    with pytest.raises(ValueError, match="TARGET_WEEK_NOT_NEXT"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)


def test_aii_direct_publication_requires_preexisting_schedule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    schedule_store = _schedule_store(tmp_path)
    artifact_dir = power_store.root_dir / "projections" / "artifacts"
    active_path = power_store.root_dir / "projections" / "active" / "active-2026-3.json"

    monkeypatch.setattr(schedule_module.duckdb, "connect", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("duckdb should not be read by publication")))

    with pytest.raises(ValueError, match="CANONICAL_SCHEDULE_MISSING"):
        publish_weekly_projections(
            season=2026,
            target_week=3,
            power_store=power_store,
            schedule_store=schedule_store,
        )

    assert not artifact_dir.exists() or not list(artifact_dir.glob("*.json"))
    assert not active_path.exists()

    monkeypatch.undo()
    materialize_canonical_weekly_schedule(season=2026, week=3, store=schedule_store, duckdb_path=_schedule_duckdb_path(tmp_path))
    out = publish_weekly_projections(season=2026, target_week=3, power_store=power_store, schedule_store=schedule_store)
    assert out["status"] == "APPLIED"


def test_ajj_concurrent_identical_projection_publication(tmp_path: Path):
    _write_valid_week3_schedule(tmp_path)
    materialize_canonical_weekly_schedule(season=2026, week=3, store=_schedule_store(tmp_path), duckdb_path=_schedule_duckdb_path(tmp_path))

    power_root = tmp_path / "power-root"
    _seed_active_lineage(PowerEngineStore(root_dir=power_root), season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    barrier = threading.Barrier(2)

    def _run() -> tuple[str, str, str]:
        barrier.wait()
        out = publish_weekly_projections(
            season=2026,
            target_week=3,
            power_store=PowerEngineStore(root_dir=power_root),
            schedule_store=_schedule_store(tmp_path),
        )
        return out["status"], out["artifact"]["artifact_id"], out["artifact"]["artifact_hash"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: _run(), range(2)))

    statuses = sorted(item[0] for item in results)
    artifact_ids = {item[1] for item in results}
    artifact_hashes = {item[2] for item in results}
    fresh = PowerEngineStore(root_dir=power_root)
    obs = active_projection_observability(power_store=fresh, season=2026, week=3)

    assert statuses == ["ALREADY_ACTIVE", "APPLIED"]
    assert len(artifact_ids) == 1
    assert len(artifact_hashes) == 1
    assert obs["artifactId"] in artifact_ids
    assert obs["artifactHash"] in artifact_hashes


def test_akk_concurrent_conflicting_projection_publication(tmp_path: Path):
    _write_valid_week3_schedule(tmp_path)
    materialize_canonical_weekly_schedule(season=2026, week=3, store=_schedule_store(tmp_path), duckdb_path=_schedule_duckdb_path(tmp_path))

    power_root = tmp_path / "power-root"
    _seed_active_lineage(PowerEngineStore(root_dir=power_root), season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    barrier = threading.Barrier(2)

    def _run(model_version: str) -> tuple[str, str]:
        barrier.wait()
        try:
            out = publish_weekly_projections(
                season=2026,
                target_week=3,
                power_store=PowerEngineStore(root_dir=power_root),
                schedule_store=_schedule_store(tmp_path),
                model_version=model_version,
            )
            return out["status"], out["artifact"]["artifact_id"]
        except Exception as exc:  # pragma: no cover - asserted below
            return "ERROR", str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        left, right = list(executor.map(_run, ["model-v1", "model-v2"]))

    results = [left, right]
    successes = [item for item in results if item[0] == "APPLIED"]
    conflicts = [item for item in results if item[0] == "ERROR"]
    fresh = PowerEngineStore(root_dir=power_root)
    obs = active_projection_observability(power_store=fresh, season=2026, week=3)

    assert len(successes) == 1
    assert len(conflicts) == 1
    assert "MODEL_VERSION_CONFLICT" in conflicts[0][1]
    assert obs["artifactId"] == successes[0][1]


def test_all_rollout_failure_after_pointer_write_preserves_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)

    _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=3)
    week3_snapshot = power_store.persist_snapshot(_snapshot(season=2026, through_week=3, snapshot_id="power-2026-wk3"))
    power_store.create_lineage(
        PowerLineageRecord(
            lineage_id="ln-2026-wk3",
            parent_lineage_id="ln-2026-wk2",
            root_snapshot_id=week3_snapshot.snapshot_id,
            active_snapshot_id=week3_snapshot.snapshot_id,
            season=2026,
            through_week=3,
            status="ACTIVE",
            created_at="2026-09-30T00:00:00Z",
            superseded_at=None,
            superseded_by=None,
        ),
        set_active=True,
    )

    _write_valid_week3_schedule(tmp_path, week=4)

    materialize_canonical_weekly_schedule(season=2026, week=4, store=_schedule_store(tmp_path), duckdb_path=_schedule_duckdb_path(tmp_path))

    original_persist = publication_module._persist_active_projection_pointer

    def _write_then_fail(*args, **kwargs):
        original_persist(*args, **kwargs)
        raise OSError("pointer fail after write")

    monkeypatch.setattr(publication_module, "_persist_active_projection_pointer", _write_then_fail)
    monkeypatch.setattr(publication_module, "_delete_active_projection_pointer", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("rollback delete fail")))

    with pytest.raises(OSError, match="rollback delete fail"):
        _publish(tmp_path=tmp_path, power_store=power_store, season=2026, target_week=4)

    fresh = PowerEngineStore(root_dir=power_store.root_dir)
    obs = active_projection_observability(power_store=fresh, season=2026, week=4)
    assert obs["artifactId"] is not None
    assert obs["validationStatus"] == "VALID"


def test_amm_crash_after_replace_restart_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    power_store = _power_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _write_valid_week3_schedule(tmp_path)
    materialize_canonical_weekly_schedule(season=2026, week=3, store=_schedule_store(tmp_path), duckdb_path=_schedule_duckdb_path(tmp_path))

    original_persist = publication_module._persist_active_projection_pointer

    def _write_then_crash(*args, **kwargs):
        original_persist(*args, **kwargs)
        raise KeyboardInterrupt("crash-after-replace")

    monkeypatch.setattr(publication_module, "_persist_active_projection_pointer", _write_then_crash)

    with pytest.raises(KeyboardInterrupt, match="crash-after-replace"):
        publish_weekly_projections(
            season=2026,
            target_week=3,
            power_store=power_store,
            schedule_store=_schedule_store(tmp_path),
        )

    fresh = PowerEngineStore(root_dir=power_store.root_dir)
    obs = active_projection_observability(power_store=fresh, season=2026, week=3)
    replay = publish_weekly_projections(
        season=2026,
        target_week=3,
        power_store=fresh,
        schedule_store=_schedule_store(tmp_path),
    )

    assert obs["artifactId"] is not None
    assert obs["validationStatus"] == "VALID"
    assert replay["status"] == "ALREADY_ACTIVE"
