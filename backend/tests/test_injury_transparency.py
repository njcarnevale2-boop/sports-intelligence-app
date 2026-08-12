"""
Data transparency tests: verify the LIVE/MOCK/CACHED/UNAVAILABLE state
machine never silently substitutes mock data for a live response.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.injuries import InjuryAnalyzer


def _live_response(injuries=None, last_updated="2026-08-12T00:00:00+00:00"):
    return {
        "injuries": injuries or [],
        "provider": "ESPN (Public)",
        "isLive": True,
        "dataStatus": "LIVE",
        "lastUpdated": last_updated,
        "rawCount": len(injuries or []),
    }


def _error_response():
    return {
        "injuries": [],
        "provider": "ESPN (Public)",
        "isLive": False,
        "dataStatus": "UNAVAILABLE",
        "lastUpdated": None,
        "error": "connection refused",
    }


def _make_analyzer_with_provider(fetch_return=None, fetch_raises=None, injury_provider_name="espn"):
    """Return an InjuryAnalyzer whose provider is fully mocked."""
    provider = MagicMock()
    provider.provider_name = "ESPN (Public)"
    provider.get_metadata.return_value = {
        "provider": "ESPN (Public)", "isLive": True, "status": "Live",
    }
    if fetch_raises:
        provider.fetch_injuries.side_effect = fetch_raises
    else:
        provider.fetch_injuries.return_value = fetch_return

    pm = MagicMock()
    pm.injury_provider_name = injury_provider_name
    pm.get_injury_provider.return_value = provider

    analyzer = InjuryAnalyzer.__new__(InjuryAnalyzer)
    analyzer.provider_manager = pm
    analyzer.provider = provider
    analyzer.provider_metadata = provider.get_metadata.return_value.copy()
    analyzer._data_status = "MOCK"
    analyzer._last_updated = None
    return analyzer


# ── LIVE zero records stays LIVE and empty ────────────────────────────────────

def test_live_zero_records_returns_empty_and_live():
    """LIVE response with 0 injuries → empty list, dataStatus=LIVE, isLive=True."""
    analyzer = _make_analyzer_with_provider(fetch_return=_live_response(injuries=[]))

    with (
        patch("app.services.injury_history.get_cached_injuries", return_value=None),
        patch("app.services.injury_history.store_snapshot"),
        patch("app.services.injury_history.detect_changes", return_value=[]),
        patch("app.services.injury_history.store_changes"),
    ):
        analyzer.injuries = analyzer._load_injuries()

    assert analyzer.injuries == []
    assert analyzer._data_status == "LIVE"
    assert analyzer.provider_metadata["isLive"] is True


def test_live_zero_records_does_not_fall_through_to_mock():
    """LIVE with 0 injuries must NOT silently become mock data."""
    analyzer = _make_analyzer_with_provider(fetch_return=_live_response(injuries=[]))

    with (
        patch("app.services.injury_history.get_cached_injuries") as mock_cache,
        patch("app.services.injury_history.store_snapshot"),
        patch("app.services.injury_history.detect_changes", return_value=[]),
        patch("app.services.injury_history.store_changes"),
    ):
        analyzer.injuries = analyzer._load_injuries()
        # Cache should never be consulted when provider returned LIVE
        mock_cache.assert_not_called()

    assert analyzer._data_status == "LIVE"
    assert analyzer.injuries == []


def test_live_result_includes_record_count_in_metadata():
    """Provider metadata must expose recordCount."""
    analyzer = _make_analyzer_with_provider(fetch_return=_live_response(injuries=[]))
    with (
        patch("app.services.injury_history.get_cached_injuries", return_value=None),
        patch("app.services.injury_history.store_snapshot"),
        patch("app.services.injury_history.detect_changes", return_value=[]),
        patch("app.services.injury_history.store_changes"),
    ):
        analyzer.injuries = analyzer._load_injuries()
    assert "recordCount" in analyzer.provider_metadata
    assert analyzer.provider_metadata["recordCount"] == 0


# ── provider failure + cache → CACHED ────────────────────────────────────────

def test_provider_failure_with_cache_returns_cached():
    """Network error + existing cache → dataStatus=CACHED, isLive=False."""
    import requests
    cached_injuries = [{"player": "Josh Allen", "team": "BUF", "position": "QB",
                        "status": "Questionable", "positionGroup": "offense",
                        "practiceStatus": "Limited", "starter": True,
                        "impact": 0.5, "notes": "Knee", "lastUpdated": "2026-08-11T12:00:00+00:00"}]
    cached_result = {
        "injuries": cached_injuries, "provider": "ESPN (Public)",
        "isLive": False, "dataStatus": "CACHED",
        "lastUpdated": "2026-08-11T12:00:00+00:00", "cachedCount": 1,
    }
    analyzer = _make_analyzer_with_provider(fetch_raises=requests.RequestException("timeout"))

    with patch("app.services.injury_history.get_cached_injuries", return_value=cached_result):
        analyzer.injuries = analyzer._load_injuries()

    assert analyzer._data_status == "CACHED"
    assert analyzer.provider_metadata["isLive"] is False
    assert len(analyzer.injuries) == 1


# ── provider failure + no cache → UNAVAILABLE ────────────────────────────────

def test_provider_failure_no_cache_returns_unavailable():
    """Network error + no cache → dataStatus=UNAVAILABLE, empty list."""
    import requests
    analyzer = _make_analyzer_with_provider(fetch_raises=requests.RequestException("timeout"))

    with patch("app.services.injury_history.get_cached_injuries", return_value=None):
        analyzer.injuries = analyzer._load_injuries()

    assert analyzer._data_status == "UNAVAILABLE"
    assert analyzer.provider_metadata["isLive"] is False
    assert analyzer.injuries == []


def test_unavailable_result_propagates_to_analyze():
    """analyze() exposes dataStatus=UNAVAILABLE when no data is available."""
    analyzer = InjuryAnalyzer.__new__(InjuryAnalyzer)
    analyzer.provider_manager = MagicMock()
    analyzer.provider_manager.injury_provider_name = "espn"
    analyzer.provider = MagicMock()
    analyzer.provider_metadata = {"provider": "ESPN (Public)", "isLive": False,
                                  "dataStatus": "UNAVAILABLE", "recordCount": 0}
    analyzer._data_status = "UNAVAILABLE"
    analyzer._last_updated = None
    analyzer.injuries = []

    result = analyzer.analyze()
    assert result["dataStatus"] == "UNAVAILABLE"
    assert result["isLive"] is False
    assert result["recordCount"] == 0


# ── explicit mock mode ────────────────────────────────────────────────────────

def test_explicit_mock_provider_returns_mock_status():
    """When INJURY_PROVIDER=mock the dataStatus must be MOCK (not LIVE)."""
    analyzer = _make_analyzer_with_provider(
        fetch_return=_live_response(),   # should be ignored — no fetch_injuries on mock
        injury_provider_name="mock",
    )
    # Mock provider doesn't expose fetch_injuries
    del analyzer.provider.fetch_injuries

    with (
        patch("app.services.injuries._ALLOW_MOCK", True),
        patch("app.services.injury_history.get_cached_injuries", return_value=None),
    ):
        analyzer.injuries = analyzer._load_injuries()

    assert analyzer._data_status == "MOCK"


def test_mock_data_status_in_analyze_output():
    """analyze() on an explicitly injected list returns dataStatus=MOCK."""
    analyzer = InjuryAnalyzer(injuries=[])
    result = analyzer.analyze()
    assert result["dataStatus"] == "MOCK"
    # Mock must never claim to be live
    assert result["isLive"] is False
