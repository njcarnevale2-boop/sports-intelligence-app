from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

from app.providers.provider_manager import ProviderManager

log = logging.getLogger("weather")

# Mock weather only when WEATHER_PROVIDER=mock; never silent fallthrough from live
_ALLOW_MOCK = os.getenv("ALLOW_MOCK_WEATHER", "true").lower() in {"1", "true", "yes"}


class WeatherAnalyzer:
    """
    Evaluate NFL game-time weather with live/cached/mock/unavailable transparency.

    Data priority
    ─────────────
    1. Live provider (WEATHER_PROVIDER=openmeteo) per home-team + kickoff
       • LIVE response     → return forecast, status=LIVE
       • UNAVAILABLE       → fall to cache
       • provider error    → fall to cache
    2. DuckDB cached snapshot  → status=CACHED
    3. Mock data  → only when WEATHER_PROVIDER=mock (never silently in prod)
    4. UNAVAILABLE  → no data, no mock allowed

    The scoring / impact logic is unchanged from the original implementation.
    """

    def __init__(
        self,
        weather_data: Optional[Dict[str, Any]] = None,
        home_team: Optional[str] = None,
        kickoff: Optional[datetime] = None,
    ):
        self.provider_manager = ProviderManager()
        self.provider = self.provider_manager.get_weather_provider()
        self.provider_metadata = self.provider.get_metadata()
        self._data_status = "MOCK"
        self._last_updated: Optional[str] = None

        if weather_data is not None:
            # Explicitly supplied data (tests / direct callers)
            self.weather_data = weather_data
            self._data_status = "MOCK"
        else:
            self.weather_data = self._load_weather(home_team, kickoff)

    def _using_mock_provider(self) -> bool:
        return self.provider_manager.weather_provider_name == "mock"

    def _load_weather(
        self,
        home_team: Optional[str],
        kickoff: Optional[datetime],
    ) -> Dict[str, Any]:
        """Fetch live weather with cached / mock fallback."""
        from app.services.weather_history import (
            detect_changes, get_cached_weather, store_changes, store_snapshot,
        )

        # ── live provider path ─────────────────────────────────────────────
        if hasattr(self.provider, "fetch_game_weather"):
            try:
                result = self.provider.fetch_game_weather(
                    home_team=home_team or "",
                    kickoff_utc=kickoff,
                )
                provider_name = result.get("provider", self.provider.provider_name)
                is_live = result.get("dataStatus") == "LIVE"

                if is_live:
                    if home_team:
                        changes = detect_changes(result, home_team)
                        if changes:
                            store_changes(changes, provider_name)
                        store_snapshot(result, home_team, kickoff_time=kickoff)

                    log.info(
                        "Live weather: team=%s temp=%s wind=%s conditions=%s",
                        home_team, result.get("temperature"),
                        result.get("windSpeed"), result.get("conditions"),
                    )
                    self.provider_metadata = {
                        **self.provider_metadata,
                        "provider": provider_name, "isLive": True,
                        "dataStatus": "LIVE", "lastUpdated": result.get("lastUpdated"),
                        "recordCount": result.get("recordCount", 1),
                    }
                    self._data_status  = "LIVE"
                    self._last_updated = result.get("lastUpdated")
                    return result   # ← exit immediately; never fall through when LIVE

                # Non-LIVE response (e.g. forecast window exceeded)
                log.info("Weather provider returned non-LIVE: %s", result.get("reason", ""))
            except Exception as exc:
                log.warning("Live weather fetch exception: %s", exc)

        # ── cached fallback ────────────────────────────────────────────────
        if home_team:
            cached = get_cached_weather(home_team)
            if cached:
                log.info("Using cached weather for %s", home_team)
                self.provider_metadata = {
                    **self.provider_metadata,
                    "isLive": False, "dataStatus": "CACHED",
                    "lastUpdated": cached.get("lastUpdated"),
                    "recordCount": 1,
                }
                self._data_status  = "CACHED"
                self._last_updated = cached.get("lastUpdated")
                return cached

        # ── mock — only for explicit mock provider ─────────────────────────
        if self._using_mock_provider() and _ALLOW_MOCK:
            log.info("Using mock weather (WEATHER_PROVIDER=mock)")
            self.provider_metadata = {
                **self.provider_metadata,
                "isLive": False, "dataStatus": "MOCK", "recordCount": 0,
            }
            self._data_status = "MOCK"
            return self._mock_weather()

        # ── unavailable ────────────────────────────────────────────────────
        log.warning("Weather data unavailable (team=%s, provider=%s)",
                    home_team, self.provider_manager.weather_provider_name)
        self.provider_metadata = {
            **self.provider_metadata,
            "isLive": False, "dataStatus": "UNAVAILABLE", "recordCount": 0,
        }
        self._data_status = "UNAVAILABLE"
        return {}

    def analyze(self) -> Dict[str, Any]:
        """Return a weather intelligence snapshot with impact estimates."""

        weather = self.weather_data or {}
        stadium_type = str(weather.get("stadiumType", "")).lower()
        surface = str(weather.get("surface", "")).lower()

        if stadium_type in {"indoor", "dome", "closed"}:
            return {
                "weatherScore": 100.0,
                "passingImpact": 0.0, "rushingImpact": 0.0, "kickingImpact": 0.0,
                "totalImpact": 0.0,
                "summary": "Indoor conditions are neutral and should not materially affect gameplay.",
                "recommendation": "Neutral",
                "providerMetadata": self.provider_metadata,
                "dataMode": self._data_status.lower(),
                "provider":    self.provider_metadata.get("provider", "Unknown"),
                "isLive":      self._data_status == "LIVE",
                "lastUpdated": self._last_updated or self.provider_metadata.get("lastUpdated"),
                "dataStatus":  self._data_status,
                "recordCount": self.provider_metadata.get("recordCount", 1),
                "temperature": weather.get("temperature", 72), "windSpeed": 0.0,
                "windGust": 0.0, "windDirection": "N/A",
                "precipitationProbability": 0.0, "precipitationAmount": 0.0,
                "humidity": weather.get("humidity", 50),
                "conditions": "Indoor — climate controlled",
                "forecastTimestamp": weather.get("forecastTimestamp"),
                "stadiumType": weather.get("stadiumType", "DOME"),
                "surface": weather.get("surface"),
            }

        temperature = float(weather.get("temperature", 70) or 70)
        wind_speed = float(weather.get("windSpeed", 0) or 0)
        # Support both "precipitation" (legacy mock) and "precipitationAmount" (live)
        precipitation = float(weather.get("precipitationAmount") or weather.get("precipitation", 0) or 0)
        humidity = float(weather.get("humidity", 50) or 50)

        weather_score = self._calculate_weather_score(
            temperature,
            wind_speed,
            precipitation,
            humidity,
            surface,
        )

        passing_impact = self._calculate_passing_impact(
            wind_speed,
            precipitation,
            humidity,
            temperature,
        )
        rushing_impact = self._calculate_rushing_impact(
            wind_speed,
            precipitation,
            temperature,
        )
        kicking_impact = self._calculate_kicking_impact(
            wind_speed,
            precipitation,
            temperature,
        )
        total_impact = round(
            clamp(passing_impact + rushing_impact + kicking_impact, 0.0, 100.0),
            1,
        )

        summary = self._build_summary(weather_score, total_impact)
        recommendation = self._recommendation(weather_score, total_impact)

        return {
            "weatherScore": round(weather_score, 1),
            "passingImpact": round(passing_impact, 1),
            "rushingImpact": round(rushing_impact, 1),
            "kickingImpact": round(kicking_impact, 1),
            "totalImpact": total_impact,
            "summary": summary,
            "recommendation": recommendation,
            "providerMetadata": self.provider_metadata,
            "dataMode": self._data_status.lower(),
            # Transparency fields (mirrors injury pattern)
            "provider":    self.provider_metadata.get("provider", "Unknown"),
            "isLive":      self._data_status == "LIVE",
            "lastUpdated": self._last_updated or self.provider_metadata.get("lastUpdated"),
            "dataStatus":  self._data_status,
            "recordCount": self.provider_metadata.get("recordCount", 1 if self.weather_data else 0),
            # Raw forecast fields surfaced for game intelligence UI
            "temperature":             self.weather_data.get("temperature"),
            "windSpeed":               self.weather_data.get("windSpeed"),
            "windGust":                self.weather_data.get("windGust"),
            "windDirection":           self.weather_data.get("windDirection"),
            "precipitationProbability": self.weather_data.get("precipitationProbability"),
            "precipitationAmount":     self.weather_data.get("precipitationAmount"),
            "humidity":                self.weather_data.get("humidity"),
            "conditions":              self.weather_data.get("conditions"),
            "forecastTimestamp":       self.weather_data.get("forecastTimestamp"),
            "stadiumType":             self.weather_data.get("stadiumType"),
            "surface":                 self.weather_data.get("surface"),
        }

    def _mock_weather(self) -> Dict[str, Any]:
        return {
            "temperature": 42,
            "windSpeed": 18,
            "windDirection": "NW",
            "precipitation": 0.2,
            "humidity": 78,
            "stadiumType": "outdoor",
            "surface": "grass",
        }

    def _calculate_weather_score(
        self,
        temperature: float,
        wind_speed: float,
        precipitation: float,
        humidity: float,
        surface: str,
    ) -> float:
        score = 100.0

        if temperature < 35:
            score -= 10
        elif temperature > 85:
            score -= 8

        if wind_speed >= 20:
            score -= 18
        elif wind_speed >= 12:
            score -= 10
        elif wind_speed >= 6:
            score -= 4

        if precipitation >= 0.25:
            score -= 20
        elif precipitation > 0:
            score -= 8

        if humidity >= 80:
            score -= 4

        if surface == "artificial":
            score -= 2

        return clamp(score, 0.0, 100.0)

    def _calculate_passing_impact(
        self,
        wind_speed: float,
        precipitation: float,
        humidity: float,
        temperature: float,
    ) -> float:
        impact = 0.0
        if wind_speed >= 20:
            impact += 22
        elif wind_speed >= 12:
            impact += 14
        elif wind_speed >= 6:
            impact += 6

        if precipitation >= 0.25:
            impact += 16
        elif precipitation > 0:
            impact += 6

        if humidity >= 80:
            impact += 4

        if temperature < 32:
            impact += 4

        return clamp(impact, 0.0, 100.0)

    def _calculate_rushing_impact(
        self,
        wind_speed: float,
        precipitation: float,
        temperature: float,
    ) -> float:
        impact = 0.0
        if wind_speed >= 20:
            impact += 8
        elif wind_speed >= 12:
            impact += 5

        if precipitation >= 0.25:
            impact += 4
        elif precipitation > 0:
            impact += 2

        if temperature < 32:
            impact += 2

        return clamp(impact, 0.0, 100.0)

    def _calculate_kicking_impact(
        self,
        wind_speed: float,
        precipitation: float,
        temperature: float,
    ) -> float:
        impact = 0.0
        if wind_speed >= 20:
            impact += 18
        elif wind_speed >= 12:
            impact += 12
        elif wind_speed >= 6:
            impact += 6

        if precipitation >= 0.25:
            impact += 14
        elif precipitation > 0:
            impact += 6

        if temperature < 32:
            impact += 4

        return clamp(impact, 0.0, 100.0)

    def _build_summary(self, weather_score: float, total_impact: float) -> str:
        if weather_score >= 85:
            return "Weather conditions are favorable and should not materially distort the game environment."
        if weather_score >= 60:
            return "Weather is moderately disruptive and could affect tempo, passing efficiency, and kicking reliability."
        return "Weather is materially disruptive and may significantly alter game script and drive quality."

    def _recommendation(self, weather_score: float, total_impact: float) -> str:
        if weather_score >= 85:
            return "Neutral"
        if weather_score >= 60:
            return "Monitor"
        return "Weather-sensitive"


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))
