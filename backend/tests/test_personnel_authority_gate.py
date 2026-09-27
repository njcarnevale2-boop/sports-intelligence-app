from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from app.routes import opportunities as route
from app.services.personnel_authority import build_personnel_authority


@dataclass
class _FakeFairPriceResult:
    fair_price: float | None = -118.0
    fair_line: float | None = -118.0
    true_playable_to: float | None = -112.0
    true_playable_to_status: str = "AVAILABLE"
    true_playable_to_reason: str = "TEST"
    worst_observed_playable_price: float | None = -112.0
    worst_observed_playable_price_status: str = "AVAILABLE"
    worst_observed_playable_price_reason: str = "TEST"
    playable_to: float | None = -112.0
    playable_to_status: str = "AVAILABLE"
    playable_to_reason: str = "TEST"
    current_win_probability: float | None = 0.62
    current_push_probability: float | None = 0.02
    current_loss_probability: float | None = 0.36
    current_ev: float | None = 0.123
    minimum_playable_ev: float | None = 0.0
    best_available_price: float | None = -110.0
    best_available_line: float | None = 3.0


class _FakeInjuryContext:
    def build_context(self, away_team: str, home_team: str):
        return {"severity": "neutral", "summary": "neutral"}


def _row() -> pd.Series:
    return pd.Series(
        {
            "api_event_id": "evt-personnel",
            "commence_time": "2026-09-27T17:00:00+00:00",
            "away_team": "SEA",
            "home_team": "WAS",
            "market": "spread",
            "side": "away",
            "point": 3.5,
            "sportsbook": "DraftKings",
            "price": -110,
            "model_prob": 0.62,
            "implied_prob_raw": 0.5238,
            "fair_odds": -118,
            "edge_pp": 0.24,
            "ev_per_dollar": 0.51,
            "kelly_full": 0.54,
            "kelly_20pct": 0.11,
            "recommendation": "STRONG BET",
            "confidence_score": 86,
            "data_completeness": 1.0,
            "market_confidence": 0.8,
            "model_confidence": 0.7,
            "rank": 1,
        }
    )


def _patch_common(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        route,
        "get_market_intelligence",
        lambda **kwargs: {
            "score": 7.0,
            "signal": "CONFIRMED",
            "steamBooks": 1,
            "booksMoving": 3,
            "booksTracked": 8,
            "consensus": 70,
        },
    )
    monkeypatch.setattr(route, "InjuryMatchupContext", _FakeInjuryContext)
    monkeypatch.setattr(route, "build_fair_price_result", lambda **kwargs: _FakeFairPriceResult())


def _available_execution() -> dict:
    return {
        "status": "AVAILABLE",
        "reason": "Synthetic current execution",
        "sportsbook": "DraftKings",
        "sportsbookCanonicalKey": "draftkings",
        "sportsbookCanonicalDisplay": "DraftKings",
        "sportsbookPolicyStatus": "ALLOWED",
        "providerTitle": "DraftKings",
        "point": 3.5,
        "price": -110.0,
        "quoteTimestamp": "2026-09-27T15:00:00Z",
        "quoteAgeMinutes": 5.0,
        "maxAllowedQuoteAgeMinutes": 30,
        "currentMarketTimestamp": "2026-09-27T15:00:00Z",
        "approvedRows": 1,
        "freshRows": 1,
    }


def test_current_personnel_preserves_actionability(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch)
    personnel = build_personnel_authority(
        season=2026,
        week=3,
        event_id="evt-personnel",
        canonical_event_key="cev-personnel",
        away_team="SEA",
        home_team="WAS",
        away_expected_starting_qb="Synthetic Away QB",
        home_expected_starting_qb="Synthetic Home QB",
        away_qb_status="CURRENT",
        home_qb_status="CURRENT",
        away_qb_verified_at="2026-09-27T15:00:00Z",
        home_qb_verified_at="2026-09-27T15:00:00Z",
        away_qb_source="synthetic",
        home_qb_source="synthetic",
        personnel_verified_at="2026-09-27T15:00:00Z",
        personnel_source_version="synthetic-test",
        personnel_status="CURRENT",
        personnel_readiness_reason="QB_STATUS_CURRENT",
    )

    opp = route.row_to_opportunity(
        _row(),
        market_snapshot={"provider": "line_movement_board", "lastUpdated": "2026-09-27T15:00:00Z", "dataStatus": "FILE", "booksTracked": 8},
        injury_ctx=_FakeInjuryContext(),
        current_execution=_available_execution(),
        personnel_authority=personnel,
        group_rows=pd.DataFrame([_row()]),
    )

    assert opp["personnelReadiness"] == "CURRENT"
    assert opp["qualificationStatus"] == "QUALIFIED"
    assert opp["currentQualification"]["actionable"] is True
    assert opp["currentSizing"]["status"] == "AVAILABLE"
    assert opp["personnelNumericallyAdjusted"] is False


@pytest.mark.parametrize(
    "status, reason",
    [
        ("STALE", "QB_STATUS_STALE"),
        ("CONFLICTED", "QB_STATUS_CONFLICTED"),
        ("UNAVAILABLE", "QB_STATUS_UNVERIFIED"),
    ],
)
def test_fail_closed_personnel_blocks_actionability(monkeypatch: pytest.MonkeyPatch, status: str, reason: str) -> None:
    _patch_common(monkeypatch)
    personnel = build_personnel_authority(
        season=2026,
        week=3,
        event_id="evt-personnel",
        canonical_event_key="cev-personnel",
        away_team="SEA",
        home_team="WAS",
        away_expected_starting_qb=None,
        home_expected_starting_qb=None,
        away_qb_status=status,
        home_qb_status=status,
        away_qb_verified_at=None,
        home_qb_verified_at=None,
        away_qb_source="synthetic",
        home_qb_source="synthetic",
        personnel_verified_at=None,
        personnel_source_version="synthetic-test",
        personnel_status=status,
        personnel_readiness_reason=reason,
    )

    opp = route.row_to_opportunity(
        _row(),
        market_snapshot={"provider": "line_movement_board", "lastUpdated": "2026-09-27T15:00:00Z", "dataStatus": "FILE", "booksTracked": 8},
        injury_ctx=_FakeInjuryContext(),
        current_execution=_available_execution(),
        personnel_authority=personnel,
        group_rows=pd.DataFrame([_row()]),
    )

    assert opp["personnelReadiness"] == status
    assert opp["qualificationStatus"] == "NOT_QUALIFIED"
    assert opp["currentQualification"]["actionable"] is False
    assert opp["currentSizing"]["status"] == "UNAVAILABLE"
    assert "Personnel readiness" in opp["currentSizing"]["reason"]
    assert opp["currentWinProbability"] == pytest.approx(0.62)
    assert opp["currentEV"] == pytest.approx(0.123)
