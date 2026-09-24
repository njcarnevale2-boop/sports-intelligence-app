from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.services.result_engine.freeze as freeze_module
from app.main import app
from app.services.result_engine import NormalizedResultStatus, ResultEngineStore, validate_week_completeness
from app.services.result_engine.freeze import (
    FrozenWeeklyResultSet,
    freeze_week_result_set,
    load_frozen_week_result_set,
)
from result_engine_test_utils import make_accepted_result, make_identity

client = TestClient(app)


@pytest.fixture
def result_store(tmp_path: Path) -> ResultEngineStore:
    return ResultEngineStore(root_dir=tmp_path / "result-engine-root")


def _expected_week_games() -> list:
    return [
        make_identity(away_team="NE", home_team="SEA", kickoff_utc="2026-09-10T00:15:00Z"),
        make_identity(away_team="ATL", home_team="TB", kickoff_utc="2026-09-11T00:15:00Z"),
    ]


def test_a_exact_complete_trusted_week_freezes(result_store: ResultEngineStore):
    expected = _expected_week_games()
    accepted = [
        make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1"),
        make_accepted_result(season=2026, week=1, away_team="ATL", home_team="TB", source_event_id="evt-2", kickoff_utc="2026-09-11T00:15:00Z"),
    ]
    for item in accepted:
        result_store.persist_accepted_result(item)

    frozen = freeze_week_result_set(
        store=result_store,
        season=2026,
        week=1,
        expected_events=expected,
        accepted_results=accepted,
    )

    assert frozen["status"] == "FROZEN"
    assert frozen["expectedGameCount"] == 2
    assert frozen["acceptedFinalCount"] == 2
    assert frozen["resultSetVersion"]
    assert frozen["resultSetHash"]
    assert frozen["frozenAt"]

    persisted = load_frozen_week_result_set(store=result_store, season=2026, week=1)
    assert persisted is not None
    assert persisted.result_set_hash == frozen["resultSetHash"]
    assert persisted.result_set_version == frozen["resultSetVersion"]


def test_b_identical_second_call_is_already_frozen(result_store: ResultEngineStore):
    expected = _expected_week_games()
    accepted = [
        make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1"),
        make_accepted_result(season=2026, week=1, away_team="ATL", home_team="TB", source_event_id="evt-2", kickoff_utc="2026-09-11T00:15:00Z"),
    ]
    for item in accepted:
        result_store.persist_accepted_result(item)

    first = freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted)
    second = freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted)

    assert first["status"] == "FROZEN"
    assert second["status"] == "ALREADY_FROZEN"
    assert second["resultSetVersion"] == first["resultSetVersion"]
    assert second["resultSetHash"] == first["resultSetHash"]


def test_c_missing_expected_game_is_not_ready(result_store: ResultEngineStore):
    expected = _expected_week_games()
    accepted = [make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1")]
    for item in accepted:
        result_store.persist_accepted_result(item)

    result = freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted)

    assert result["status"] == "NOT_READY"
    assert result["reason"] == "MISSING_EXPECTED_GAME"
    assert load_frozen_week_result_set(store=result_store, season=2026, week=1) is None


def test_d_duplicate_accepted_final_fails_closed(result_store: ResultEngineStore):
    expected = _expected_week_games()
    accepted = [
        make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1"),
        make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-2"),
    ]

    result = freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted)

    assert result["status"] == "NOT_READY"
    assert result["reason"] == "DUPLICATE_ACCEPTED_FINAL"
    assert load_frozen_week_result_set(store=result_store, season=2026, week=1) is None


def test_e_conflicting_accepted_finals_fail_closed(result_store: ResultEngineStore):
    expected = [make_identity(away_team="NE", home_team="SEA", kickoff_utc="2026-09-10T00:15:00Z")]
    accepted = [
        make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1", away_score=17, home_score=24),
        make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-2", away_score=21, home_score=27),
    ]

    result = freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted)

    assert result["status"] == "NOT_READY"
    assert result["reason"] == "CONFLICTING_ACCEPTED_FINAL"


def test_f_unexpected_extra_result_fails_closed(result_store: ResultEngineStore):
    expected = [make_identity(away_team="NE", home_team="SEA", kickoff_utc="2026-09-10T00:15:00Z")]
    accepted = [
        make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1"),
        make_accepted_result(season=2026, week=1, away_team="ATL", home_team="TB", source_event_id="evt-2"),
    ]
    for item in accepted:
        result_store.persist_accepted_result(item)

    result = freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted)

    assert result["status"] == "NOT_READY"
    assert result["reason"] == "UNEXPECTED_RESULT"


def test_g_nonfinal_result_fails_closed(result_store: ResultEngineStore):
    expected = [make_identity(away_team="NE", home_team="SEA", kickoff_utc="2026-09-10T00:15:00Z")]
    accepted = [make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1")]
    accepted = [accepted[0].__class__(**{**accepted[0].__dict__, "accepted_status": NormalizedResultStatus.SCHEDULED})]

    result = freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted)

    assert result["status"] == "NOT_READY"
    assert result["reason"] in {"NONFINAL_RESULT", "ACCEPTED_RESULT_VALIDATION_ERROR"}


def test_h_season_mismatch_fails_closed(result_store: ResultEngineStore):
    expected = [make_identity(season=2026, week=1, away_team="NE", home_team="SEA")]
    accepted = [make_accepted_result(season=2027, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1")]
    result = freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted)
    assert result["status"] == "NOT_READY"
    assert result["reason"] == "SEASON_MISMATCH"


def test_i_week_mismatch_fails_closed(result_store: ResultEngineStore):
    expected = [make_identity(season=2026, week=1, away_team="NE", home_team="SEA")]
    accepted = [make_accepted_result(season=2026, week=2, away_team="NE", home_team="SEA", source_event_id="evt-1")]
    result = freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted)
    assert result["status"] == "NOT_READY"
    assert result["reason"] == "WEEK_MISMATCH"


def test_j_ambiguous_identity_is_rejected(result_store: ResultEngineStore):
    expected = [make_identity(away_team="NE", home_team="SEA")]
    accepted = [make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1")]
    result = freeze_week_result_set(
        store=result_store,
        season=2026,
        week=1,
        expected_events=expected,
        accepted_results=accepted,
        require_unique_identity=True,
    )
    assert result["status"] in {"FROZEN", "NOT_READY"}


def test_k_same_logical_inputs_different_order_same_hash(result_store: ResultEngineStore):
    expected = _expected_week_games()
    accepted_a = [
        make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1"),
        make_accepted_result(season=2026, week=1, away_team="ATL", home_team="TB", source_event_id="evt-2", kickoff_utc="2026-09-11T00:15:00Z"),
    ]
    accepted_b = [accepted_a[1], accepted_a[0]]
    first = freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted_a)
    second = freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted_b)
    assert first["resultSetHash"] == second["resultSetHash"]
    assert first["resultSetVersion"] == second["resultSetVersion"]


def test_l_changed_score_changes_hash(result_store: ResultEngineStore):
    expected = [make_identity(away_team="NE", home_team="SEA")]
    accepted_a = [make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1", away_score=17, home_score=24)]
    accepted_b = [make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-2", away_score=20, home_score=27)]

    store_a = ResultEngineStore(root_dir=result_store.root_dir / "hash-a")
    store_b = ResultEngineStore(root_dir=result_store.root_dir / "hash-b")

    first = freeze_week_result_set(store=store_a, season=2026, week=1, expected_events=expected, accepted_results=accepted_a)
    second = freeze_week_result_set(store=store_b, season=2026, week=1, expected_events=expected, accepted_results=accepted_b)
    assert first["resultSetHash"] != second["resultSetHash"]


def test_m_persisted_artifact_reconstructs_frozen_contents(result_store: ResultEngineStore):
    expected = _expected_week_games()
    accepted = [
        make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1"),
        make_accepted_result(season=2026, week=1, away_team="ATL", home_team="TB", source_event_id="evt-2", kickoff_utc="2026-09-11T00:15:00Z"),
    ]
    for item in accepted:
        result_store.persist_accepted_result(item)

    result = freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted)
    persisted = load_frozen_week_result_set(store=result_store, season=2026, week=1)

    assert persisted is not None
    assert persisted.season == 2026
    assert persisted.week == 1
    assert len(persisted.accepted_results) == 2
    assert persisted.accepted_results[0].canonical_event_key in {item.canonical_event_key for item in accepted}


def test_n_conflicting_overwrite_rejected(result_store: ResultEngineStore):
    expected = _expected_week_games()
    accepted = [
        make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1"),
        make_accepted_result(season=2026, week=1, away_team="ATL", home_team="TB", source_event_id="evt-2", kickoff_utc="2026-09-11T00:15:00Z"),
    ]
    for item in accepted:
        result_store.persist_accepted_result(item)

    first = freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted)
    second = freeze_week_result_set(
        store=result_store,
        season=2026,
        week=1,
        expected_events=expected,
        accepted_results=[accepted[0]],
    )

    assert first["status"] == "FROZEN"
    assert second["status"] == "NOT_READY"
    assert second["reason"] == "FROZEN_SET_CONFLICT"


def test_o_freeze_has_no_downstream_side_effects(result_store: ResultEngineStore):
    expected = _expected_week_games()
    accepted = [
        make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1"),
        make_accepted_result(season=2026, week=1, away_team="ATL", home_team="TB", source_event_id="evt-2", kickoff_utc="2026-09-11T00:15:00Z"),
    ]
    for item in accepted:
        result_store.persist_accepted_result(item)

    result = freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted)

    assert result["status"] == "FROZEN"
    assert result_store.list_accepted_results(season=2026, week=1)


def test_p_endpoint_reports_persisted_frozen_metadata(result_store: ResultEngineStore, monkeypatch: pytest.MonkeyPatch):
    expected = _expected_week_games()
    accepted = [
        make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1"),
        make_accepted_result(season=2026, week=1, away_team="ATL", home_team="TB", source_event_id="evt-2", kickoff_utc="2026-09-11T00:15:00Z"),
    ]
    for item in accepted:
        result_store.persist_accepted_result(item)

    freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted)
    frozen = load_frozen_week_result_set(store=result_store, season=2026, week=1)
    assert frozen is not None

    artifact_path = result_store.root_dir / "frozen" / "weekly-result-set-2026-1.json"
    before_bytes = artifact_path.read_bytes()

    monkeypatch.setenv("RESULT_ENGINE_ROOT", str(result_store.root_dir))
    monkeypatch.setattr(
        "app.routes.admin_status.resolve_canonical_week_metadata",
        lambda *args, **kwargs: {"season": 2026, "week": 2, "status": "ACTIVE", "source": "test", "reason": "test", "nextKickoffUtc": None, "warnings": []},
    )
    monkeypatch.setattr(
        "app.routes.admin_status.build_week_readiness",
        lambda *args, **kwargs: {"season": 2026, "week": 2, "status": "READY", "scheduleReady": True, "marketsReady": True, "projectionsReady": True, "rankingsReady": True, "warnings": [], "details": {}},
    )

    response = client.get("/api/admin/football-lineage")

    assert response.status_code == 200
    payload = response.json()
    previous = payload["previousWeek"]
    assert previous["season"] == 2026
    assert previous["week"] == 1
    assert previous["expectedGames"] == 2
    assert previous["acceptedFinals"] == 2
    assert previous["complete"] is True
    assert previous["frozen"] is True
    assert previous["resultSetVersion"] == frozen.result_set_version
    assert previous["resultSetHash"] == frozen.result_set_hash
    assert previous["frozenAt"] == frozen.frozen_at_utc
    assert artifact_path.read_bytes() == before_bytes


def test_p_no_frozen_artifact_is_not_created_by_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store_root = tmp_path / "result-engine-root"
    monkeypatch.setenv("RESULT_ENGINE_ROOT", str(store_root))
    monkeypatch.setattr(
        "app.routes.admin_status.resolve_canonical_week_metadata",
        lambda *args, **kwargs: {"season": 2026, "week": 2, "status": "ACTIVE", "source": "test", "reason": "test", "nextKickoffUtc": None, "warnings": []},
    )
    monkeypatch.setattr(
        "app.routes.admin_status.build_week_readiness",
        lambda *args, **kwargs: {"season": 2026, "week": 2, "status": "READY", "scheduleReady": True, "marketsReady": True, "projectionsReady": True, "rankingsReady": True, "warnings": [], "details": {}},
    )

    response = client.get("/api/admin/football-lineage")

    assert response.status_code == 200
    payload = response.json()
    previous = payload.get("previousWeek") or {}
    assert previous.get("frozen") is False
    assert not (store_root / "frozen").exists()


def test_p_malformed_frozen_artifact_fails_safely_without_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store_root = tmp_path / "result-engine-root"
    frozen_dir = store_root / "frozen"
    frozen_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = frozen_dir / "weekly-result-set-2026-1.json"
    artifact_path.write_text('{"broken": true', encoding="utf-8")
    monkeypatch.setenv("RESULT_ENGINE_ROOT", str(store_root))
    monkeypatch.setattr(
        "app.routes.admin_status.resolve_canonical_week_metadata",
        lambda *args, **kwargs: {"season": 2026, "week": 2, "status": "ACTIVE", "source": "test", "reason": "test", "nextKickoffUtc": None, "warnings": []},
    )
    monkeypatch.setattr(
        "app.routes.admin_status.build_week_readiness",
        lambda *args, **kwargs: {"season": 2026, "week": 2, "status": "READY", "scheduleReady": True, "marketsReady": True, "projectionsReady": True, "rankingsReady": True, "warnings": [], "details": {}},
    )

    response = client.get("/api/admin/football-lineage")

    assert response.status_code == 200
    payload = response.json()
    previous = payload.get("previousWeek") or {}
    assert previous.get("frozen") is False
    assert artifact_path.read_text(encoding="utf-8") == '{"broken": true'


def _run_freeze_in_thread(
    *,
    store: ResultEngineStore,
    season: int,
    week: int,
    expected_events: list,
    accepted_results: list,
    out: list[dict | BaseException],
    barrier: threading.Barrier,
):
    try:
        barrier.wait(timeout=5)
        out.append(
            freeze_week_result_set(
                store=store,
                season=season,
                week=week,
                expected_events=expected_events,
                accepted_results=accepted_results,
            )
        )
    except BaseException as exc:  # noqa: BLE001
        out.append(exc)


def test_q_two_concurrent_identical_freeze_attempts_same_authoritative_artifact(result_store: ResultEngineStore):
    expected = _expected_week_games()
    accepted = [
        make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1"),
        make_accepted_result(season=2026, week=1, away_team="ATL", home_team="TB", source_event_id="evt-2", kickoff_utc="2026-09-11T00:15:00Z"),
    ]

    results: list[dict | BaseException] = []
    barrier = threading.Barrier(2)
    t1 = threading.Thread(
        target=_run_freeze_in_thread,
        kwargs={
            "store": result_store,
            "season": 2026,
            "week": 1,
            "expected_events": expected,
            "accepted_results": accepted,
            "out": results,
            "barrier": barrier,
        },
    )
    t2 = threading.Thread(
        target=_run_freeze_in_thread,
        kwargs={
            "store": result_store,
            "season": 2026,
            "week": 1,
            "expected_events": expected,
            "accepted_results": accepted,
            "out": results,
            "barrier": barrier,
        },
    )
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert len(results) == 2
    assert all(not isinstance(item, BaseException) for item in results)
    statuses = sorted(str(item["status"]) for item in results if isinstance(item, dict))
    assert statuses == ["ALREADY_FROZEN", "FROZEN"]

    hashes = {str(item["resultSetHash"]) for item in results if isinstance(item, dict)}
    versions = {str(item["resultSetVersion"]) for item in results if isinstance(item, dict)}
    assert len(hashes) == 1
    assert len(versions) == 1

    frozen_files = list((result_store.root_dir / "frozen").glob("weekly-result-set-2026-1.json"))
    assert len(frozen_files) == 1
    persisted = load_frozen_week_result_set(store=result_store, season=2026, week=1)
    assert persisted is not None
    assert persisted.result_set_hash in hashes
    assert persisted.result_set_version in versions


def test_r_two_concurrent_conflicting_freeze_attempts_single_authoritative_winner(result_store: ResultEngineStore):
    expected = [make_identity(away_team="NE", home_team="SEA", kickoff_utc="2026-09-10T00:15:00Z")]
    accepted_a = [
        make_accepted_result(
            season=2026,
            week=1,
            away_team="NE",
            home_team="SEA",
            source_event_id="evt-a",
            away_score=17,
            home_score=24,
        )
    ]
    accepted_b = [
        make_accepted_result(
            season=2026,
            week=1,
            away_team="NE",
            home_team="SEA",
            source_event_id="evt-b",
            away_score=20,
            home_score=27,
        )
    ]

    results_a: list[dict | BaseException] = []
    results_b: list[dict | BaseException] = []
    barrier = threading.Barrier(2)
    t1 = threading.Thread(
        target=_run_freeze_in_thread,
        kwargs={
            "store": result_store,
            "season": 2026,
            "week": 1,
            "expected_events": expected,
            "accepted_results": accepted_a,
            "out": results_a,
            "barrier": barrier,
        },
    )
    t2 = threading.Thread(
        target=_run_freeze_in_thread,
        kwargs={
            "store": result_store,
            "season": 2026,
            "week": 1,
            "expected_events": expected,
            "accepted_results": accepted_b,
            "out": results_b,
            "barrier": barrier,
        },
    )
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert len(results_a) == 1
    assert len(results_b) == 1
    assert not isinstance(results_a[0], BaseException)
    assert not isinstance(results_b[0], BaseException)

    status_pair = {str(results_a[0]["status"]), str(results_b[0]["status"])}
    assert status_pair == {"FROZEN", "NOT_READY"}

    loser = results_a[0] if str(results_a[0]["status"]) == "NOT_READY" else results_b[0]
    assert loser["reason"] == "FROZEN_SET_CONFLICT"

    persisted = load_frozen_week_result_set(store=result_store, season=2026, week=1)
    assert persisted is not None
    winner_hash = results_a[0]["resultSetHash"] if str(results_a[0]["status"]) == "FROZEN" else results_b[0]["resultSetHash"]
    assert persisted.result_set_hash == winner_hash


def test_s_restart_after_concurrent_freeze_loads_single_winner(tmp_path: Path):
    store = ResultEngineStore(root_dir=tmp_path / "result-engine-root")
    expected = [make_identity(away_team="NE", home_team="SEA", kickoff_utc="2026-09-10T00:15:00Z")]
    accepted_a = [
        make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-a", away_score=14, home_score=21)
    ]
    accepted_b = [
        make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-b", away_score=10, home_score=24)
    ]

    results_a: list[dict | BaseException] = []
    results_b: list[dict | BaseException] = []
    barrier = threading.Barrier(2)
    t1 = threading.Thread(target=_run_freeze_in_thread, kwargs={"store": store, "season": 2026, "week": 1, "expected_events": expected, "accepted_results": accepted_a, "out": results_a, "barrier": barrier})
    t2 = threading.Thread(target=_run_freeze_in_thread, kwargs={"store": store, "season": 2026, "week": 1, "expected_events": expected, "accepted_results": accepted_b, "out": results_b, "barrier": barrier})
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    fresh_store = ResultEngineStore(root_dir=tmp_path / "result-engine-root")
    loaded = load_frozen_week_result_set(store=fresh_store, season=2026, week=1)
    assert loaded is not None

    frozen_hashes = {
        item["resultSetHash"]
        for item in [results_a[0], results_b[0]]
        if isinstance(item, dict) and str(item.get("status")) == "FROZEN"
    }
    assert len(frozen_hashes) == 1
    assert loaded.result_set_hash in frozen_hashes


def test_t_simulated_failure_before_replace_creates_no_authoritative_partial(result_store: ResultEngineStore, monkeypatch: pytest.MonkeyPatch):
    expected = _expected_week_games()
    accepted = [
        make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1"),
        make_accepted_result(season=2026, week=1, away_team="ATL", home_team="TB", source_event_id="evt-2", kickoff_utc="2026-09-11T00:15:00Z"),
    ]

    def _boom_atomic_write(path, text):
        raise OSError("write-before-replace-failure")

    monkeypatch.setattr(freeze_module, "_atomic_write_text", _boom_atomic_write)

    result = None
    caught = None
    try:
        result = freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted)
    except OSError as exc:
        caught = exc

    assert caught is not None or (isinstance(result, dict) and result.get("status") != "FROZEN")

    artifact_path = result_store.root_dir / "frozen" / "weekly-result-set-2026-1.json"
    assert not artifact_path.exists()
    assert load_frozen_week_result_set(store=result_store, season=2026, week=1) is None


def test_u_simulated_failure_with_existing_authoritative_artifact_preserves_bytes(result_store: ResultEngineStore, monkeypatch: pytest.MonkeyPatch):
    expected = _expected_week_games()
    accepted = [
        make_accepted_result(season=2026, week=1, away_team="NE", home_team="SEA", source_event_id="evt-1"),
        make_accepted_result(season=2026, week=1, away_team="ATL", home_team="TB", source_event_id="evt-2", kickoff_utc="2026-09-11T00:15:00Z"),
    ]

    first = freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted)
    assert first["status"] == "FROZEN"

    artifact_path = result_store.root_dir / "frozen" / "weekly-result-set-2026-1.json"
    before = artifact_path.read_bytes()

    def _boom_replace(src, dst):
        raise OSError("replace-failure")

    monkeypatch.setattr("app.services.result_engine.freeze.os.replace", _boom_replace)

    replay = freeze_week_result_set(store=result_store, season=2026, week=1, expected_events=expected, accepted_results=accepted)

    assert replay["status"] == "ALREADY_FROZEN"
    assert artifact_path.read_bytes() == before
