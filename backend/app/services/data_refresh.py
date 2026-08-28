from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from app.runtime_paths import runtime_paths
from app.services.executive_analyst import generate_executive_analysis
from app.services.injury_matchup import InjuryMatchupContext
from app.services.market_intelligence import get_market_intelligence
from app.services.sports_intelligence_score import calculate_sports_intelligence_score
from app.services.weather import WeatherAnalyzer


MODEL_ROOT = runtime_paths.root
GAME_PROJECTIONS = runtime_paths.current_game_projections_csv


class DataRefreshService:
    def __init__(self) -> None:
        self.errors: List[str] = []

    def refresh_all_data(self) -> Dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        self.errors = []

        try:
            if not GAME_PROJECTIONS.exists():
                raise FileNotFoundError("Game projections file not found")

            df = pd.read_csv(GAME_PROJECTIONS)
            games_updated = int(df["api_event_id"].nunique()) if not df.empty else 0
            opportunities_updated = int(len(df)) if not df.empty else 0

            refreshed: List[Dict[str, Any]] = []
            for _, row in df.iterrows():
                try:
                    opportunity = self._build_refreshed_opportunity(row)
                    refreshed.append(opportunity)
                except Exception as exc:  # pragma: no cover - defensive logging
                    self.errors.append(f"{row.get('api_event_id', 'unknown')}: {exc}")

            ended_at = datetime.now(timezone.utc)
            duration = round((ended_at - started_at).total_seconds(), 3)

            return {
                "success": True,
                "duration": duration,
                "gamesUpdated": games_updated,
                "opportunitiesUpdated": opportunities_updated,
                "timestamp": ended_at.isoformat(),
                "errors": self.errors,
                "refreshed": refreshed[:1],
            }
        except Exception as exc:  # pragma: no cover - defensive logging
            ended_at = datetime.now(timezone.utc)
            duration = round((ended_at - started_at).total_seconds(), 3)
            self.errors.append(str(exc))
            return {
                "success": False,
                "duration": duration,
                "gamesUpdated": 0,
                "opportunitiesUpdated": 0,
                "timestamp": ended_at.isoformat(),
                "errors": self.errors,
            }

    def _build_refreshed_opportunity(self, row: pd.Series) -> Dict[str, Any]:
        opportunity = {
            "eventId": str(row["api_event_id"]),
            "awayTeam": str(row["away_team"]),
            "homeTeam": str(row["home_team"]),
            "market": str(row["market"]),
            "side": str(row["side"]),
            "point": float(row["point"]),
            "price": float(row["price"]),
            "edge": float(row["edge_pp"]),
            "evPerDollar": float(row["ev_per_dollar"]),
            "confidence": float(row["confidence_score"]),
            "dataCompleteness": float(row["data_completeness"] * 100),
        }

        market_intelligence = get_market_intelligence(
            event_id=str(row["api_event_id"]),
            market=str(row["market"]),
            side=str(row["side"]),
        )
        injury_context = InjuryMatchupContext().build_context(
            away_team=str(row["away_team"]),
            home_team=str(row["home_team"]),
        )
        weather_context = WeatherAnalyzer().analyze()
        sports_score = calculate_sports_intelligence_score(
            opportunity=opportunity,
            market_intelligence=market_intelligence,
        )
        executive_analysis = generate_executive_analysis(
            {
                **opportunity,
                "marketIntelligence": market_intelligence,
                "injuryContext": injury_context,
                "sportsIntelligenceScore": sports_score,
            }
        )

        opportunity["marketIntelligence"] = market_intelligence
        opportunity["injuryContext"] = injury_context
        opportunity["weatherContext"] = weather_context
        opportunity["sportsIntelligenceScore"] = sports_score
        opportunity["executiveAnalysis"] = executive_analysis
        return opportunity


def refresh_all_data() -> Dict[str, Any]:
    return DataRefreshService().refresh_all_data()
