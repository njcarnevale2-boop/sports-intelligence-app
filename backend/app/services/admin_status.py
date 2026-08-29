from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
from sqlalchemy import text

from app.providers.provider_manager import ProviderManager
from app.services.data_refresh import refresh_all_data
from app.services.injury_history import get_injury_summary
from app.services.odds_status import get_odds_status
from app.services.recommendation_snapshot import get_clv_summary
from app.services.refresh_orchestrator import get_refresh_status
from app.services.social_history import get_query_usage_summary
from app.services.social_intelligence import social_intelligence_service
from app.services.social_sources import get_social_source_coverage_report
from app.services.weather_history import get_weather_summary
from app.services.decision_ledger import get_admin_ledger_summary, get_official_publication_for_week
from app.services.games import service as games_service
from app.runtime_paths import runtime_paths, runtime_readiness
from database.models import PerformanceRecord
from database.session import SessionLocal


MODEL_ROOT = runtime_paths.root
GAME_PROJECTIONS = runtime_paths.current_game_projections_csv


class AdminStatusService:
    def __init__(self) -> None:
        self.session = SessionLocal()
        self.provider_manager = ProviderManager()

    def get_status(self) -> Dict[str, Any]:
        last_refresh = self._read_last_refresh()
        games_loaded = self._count_games()
        opportunities_loaded = self._count_opportunities()
        injuries_loaded = self._count_injuries()
        weather_loaded = self._count_weather()
        database_status = self._database_status()
        error_log = self._error_log()

        provider_metadata = self.provider_manager.metadata()
        odds_status = get_odds_status()
        refresh_status = get_refresh_status()
        clv_summary = get_clv_summary()
        inj_summary = get_injury_summary()
        social_summary = social_intelligence_service.metadata()
        social_coverage = get_social_source_coverage_report()
        social_usage = get_query_usage_summary()
        wx_summary = get_weather_summary()
        ledger_summary = get_admin_ledger_summary(limit=100)
        runtime_status = runtime_readiness()
        api_health = self._api_health(
            database_status=database_status,
            runtime_status=runtime_status,
            refresh_status=refresh_status,
        )
        official_this_week = None
        official_published = False
        try:
            games_payload = games_service.list_games()
            games = games_payload.get("games") or []
            if games:
                season = int(games[0].get("season"))
                week = int(games[0].get("week"))
                official_this_week = get_official_publication_for_week(season, week)
                official_published = official_this_week is not None
        except Exception:
            official_this_week = None
            official_published = False
        inj_provider_meta = provider_metadata.get("injury", {})
        wx_provider_meta  = provider_metadata.get("weather", {})

        return {
            "apiHealth": api_health,
            "lastRefresh": last_refresh,
            "refreshDuration": self._latest_refresh_duration(),
            "gamesLoaded": games_loaded,
            "opportunitiesLoaded": opportunities_loaded,
            "injuriesLoaded": injuries_loaded,
            "weatherLoaded": weather_loaded,
            "databaseStatus": database_status,
            "queueStatus": "running" if refresh_status["isRunning"] else "idle",
            "providerMetadata": {
                **provider_metadata,
                "social": {
                    "provider": social_summary.get("provider", "MOCK"),
                    "lastUpdated": social_summary.get("lastIngestion"),
                    "isLive": social_summary.get("isLive", False),
                    "status": social_summary.get("dataStatus", "MOCK").title(),
                },
            },
            "errorLog": error_log,
            # Live odds fields
            "oddsProvider": odds_status["oddsProvider"],
            "oddsDataStatus": odds_status["oddsDataStatus"],
            "lastLiveOddsRefresh": odds_status["lastLiveOddsRefresh"],
            "oddsGamesUpdated": odds_status["gamesUpdated"],
            "snapshotCount": odds_status["snapshotCount"],
            "apiUsageRemaining": odds_status["apiUsageRemaining"],
            "coreOddsLastRequestCredits": odds_status.get("coreOddsLastRequestCredits"),
            "coreOddsRequestsUsed": odds_status.get("coreOddsRequestsUsed"),
            "coreOddsRequestsRemaining": odds_status.get("coreOddsRequestsRemaining"),
            "coreOddsLastRequestAt": odds_status.get("coreOddsLastRequestAt"),
            "coreOddsRequestShapeId": odds_status.get("coreOddsRequestShapeId"),
            "coreOddsVerifiedRequestCost": odds_status.get("coreOddsVerifiedRequestCost"),
            "coreOddsCostVerificationStatus": odds_status.get("coreOddsCostVerificationStatus"),
            "quotaSafety": odds_status.get("quotaSafety"),
            # Scheduler fields
            "scheduler": refresh_status,
            # CLV / closing line fields
            "closingCaptureLastRun": refresh_status.get("closingCaptureLastRun"),
            "closingLinesCapturedThisRun": refresh_status.get("closingLinesCapturedThisRun", 0),
            "closingCaptureErrors": refresh_status.get("closingCaptureErrors", 0),
            "lastClosingCaptureError": refresh_status.get("lastClosingCaptureError"),
            "closingLinesCaptured": clv_summary["closingLinesCaptured"],
            "pendingClosingLines":  clv_summary["pendingClosingLines"],
            "missingClosingLines":  clv_summary["missingClosingLines"],
            "averageCLV":           clv_summary["averageCLVPoints"],
            # Injury status fields
            "injuryProvider":     inj_provider_meta.get("provider", "ESPN (Public)"),
            "injuryIsLive":       inj_provider_meta.get("isLive", False),
            "injuryDataStatus":   inj_provider_meta.get("dataStatus") or refresh_status.get("injuryDataStatus", "MOCK"),
            "lastInjuryRefresh":  inj_summary.get("lastInjuryRefresh"),
            "injuryPlayersTracked": inj_summary.get("playersTracked", 0),
            "injuryTeamsUpdated": inj_summary.get("teamsUpdated", 0),
            "lastInjuryError":    inj_summary.get("lastInjuryError") or refresh_status.get("lastInjuryError"),
            # Social status fields
            "socialProvider": social_summary.get("provider", "MOCK"),
            "socialIsLive": social_summary.get("isLive", False),
            "socialDataStatus": social_summary.get("dataStatus", "MOCK"),
            "socialSourcesActive": social_summary.get("sourcesActive", 0),
            "socialSignalsDetected": social_summary.get("signalsDetected", 0),
            "socialCorroboratedSignals": social_summary.get("corroboratedSignals", 0),
            "socialOfficialSignals": social_summary.get("officialSignals", 0),
            "lastSocialIngestion": social_summary.get("lastIngestion"),
            "lastSocialError": (social_summary.get("errors") or [None])[0],
            "socialCoveragePercent": social_coverage.get("coveragePercent", 0.0),
            "socialTeamsComplete": social_coverage.get("teamsComplete", 0),
            "socialTeamsPartial": social_coverage.get("teamsPartial", 0),
            "socialTeamsMissing": social_coverage.get("teamsMissing", 0),
            "socialQueriesExecuted": social_usage.get("queriesExecuted", 0),
            "socialPostsRead": social_usage.get("postsRead", 0),
            # Weather status fields
            "weatherProvider":     wx_provider_meta.get("provider", "Open-Meteo (Free)"),
            "weatherIsLive":       wx_provider_meta.get("isLive", False),
            "weatherDataStatus":   wx_provider_meta.get("dataStatus") or refresh_status.get("weatherDataStatus", "MOCK"),
            "lastWeatherRefresh":  wx_summary.get("lastWeatherRefresh"),
            "weatherGamesUpdated": wx_summary.get("gamesUpdated", 0),
            "weatherForecastsAvailable": wx_summary.get("forecastsAvailable", 0),
            "lastWeatherError":    refresh_status.get("lastWeatherError"),
            # Decision ledger
            "ledgerDecisionsRecorded": ledger_summary.get("decisionsRecorded", 0),
            "ledgerOfficialPublications": ledger_summary.get("officialSia3Publications", 0),
            "ledgerLatestPublication": ledger_summary.get("latestPublication"),
            "ledgerIntegrity": ledger_summary.get("ledgerIntegrity"),
            "ledgerOutcomesCaptured": ledger_summary.get("outcomesCaptured", 0),
            "ledgerClosingLinesCaptured": ledger_summary.get("closingLinesCaptured", 0),
            "ledgerMissingOutcomes": ledger_summary.get("missingOutcomes", 0),
            "ledgerMissingClosingLines": ledger_summary.get("missingClosingLines", 0),
            "ledgerMyCardDecisionsCaptured": ledger_summary.get("myCardDecisionsCaptured", 0),
            "ledgerSia3DecisionsCaptured": ledger_summary.get("sia3DecisionsCaptured", 0),
            "ledgerMissingOddsSnapshotLinkages": ledger_summary.get("missingOddsSnapshotLinkages", 0),
            "officialSia3PublishedThisWeek": official_published,
            "officialSia3PublicationTime": None if official_this_week is None else official_this_week.get("publishedAtUTC"),
            "ledgerAuditRows": ledger_summary.get("auditRows", []),
            "runtimeRootConfigured": runtime_status.get("runtimeRootConfigured"),
            "runtimeRoot": runtime_status.get("runtimeRoot"),
            "runtimeRootSource": runtime_status.get("runtimeRootSource"),
            "persistentStorageReady": runtime_status.get("persistentStorageReady"),
            "requiredArtifactsReady": runtime_status.get("requiredArtifactsReady"),
            "missingArtifacts": runtime_status.get("missingArtifacts"),
            "deploymentReadiness": runtime_status.get("deploymentReadiness"),
            "backendReplicaRequirement": runtime_status.get("backendReplicaRequirement"),
            "backendInstanceId": runtime_status.get("backendInstanceId"),
        }

    def _read_last_refresh(self) -> str:
        try:
            result = self.session.query(PerformanceRecord).order_by(PerformanceRecord.created_at.desc()).first()
            if result and result.timestamp:
                return result.timestamp.isoformat()
        except Exception:
            pass
        return datetime.now(timezone.utc).isoformat()

    def _latest_refresh_duration(self) -> float:
        try:
            result = self.session.query(PerformanceRecord).order_by(PerformanceRecord.created_at.desc()).first()
            if result:
                return round(float(result.final_score or 0.0), 3)
        except Exception:
            pass
        return 0.0

    def _count_games(self) -> int:
        if GAME_PROJECTIONS.exists():
            try:
                return int(pd.read_csv(GAME_PROJECTIONS)["api_event_id"].nunique())
            except Exception:
                return 0
        return 0

    def _count_opportunities(self) -> int:
        if GAME_PROJECTIONS.exists():
            try:
                return int(len(pd.read_csv(GAME_PROJECTIONS)))
            except Exception:
                return 0
        return 0

    def _count_injuries(self) -> int:
        try:
            return int(self.session.query(PerformanceRecord).count())
        except Exception:
            return 0

    def _count_weather(self) -> int:
        try:
            return int(self.session.query(PerformanceRecord).count())
        except Exception:
            return 0

    def _database_status(self) -> str:
        try:
            self.session.execute(text("SELECT 1"))
            return "connected"
        except Exception:
            return "disconnected"

    def _api_health(self, *, database_status: str, runtime_status: Dict[str, Any], refresh_status: Dict[str, Any]) -> str:
        if str(runtime_status.get("deploymentReadiness") or "").upper() == "NOT_READY":
            return "degraded"

        if database_status != "connected":
            return "degraded"

        automation_enabled = bool(refresh_status.get("oddsRefreshAutomationEnabled"))
        if automation_enabled and bool(refresh_status.get("lastError")):
            return "degraded"

        return "healthy"

    def _error_log(self) -> List[Dict[str, Any]]:
        return [
            {"timestamp": datetime.now(timezone.utc).isoformat(), "message": "No recent errors"}
        ]


def get_admin_status_service() -> AdminStatusService:
    return AdminStatusService()
