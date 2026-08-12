"""
Live injury provider tests.

All tests inject data directly so no network calls or DuckDB are required.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from app.providers.espn_injury_provider import ESPNInjuryProvider, _position_group, _status_impact
from app.services.injuries import InjuryAnalyzer
from app.services.injury_matchup import InjuryMatchupContext


# ── shared fixtures ───────────────────────────────────────────────────────────

def _make_injury(player, team, position, status, starter=True, impact=None, notes=""):
    return {
        "player": player, "team": team, "position": position,
        "positionGroup": _position_group(position),
        "status": status, "practiceStatus": "Unknown",
        "starter": starter,
        "impact": impact if impact is not None else _status_impact(status),
        "notes": notes,
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
    }


def _healthy_team(team: str) -> List[Dict[str, Any]]:
    """No injuries – clean bill of health."""
    return []


def _qb_out(team: str) -> List[Dict[str, Any]]:
    return [_make_injury("Patrick Mahomes", team, "QB", "Out", starter=True, impact=0.9)]


def _multi_injury(team: str) -> List[Dict[str, Any]]:
    return [
        _make_injury("Josh Allen",   team, "QB", "Questionable", impact=0.5),
        _make_injury("Dalton Kincaid", team, "TE", "Out",        impact=0.9),
        _make_injury("Tre'Davious White", team, "CB", "Doubtful", impact=0.7),
    ]


# ── InjuryAnalyzer with injected data ────────────────────────────────────────

class TestInjuryAnalyzerWithMockData:

    def _analyzer(self, injuries):
        """Create an InjuryAnalyzer with pre-supplied injury list (skips live fetch)."""
        return InjuryAnalyzer(injuries=injuries)

    def test_healthy_team_zero_scores(self):
        result = self._analyzer([]).analyze()
        assert result["injuryScore"] == 0.0
        assert result["pointAdjustment"] == 0.0

    def test_major_qb_injury_elevates_score(self):
        injuries = _qb_out("KC")
        result = self._analyzer(injuries).analyze()
        team = result["teams"]["KC"]
        assert team["injuryScore"] > 0
        assert team["offensiveImpact"] > 0
        assert team["pointAdjustment"] > 0

    def test_multiple_injuries_aggregate(self):
        injuries = _multi_injury("BUF")
        result = self._analyzer(injuries).analyze()
        team = result["teams"]["BUF"]
        # Multiple injuries should push score higher than a single one
        single = self._analyzer([_make_injury("Josh Allen", "BUF", "QB", "Questionable")]).analyze()
        assert team["injuryScore"] >= single["teams"]["BUF"]["injuryScore"]

    def test_status_downgrade_reflected(self):
        """Downgrading from Questionable → Out should increase impact."""
        q  = self._analyzer([_make_injury("P1", "DAL", "WR", "Questionable")]).analyze()
        out = self._analyzer([_make_injury("P1", "DAL", "WR", "Out")]).analyze()
        assert out["teams"]["DAL"]["injuryScore"] > q["teams"]["DAL"]["injuryScore"]

    def test_status_upgrade_reflected(self):
        """Upgrading from Out → Active should decrease impact."""
        out    = self._analyzer([_make_injury("P1", "DAL", "WR", "Out")]).analyze()
        active = self._analyzer([_make_injury("P1", "DAL", "WR", "Active", impact=0.1)]).analyze()
        assert active["teams"]["DAL"]["injuryScore"] < out["teams"]["DAL"]["injuryScore"]

    def test_result_includes_status_fields(self):
        result = self._analyzer([]).analyze()
        assert "provider" in result
        assert "isLive" in result
        assert "dataStatus" in result
        assert "lastUpdated" in result

    def test_data_status_mock_when_injected(self):
        result = self._analyzer([]).analyze()
        assert result["dataStatus"] == "MOCK"


# ── Provider unavailable / cached fallback ────────────────────────────────────

class TestInjuryFallback:

    def test_provider_unavailable_uses_mock_when_allowed(self):
        """When live fetch fails, mock data is available through direct injection."""
        analyzer = InjuryAnalyzer.__new__(InjuryAnalyzer)
        analyzer.provider_manager = MagicMock()
        analyzer.provider = MagicMock()
        analyzer.provider_metadata = {"provider": "ESPN (Public)", "isLive": False, "status": "Mock"}
        analyzer._data_status = "MOCK"
        analyzer._last_updated = None
        analyzer.injuries = analyzer._mock_injuries()
        result = analyzer.analyze()
        assert result["dataStatus"] == "MOCK"
        assert len(result["teams"]) > 0

    def test_cached_fallback_returns_cached_status(self):
        """When live fails but cache exists, data_status is CACHED."""
        cached_data = {
            "injuries": [_make_injury("Josh Allen", "BUF", "QB", "Active")],
            "provider": "ESPN (Public)",
            "isLive": False,
            "dataStatus": "CACHED",
            "lastUpdated": "2026-08-12T00:00:00+00:00",
        }
        analyzer = InjuryAnalyzer.__new__(InjuryAnalyzer)
        analyzer.provider_manager = MagicMock()
        analyzer.provider = MagicMock()
        analyzer.provider_metadata = {"provider": "ESPN (Public)", "isLive": False}
        analyzer._data_status = "CACHED"
        analyzer._last_updated = cached_data["lastUpdated"]
        analyzer.injuries = cached_data["injuries"]
        result = analyzer.analyze()
        assert result["dataStatus"] == "CACHED"


# ── ESPN provider normalisation ───────────────────────────────────────────────

class TestESPNInjuryProvider:

    def _provider(self):
        return ESPNInjuryProvider()

    def test_normalise_empty_payload(self):
        p = self._provider()
        result = p._normalise({}, "2026-08-12T00:00:00+00:00")
        assert result == []

    def test_normalise_basic_record(self):
        p = self._provider()
        raw = {
            "injuries": [{
                "status": "Questionable",
                "details": {
                    "athlete": {
                        "displayName": "Patrick Mahomes",
                        "position": {"abbreviation": "QB"},
                        "team": {"abbreviation": "KC"},
                    },
                    "type": "Knee",
                }
            }]
        }
        result = p._normalise(raw, "2026-08-12T00:00:00+00:00")
        assert len(result) == 1
        r = result[0]
        assert r["player"] == "Patrick Mahomes"
        assert r["team"] == "KC"
        assert r["position"] == "QB"
        assert r["status"] == "Questionable"
        assert r["positionGroup"] == "offense"

    def test_espn_abbr_normalisation(self):
        """WSH → WAS normalisation."""
        p = self._provider()
        raw = {"injuries": [{
            "status": "Out",
            "details": {
                "athlete": {
                    "displayName": "Jayden Daniels",
                    "position": {"abbreviation": "QB"},
                    "team": {"abbreviation": "WSH"},
                },
            }
        }]}
        result = p._normalise(raw, "2026-08-12T00:00:00+00:00")
        assert result[0]["team"] == "WAS"

    def test_metadata_has_required_fields(self):
        p = self._provider()
        meta = p.get_metadata()
        assert meta["provider"] == "ESPN (Public)"
        assert meta["isLive"] is True
        assert meta["requiresCredentials"] is False

    def test_fetch_returns_unavailable_on_network_error(self):
        import requests as req
        p = self._provider()
        with patch("app.providers.espn_injury_provider.requests.get",
                   side_effect=req.RequestException("timeout")):
            result = p.fetch_injuries()
        assert result["dataStatus"] == "UNAVAILABLE"
        assert result["injuries"] == []
        assert result["isLive"] is False


# ── Matchup context ───────────────────────────────────────────────────────────

class TestInjuryMatchupContext:

    def test_matchup_returns_expected_fields(self):
        injuries = _qb_out("KC") + _healthy_team("BUF")
        analyzer = InjuryAnalyzer(injuries=injuries)
        ctx = InjuryMatchupContext(analyzer=analyzer).build_context("BUF", "KC")
        for field in ("awayTeam", "homeTeam", "awayInjuryScore", "homeInjuryScore",
                      "awayPointAdjustment", "homePointAdjustment",
                      "netHomeInjuryAdvantage", "healthierTeam", "severity",
                      "keyInjuries", "summary"):
            assert field in ctx, f"Missing field: {field}"

    def test_qb_out_home_favours_away(self):
        """Home QB ruled out → away team should have healthier context."""
        injuries = _qb_out("KC")
        analyzer = InjuryAnalyzer(injuries=injuries)
        ctx = InjuryMatchupContext(analyzer=analyzer).build_context("BUF", "KC")
        assert ctx["homeInjuryScore"] > ctx["awayInjuryScore"]

    def test_si_injury_context_integration(self):
        """InjuryMatchupContext result is correctly shaped for SI Score input."""
        injuries = _multi_injury("DAL")
        ctx = InjuryMatchupContext(
            analyzer=InjuryAnalyzer(injuries=injuries)
        ).build_context("PHI", "DAL")
        # SI Score consumes awayInjuryScore and homeInjuryScore
        assert isinstance(ctx["awayInjuryScore"], float)
        assert isinstance(ctx["homeInjuryScore"], float)
        assert ctx["homeInjuryScore"] > 0
