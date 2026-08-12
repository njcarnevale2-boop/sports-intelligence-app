"""
Open-Meteo weather provider — no API key required.

Fetches hourly game-time forecasts from the Open-Meteo free API
(https://open-meteo.com) using NFL stadium coordinates from nfl_stadiums.py.

Open-Meteo is a free, open-source weather forecast API that supports
hourly data up to 16 days ahead with no authentication requirement.

DEVELOPMENT NOTE: Open-Meteo is a well-maintained open-source project
suitable for production use. Review rate limits and SLA requirements
before scaling to high-frequency fetching.

Response is normalised into the internal weather schema:
  temperature             – Fahrenheit
  windSpeed               – mph
  windGust                – mph
  windDirection           – cardinal string (N / NE / …)
  precipitationProbability – 0-100 %
  precipitationAmount     – inches
  humidity                – 0-100 %
  conditions              – human-readable conditions string
  forecastTimestamp       – ISO timestamp of the matched forecast hour
  stadiumType             – OUTDOOR / DOME / RETRACTABLE
  surface                 – grass / artificial
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import requests

from app.data.nfl_stadiums import get_stadium, NEUTRAL_WEATHER
from app.providers.base_provider import BaseProvider

log = logging.getLogger("openmeteo_weather_provider")

_BASE_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT_SECONDS = 20

# WMO weather code → human-readable conditions
_WMO_CODES: Dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}

_CARDINAL = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def _degrees_to_cardinal(degrees: Optional[float]) -> str:
    if degrees is None:
        return "N/A"
    return _CARDINAL[round(float(degrees) / 22.5) % 16]


def _mm_to_inches(mm: float) -> float:
    return round(mm / 25.4, 3)


class OpenMeteoWeatherProvider(BaseProvider):
    provider_name = "Open-Meteo (Free)"

    def fetch_data(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        team = kwargs.get("team", "")
        kickoff = kwargs.get("kickoff")
        return self.fetch_game_weather(team, kickoff)

    def get_metadata(self) -> Dict[str, Any]:
        meta = super().get_metadata()
        meta.update({
            "provider": self.provider_name,
            "isLive": True,
            "status": "Live",
            "requiresCredentials": False,
        })
        return meta

    # ── public ───────────────────────────────────────────────────────────────

    def fetch_game_weather(
        self,
        home_team: str,
        kickoff_utc: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Return weather forecast for the home team's stadium at kickoff time.
        For DOME stadiums returns neutral weather immediately (no API call).
        """
        fetch_time = datetime.now(timezone.utc).isoformat()

        stadium = get_stadium(home_team)
        if stadium is None:
            return self._unavailable(fetch_time, f"Unknown team: {home_team}")

        roof = stadium.get("roofType", "OUTDOOR")

        # Indoor domes: no weather impact
        if roof == "DOME":
            return {
                **NEUTRAL_WEATHER,
                "stadiumType": "DOME",
                "surface": stadium.get("surface", "artificial"),
                "team": home_team,
                "stadium": stadium.get("stadium"),
                "provider": self.provider_name,
                "isLive": True,
                "dataStatus": "LIVE",
                "lastUpdated": fetch_time,
                "forecastTimestamp": fetch_time,
                "recordCount": 1,
            }

        lat = stadium["latitude"]
        lon = stadium["longitude"]

        # If no kickoff given or kickoff is beyond 16-day window, return UNAVAILABLE
        if kickoff_utc is None:
            return self._unavailable(fetch_time, "No kickoff time provided")

        now_utc = datetime.now(timezone.utc)
        days_ahead = (kickoff_utc - now_utc).days
        if days_ahead > 15:
            return self._unavailable(
                fetch_time,
                f"Kickoff is {days_ahead} days away — outside 16-day forecast window",
            )

        return self._fetch(lat, lon, kickoff_utc, stadium, fetch_time)

    # ── private ──────────────────────────────────────────────────────────────

    def _fetch(
        self,
        lat: float,
        lon: float,
        kickoff: datetime,
        stadium: Dict[str, Any],
        fetch_time: str,
    ) -> Dict[str, Any]:
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": ",".join([
                "temperature_2m",
                "relativehumidity_2m",
                "precipitation_probability",
                "precipitation",
                "rain",
                "snowfall",
                "windspeed_10m",
                "windgusts_10m",
                "winddirection_10m",
                "weathercode",
            ]),
            "wind_speed_unit": "mph",
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "inch",
            "timeformat": "iso8601",
            "timezone": "UTC",
            "forecast_days": 16,
        }
        try:
            resp = requests.get(_BASE_URL, params=params, timeout=_TIMEOUT_SECONDS)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            log.warning("Open-Meteo fetch failed: %s", exc)
            return self._unavailable(fetch_time, str(exc)[:200])

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        if not times:
            return self._unavailable(fetch_time, "Empty hourly data from Open-Meteo")

        idx = self._closest_hour_index(times, kickoff)
        if idx is None:
            return self._unavailable(fetch_time, "Could not find matching forecast hour")

        def _get(key: str):
            vals = hourly.get(key, [])
            return vals[idx] if idx < len(vals) else None

        temp           = _get("temperature_2m")
        humidity       = _get("relativehumidity_2m")
        precip_prob    = _get("precipitation_probability")
        precip_inch    = _get("precipitation")
        wind_speed     = _get("windspeed_10m")
        wind_gust      = _get("windgusts_10m")
        wind_dir_deg   = _get("winddirection_10m")
        weather_code   = _get("weathercode")
        forecast_ts    = times[idx]

        conditions = _WMO_CODES.get(int(weather_code) if weather_code is not None else 0, "Unknown")
        wind_cardinal = _degrees_to_cardinal(wind_dir_deg)

        roof = stadium.get("roofType", "OUTDOOR")
        log.info(
            "Open-Meteo weather: team=%s temp=%.1f wind=%.1f conditions=%s",
            stadium.get("team", "?"),
            float(temp or 0),
            float(wind_speed or 0),
            conditions,
        )

        return {
            "temperature":             round(float(temp or 72), 1),
            "windSpeed":               round(float(wind_speed or 0), 1),
            "windGust":                round(float(wind_gust or 0), 1),
            "windDirection":           wind_cardinal,
            "precipitationProbability": round(float(precip_prob or 0), 1),
            "precipitationAmount":     round(float(precip_inch or 0), 3),
            "humidity":                round(float(humidity or 50), 1),
            "conditions":              conditions,
            "forecastTimestamp":       forecast_ts,
            "stadiumType":             roof,
            "surface":                 stadium.get("surface", "grass"),
            "team":                    stadium.get("team"),
            "stadium":                 stadium.get("stadium"),
            "city":                    stadium.get("city"),
            "state":                   stadium.get("state"),
            "provider":                self.provider_name,
            "isLive":                  True,
            "dataStatus":              "LIVE",
            "lastUpdated":             fetch_time,
            "recordCount":             1,
        }

    @staticmethod
    def _closest_hour_index(times: list, kickoff: datetime) -> Optional[int]:
        """Return index of the forecast hour closest to kickoff."""
        kickoff_naive = kickoff.astimezone(timezone.utc).replace(tzinfo=None)
        best_idx, best_delta = None, timedelta.max
        for i, t in enumerate(times):
            try:
                ft = datetime.fromisoformat(str(t).replace("Z", ""))
                delta = abs(ft - kickoff_naive)
                if delta < best_delta:
                    best_delta, best_idx = delta, i
            except (ValueError, TypeError):
                continue
        return best_idx

    @staticmethod
    def _unavailable(fetch_time: str, reason: str) -> Dict[str, Any]:
        return {
            "temperature": None,
            "windSpeed": None,
            "windGust": None,
            "windDirection": None,
            "precipitationProbability": None,
            "precipitationAmount": None,
            "humidity": None,
            "conditions": None,
            "forecastTimestamp": None,
            "stadiumType": None,
            "surface": None,
            "provider": "Open-Meteo (Free)",
            "isLive": False,
            "dataStatus": "UNAVAILABLE",
            "lastUpdated": fetch_time,
            "recordCount": 0,
            "reason": reason,
        }
