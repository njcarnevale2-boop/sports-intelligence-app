from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
    ):
        assert orch._run_once() is False

    status = json.loads(state_file.read_text())
    assert status["lastRefreshAt"] is None
    assert status["lastAttemptAt"] is not None
    assert status["consecutiveFailures"] == 1
    assert status["isRunning"] is False
    assert "odds_refresh failed" in str(status["lastError"])

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
