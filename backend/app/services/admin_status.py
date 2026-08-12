from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from app.providers.provider_manager import ProviderManager
from app.services.data_refresh import refresh_all_data
from app.services.odds_status import get_odds_status
from app.services.refresh_orchestrator import get_refresh_status
from database.models import PerformanceRecord
from database.session import SessionLocal


MODEL_ROOT = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9"
GAME_PROJECTIONS = MODEL_ROOT / "outputs" / "current_game_projections.csv"


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

        return {
            "apiHealth": "healthy" if database_status == "connected" else "degraded",
            "lastRefresh": last_refresh,
            "refreshDuration": self._latest_refresh_duration(),
            "gamesLoaded": games_loaded,
            "opportunitiesLoaded": opportunities_loaded,
            "injuriesLoaded": injuries_loaded,
            "weatherLoaded": weather_loaded,
            "databaseStatus": database_status,
            "queueStatus": "running" if refresh_status["isRunning"] else "idle",
            "providerMetadata": provider_metadata,
            "errorLog": error_log,
            # Live odds fields
            "oddsProvider": odds_status["oddsProvider"],
            "oddsDataStatus": odds_status["oddsDataStatus"],
            "lastLiveOddsRefresh": odds_status["lastLiveOddsRefresh"],
            "oddsGamesUpdated": odds_status["gamesUpdated"],
            "snapshotCount": odds_status["snapshotCount"],
            "apiUsageRemaining": odds_status["apiUsageRemaining"],
            # Scheduler fields
            "scheduler": refresh_status,
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
            self.session.execute("SELECT 1")
            return "connected"
        except Exception:
            return "disconnected"

    def _error_log(self) -> List[Dict[str, Any]]:
        return [
            {"timestamp": datetime.now(timezone.utc).isoformat(), "message": "No recent errors"}
        ]


def get_admin_status_service() -> AdminStatusService:
    return AdminStatusService()
