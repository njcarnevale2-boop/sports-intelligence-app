from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import main
from app.config import settings
from app.runtime_paths import DEFAULT_NFL_ANALYTICS_OS_ROOT, resolve_sqlite_database_path, runtime_paths, runtime_readiness
from app.services import refresh_orchestrator as orch


def test_custom_nfl_analytics_os_root_resolution(monkeypatch, tmp_path: Path):
    root = tmp_path / "runtime-root"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(root))

    assert str(runtime_paths.root) == str(root.resolve())
    assert str(runtime_paths.nfl_model_duckdb).endswith("database/nfl_model.duckdb")
    assert str(runtime_paths.refresh_state_json).endswith("logs/refresh_state.json")


def test_local_fallback_preserved(monkeypatch):
    monkeypatch.delenv("NFL_ANALYTICS_OS_ROOT", raising=False)

    assert str(runtime_paths.root) == str(DEFAULT_NFL_ANALYTICS_OS_ROOT.expanduser().resolve())
    assert runtime_paths.root_source == "LOCAL_FALLBACK"


def test_sqlite_persistent_path_resolution_supported(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:////data/sports_intelligence.db")
    assert resolve_sqlite_database_path() == Path("/data/sports_intelligence.db")

    rel = tmp_path / "repo.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{rel.name}")
    assert resolve_sqlite_database_path() == (Path.cwd() / rel.name).resolve()


def test_runtime_readiness_ready_and_degraded(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    (root / "database").mkdir(parents=True)
    (root / "outputs").mkdir()
    (root / "logs").mkdir()
    (root / "scripts").mkdir()
    (root / "database" / "nfl_model.duckdb").write_text("")
    (root / "outputs" / "current_game_projections.csv").write_text("api_event_id\n")
    (root / "outputs" / "line_movement_board.csv").write_text("api_event_id\n")

    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(root))
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{(tmp_path / 'sports_intelligence.db').name}")

    degraded = runtime_readiness()
    assert degraded["deploymentReadiness"] == "DEGRADED"
    assert degraded["persistentStorageReady"] is True
    assert degraded["requiredArtifactsReady"] is True
    assert "scheduleContextLatest" in degraded["missingArtifacts"]
    assert "rankedBetBoard" in degraded["missingArtifacts"]

    (root / "outputs" / "schedule_context_latest.csv").write_text("game_date\n")
    (root / "outputs" / "ranked_bet_board.csv").write_text("api_event_id\n")
    ready = runtime_readiness()
    assert ready["deploymentReadiness"] == "READY"


def test_runtime_readiness_not_ready_when_required_artifact_missing(tmp_path, monkeypatch):
    root = tmp_path / "runtime-missing"
    (root / "database").mkdir(parents=True)
    (root / "outputs").mkdir()
    (root / "logs").mkdir()
    (root / "scripts").mkdir()
    (root / "database" / "nfl_model.duckdb").write_text("")

    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(root))
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{(tmp_path / 'sports_intelligence.db').name}")

    out = runtime_readiness()
    assert out["deploymentReadiness"] == "NOT_READY"
    assert "currentGameProjections" in out["missingArtifacts"]
    assert "lineMovementBoard" in out["missingArtifacts"]


def test_runtime_readiness_scripts_dir_optional(tmp_path, monkeypatch):
    root = tmp_path / "runtime-no-scripts"
    (root / "database").mkdir(parents=True)
    (root / "outputs").mkdir()
    (root / "logs").mkdir()
    (root / "database" / "nfl_model.duckdb").write_text("")
    (root / "outputs" / "current_game_projections.csv").write_text("api_event_id\n")
    (root / "outputs" / "line_movement_board.csv").write_text("api_event_id\n")

    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(root))
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{(tmp_path / 'sports_intelligence.db').name}")

    out = runtime_readiness()
    assert out["requiredArtifactsReady"] is True
    assert "scriptsDir" in out["missingArtifacts"]
    assert out["deploymentReadiness"] == "DEGRADED"


def test_startup_event_logs_readiness_and_starts_scheduler(monkeypatch):
    with (
        patch("app.main.init_db") as init_db,
        patch("app.services.refresh_orchestrator.start_scheduler") as start_scheduler,
        patch("app.services.market_data.market_data_service.load_normalized_market_rows", return_value=[]),
        patch("app.services.market_data.market_data_service.all_event_snapshots", return_value={}),
        patch("app.services.market_intelligence.build_market_intelligence_lookup", return_value={}),
        patch("app.main.runtime_readiness", return_value={"deploymentReadiness": "READY", "runtimeRoot": "/data/NFL_Analytics_OS_v1_9", "missingArtifacts": []}),
    ):
        main.startup_event()

    init_db.assert_called_once()
    start_scheduler.assert_called_once()


def test_restart_safe_scheduler_initialization_and_no_provider_call_when_no_work_due(tmp_path, monkeypatch):
    root = tmp_path / "portable-root"
    (root / "logs").mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(root))
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "1")

    state_file = root / "logs" / "refresh_state.json"
    state_file.write_text(json.dumps({"lastRefreshAt": "2026-09-10T00:00:00+00:00"}))
    success = SimpleNamespace(returncode=0, stdout="ok", stderr="")

    with (
        patch.object(orch.subprocess, "run", side_effect=lambda *args, **kwargs: success),
        patch("app.services.pregame_collection_manager.build_pregame_collection_schedule_v1", return_value={"events": [], "policy": {"windows": {"openingHoursGreaterThan": 24, "closingHoursAtMost": 2}}, "totals": {"standardSnapshotsDue": 0, "playerPropSnapshotsDue": 0, "nextCollectionWindow": None}}),
        patch("app.services.pregame_collection_manager.run_pregame_collection_manager") as run_manager,
        patch("app.services.recommendation_snapshot.capture_closing_lines", return_value={"eligible": 0, "captured": 0, "pending": 0, "missing": 0, "errors": 0}),
        patch("app.services.decision_ledger.run_official_postgame_lifecycle", return_value={"checked": 0, "settled": 0, "pending": 0}),
        patch("app.services.shadow_markets.append_shadow_outcomes", return_value={"checked": 0, "appended": 0, "pending": 0}),
        patch("app.services.performance.get_performance_service") as perf_factory,
        patch("app.services.injuries.InjuryAnalyzer") as injury_analyzer,
        patch("app.services.injury_history.get_injury_summary", return_value={"playersTracked": 0, "teamsUpdated": 0}),
        patch("app.services.weather_history.get_weather_summary", return_value={"forecastsAvailable": 0}),
        patch.object(orch, "_read_quota_from_db", return_value=None),
    ):
        perf_factory.return_value.get_performance_summary.return_value = {
            "closingLinesCaptured": 0,
            "pendingClosingLines": 0,
            "missingClosingLines": 0,
            "averageCLV": None,
        }
        injury_analyzer.return_value.analyze.return_value = None
        injury_analyzer.return_value._data_status = "LIVE"

        assert orch._run_once() is True
        run_manager.assert_not_called()

    status = json.loads(state_file.read_text())
    assert status["pregameLastStatus"] == "NO_WORK_DUE"
    assert status["pregameLastProviderRequests"] == 0