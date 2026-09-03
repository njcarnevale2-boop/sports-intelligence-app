from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from app.services import refresh_orchestrator as orch

def test_run_once_uses_repo_runtime_jobs_not_persistent_scripts(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    (runtime_root / "logs").mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "0")

    state_file = runtime_root / "logs" / "refresh_state.json"
    calls: list[tuple[list[str], dict]] = []

    def _fake_run(cmd, **kwargs):
        calls.append((list(cmd), dict(kwargs)))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    with (
        patch.object(orch, "_STATE_FILE", state_file),
        patch.object(orch.subprocess, "run", side_effect=_fake_run),
        patch.object(orch, "_children_ru_maxrss_kb", side_effect=[1000, 1100, 1200, 1300, 1400, 1500]),
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

    status = json.loads(state_file.read_text())
    assert status["lastRefreshCompleted"] is True
    assert status["lastOddsRefreshExitCode"] == 0
    assert status["lastLineMovementExitCode"] == 0
    assert status["lastRefreshChildrenRuMaxRssKbBefore"] == 1000
    assert status["lastRefreshChildrenRuMaxRssKbAfter"] == 1500
    assert status["lastRefreshChildrenRuMaxRssKbDelta"] == 500
    assert status["refreshMemoryTelemetryMode"] == "RUSAGE_CHILDREN_RU_MAXRSS_BEST_EFFORT"

    assert len(calls) >= 2
    first_cmd, first_kwargs = calls[0]
    second_cmd, second_kwargs = calls[1]

    assert first_cmd[1:] == ["-m", "app.runtime_jobs.odds_refresh"]
    assert second_cmd[1:] == ["-m", "app.runtime_jobs.line_movement"]

    backend_root = Path(orch.__file__).resolve().parents[2]
    assert first_kwargs.get("cwd") == str(backend_root)
    assert second_kwargs.get("cwd") == str(backend_root)

    assert "scripts/update_odds.py" not in " ".join(first_cmd)
    assert "scripts/build_line_movement.py" not in " ".join(second_cmd)


def test_run_once_failure_records_last_attempt_and_backoff_anchor(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    (runtime_root / "logs").mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))

    state_file = runtime_root / "logs" / "refresh_state.json"
    failed = SimpleNamespace(returncode=1, stdout="", stderr="missing runtime job")

    with (
        patch.object(orch, "_STATE_FILE", state_file),
        patch.object(orch.subprocess, "run", return_value=failed),
        patch.object(orch, "_children_ru_maxrss_kb", side_effect=[1000, 1010, 1020, 1030]),
    ):
        assert orch._run_once() is False

    status = json.loads(state_file.read_text())
    assert status["lastRefreshAt"] is None
    assert status["lastAttemptAt"] is not None
    assert status["consecutiveFailures"] == 1
    assert status["isRunning"] is False
    assert "odds_refresh failed" in str(status["lastError"])
    assert status["lastRefreshCompleted"] is False
    assert status["lastOddsRefreshExitCode"] == 1
    assert status["lastLineMovementExitCode"] is None

    now = datetime.now(timezone.utc)
    next_dt = orch._next_refresh_dt(status, now, cadence_minutes=15)
    assert next_dt > now


def test_next_refresh_uses_last_attempt_when_last_refresh_missing():
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    state = {
        "lastRefreshAt": None,
        "lastAttemptAt": "2026-09-01T11:45:00+00:00",
    }
    next_dt = orch._next_refresh_dt(state, now, cadence_minutes=15)
    assert next_dt == datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def test_scheduler_iteration_default_disabled_even_with_odds_api_key(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    (runtime_root / "logs").mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("ODDS_API_KEY", "present-but-not-opted-in")
    monkeypatch.delenv("ODDS_REFRESH_AUTOMATION_ENABLED", raising=False)

    state_file = runtime_root / "logs" / "refresh_state.json"
    with (
        patch.object(orch, "_STATE_FILE", state_file),
        patch.object(orch, "_run_once") as run_once,
    ):
        sleep_secs = orch._scheduler_iteration(now=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc))

    status = json.loads(state_file.read_text())
    assert status["oddsRefreshAutomationEnabled"] is False
    assert status["nextRefreshAt"] is None
    assert sleep_secs >= 300
    run_once.assert_not_called()


def test_scheduler_iteration_disabled_on_explicit_false_and_restart_state(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    (runtime_root / "logs").mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("ODDS_API_KEY", "present")
    monkeypatch.setenv("ODDS_REFRESH_AUTOMATION_ENABLED", "false")

    state_file = runtime_root / "logs" / "refresh_state.json"
    state_file.write_text(json.dumps({"lastRefreshAt": "2026-09-01T11:00:00+00:00"}))

    with (
        patch.object(orch, "_STATE_FILE", state_file),
        patch.object(orch, "_run_once") as run_once,
    ):
        sleep_secs = orch._scheduler_iteration(now=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc))

    status = json.loads(state_file.read_text())
    assert status["oddsRefreshAutomationEnabled"] is False
    assert status["nextRefreshAt"] is None
    assert sleep_secs >= 300
    run_once.assert_not_called()


def test_scheduler_iteration_enabled_can_trigger_run_once_with_mocked_provider(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    (runtime_root / "logs").mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("ODDS_REFRESH_AUTOMATION_ENABLED", "true")

    state_file = runtime_root / "logs" / "refresh_state.json"
    state_file.write_text(json.dumps({"lastRefreshAt": "2026-09-01T10:00:00+00:00", "quotaRemaining": 9999}))

    with (
        patch.object(orch, "_STATE_FILE", state_file),
        patch.object(orch, "_determine_base_cadence_minutes", return_value=30),
        patch.object(orch, "_run_once", return_value=True) as run_once,
    ):
        sleep_secs = orch._scheduler_iteration(now=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc))

    assert sleep_secs >= 5
    run_once.assert_called_once()


def test_scheduler_iteration_no_immediate_retry_after_completed_cycle(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    (runtime_root / "logs").mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("ODDS_REFRESH_AUTOMATION_ENABLED", "true")

    state_file = runtime_root / "logs" / "refresh_state.json"
    state_file.write_text(json.dumps({"lastRefreshAt": "2026-09-01T10:00:00+00:00", "quotaRemaining": 20000}))

    first_now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    def _fake_run_once(_request_provenance: str = "SCHEDULER_AUTOMATION") -> bool:
        state = json.loads(state_file.read_text())
        state["lastRefreshAt"] = first_now.isoformat()
        state["lastAttemptAt"] = first_now.isoformat()
        state_file.write_text(json.dumps(state))
        return True

    with (
        patch.object(orch, "_STATE_FILE", state_file),
        patch.object(orch, "_determine_base_cadence_minutes", return_value=30),
        patch.object(orch, "_run_once", side_effect=_fake_run_once) as run_once,
    ):
        first_sleep = orch._scheduler_iteration(now=first_now)
        second_sleep = orch._scheduler_iteration(now=first_now + timedelta(seconds=1))

    assert first_sleep >= 5
    assert second_sleep >= 5
    run_once.assert_called_once()


def test_cached_week_data_still_usable_when_odds_refresh_automation_disabled(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    outputs = runtime_root / "outputs"
    database = runtime_root / "database"
    logs = runtime_root / "logs"
    outputs.mkdir(parents=True)
    database.mkdir(parents=True)
    logs.mkdir(parents=True)

    # Presence-only file for data status.
    (database / "nfl_model.duckdb").write_text("")

    pd.DataFrame(
        [
            {
                "api_event_id": "evt-1",
                "commence_time": "2026-09-10T00:00:00+00:00",
                "away_team": "BUF",
                "home_team": "KC",
                "market_home_spread": -2.5,
                "market_total": 47.5,
            }
        ]
    ).to_csv(outputs / "current_game_projections.csv", index=False)

    pd.DataFrame(
        [
            {
                "season": 2026,
                "week": 1,
                "gameday": "2026-09-10",
                "away_team": "BUF",
                "home_team": "KC",
            }
        ]
    ).to_csv(outputs / "schedule_context_latest.csv", index=False)

    pd.DataFrame(
        columns=[
            "api_event_id",
            "sportsbook",
            "market",
            "side",
            "latest_point",
            "opening_point_observed",
            "latest_price",
            "opening_price_observed",
            "snapshots",
            "first_seen",
            "last_seen",
            "steam_flag",
            "commence_time",
            "away_team",
            "home_team",
        ]
    ).to_csv(outputs / "line_movement_board.csv", index=False)

    pd.DataFrame(columns=["api_event_id", "market", "side", "rank", "point", "price", "edge_pp", "ev_per_dollar", "confidence_score", "data_completeness"]).to_csv(
        outputs / "ranked_bet_board.csv", index=False
    )

    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("ODDS_REFRESH_AUTOMATION_ENABLED", "false")

    from app.services.games import service as games_service

    out = games_service.list_games(week=1)
    assert out["count"] == 1
    assert (out.get("dataStatus") or {}).get("schedule") == "CACHED"


def test_get_refresh_status_disables_running_and_retires_legacy_error_when_automation_off(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    (runtime_root / "logs").mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("ODDS_REFRESH_AUTOMATION_ENABLED", "false")

    state_file = runtime_root / "logs" / "refresh_state.json"
    state_file.write_text(
        json.dumps(
            {
                "isRunning": True,
                "lastError": "update_odds.py failed: python3: can't open file '/data/NFL_Analytics_OS_v1_9/scripts/update_odds.py'",
                "consecutiveFailures": 26329,
            }
        )
    )

    with patch.object(orch, "_STATE_FILE", state_file):
        status = orch.get_refresh_status()

    assert status["oddsRefreshAutomationEnabled"] is False
    assert status["oddsRefreshAutomationState"] == "DISABLED"
    assert status["isRunning"] is False
    assert status["nextRefreshAt"] is None
    assert status["lastError"] is None
    assert status["consecutiveFailures"] == 0
    assert "scripts/update_odds.py" in str(status["historicalLastError"])
    assert status["historicalConsecutiveFailures"] == 26329


def test_run_once_memory_telemetry_unavailable_fails_safe(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    (runtime_root / "logs").mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "0")

    state_file = runtime_root / "logs" / "refresh_state.json"

    with (
        patch.object(orch, "_STATE_FILE", state_file),
        patch.object(orch.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="ok", stderr="")),
        patch.object(orch, "_children_ru_maxrss_kb", return_value=None),
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

    status = json.loads(state_file.read_text())
    assert status["lastRefreshCompleted"] is True
    assert status["lastRefreshChildrenRuMaxRssKbBefore"] is None
    assert status["lastRefreshChildrenRuMaxRssKbAfter"] is None
    assert status["lastRefreshChildrenRuMaxRssKbDelta"] is None


def test_get_refresh_status_surfaces_instrumentation_fields(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    (runtime_root / "logs").mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))

    state_file = runtime_root / "logs" / "refresh_state.json"
    state_file.write_text(
        json.dumps(
            {
                "lastRefreshCompleted": True,
                "lastRefreshOverallElapsedSeconds": 12.34,
                "lastOddsRefreshExitCode": 0,
                "lastOddsRefreshElapsedSeconds": 3.21,
                "lastLineMovementExitCode": 0,
                "lastLineMovementElapsedSeconds": 2.1,
                "lastRefreshChildrenRuMaxRssKbBefore": 100,
                "lastRefreshChildrenRuMaxRssKbAfter": 200,
                "lastRefreshChildrenRuMaxRssKbDelta": 100,
            }
        )
    )

    with patch.object(orch, "_STATE_FILE", state_file):
        status = orch.get_refresh_status()

    assert status["lastRefreshCompleted"] is True
    assert status["lastRefreshOverallElapsedSeconds"] == 12.34
    assert status["lastOddsRefreshExitCode"] == 0
    assert status["lastLineMovementExitCode"] == 0
    assert status["lastRefreshChildrenRuMaxRssKbDelta"] == 100


def test_instrumented_orchestrator_run_makes_no_direct_provider_request(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    (runtime_root / "logs").mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "0")

    state_file = runtime_root / "logs" / "refresh_state.json"

    with (
        patch.object(orch, "_STATE_FILE", state_file),
        patch.object(orch.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="ok", stderr="")),
        patch("app.runtime_jobs.odds_refresh.requests.get") as request_get,
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
        request_get.assert_not_called()


def test_base_cadence_defaults_match_balanced_week1_policy():
    assert orch.MINS_OFFSEASON() == 360
    assert orch.MINS_GAMEWEEK() == 180
    assert orch.MINS_GAMEDAY() == 60
    assert orch.MINS_NEARKICKOFF() == 20


def test_determine_base_cadence_minutes_at_uses_balanced_windows(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    outputs = runtime_root / "outputs"
    outputs.mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))

    pd.DataFrame(
        [
            {"api_event_id": "evt-1", "commence_time": "2026-09-10T00:15:00+00:00", "away_team": "NE", "home_team": "SEA"},
            {"api_event_id": "evt-2", "commence_time": "2026-09-13T17:00:00+00:00", "away_team": "NO", "home_team": "ATL"},
        ]
    ).to_csv(outputs / "current_game_projections.csv", index=False)

    assert orch._determine_base_cadence_minutes_at(datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)) == 360
    assert orch._determine_base_cadence_minutes_at(datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)) == 180
    assert orch._determine_base_cadence_minutes_at(datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)) == 60
    assert orch._determine_base_cadence_minutes_at(datetime(2026, 9, 9, 22, 0, tzinfo=timezone.utc)) == 20


def test_week1_balanced_cadence_cost_regression(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    outputs = runtime_root / "outputs"
    outputs.mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))

    kickoffs = [
        "2026-09-10T00:15:00+00:00",
        "2026-09-11T00:15:00+00:00",
        "2026-09-13T17:00:00+00:00",
        "2026-09-13T17:00:00+00:00",
        "2026-09-13T17:00:00+00:00",
        "2026-09-13T17:00:00+00:00",
        "2026-09-13T17:00:00+00:00",
        "2026-09-13T17:00:00+00:00",
        "2026-09-13T17:00:00+00:00",
        "2026-09-13T17:00:00+00:00",
        "2026-09-13T20:05:00+00:00",
        "2026-09-13T20:25:00+00:00",
        "2026-09-13T20:25:00+00:00",
        "2026-09-13T20:25:00+00:00",
        "2026-09-14T00:20:00+00:00",
        "2026-09-15T00:15:00+00:00",
    ]
    rows = [
        {"api_event_id": f"evt-{idx}", "commence_time": kickoff, "away_team": f"A{idx}", "home_team": f"H{idx}"}
        for idx, kickoff in enumerate(kickoffs, start=1)
    ]
    pd.DataFrame(rows).to_csv(outputs / "current_game_projections.csv", index=False)

    start = datetime(2026, 9, 3, 22, 9, 26, 555699, tzinfo=timezone.utc)
    end = datetime(2026, 9, 15, 4, 30, tzinfo=timezone.utc)
    now = start
    runs: list[datetime] = []
    while now < end:
        cadence = orch._determine_base_cadence_minutes_at(now)
        runs.append(now)
        now += timedelta(minutes=cadence)

    max_runs_in_seven_days = 0
    left = 0
    for right, current in enumerate(runs):
        while runs[left] < current - timedelta(days=7):
            left += 1
        max_runs_in_seven_days = max(max_runs_in_seven_days, right - left + 1)

    assert len(runs) == 181
    assert len(runs) * 3 == 543
    assert max_runs_in_seven_days == 159
    assert max_runs_in_seven_days * 3 == 477


def test_refresh_status_surfaces_player_prop_collection_enabled(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    (runtime_root / "logs").mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("PLAYER_PROP_COLLECTION_ENABLED", "0")

    state_file = runtime_root / "logs" / "refresh_state.json"
    state_file.write_text(json.dumps({"pregameAutomationEnabled": True}))

    with patch.object(orch, "_STATE_FILE", state_file):
        status = orch.get_refresh_status()

    assert status["playerPropCollectionEnabled"] is False
