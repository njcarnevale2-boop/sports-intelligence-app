"""
Live weather data tests covering all required scenarios.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from app.providers.openmeteo_weather_provider import (
    OpenMeteoWeatherProvider, _degrees_to_cardinal, _mm_to_inches,
)
from app.services.weather import WeatherAnalyzer


# ── helpers ───────────────────────────────────────────────────────────────────

def _live_weather(**kwargs) -> Dict[str, Any]:
    base = {
        "temperature": 65.0, "windSpeed": 5.0, "windGust": 8.0,
        "windDirection": "SW", "precipitationProbability": 10.0,
        "precipitationAmount": 0.0, "humidity": 55.0,
        "conditions": "Partly cloudy", "forecastTimestamp": "2026-09-10T18:00",
        "stadiumType": "OUTDOOR", "surface": "grass",
        "provider": "Open-Meteo (Free)", "isLive": True,
        "dataStatus": "LIVE", "lastUpdated": "2026-08-12T00:00:00+00:00",
        "recordCount": 1,
    }
    base.update(kwargs)
    return base


def _analyzer(weather_data=None, home_team=None, kickoff=None):
    return WeatherAnalyzer(weather_data=weather_data, home_team=home_team, kickoff=kickoff)


def _make_provider(return_value=None, raise_exc=None):
    p = MagicMock()
    p.provider_name = "Open-Meteo (Free)"
    p.get_metadata.return_value = {
        "provider": "Open-Meteo (Free)", "isLive": True, "status": "Live",
    }
    if raise_exc:
        p.fetch_game_weather.side_effect = raise_exc
    else:
        p.fetch_game_weather.return_value = return_value
    return p


def _make_wx_analyzer(provider_return=None, provider_exc=None,
                      weather_provider_name="openmeteo"):
    provider = _make_provider(return_value=provider_return, raise_exc=provider_exc)
    pm = MagicMock()
    pm.weather_provider_name = weather_provider_name
    pm.get_weather_provider.return_value = provider

    az = WeatherAnalyzer.__new__(WeatherAnalyzer)
    az.provider_manager = pm
    az.provider = provider
    az.provider_metadata = provider.get_metadata.return_value.copy()
    az._data_status = "MOCK"
    az._last_updated = None
    return az


# ── scoring scenarios ─────────────────────────────────────────────────────────

class TestWeatherScenarios:

    def test_calm_outdoor_weather_is_neutral(self):
        result = _analyzer(weather_data=_live_weather(
            windSpeed=4.0, precipitationAmount=0.0, temperature=68.0,
        )).analyze()
        assert result["weatherScore"] >= 85
        assert result["totalImpact"] < 15
        assert result["recommendation"] == "Neutral"

    def test_high_wind_reduces_score(self):
        calm = _analyzer(weather_data=_live_weather(windSpeed=4.0)).analyze()
        windy = _analyzer(weather_data=_live_weather(windSpeed=22.0)).analyze()
        assert windy["weatherScore"] < calm["weatherScore"]
        assert windy["kickingImpact"] > calm["kickingImpact"]

    def test_rain_increases_impact(self):
        dry = _analyzer(weather_data=_live_weather(
            precipitationAmount=0.0, precipitationProbability=5.0
        )).analyze()
        rain = _analyzer(weather_data=_live_weather(
            precipitationAmount=0.3, precipitationProbability=85.0
        )).analyze()
        assert rain["totalImpact"] > dry["totalImpact"]
        assert rain["passingImpact"] > dry["passingImpact"]

    def test_extreme_heat_reduces_score(self):
        normal = _analyzer(weather_data=_live_weather(temperature=68.0)).analyze()
        hot    = _analyzer(weather_data=_live_weather(temperature=95.0)).analyze()
        assert hot["weatherScore"] <= normal["weatherScore"]

    def test_extreme_cold_increases_kicking_impact(self):
        warm = _analyzer(weather_data=_live_weather(temperature=72.0)).analyze()
        cold = _analyzer(weather_data=_live_weather(temperature=15.0)).analyze()
        assert cold["kickingImpact"] >= warm["kickingImpact"]

    def test_dome_game_returns_neutral(self):
        result = _analyzer(weather_data={
            "stadiumType": "DOME", "surface": "artificial",
        }).analyze()
        assert result["weatherScore"] == 100.0
        assert result["totalImpact"] == 0.0
        assert result["windSpeed"] == 0.0

    def test_retractable_roof_unknown_uses_outdoor_values(self):
        """RETRACTABLE roof without explicit indoor flag uses live outdoor score."""
        result = _analyzer(weather_data=_live_weather(
            stadiumType="RETRACTABLE", windSpeed=15.0, temperature=50.0
        )).analyze()
        # Not treated as dome — scoring reflects actual conditions
        assert result["weatherScore"] < 100.0


# ── transparency ──────────────────────────────────────────────────────────────

class TestWeatherTransparency:

    def test_live_zero_impact_stays_live(self):
        """Perfect weather → still LIVE, not MOCK."""
        az = _make_wx_analyzer(provider_return=_live_weather(
            windSpeed=2.0, precipitationAmount=0.0, temperature=72.0
        ))
        with (
            patch("app.services.weather_history.store_snapshot"),
            patch("app.services.weather_history.detect_changes", return_value=[]),
            patch("app.services.weather_history.store_changes"),
        ):
            az.weather_data = az._load_weather("KC", None)
        assert az._data_status == "LIVE"

    def test_live_neutral_forecast_not_replaced_by_mock(self):
        """LIVE result must not fall through to mock even when impact is 0."""
        az = _make_wx_analyzer(provider_return=_live_weather())
        with (
            patch("app.services.weather_history.store_snapshot"),
            patch("app.services.weather_history.detect_changes", return_value=[]),
            patch("app.services.weather_history.store_changes"),
            patch("app.services.weather_history.get_cached_weather") as mock_cache,
        ):
            az.weather_data = az._load_weather("KC", None)
            mock_cache.assert_not_called()
        assert az._data_status == "LIVE"

    def test_provider_failure_cache_exists_returns_cached(self):
        """Network error + cached data → CACHED."""
        import requests
        cached = {**_live_weather(), "dataStatus": "CACHED", "isLive": False,
                  "lastUpdated": "2026-08-11T00:00:00+00:00"}
        az = _make_wx_analyzer(provider_exc=requests.RequestException("timeout"))
        with patch("app.services.weather_history.get_cached_weather", return_value=cached):
            az.weather_data = az._load_weather("BUF", None)
        assert az._data_status == "CACHED"
        assert az.provider_metadata["isLive"] is False

    def test_provider_failure_no_cache_returns_unavailable(self):
        """Network error + no cache → UNAVAILABLE, empty dict."""
        import requests
        az = _make_wx_analyzer(provider_exc=requests.RequestException("timeout"))
        with patch("app.services.weather_history.get_cached_weather", return_value=None):
            az.weather_data = az._load_weather("BUF", None)
        assert az._data_status == "UNAVAILABLE"
        assert az.weather_data == {}

    def test_unavailable_propagates_through_analyze(self):
        az = WeatherAnalyzer.__new__(WeatherAnalyzer)
        az.provider_manager = MagicMock()
        az.provider_manager.weather_provider_name = "openmeteo"
        az.provider = MagicMock()
        az.provider_metadata = {"provider": "Open-Meteo (Free)", "isLive": False,
                                 "dataStatus": "UNAVAILABLE", "recordCount": 0}
        az._data_status = "UNAVAILABLE"
        az._last_updated = None
        az.weather_data = {}
        result = az.analyze()
        assert result["dataStatus"] == "UNAVAILABLE"
        assert result["isLive"] is False

    def test_explicit_mock_provider_returns_mock(self):
        az = _make_wx_analyzer(weather_provider_name="mock")
        del az.provider.fetch_game_weather
        with (
            patch("app.services.weather.WeatherAnalyzer._using_mock_provider", return_value=True),
            patch("app.services.weather._ALLOW_MOCK", True),
            patch("app.services.weather_history.get_cached_weather", return_value=None),
        ):
            az.weather_data = az._load_weather(None, None)
        assert az._data_status == "MOCK"

    def test_analyze_returns_required_transparency_fields(self):
        result = _analyzer(weather_data=_live_weather()).analyze()
        for field in ("provider", "isLive", "dataStatus", "lastUpdated",
                      "recordCount", "forecastTimestamp"):
            assert field in result, f"Missing field: {field}"


# ── Open-Meteo provider unit tests ────────────────────────────────────────────

class TestOpenMeteoProvider:

    def test_dome_stadium_returns_neutral_live(self):
        p = OpenMeteoWeatherProvider()
        kickoff = datetime.now(timezone.utc) + timedelta(days=5)
        result = p.fetch_game_weather("LV", kickoff)
        assert result["dataStatus"] == "LIVE"
        assert result["stadiumType"] == "DOME"
        assert result["windSpeed"] == 0.0

    def test_unknown_team_returns_unavailable(self):
        p = OpenMeteoWeatherProvider()
        result = p.fetch_game_weather("XYZ")
        assert result["dataStatus"] == "UNAVAILABLE"

    def test_kickoff_beyond_16_days_returns_unavailable(self):
        p = OpenMeteoWeatherProvider()
        far_kickoff = datetime.now(timezone.utc) + timedelta(days=30)
        result = p.fetch_game_weather("KC", far_kickoff)
        assert result["dataStatus"] == "UNAVAILABLE"

    def test_no_kickoff_returns_unavailable(self):
        p = OpenMeteoWeatherProvider()
        result = p.fetch_game_weather("KC", None)
        assert result["dataStatus"] == "UNAVAILABLE"

    def test_network_error_returns_unavailable(self):
        import requests
        p = OpenMeteoWeatherProvider()
        kickoff = datetime.now(timezone.utc) + timedelta(days=3)
        with patch("app.providers.openmeteo_weather_provider.requests.get",
                   side_effect=requests.RequestException("timeout")):
            result = p.fetch_game_weather("KC", kickoff)
        assert result["dataStatus"] == "UNAVAILABLE"
        assert result["isLive"] is False

    def test_metadata_has_required_fields(self):
        meta = OpenMeteoWeatherProvider().get_metadata()
        assert meta["provider"] == "Open-Meteo (Free)"
        assert meta["isLive"] is True
        assert meta["requiresCredentials"] is False

    def test_degrees_to_cardinal(self):
        assert _degrees_to_cardinal(0)   == "N"
        assert _degrees_to_cardinal(90)  == "E"
        assert _degrees_to_cardinal(180) == "S"
        assert _degrees_to_cardinal(270) == "W"
        assert _degrees_to_cardinal(None) == "N/A"


# ── stadium metadata ──────────────────────────────────────────────────────────

def test_all_32_teams_have_stadium_metadata():
    from app.data.nfl_stadiums import NFL_STADIUMS
    nfl_teams = {
        "ARI","ATL","BAL","BUF","CAR","CHI","CIN","CLE","DAL","DEN",
        "DET","GB","HOU","IND","JAX","KC","LAC","LAR","LV","MIA",
        "MIN","NE","NO","NYG","NYJ","PHI","PIT","SEA","SF","TB",
        "TEN","WAS",
    }
    assert set(NFL_STADIUMS.keys()) == nfl_teams


def test_stadium_metadata_required_fields():
    from app.data.nfl_stadiums import NFL_STADIUMS
    required = {"team", "stadium", "city", "state", "latitude", "longitude",
                "roofType", "surface"}
    for code, meta in NFL_STADIUMS.items():
        missing = required - set(meta.keys())
        assert not missing, f"{code} missing fields: {missing}"
        assert meta["roofType"] in {"OUTDOOR", "DOME", "RETRACTABLE"}, \
            f"{code} invalid roofType: {meta['roofType']}"
        assert meta["surface"] in {"grass", "artificial"}, \
            f"{code} invalid surface: {meta['surface']}"
