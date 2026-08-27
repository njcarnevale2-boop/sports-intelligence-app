from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from app.services import refresh_orchestrator as orch


def _schedule(*, standard_due: int, prop_due: int, next_state: str | None = "OPENING") -> dict:
    return {
        "policy": {
            "windows": {
                "openingHoursGreaterThan": 24,
                "closingHoursAtMost": 2,
            }
        },
        "events": [
            {
                "kickoff": "2026-09-10T00:15:00+00:00",
            }
        ],
        "totals": {
            "standardSnapshotsDue": standard_due,
            "playerPropSnapshotsDue": prop_due,
            "nextCollectionWindow": next_state,
        },
    }


def test_pregame_automation_disabled_zero_execution(monkeypatch):
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "0")
    with patch("app.services.pregame_collection_manager.build_pregame_collection_schedule_v1") as schedule_mock:
        out = orch._run_pregame_automation_tick()

    assert out["enabled"] is False
    assert out["status"] == "DISABLED"
    assert out["providerRequests"] == 0
    schedule_mock.assert_not_called()


def test_pregame_automation_enabled_nothing_due_zero_provider_requests(monkeypatch):
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "1")
    with (
        patch("app.services.pregame_collection_manager.build_pregame_collection_schedule_v1", return_value=_schedule(standard_due=0, prop_due=0, next_state="OPENING")),
        patch("app.services.pregame_collection_manager.run_pregame_collection_manager") as run_mock,
    ):
        out = orch._run_pregame_automation_tick()

    assert out["status"] == "NO_WORK_DUE"
    assert out["providerRequests"] == 0
    run_mock.assert_not_called()


def test_pregame_automation_opening_due_executes_standard_zero_provider(monkeypatch):
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "1")
    with (
        patch("app.services.pregame_collection_manager.build_pregame_collection_schedule_v1", return_value=_schedule(standard_due=3, prop_due=0, next_state="OPENING")),
        patch(
            "app.services.pregame_collection_manager.run_pregame_collection_manager",
            return_value={
                "status": "COMPLETED",
                "plan": {"estimatedCreditsStatus": "VERIFIED", "estimatedCredits": 0.0},
                "execution": {"providerRequests": 0},
            },
        ) as run_mock,
    ):
        out = orch._run_pregame_automation_tick()

    assert out["status"] == "COMPLETED"
    assert out["providerRequests"] == 0
    run_mock.assert_called_once_with(dry_run=False)


def test_pregame_automation_game_day_due_player_props_enforces_verified_budget(monkeypatch):
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "1")
    due_events = 2
    with (
        patch("app.services.pregame_collection_manager.build_pregame_collection_schedule_v1", return_value=_schedule(standard_due=0, prop_due=due_events, next_state="GAME_DAY")),
        patch(
            "app.services.pregame_collection_manager.run_pregame_collection_manager",
            return_value={
                "status": "COMPLETED",
                "plan": {"estimatedCreditsStatus": "VERIFIED", "estimatedCredits": 12.0},
                "execution": {"providerRequests": due_events},
            },
        ),
    ):
        out = orch._run_pregame_automation_tick()

    assert out["status"] == "COMPLETED"
    assert out["providerRequests"] == due_events
    assert out["verifiedCredits"] == 12.0


def test_repeated_game_day_tick_after_success_makes_zero_duplicate_provider_requests(monkeypatch):
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "1")

    schedules = [
        _schedule(standard_due=0, prop_due=2, next_state="GAME_DAY"),
        _schedule(standard_due=0, prop_due=0, next_state="GAME_DAY"),
    ]
    with (
        patch("app.services.pregame_collection_manager.build_pregame_collection_schedule_v1", side_effect=schedules),
        patch(
            "app.services.pregame_collection_manager.run_pregame_collection_manager",
            return_value={
                "status": "COMPLETED",
                "plan": {"estimatedCreditsStatus": "VERIFIED", "estimatedCredits": 12.0},
                "execution": {"providerRequests": 2},
            },
        ) as run_mock,
    ):
        first = orch._run_pregame_automation_tick()
        second = orch._run_pregame_automation_tick()

    assert first["providerRequests"] == 2
    assert second["providerRequests"] == 0
    assert second["status"] == "NO_WORK_DUE"
    assert run_mock.call_count == 1


def test_pregame_automation_closing_due_standard_only_zero_player_prop_provider(monkeypatch):
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "1")
    with (
        patch("app.services.pregame_collection_manager.build_pregame_collection_schedule_v1", return_value=_schedule(standard_due=5, prop_due=0, next_state="CLOSING")),
        patch(
            "app.services.pregame_collection_manager.run_pregame_collection_manager",
            return_value={
                "status": "COMPLETED",
                "plan": {"estimatedCreditsStatus": "VERIFIED", "estimatedCredits": 0.0},
                "execution": {"providerRequests": 0},
            },
        ),
    ):
        out = orch._run_pregame_automation_tick()

    assert out["status"] == "COMPLETED"
    assert out["providerRequests"] == 0


def test_pregame_automation_post_kickoff_zero_provider_requests(monkeypatch):
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "1")
    with (
        patch("app.services.pregame_collection_manager.build_pregame_collection_schedule_v1", return_value=_schedule(standard_due=0, prop_due=0, next_state=None)),
        patch("app.services.pregame_collection_manager.run_pregame_collection_manager") as run_mock,
    ):
        out = orch._run_pregame_automation_tick()

    assert out["providerRequests"] == 0
    assert out["status"] == "NO_WORK_DUE"
    run_mock.assert_not_called()


def test_pregame_automation_unknown_cost_blocks_provider_execution(monkeypatch):
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "1")
    with (
        patch("app.services.pregame_collection_manager.build_pregame_collection_schedule_v1", return_value=_schedule(standard_due=0, prop_due=1, next_state="GAME_DAY")),
        patch(
            "app.services.pregame_collection_manager.run_pregame_collection_manager",
            return_value={
                "status": "SKIPPED",
                "plan": {"estimatedCreditsStatus": "UNKNOWN", "estimatedCredits": None},
                "execution": {"providerRequests": 0, "skipReason": "UNKNOWN_PROVIDER_CREDIT_COST"},
            },
        ),
    ):
        out = orch._run_pregame_automation_tick()

    assert out["status"] == "SKIPPED"
    assert out["skipReason"] == "UNKNOWN_PROVIDER_CREDIT_COST"
    assert out["providerRequests"] == 0
    assert out["verifiedCredits"] is None


def test_pregame_automation_budget_exceeded_blocks_provider_execution(monkeypatch):
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "1")
    with (
        patch("app.services.pregame_collection_manager.build_pregame_collection_schedule_v1", return_value=_schedule(standard_due=0, prop_due=3, next_state="GAME_DAY")),
        patch(
            "app.services.pregame_collection_manager.run_pregame_collection_manager",
            return_value={
                "status": "SKIPPED",
                "plan": {"estimatedCreditsStatus": "VERIFIED", "estimatedCredits": 18.0},
                "execution": {"providerRequests": 0, "skipReason": "REQUEST_BUDGET_EXCEEDED"},
            },
        ),
    ):
        out = orch._run_pregame_automation_tick()

    assert out["status"] == "SKIPPED"
    assert out["skipReason"] == "REQUEST_BUDGET_EXCEEDED"
    assert out["providerRequests"] == 0


def test_pregame_automation_exception_is_non_fatal(monkeypatch):
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "1")
    with patch("app.services.pregame_collection_manager.build_pregame_collection_schedule_v1", side_effect=RuntimeError("boom")):
        out = orch._run_pregame_automation_tick()

    assert out["status"] == "ERROR"
    assert out["providerRequests"] == 0
    assert out["success"] is False


def test_run_once_survives_pregame_exception_and_preserves_postgame(tmp_path, monkeypatch):
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "1")
    state_file = tmp_path / "state.json"
    success = SimpleNamespace(returncode=0, stdout="ok", stderr="")

    with (
        patch.object(orch, "_STATE_FILE", state_file),
        patch.object(orch.subprocess, "run", side_effect=lambda *args, **kwargs: success),
        patch("app.services.pregame_collection_manager.build_pregame_collection_schedule_v1", side_effect=RuntimeError("pregame failed")),
        patch("app.services.recommendation_snapshot.capture_closing_lines", return_value={"eligible": 0, "captured": 0, "pending": 0, "missing": 0, "errors": 0}),
        patch("app.services.decision_ledger.run_official_postgame_lifecycle", return_value={"checked": 1, "settled": 1, "pending": 0}) as lifecycle_mock,
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
        lifecycle_mock.assert_called_once()

    status = json.loads(state_file.read_text())
    assert status["lastError"] is None
    assert status["pregameLastStatus"] == "ERROR"


def test_run_once_postgame_lifecycle_still_runs_when_pregame_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("PREGAME_AUTOMATION_ENABLED", "0")
    state_file = tmp_path / "state.json"
    success = SimpleNamespace(returncode=0, stdout="ok", stderr="")

    with (
        patch.object(orch, "_STATE_FILE", state_file),
        patch.object(orch.subprocess, "run", side_effect=lambda *args, **kwargs: success),
        patch("app.services.recommendation_snapshot.capture_closing_lines", return_value={"eligible": 0, "captured": 0, "pending": 0, "missing": 0, "errors": 0}),
        patch("app.services.decision_ledger.run_official_postgame_lifecycle", return_value={"checked": 2, "settled": 1, "pending": 1}) as lifecycle_mock,
        patch("app.services.shadow_markets.append_shadow_outcomes", return_value={"checked": 1, "appended": 0, "pending": 1}),
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
        lifecycle_mock.assert_called_once()

    status = json.loads(state_file.read_text())
    assert status["lastError"] is None
    assert status["pregameAutomationEnabled"] is False
    assert status["pregameLastStatus"] == "DISABLED"
