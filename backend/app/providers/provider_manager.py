from __future__ import annotations

import os
from typing import Any, Dict, Optional

from app.providers.espn_injury_provider import ESPNInjuryProvider
from app.providers.mock_provider import MockProvider
from app.providers.odds_provider import OddsProvider
from app.providers.sportsradar_provider import SportsRadarProvider
from app.providers.weather_provider import WeatherProvider


class ProviderManager:
    def __init__(self) -> None:
        self.sportsradar_api_key = os.getenv("SPORTSRADAR_API_KEY", "")
        self.weather_api_key = os.getenv("WEATHER_API_KEY", "")
        self.odds_api_key = os.getenv("ODDS_API_KEY", "")
        # INJURY_PROVIDER: "espn" (default, no key needed) | "sportsradar" | "mock"
        self.injury_provider_name = os.getenv("INJURY_PROVIDER", "espn").lower().strip()
        self.use_mock_weather = os.getenv("USE_MOCK_WEATHER", "true").lower() in {"1", "true", "yes"}

    def get_injury_provider(self) -> Any:
        if self.injury_provider_name == "sportsradar" and self.sportsradar_api_key:
            return SportsRadarProvider(self.sportsradar_api_key)
        if self.injury_provider_name == "mock":
            return MockProvider()
        # Default: ESPN public API (no credentials required)
        return ESPNInjuryProvider()

    def get_weather_provider(self) -> Any:
        if self.use_mock_weather or not self.weather_api_key:
            return MockProvider()
        return WeatherProvider(self.weather_api_key)

    def get_odds_provider(self) -> Any:
        if not self.odds_api_key:
            return MockProvider()
        return OddsProvider(self.odds_api_key)

    def metadata(self) -> Dict[str, Dict[str, Any]]:
        return {
            "injury": self.get_injury_provider().get_metadata(),
            "weather": self.get_weather_provider().get_metadata(),
            "odds": self.get_odds_provider().get_metadata(),
        }
