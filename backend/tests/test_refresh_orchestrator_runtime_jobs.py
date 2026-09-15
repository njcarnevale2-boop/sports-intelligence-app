from __future__ import annotations

import json
import time
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
        patch("app.services.decision_ledger.run_personal_postgame_lifecycle", return_value={"checked": 0, "settled": 0, "pending": 0}),
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
        patch.object(
            orch,
            "_determine_base_cadence_context_at",
            return_value={
                "bucket": "WITHIN_24H_TO_KICKOFF",
                "cadenceMinutes": 30,
                "nextKickoffAt": "2026-09-01T15:00:00+00:00",
                "hoursToNextKickoff": 3.0,
                "activeWeek": True,
                "activeSlate": False,
            },
        ),
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
        patch.object(
            orch,
            "_determine_base_cadence_context_at",
            return_value={
                "bucket": "WITHIN_24H_TO_KICKOFF",
                "cadenceMinutes": 30,
                "nextKickoffAt": "2026-09-01T15:00:00+00:00",
                "hoursToNextKickoff": 3.0,
                "activeWeek": True,
                "activeSlate": False,
            },
        ),
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
        patch("app.services.decision_ledger.run_personal_postgame_lifecycle", return_value={"checked": 0, "settled": 0, "pending": 0}),
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


def test_run_once_personal_lifecycle_exception_is_non_fatal(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    (runtime_root / "logs").mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "0")

    state_file = runtime_root / "logs" / "refresh_state.json"

    with (
        patch.object(orch, "_STATE_FILE", state_file),
        patch.object(orch.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="ok", stderr="")),
        patch.object(orch, "_children_ru_maxrss_kb", side_effect=[1000, 1005, 1010, 1015, 1020, 1025]),
        patch("app.services.recommendation_snapshot.capture_closing_lines", return_value={"eligible": 1, "captured": 1, "pending": 0, "missing": 0, "errors": 0}),
        patch("app.services.decision_ledger.run_official_postgame_lifecycle", return_value={"checked": 3, "settled": 2, "pending": 1}) as official_lifecycle,
        patch("app.services.shadow_markets.append_shadow_outcomes", return_value={"checked": 2, "appended": 1, "pending": 1}) as shadow_lifecycle,
        patch("app.services.decision_ledger.run_personal_postgame_lifecycle", side_effect=RuntimeError("personal boom")) as personal_lifecycle,
        patch("app.services.performance.get_performance_service") as perf_factory,
        patch("app.services.injuries.InjuryAnalyzer") as injury_analyzer,
        patch("app.services.injury_history.get_injury_summary", return_value={"playersTracked": 0, "teamsUpdated": 0}),
        patch("app.services.weather_history.get_weather_summary", return_value={"forecastsAvailable": 0}),
        patch.object(orch, "_read_quota_from_db", return_value=None),
    ):
        perf_factory.return_value.get_performance_summary.return_value = {
            "closingLinesCaptured": 1,
            "pendingClosingLines": 0,
            "missingClosingLines": 0,
            "averageCLV": 0.1,
        }
        injury_analyzer.return_value.analyze.return_value = None
        injury_analyzer.return_value._data_status = "LIVE"

        assert orch._run_once() is True

    official_lifecycle.assert_called_once()
    shadow_lifecycle.assert_called_once()
    personal_lifecycle.assert_called_once()

    status = json.loads(state_file.read_text())
    assert status["lastRefreshCompleted"] is True
    assert status["ledgerOutcomeChecked"] == 3
    assert status["ledgerOutcomesAppended"] == 2
    assert status["shadowOutcomeChecked"] == 2
    assert status["shadowOutcomesAppended"] == 1
    assert status["personalOutcomeChecked"] == 0
    assert status["personalOutcomesSettled"] == 0
    assert status["lastPersonalOutcomeError"] is not None
    assert "personal boom" in status["lastPersonalOutcomeError"]


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
        patch("app.services.decision_ledger.run_personal_postgame_lifecycle", return_value={"checked": 0, "settled": 0, "pending": 0}),
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
    assert orch.MINS_ACTIVE_WEEK() == 60
    assert orch.MINS_WITHIN_24H() == 30
    assert orch.MINS_ACTIVE_SLATE() == 15


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

    assert orch._determine_base_cadence_minutes_at(datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)) == 360
    assert orch._determine_base_cadence_minutes_at(datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)) == 60
    assert orch._determine_base_cadence_minutes_at(datetime(2026, 9, 9, 12, 30, tzinfo=timezone.utc)) == 30
    assert orch._determine_base_cadence_minutes_at(datetime(2026, 9, 9, 22, 0, tzinfo=timezone.utc)) == 15


def test_week1_balanced_cadence_windows_regression(tmp_path, monkeypatch):
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

    ctx_offseason = orch._determine_base_cadence_context_at(datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc))
    ctx_active_week = orch._determine_base_cadence_context_at(datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc))
    ctx_24h = orch._determine_base_cadence_context_at(datetime(2026, 9, 9, 12, 30, tzinfo=timezone.utc))
    ctx_active_slate_tnf = orch._determine_base_cadence_context_at(datetime(2026, 9, 9, 22, 0, tzinfo=timezone.utc))
    ctx_active_slate_sunday = orch._determine_base_cadence_context_at(datetime(2026, 9, 13, 18, 0, tzinfo=timezone.utc))
    ctx_active_slate_mnf = orch._determine_base_cadence_context_at(datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc))

    assert ctx_offseason["bucket"] == "OFFSEASON"
    assert ctx_offseason["cadenceMinutes"] == 360

    assert ctx_active_week["bucket"] == "ACTIVE_WEEK_GT_24H"
    assert ctx_active_week["cadenceMinutes"] == 60

    assert ctx_24h["bucket"] == "WITHIN_24H_TO_KICKOFF"
    assert ctx_24h["cadenceMinutes"] == 30

    assert ctx_active_slate_tnf["bucket"] == "ACTIVE_SLATE"
    assert ctx_active_slate_tnf["cadenceMinutes"] == 15

    assert ctx_active_slate_sunday["bucket"] == "ACTIVE_SLATE"
    assert ctx_active_slate_sunday["cadenceMinutes"] == 15

    assert ctx_active_slate_mnf["bucket"] == "ACTIVE_SLATE"
    assert ctx_active_slate_mnf["cadenceMinutes"] == 15


def test_scheduler_iteration_surfaces_overdue_health_and_recovers_once(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    (runtime_root / "logs").mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("ODDS_REFRESH_AUTOMATION_ENABLED", "1")

    state_file = runtime_root / "logs" / "refresh_state.json"
    state_file.write_text(
        json.dumps(
            {
                "lastRefreshAt": "2026-09-01T10:00:00+00:00",
                "lastAttemptAt": "2026-09-01T10:00:00+00:00",
                "quotaRemaining": 5000,
            }
        )
    )

    call_count = 0

    def _fake_run_once(_request_provenance: str = "SCHEDULER_AUTOMATION") -> bool:
        nonlocal call_count
        call_count += 1
        state = json.loads(state_file.read_text())
        now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        state["lastRefreshAt"] = now.isoformat()
        state["lastAttemptAt"] = now.isoformat()
        state_file.write_text(json.dumps(state))
        return True

    with (
        patch.object(orch, "_STATE_FILE", state_file),
        patch.object(
            orch,
            "_determine_base_cadence_context_at",
            return_value={
                "bucket": "WITHIN_24H_TO_KICKOFF",
                "cadenceMinutes": 30,
                "nextKickoffAt": "2026-09-01T18:00:00+00:00",
                "hoursToNextKickoff": 6.0,
                "activeWeek": True,
                "activeSlate": False,
            },
        ),
        patch.object(orch, "_run_once", side_effect=_fake_run_once),
    ):
        orch._scheduler_iteration(now=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc))
        orch._scheduler_iteration(now=datetime(2026, 9, 1, 12, 1, tzinfo=timezone.utc))

    status = json.loads(state_file.read_text())

    assert call_count == 1
    assert status["schedulerHealth"] == "HEALTHY"
    assert status["overdueMinutes"] == 0.0
    assert status["selectedCadenceBucket"] == "WITHIN_24H_TO_KICKOFF"
    assert status["effectiveCadenceMinutes"] == 30


def test_get_refresh_status_marks_overdue_when_next_refresh_passed(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    (runtime_root / "logs").mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("ODDS_REFRESH_AUTOMATION_ENABLED", "1")

    now = datetime.now(timezone.utc)
    state_file = runtime_root / "logs" / "refresh_state.json"
    state_file.write_text(
        json.dumps(
            {
                "oddsRefreshAutomationEnabled": True,
                "nextRefreshAt": (now - timedelta(minutes=11)).isoformat(),
                "quotaRemaining": 1000,
            }
        )
    )

    with (
        patch.object(orch, "_STATE_FILE", state_file),
        patch.object(
            orch,
            "_determine_base_cadence_context",
            return_value={
                "bucket": "ACTIVE_WEEK_GT_24H",
                "cadenceMinutes": 60,
                "nextKickoffAt": None,
                "hoursToNextKickoff": None,
                "activeWeek": True,
                "activeSlate": False,
            },
        ),
        patch.object(orch, "_scheduler_started", True),
        patch.object(orch, "_scheduler_thread", SimpleNamespace(is_alive=lambda: True)),
    ):
        status = orch.get_refresh_status()

    assert status["schedulerHealth"] == "OVERDUE"
    assert status["overdueMinutes"] is not None
    assert float(status["overdueMinutes"]) >= 10.0


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


def _write_representative_prime_time_schedule(outputs: Path) -> None:
    pd.DataFrame(
        [
            {"api_event_id": "evt-tnf", "commence_time": "2026-09-18T00:15:00+00:00", "away_team": "A1", "home_team": "H1"},
            {"api_event_id": "evt-sun-1", "commence_time": "2026-09-20T17:00:00+00:00", "away_team": "A2", "home_team": "H2"},
            {"api_event_id": "evt-sun-2", "commence_time": "2026-09-20T20:25:00+00:00", "away_team": "A3", "home_team": "H3"},
            {"api_event_id": "evt-snf", "commence_time": "2026-09-21T00:20:00+00:00", "away_team": "A4", "home_team": "H4"},
            {"api_event_id": "evt-mnf", "commence_time": "2026-09-22T00:15:00+00:00", "away_team": "A5", "home_team": "H5"},
        ]
    ).to_csv(outputs / "current_game_projections.csv", index=False)


def test_quota_cap_reduce_branch_uses_active_week_floor_without_exception() -> None:
    quota = orch.QUOTA_REDUCE()
    capped_from_aggressive = orch._quota_cap(15, quota)
    capped_from_slower = orch._quota_cap(120, quota)

    assert capped_from_aggressive == orch.MINS_ACTIVE_WEEK()
    assert capped_from_slower == 120
    assert capped_from_aggressive >= 15


def test_cadence_leaves_active_slate_after_tnf_window_and_stays_non_15_on_friday_saturday(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    outputs = runtime_root / "outputs"
    outputs.mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _write_representative_prime_time_schedule(outputs)

    tnf_plus_6h_1m = datetime(2026, 9, 18, 6, 16, tzinfo=timezone.utc)
    friday_morning = datetime(2026, 9, 18, 13, 0, tzinfo=timezone.utc)
    saturday_noon = datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc)

    for dt in (tnf_plus_6h_1m, friday_morning, saturday_noon):
        ctx = orch._determine_base_cadence_context_at(dt)
        assert ctx["bucket"] != "ACTIVE_SLATE"
        assert ctx["cadenceMinutes"] != 15


def test_cadence_transitions_sunday_slate_to_snf_then_to_mnf_prewindow(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    outputs = runtime_root / "outputs"
    outputs.mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _write_representative_prime_time_schedule(outputs)

    sunday_early = orch._determine_base_cadence_context_at(datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc))
    sunday_late = orch._determine_base_cadence_context_at(datetime(2026, 9, 20, 21, 0, tzinfo=timezone.utc))
    sunday_night = orch._determine_base_cadence_context_at(datetime(2026, 9, 21, 1, 0, tzinfo=timezone.utc))
    after_snf_plus_6h = orch._determine_base_cadence_context_at(datetime(2026, 9, 21, 6, 21, tzinfo=timezone.utc))
    mnf_prewindow = orch._determine_base_cadence_context_at(datetime(2026, 9, 21, 18, 16, tzinfo=timezone.utc))
    after_mnf_plus_6h = orch._determine_base_cadence_context_at(datetime(2026, 9, 22, 6, 16, tzinfo=timezone.utc))

    assert sunday_early["bucket"] == "ACTIVE_SLATE"
    assert sunday_late["bucket"] == "ACTIVE_SLATE"
    assert sunday_night["bucket"] == "ACTIVE_SLATE"

    assert after_snf_plus_6h["bucket"] == "WITHIN_24H_TO_KICKOFF"
    assert after_snf_plus_6h["cadenceMinutes"] == 30

    assert mnf_prewindow["bucket"] == "ACTIVE_SLATE"
    assert mnf_prewindow["cadenceMinutes"] == 15

    assert after_mnf_plus_6h["bucket"] == "OFFSEASON"
    assert after_mnf_plus_6h["cadenceMinutes"] == 360


def test_start_scheduler_is_idempotent_for_scheduler_and_watchdog_threads(monkeypatch):
    created: list[SimpleNamespace] = []

    def _fake_thread(*, target, name, daemon):
        thread = SimpleNamespace(_alive=False, target=target, name=name, daemon=daemon)

        def _start() -> None:
            thread._alive = True

        def _is_alive() -> bool:
            return bool(thread._alive)

        thread.start = _start
        thread.is_alive = _is_alive
        created.append(thread)
        return thread

    with (
        patch.object(orch, "_scheduler_thread", None),
        patch.object(orch, "_watchdog_thread", None),
        patch.object(orch, "_scheduler_started", False),
        patch.object(orch.threading, "Thread", side_effect=_fake_thread),
        patch.object(orch, "_read_state", return_value={}),
        patch.object(orch, "_write_state"),
    ):
        orch.start_scheduler()
        orch.start_scheduler()
        orch.start_scheduler()

    assert len(created) == 2
    assert {t.name for t in created} == {"odds-refresh-scheduler", "odds-refresh-watchdog"}


def test_watchdog_restarts_dead_scheduler_once_and_skips_live_scheduler(monkeypatch):
    state: dict[str, object] = {"schedulerRestartCount": 0}

    def _read_state() -> dict[str, object]:
        return dict(state)

    def _write_state(payload: dict[str, object]) -> None:
        state.update(payload)

    dead_scheduler = SimpleNamespace(is_alive=lambda: False)
    live_scheduler = SimpleNamespace(is_alive=lambda: True)

    def _start_replacement() -> None:
        orch._scheduler_thread = live_scheduler

    original_scheduler_thread = orch._scheduler_thread
    try:
        orch._scheduler_thread = dead_scheduler
        with (
            patch.object(orch, "_read_state", side_effect=_read_state),
            patch.object(orch, "_write_state", side_effect=_write_state),
            patch.object(orch, "_start_scheduler_thread_locked", side_effect=_start_replacement) as restart,
            patch.object(time, "sleep", side_effect=RuntimeError("stop")),
        ):
            try:
                orch._scheduler_watchdog_loop()
            except RuntimeError as exc:
                assert str(exc) == "stop"

        assert restart.call_count == 1
        assert int(state.get("schedulerRestartCount") or 0) == 1
        assert state.get("schedulerRestartedAt") is not None

        with (
            patch.object(orch, "_read_state", side_effect=_read_state),
            patch.object(orch, "_write_state", side_effect=_write_state),
            patch.object(orch, "_start_scheduler_thread_locked") as restart_live,
            patch.object(time, "sleep", side_effect=RuntimeError("stop")),
        ):
            try:
                orch._scheduler_watchdog_loop()
            except RuntimeError as exc:
                assert str(exc) == "stop"

        assert restart_live.call_count == 0
        assert int(state.get("schedulerRestartCount") or 0) == 1
    finally:
        orch._scheduler_thread = original_scheduler_thread


def test_run_once_overlap_lock_prevents_concurrent_execution(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    (runtime_root / "logs").mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))

    state_file = runtime_root / "logs" / "refresh_state.json"
    acquired = orch._run_lock.acquire(blocking=False)
    assert acquired is True
    try:
        with (
            patch.object(orch, "_STATE_FILE", state_file),
            patch.object(orch.subprocess, "run") as run_subprocess,
        ):
            out = orch._run_once()
        assert out is False
        run_subprocess.assert_not_called()
    finally:
        orch._run_lock.release()


def test_scheduler_due_quota_block_skips_provider_and_progresses_next_refresh(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    logs = runtime_root / "logs"
    outputs = runtime_root / "outputs"
    logs.mkdir(parents=True)
    outputs.mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("ODDS_REFRESH_AUTOMATION_ENABLED", "1")
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "0")

    _write_representative_prime_time_schedule(outputs)

    state_file = logs / "refresh_state.json"
    state_file.write_text(
        json.dumps(
            {
                "lastRefreshAt": "2026-09-01T10:00:00+00:00",
                "lastAttemptAt": "2026-09-01T10:00:00+00:00",
                "quotaRemaining": 5000,
                "schedulerRestartCount": 0,
            }
        )
    )

    from app.runtime_jobs import odds_refresh as refresh_job

    def _fake_subprocess_run(cmd, **_kwargs):
        command = list(cmd)
        if command[1:] == ["-m", "app.runtime_jobs.odds_refresh"]:
            out = refresh_job.run_refresh()
            return SimpleNamespace(returncode=0, stdout=json.dumps(out), stderr="")
        if command[1:] == ["-m", "app.runtime_jobs.line_movement"]:
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")
        raise AssertionError(f"unexpected command: {command}")

    with (
        patch.object(orch, "_STATE_FILE", state_file),
        patch.object(orch, "_children_ru_maxrss_kb", return_value=None),
        patch.object(orch, "_read_quota_from_db", return_value=5000),
        patch.object(
            orch,
            "_determine_base_cadence_context_at",
            return_value={
                "bucket": "WITHIN_24H_TO_KICKOFF",
                "cadenceMinutes": 30,
                "nextKickoffAt": "2026-09-01T18:00:00+00:00",
                "hoursToNextKickoff": 6.0,
                "activeWeek": True,
                "activeSlate": False,
            },
        ),
        patch.object(orch.subprocess, "run", side_effect=_fake_subprocess_run),
        patch.object(refresh_job, "_evaluate_core_quota_guard", return_value={"allowed": False, "reason": "WEEKLY_HARD_BUDGET_EXCEEDED"}),
        patch.object(refresh_job.requests, "get") as provider_get,
        patch("app.services.recommendation_snapshot.capture_closing_lines", return_value={"eligible": 0, "captured": 0, "pending": 0, "missing": 0, "errors": 0}),
        patch("app.services.decision_ledger.run_official_postgame_lifecycle", return_value={"checked": 0, "settled": 0, "pending": 0}),
        patch("app.services.decision_ledger.run_personal_postgame_lifecycle", return_value={"checked": 0, "settled": 0, "pending": 0}),
        patch("app.services.shadow_markets.append_shadow_outcomes", return_value={"checked": 0, "appended": 0, "pending": 0}),
        patch("app.services.performance.get_performance_service") as perf_factory,
        patch("app.services.injuries.InjuryAnalyzer") as injury_analyzer,
        patch("app.services.injury_history.get_injury_summary", return_value={"playersTracked": 0, "teamsUpdated": 0}),
        patch("app.services.weather_history.get_weather_summary", return_value={"forecastsAvailable": 0}),
    ):
        perf_factory.return_value.get_performance_summary.return_value = {
            "closingLinesCaptured": 0,
            "pendingClosingLines": 0,
            "missingClosingLines": 0,
            "averageCLV": None,
        }
        injury_analyzer.return_value.analyze.return_value = None
        injury_analyzer.return_value._data_status = "LIVE"

        orch._scheduler_iteration(now=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc))
        first_state = json.loads(state_file.read_text())
        orch._scheduler_iteration(now=datetime(2026, 9, 1, 12, 1, tzinfo=timezone.utc))
        second_state = json.loads(state_file.read_text())

        with (
            patch.object(orch, "_scheduler_started", True),
            patch.object(orch, "_scheduler_thread", SimpleNamespace(is_alive=lambda: True)),
            patch.object(
                orch,
                "_determine_base_cadence_context",
                return_value={
                    "bucket": "WITHIN_24H_TO_KICKOFF",
                    "cadenceMinutes": 30,
                    "nextKickoffAt": "2026-09-01T18:00:00+00:00",
                    "hoursToNextKickoff": 6.0,
                    "activeWeek": True,
                    "activeSlate": False,
                },
            ),
        ):
            status = orch.get_refresh_status()

    provider_get.assert_not_called()
    assert first_state["lastOddsRefreshExitCode"] == 0
    assert first_state["schedulerHealth"] == "HEALTHY"
    first_next = datetime.fromisoformat(str(first_state["nextRefreshAt"]).replace("Z", "+00:00"))
    second_next = datetime.fromisoformat(str(second_state["nextRefreshAt"]).replace("Z", "+00:00"))
    assert second_next > first_next
    assert status["schedulerHealth"] != "ERROR"
    assert int(status["schedulerRestartCount"] or 0) == 0


def test_get_refresh_status_reports_running_disabled_error_healthy_and_restart_fields(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    (runtime_root / "logs").mkdir(parents=True)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))

    state_file = runtime_root / "logs" / "refresh_state.json"

    def _read_status(payload: dict, *, automation: str, started: bool, alive: bool) -> dict:
        state_file.write_text(json.dumps(payload))
        monkeypatch.setenv("ODDS_REFRESH_AUTOMATION_ENABLED", automation)
        with (
            patch.object(orch, "_STATE_FILE", state_file),
            patch.object(orch, "_scheduler_started", started),
            patch.object(orch, "_scheduler_thread", SimpleNamespace(is_alive=lambda: alive)),
            patch.object(
                orch,
                "_determine_base_cadence_context",
                return_value={
                    "bucket": "ACTIVE_WEEK_GT_24H",
                    "cadenceMinutes": 60,
                    "nextKickoffAt": None,
                    "hoursToNextKickoff": None,
                    "activeWeek": True,
                    "activeSlate": False,
                },
            ),
        ):
            return orch.get_refresh_status()

    running = _read_status(
        {
            "oddsRefreshAutomationEnabled": True,
            "isRunning": True,
            "quotaRemaining": 5000,
            "nextRefreshAt": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
        },
        automation="1",
        started=True,
        alive=True,
    )
    assert running["schedulerHealth"] == "RUNNING"

    disabled = _read_status(
        {
            "oddsRefreshAutomationEnabled": False,
            "quotaRemaining": 5000,
        },
        automation="0",
        started=True,
        alive=True,
    )
    assert disabled["schedulerHealth"] == "DISABLED"

    errored = _read_status(
        {
            "oddsRefreshAutomationEnabled": True,
            "lastSchedulerException": "boom",
            "lastSchedulerExceptionAt": datetime.now(timezone.utc).isoformat(),
            "schedulerRestartCount": 1,
            "schedulerRestartedAt": datetime.now(timezone.utc).isoformat(),
            "quotaRemaining": 5000,
            "nextRefreshAt": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
        },
        automation="1",
        started=True,
        alive=True,
    )
    assert errored["schedulerHealth"] == "ERROR"
    assert errored["schedulerRestartCount"] == 1
    assert errored["schedulerRestartedAt"] is not None

    healthy = _read_status(
        {
            "oddsRefreshAutomationEnabled": True,
            "lastSchedulerException": None,
            "lastError": None,
            "consecutiveFailures": 0,
            "quotaRemaining": 5000,
            "nextRefreshAt": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
        },
        automation="1",
        started=True,
        alive=True,
    )
    assert healthy["schedulerHealth"] == "HEALTHY"
