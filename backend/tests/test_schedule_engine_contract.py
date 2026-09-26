from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import duckdb
import pytest

import app.services.schedule_engine.service as schedule_module
from app.services.result_engine import build_canonical_event_identity
from app.services.schedule_engine import (
    ScheduleEngineError,
    ScheduleEngineStore,
    load_canonical_weekly_schedule,
    materialize_canonical_weekly_schedule,
)


def _store(tmp_path: Path, name: str = "schedule-store") -> ScheduleEngineStore:
    return ScheduleEngineStore(root_dir=tmp_path / name)


def _duckdb_path(tmp_path: Path, name: str = "schedule-source.duckdb") -> Path:
    return tmp_path / name


def _write_source_rows(path: Path, rows: list[dict]) -> None:
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


def _week3_rows() -> list[dict]:
    return [
        {"game_id": "2026_03_ATL_GB", "season": 2026, "week": 3, "gameday": "2026-09-24", "gametime": "20:15", "away_team": "ATL", "home_team": "GB"},
        {"game_id": "2026_03_KC_MIA", "season": 2026, "week": 3, "gameday": "2026-09-27", "gametime": "13:00", "away_team": "KC", "home_team": "MIA"},
        {"game_id": "2026_03_ARI_SF", "season": 2026, "week": 3, "gameday": "2026-09-27", "gametime": "16:05", "away_team": "ARI", "home_team": "SF"},
        {"game_id": "2026_03_LA_DEN", "season": 2026, "week": 3, "gameday": "2026-09-27", "gametime": "20:20", "away_team": "LA", "home_team": "DEN"},
        {"game_id": "2026_03_PHI_CHI", "season": 2026, "week": 3, "gameday": "2026-09-28", "gametime": "20:15", "away_team": "PHI", "home_team": "CHI"},
    ]


def _materialize(tmp_path: Path, rows: list[dict] | None = None, *, season: int = 2026, week: int = 3, store_name: str = "schedule-store", db_name: str = "schedule-source.duckdb") -> dict:
    source_rows = list(rows or _week3_rows())
    db_path = _duckdb_path(tmp_path, db_name)
    _write_source_rows(db_path, source_rows)
    return materialize_canonical_weekly_schedule(
        season=season,
        week=week,
        store=_store(tmp_path, store_name),
        duckdb_path=db_path,
    )


def test_a_deterministic_schedule_identity(tmp_path: Path):
    left = _materialize(tmp_path / "left")
    right = _materialize(tmp_path / "right")

    assert left["schedule"]["schedule_hash"] == right["schedule"]["schedule_hash"]
    assert left["schedule"]["schedule_version"] == right["schedule"]["schedule_version"]


def test_b_row_order_independence(tmp_path: Path):
    normal = _materialize(tmp_path / "normal")
    reversed_rows = list(reversed(_week3_rows()))
    reversed_out = _materialize(tmp_path / "reversed", rows=reversed_rows)

    assert normal["schedule"]["schedule_hash"] == reversed_out["schedule"]["schedule_hash"]


def test_c_generated_timestamp_independence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(schedule_module, "_utc_now_iso", lambda: "2026-09-24T10:00:00Z")
    left = _materialize(tmp_path / "left")
    monkeypatch.setattr(schedule_module, "_utc_now_iso", lambda: "2026-09-24T11:00:00Z")
    right = _materialize(tmp_path / "right")

    assert left["schedule"]["schedule_hash"] == right["schedule"]["schedule_hash"]
    assert left["schedule"]["generated_at"] != right["schedule"]["generated_at"]


def test_d_exact_replay_idempotency(tmp_path: Path):
    first = _materialize(tmp_path)
    second = materialize_canonical_weekly_schedule(
        season=2026,
        week=3,
        store=_store(tmp_path),
        duckdb_path=_duckdb_path(tmp_path),
    )

    assert first["status"] == "MATERIALIZED"
    assert second["status"] == "ALREADY_MATERIALIZED"
    assert first["schedule"]["schedule_hash"] == second["schedule"]["schedule_hash"]


def test_e_conflicting_replay_fails_closed(tmp_path: Path):
    _materialize(tmp_path)
    rows = _week3_rows()
    rows[0]["gametime"] = "20:25"
    _write_source_rows(_duckdb_path(tmp_path), rows)

    with pytest.raises(ValueError, match="SCHEDULE_CONFLICT"):
        materialize_canonical_weekly_schedule(season=2026, week=3, store=_store(tmp_path), duckdb_path=_duckdb_path(tmp_path))


def test_f_duplicate_source_event_rejection(tmp_path: Path):
    rows = _week3_rows()
    rows[1]["game_id"] = rows[0]["game_id"]

    with pytest.raises(ValueError, match="SCHEDULE_DUPLICATE_SOURCE_EVENT_ID"):
        _materialize(tmp_path, rows=rows)


def test_g_duplicate_canonical_identity_rejection(tmp_path: Path):
    rows = _week3_rows()
    rows[1]["gameday"] = rows[0]["gameday"]
    rows[1]["gametime"] = rows[0]["gametime"]
    rows[1]["away_team"] = rows[0]["away_team"]
    rows[1]["home_team"] = rows[0]["home_team"]

    with pytest.raises(ValueError, match="SCHEDULE_DUPLICATE_CANONICAL_EVENT_KEY"):
        _materialize(tmp_path, rows=rows)


def test_h_duplicate_team_rejection(tmp_path: Path):
    rows = _week3_rows()
    rows[1]["away_team"] = "ATL"

    with pytest.raises(ValueError, match="SCHEDULE_DUPLICATE_TEAM"):
        _materialize(tmp_path, rows=rows)


def test_i_unknown_team_rejection(tmp_path: Path):
    rows = _week3_rows()
    rows[0]["away_team"] = "XYZ"

    with pytest.raises(ValueError):
        _materialize(tmp_path, rows=rows)


def test_j_malformed_gameday_rejection(tmp_path: Path):
    rows = _week3_rows()
    rows[0]["gameday"] = "2026/09/24"

    with pytest.raises(ValueError, match="SCHEDULE_GAMEDAY_INVALID"):
        _materialize(tmp_path, rows=rows)


def test_k_malformed_gametime_rejection(tmp_path: Path):
    rows = _week3_rows()
    rows[0]["gametime"] = "8:15 PM"

    with pytest.raises(ValueError, match="SCHEDULE_GAMETIME_INVALID"):
        _materialize(tmp_path, rows=rows)


def test_l_edt_conversion(tmp_path: Path):
    out = _materialize(tmp_path, rows=[{"game_id": "2026_03_ATL_GB", "season": 2026, "week": 3, "gameday": "2026-09-24", "gametime": "20:15", "away_team": "ATL", "home_team": "GB"}], week=3)
    event = out["schedule"]["events"][0]
    assert event["kickoff_utc"] == "2026-09-25T00:15:00Z"


def test_m_est_conversion(tmp_path: Path):
    out = _materialize(tmp_path, rows=[{"game_id": "2026_14_ATL_GB", "season": 2026, "week": 14, "gameday": "2026-12-03", "gametime": "20:15", "away_team": "ATL", "home_team": "GB"}], season=2026, week=14)
    event = out["schedule"]["events"][0]
    assert event["kickoff_utc"] == "2026-12-04T01:15:00Z"


def test_n_canonical_identity_compatibility_with_result_engine(tmp_path: Path):
    out = _materialize(tmp_path)
    event = out["schedule"]["events"][0]
    identity = build_canonical_event_identity(
        season=event["season"],
        week=event["week"],
        kickoff_utc=event["kickoff_utc"],
        away_team=event["away_team"],
        home_team=event["home_team"],
    )
    assert identity.canonical_event_key == event["canonical_event_key"]


def test_o_no_stadium_timezone_dependency(tmp_path: Path):
    rows = [
        {"game_id": "2026_03_SEA_WAS", "season": 2026, "week": 3, "gameday": "2026-09-27", "gametime": "13:00", "away_team": "SEA", "home_team": "WAS"},
        {"game_id": "2026_03_KC_MIA", "season": 2026, "week": 3, "gameday": "2026-09-27", "gametime": "13:00", "away_team": "KC", "home_team": "MIA"},
    ]
    out = _materialize(tmp_path, rows=rows)
    kickoffs = {event["source_event_id"]: event["kickoff_utc"] for event in out["schedule"]["events"]}
    assert kickoffs["2026_03_SEA_WAS"] == "2026-09-27T17:00:00Z"
    assert kickoffs["2026_03_KC_MIA"] == "2026-09-27T17:00:00Z"


def test_p_no_market_odds_dependency(tmp_path: Path):
    out = _materialize(tmp_path)
    assert out["status"] == "MATERIALIZED"


def test_q_no_current_game_projections_dependency(tmp_path: Path):
    (tmp_path / "current_game_projections.csv").write_text("api_event_id,away_team,home_team\nwrong,AAA,BBB\n", encoding="utf-8")
    out = _materialize(tmp_path)
    assert out["status"] == "MATERIALIZED"


def test_r_atomic_persistence(tmp_path: Path):
    out = _materialize(tmp_path)
    loaded = load_canonical_weekly_schedule(season=2026, week=3, store=_store(tmp_path))
    assert loaded is not None
    assert loaded.schedule_hash == out["schedule"]["schedule_hash"]


def test_s_failure_before_replace_leaves_no_partial_authoritative_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rows = _week3_rows()
    _write_source_rows(_duckdb_path(tmp_path), rows)
    monkeypatch.setattr(schedule_module, "_atomic_write_text", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("boom")))

    with pytest.raises(OSError, match="boom"):
        materialize_canonical_weekly_schedule(season=2026, week=3, store=_store(tmp_path), duckdb_path=_duckdb_path(tmp_path))

    assert load_canonical_weekly_schedule(season=2026, week=3, store=_store(tmp_path)) is None


def test_t_failure_preserves_existing_authoritative_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    first = _materialize(tmp_path)
    rows = _week3_rows()
    rows[0]["gametime"] = "20:25"
    _write_source_rows(_duckdb_path(tmp_path), rows)
    monkeypatch.setattr(schedule_module, "_atomic_write_text", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("boom")))

    with pytest.raises(ValueError, match="SCHEDULE_CONFLICT"):
        materialize_canonical_weekly_schedule(season=2026, week=3, store=_store(tmp_path), duckdb_path=_duckdb_path(tmp_path))

    loaded = load_canonical_weekly_schedule(season=2026, week=3, store=_store(tmp_path))
    assert loaded is not None
    assert loaded.schedule_hash == first["schedule"]["schedule_hash"]


def test_u_restart_safe_exact_replay(tmp_path: Path):
    first = _materialize(tmp_path)
    fresh_store = _store(tmp_path)
    second = materialize_canonical_weekly_schedule(season=2026, week=3, store=fresh_store, duckdb_path=_duckdb_path(tmp_path))
    assert first["schedule"]["schedule_hash"] == second["schedule"]["schedule_hash"]
    assert second["status"] == "ALREADY_MATERIALIZED"


def test_v_missing_duckdb_fails_closed(tmp_path: Path):
    with pytest.raises(ValueError, match="SCHEDULE_SOURCE_MISSING"):
        materialize_canonical_weekly_schedule(
            season=2026,
            week=3,
            store=_store(tmp_path),
            duckdb_path=_duckdb_path(tmp_path, "missing.duckdb"),
        )

    assert load_canonical_weekly_schedule(season=2026, week=3, store=_store(tmp_path)) is None


def test_w_missing_schedules_table_fails_closed(tmp_path: Path):
    db_path = _duckdb_path(tmp_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE not_schedules (id INTEGER)")
    con.close()

    with pytest.raises(ValueError, match="SCHEDULE_SOURCE_TABLE_MISSING"):
        materialize_canonical_weekly_schedule(season=2026, week=3, store=_store(tmp_path), duckdb_path=db_path)

    assert load_canonical_weekly_schedule(season=2026, week=3, store=_store(tmp_path)) is None


def test_x_empty_target_week_fails_closed(tmp_path: Path):
    rows = _week3_rows()
    _write_source_rows(_duckdb_path(tmp_path), rows)

    with pytest.raises(ValueError, match="SCHEDULE_SOURCE_WEEK_MISSING"):
        materialize_canonical_weekly_schedule(season=2026, week=4, store=_store(tmp_path), duckdb_path=_duckdb_path(tmp_path))

    assert load_canonical_weekly_schedule(season=2026, week=4, store=_store(tmp_path)) is None


def test_y_concurrent_identical_materialization(tmp_path: Path):
    _write_source_rows(_duckdb_path(tmp_path), _week3_rows())
    barrier = threading.Barrier(2)

    def _run() -> tuple[str, str]:
        barrier.wait()
        out = materialize_canonical_weekly_schedule(
            season=2026,
            week=3,
            store=_store(tmp_path),
            duckdb_path=_duckdb_path(tmp_path),
        )
        return out["status"], out["schedule"]["schedule_hash"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: _run(), range(2)))

    statuses = sorted(status for status, _ in results)
    hashes = {schedule_hash for _, schedule_hash in results}
    files = list((_store(tmp_path).root_dir / "weeks").glob("*.json"))
    fresh = load_canonical_weekly_schedule(season=2026, week=3, store=_store(tmp_path))

    assert statuses == ["ALREADY_MATERIALIZED", "MATERIALIZED"]
    assert len(hashes) == 1
    assert len(files) == 1
    assert fresh is not None
    assert fresh.schedule_hash in hashes


def test_z_concurrent_conflicting_materialization(tmp_path: Path):
    left_db = _duckdb_path(tmp_path, "left.duckdb")
    right_db = _duckdb_path(tmp_path, "right.duckdb")
    _write_source_rows(left_db, _week3_rows())
    conflict_rows = _week3_rows()
    conflict_rows[0]["gametime"] = "20:25"
    _write_source_rows(right_db, conflict_rows)
    barrier = threading.Barrier(2)

    def _run(db_path: Path) -> tuple[str, str]:
        barrier.wait()
        try:
            out = materialize_canonical_weekly_schedule(
                season=2026,
                week=3,
                store=_store(tmp_path),
                duckdb_path=db_path,
            )
            return out["status"], out["schedule"]["schedule_hash"]
        except Exception as exc:  # pragma: no cover - asserted below
            return "ERROR", str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        left_result, right_result = list(executor.map(_run, [left_db, right_db]))

    results = [left_result, right_result]
    successes = [item for item in results if item[0] == "MATERIALIZED"]
    conflicts = [item for item in results if item[0] == "ERROR"]
    files = list((_store(tmp_path).root_dir / "weeks").glob("*.json"))
    fresh = load_canonical_weekly_schedule(season=2026, week=3, store=_store(tmp_path))

    assert len(successes) == 1
    assert len(conflicts) == 1
    assert "SCHEDULE_CONFLICT" in conflicts[0][1]
    assert len(files) == 1
    assert fresh is not None
    assert fresh.schedule_hash == successes[0][1]