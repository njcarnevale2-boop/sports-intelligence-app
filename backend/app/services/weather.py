from __future__ import annotations

from typing import Any, Dict, Optional


class WeatherAnalyzer:
    """
    Evaluate mock game weather for NFL matchup context.

    This is intentionally isolated so a future live provider such as OpenWeather
    can replace the mock data without changing the API contract.
    """

    def __init__(self, weather_data: Optional[Dict[str, Any]] = None):
        self.weather_data = weather_data or self._mock_weather()

    def analyze(self) -> Dict[str, Any]:
        """
        Return a weather intelligence snapshot with impact estimates.
        """

        weather = self.weather_data or {}
        stadium_type = str(weather.get("stadiumType", "")).lower()
        surface = str(weather.get("surface", "")).lower()

        if stadium_type in {"indoor", "dome", "closed"}:
            return {
                "weatherScore": 100.0,
                "passingImpact": 0.0,
                "rushingImpact": 0.0,
                "kickingImpact": 0.0,
                "totalImpact": 0.0,
                "summary": "Indoor conditions are neutral and should not materially affect gameplay.",
                "recommendation": "Neutral",
            }

        temperature = float(weather.get("temperature", 70) or 70)
        wind_speed = float(weather.get("windSpeed", 0) or 0)
        precipitation = float(weather.get("precipitation", 0) or 0)
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
