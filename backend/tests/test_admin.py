from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import text

from fastapi.testclient import TestClient

from app.main import app
from app.services.admin_status import AdminStatusService


client = TestClient(app)


def test_admin_status_endpoint_returns_metrics():
    response = client.get("/api/admin/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["apiHealth"] in {"healthy", "degraded"}
    assert "lastRefresh" in payload
    assert "gamesLoaded" in payload
    assert "opportunitiesLoaded" in payload
    assert "databaseStatus" in payload
    assert "queueStatus" in payload
    assert "errorLog" in payload
    # Odds fields
    assert "oddsProvider" in payload
    assert "oddsDataStatus" in payload
    assert "snapshotCount" in payload
    assert "coreOddsLastRequestCredits" in payload
    assert "coreOddsRequestsUsed" in payload
    assert "coreOddsRequestsRemaining" in payload
    assert "coreOddsLastRequestAt" in payload
    assert "quotaSafety" in payload
    assert "socialProvider" in payload
    assert "socialDataStatus" in payload
    assert "socialSourcesActive" in payload
    assert "socialCoveragePercent" in payload
    # Ledger fields
    assert "ledgerMyCardDecisionsCaptured" in payload
    assert "ledgerSia3DecisionsCaptured" in payload
    assert "ledgerMissingOddsSnapshotLinkages" in payload
    assert "officialSia3PublishedThisWeek" in payload
    assert "officialSia3PublicationTime" in payload
    assert "runtimeRootConfigured" in payload
    assert "runtimeRoot" in payload
    assert "runtimeRootSource" in payload
    assert "persistentStorageReady" in payload
    assert "requiredArtifactsReady" in payload
    assert "missingArtifacts" in payload
    assert "deploymentReadiness" in payload
    assert "backendReplicaRequirement" in payload
    assert payload["backendReplicaRequirement"] == 1
    assert "backendInstanceId" in payload
    # Scheduler fields
    assert "scheduler" in payload
    sched = payload["scheduler"]
    assert "isRunning" in sched
    assert "cadenceMinutes" in sched
    assert "quotaRemaining" in sched
    assert "quotaPaused" in sched


def test_admin_refresh_status_endpoint():
    response = client.get("/api/admin/refresh-status")
    assert response.status_code == 200
    payload = response.json()
    assert "isRunning" in payload
    assert "cadenceMinutes" in payload
    assert "provider" in payload
    assert payload["provider"] == "The Odds API"


def test_admin_refresh_endpoint_returns_summary():
    response = client.post("/api/admin/refresh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "timestamp" in payload
    assert "oddsRefresh" in payload
    assert payload["oddsRefresh"]["triggered"] is False
    assert payload["oddsRefresh"]["reason"] == "SPORTSBOOK_REFRESH_NOT_REQUESTED"


def test_admin_refresh_default_does_not_trigger_sportsbook_provider_calls():
    with patch("app.routes.admin_status.trigger_now") as trigger_now:
        response = client.post("/api/admin/refresh")

    assert response.status_code == 200
    trigger_now.assert_not_called()


def test_admin_refresh_can_trigger_sportsbook_refresh_only_with_explicit_opt_in_and_overrides():
    with (
        patch("app.routes.admin_status.evaluate_optional_provider_request", return_value={
            "allowed": True,
            "reason": None,
            "warnings": [],
            "quotaSafety": {"weeklyUsageStatus": "UNKNOWN"},
        }),
        patch("app.routes.admin_status.trigger_now", return_value={"triggered": True, "success": True}) as trigger_now,
    ):
        response = client.post(
            "/api/admin/refresh?sportsbookRefresh=true&allowUnknownCreditCost=true&allowUnknownWeeklyUsage=true"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["oddsRefresh"]["triggered"] is True
    trigger_now.assert_called_once()


def test_admin_social_sources_coverage_endpoint():
    response = client.get("/api/admin/social-sources/coverage")
    assert response.status_code == 200
    payload = response.json()
    assert payload["teamsCovered"] == 32
    assert "teams" in payload


def test_database_status_uses_sqlalchemy_text_clause():
    service = AdminStatusService()

    class _FakeSession:
        def execute(self, stmt):
            assert str(stmt) == str(text("SELECT 1"))

    service.session = _FakeSession()
    assert service._database_status() == "connected"


def test_api_health_stays_healthy_when_automation_intentionally_disabled():
    service = AdminStatusService()

    with (
        patch.object(service, "_read_last_refresh", return_value="2026-09-01T12:00:00+00:00"),
        patch.object(service, "_latest_refresh_duration", return_value=0.0),
        patch.object(service, "_count_games", return_value=16),
        patch.object(service, "_count_opportunities", return_value=16),
        patch.object(service, "_count_injuries", return_value=0),
        patch.object(service, "_count_weather", return_value=0),
        patch.object(service, "_database_status", return_value="connected"),
        patch.object(service, "_error_log", return_value=[]),
        patch("app.services.admin_status.get_refresh_status", return_value={
            "isRunning": False,
            "lastError": None,
            "lastRefreshAt": None,
            "nextRefreshAt": None,
            "cadenceMinutes": None,
            "consecutiveFailures": 0,
            "quotaRemaining": None,
            "quotaPaused": False,
            "provider": "The Odds API",
            "oddsRefreshAutomationEnabled": False,
            "oddsRefreshAutomationState": "DISABLED",
            "pregameAutomationEnabled": False,
            "pregameLastStatus": "DISABLED",
            "pregameLastSkipReason": "PREGAME_AUTOMATION_DISABLED",
            "pregameLastProviderRequests": 0,
            "pregameLastVerifiedCredits": 0.0,
        }),
        patch("app.services.admin_status.get_odds_status", return_value={
            "oddsProvider": "The Odds API",
            "oddsDataStatus": "STALE",
            "lastLiveOddsRefresh": None,
            "gamesUpdated": 0,
            "snapshotCount": 0,
            "apiUsageRemaining": 19604,
        }),
        patch("app.services.admin_status.get_clv_summary", return_value={
            "closingLinesCaptured": 0,
            "pendingClosingLines": 0,
            "missingClosingLines": 0,
            "averageCLVPoints": None,
        }),
        patch("app.services.admin_status.get_injury_summary", return_value={
            "lastInjuryRefresh": None,
            "playersTracked": 0,
            "teamsUpdated": 0,
            "lastInjuryError": None,
        }),
        patch("app.services.admin_status.get_social_source_coverage_report", return_value={
            "coveragePercent": 100.0,
            "teamsComplete": 32,
            "teamsPartial": 0,
            "teamsMissing": 0,
        }),
        patch("app.services.admin_status.get_query_usage_summary", return_value={
            "queriesExecuted": 0,
            "postsRead": 0,
        }),
        patch("app.services.admin_status.get_weather_summary", return_value={
            "lastWeatherRefresh": None,
            "gamesUpdated": 0,
            "forecastsAvailable": 0,
        }),
        patch("app.services.admin_status.get_admin_ledger_summary", return_value={
            "decisionsRecorded": 0,
            "officialSia3Publications": 0,
            "latestPublication": None,
            "ledgerIntegrity": "OK",
            "outcomesCaptured": 0,
            "closingLinesCaptured": 0,
            "missingOutcomes": 0,
            "missingClosingLines": 0,
            "myCardDecisionsCaptured": 0,
            "sia3DecisionsCaptured": 0,
            "missingOddsSnapshotLinkages": 0,
            "auditRows": [],
        }),
        patch("app.services.admin_status.runtime_readiness", return_value={
            "runtimeRootConfigured": True,
            "runtimeRoot": "/data/NFL_Analytics_OS_v1_9",
            "runtimeRootSource": "env",
            "persistentStorageReady": True,
            "requiredArtifactsReady": True,
            "missingArtifacts": [],
            "deploymentReadiness": "READY",
            "backendReplicaRequirement": 1,
            "backendInstanceId": "node:123",
        }),
        patch("app.services.admin_status.games_service") as games_service,
        patch("app.services.admin_status.get_official_publication_for_week", return_value=None),
    ):
        service.provider_manager = SimpleNamespace(
            metadata=lambda: {
                "injury": {"provider": "ESPN", "isLive": False, "dataStatus": "MOCK"},
                "weather": {"provider": "Open-Meteo", "isLive": False, "dataStatus": "MOCK"},
            }
        )
        games_service.list_games.return_value = {
            "games": [{"season": 2026, "week": 1}],
        }

        payload = service.get_status()

    assert payload["databaseStatus"] == "connected"
    assert payload["apiHealth"] == "healthy"
