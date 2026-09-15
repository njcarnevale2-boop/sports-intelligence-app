from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

import app.routes.opportunities as opportunities_route
import app.services.games as games_module
from app.services.decision_board import build_decision_board_payload
import app.services.decision_ledger as decision_ledger


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
    best_available_price: float | None = -105.0
    best_available_line: float | None = 4.0


def _base_artifact_row(*, event_id: str = "evt-sizing") -> dict:
    return {
        "api_event_id": event_id,
        "commence_time": "2026-09-20T17:00:00+00:00",
        "away_team": "NO",
        "home_team": "ATL",
        "market": "spread",
        "side": "away",
        "point": 3.0,
        "sportsbook": "DraftKings",
        "price": -110.0,
        "model_prob": 0.62,
        "implied_prob_raw": 0.5238,
        "market_no_vig_prob": 0.5238,
        "fair_odds": -118.0,
        "edge_pp": 0.24,
        "ev_per_dollar": 0.51,
        "kelly_full": 0.54,
        "kelly_20pct": 0.11,
        "recommendation": "STRONG BET",
        "qualification_status": "QUALIFIED",
        "qualification_reasons": ["Current model edge and confidence meet SIA qualification thresholds."],
        "confidence_score": 86,
        "data_completeness": 1.0,
        "market_confidence": 0.8,
        "model_confidence": 0.7,
        "rank": 1,
    }


def _write_fixture_files(tmp_path: Path, *, artifact_rows: list[dict]) -> tuple[Path, Path]:
    ranked_board = tmp_path / "ranked_bet_board.csv"
    projections = tmp_path / "current_game_projections.csv"
    pd.DataFrame(artifact_rows).to_csv(ranked_board, index=False)
    pd.DataFrame(
        [
            {
                "api_event_id": row["api_event_id"],
                "commence_time": row["commence_time"],
                "away_team": row["away_team"],
                "home_team": row["home_team"],
                "model_margin_home": -1.0,
                "market_home_spread": -3.0,
                "model_total_baseline": 45.0,
                "market_total": 44.5,
            }
            for row in artifact_rows
        ]
    ).to_csv(projections, index=False)
    return ranked_board, projections


def _expected_kelly20(*, win: float, push: float, loss: float, american_odds: float) -> float:
    if american_odds > 0:
        profit_multiplier = american_odds / 100.0
    else:
        profit_multiplier = 100.0 / abs(american_odds)
    full_kelly = max(0.0, ((profit_multiplier * win) - loss) / profit_multiplier)
    return round(full_kelly * 0.2, 4)


def _patch_current_execution_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    artifact_row: dict,
    current_quotes: list[dict],
    fair_price_result: _FakeFairPriceResult,
) -> None:
    ranked_board, projections = _write_fixture_files(tmp_path, artifact_rows=[artifact_row])
    event_id = str(artifact_row["api_event_id"])

    monkeypatch.setattr(opportunities_route, "RANKED_BET_BOARD", ranked_board)
    monkeypatch.setattr(opportunities_route, "GAME_PROJECTIONS", projections)
    monkeypatch.setattr(games_module, "RANKED_BET_BOARD", ranked_board)
    monkeypatch.setattr(games_module, "GAME_PROJECTIONS", projections)
    monkeypatch.setattr(opportunities_route, "_build_generated_multimarket_candidates", lambda **kwargs: [])
    monkeypatch.setattr(opportunities_route, "load_game_projection_lookup", lambda: {event_id: {"model_margin_home": -1.0, "model_total_baseline": 45.0}})
    monkeypatch.setattr(opportunities_route, "get_market_intelligence", lambda **kwargs: {
        "score": 7.0,
        "grade": "A",
        "signal": "CONFIRMED",
        "steamBooks": 1,
        "booksMoving": 3,
        "booksTracked": 6,
        "supportingBooks": 2,
        "opposingBooks": 1,
        "consensus": 70,
        "largestPointMove": 0.5,
        "largestPriceMove": 8.0,
        "marketSupport": True,
        "snapshots": 6,
    })

    class _FakeInjuryContext:
        def build_context(self, away_team: str, home_team: str) -> dict[str, str]:
            return {"summary": f"{away_team} vs {home_team} injury context", "severity": "neutral"}

    monkeypatch.setattr(opportunities_route, "InjuryMatchupContext", _FakeInjuryContext)
    monkeypatch.setattr(opportunities_route, "build_fair_price_result", lambda **kwargs: fair_price_result)
    monkeypatch.setattr(opportunities_route.market_data_service, "metadata", lambda: {
        "provider": "line_movement_board",
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "dataStatus": "FILE",
    })

    def _snapshot() -> dict:
        approved_quotes = [q for q in current_quotes if q["sportsbook"] in {"DraftKings", "FanDuel", "BetMGM", "Caesars Sportsbook", "Caesars", "Fanatics Sportsbook", "Fanatics", "BetRivers"}]
        best_quote = approved_quotes[0] if approved_quotes else None
        return {
            "provider": "line_movement_board",
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "dataStatus": "FILE",
            "booksTracked": len(current_quotes),
            "bestAwaySpread": None if best_quote is None else {
                "sportsbook": best_quote["sportsbook"],
                "line": best_quote["point"],
                "price": best_quote["americanOdds"],
                "lastUpdated": best_quote["lastUpdated"],
            },
            "bestHomeSpread": None,
            "bestAwayMoneyline": None,
            "bestHomeMoneyline": None,
            "bestOver": None,
            "bestUnder": None,
            "bestPriceAwaySpread": None if best_quote is None else {
                "sportsbook": best_quote["sportsbook"],
                "line": best_quote["point"],
                "price": best_quote["americanOdds"],
                "lastUpdated": best_quote["lastUpdated"],
            },
            "bestPriceHomeSpread": None,
            "bestPriceAwayMoneyline": None,
            "bestPriceHomeMoneyline": None,
            "bestPriceOver": None,
            "bestPriceUnder": None,
            "consensusSpread": -3.0,
            "consensusTotal": 44.5,
            "consensusMoneyline": None,
        }

    monkeypatch.setattr(opportunities_route.market_data_service, "all_event_snapshots", lambda: {event_id: _snapshot()})
    monkeypatch.setattr(games_module.market_data_service, "all_event_snapshots", lambda: {event_id: _snapshot()})
    monkeypatch.setattr(opportunities_route.market_data_service, "event_market_snapshot", lambda eid: _snapshot() if str(eid) == event_id else {})
    monkeypatch.setattr(opportunities_route.market_data_service, "records_for_event", lambda eid: list(current_quotes) if str(eid) == event_id else [])
    monkeypatch.setattr(games_module.market_data_service, "metadata", lambda: _snapshot())
    monkeypatch.setattr(games_module.service, "_load_schedule_context_lookup", lambda: {("2026-09-20", "NO", "ATL"): (2026, 1)})


def _current_quote(*, point: float, price: float, sportsbook: str = "DraftKings", minutes_old: int = 5, event_id: str = "evt-sizing") -> dict:
    return {
        "eventId": event_id,
        "market": "spread",
        "side": "away",
        "point": point,
        "americanOdds": price,
        "sportsbook": sportsbook,
        "lastUpdated": (datetime.now(timezone.utc) - timedelta(minutes=minutes_old)).isoformat(),
    }


def test_current_execution_sizing_uses_current_quote_not_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_row = _base_artifact_row()
    current_quotes = [_current_quote(point=4.0, price=-105.0)]
    fair = _FakeFairPriceResult(current_win_probability=0.62, current_push_probability=0.02, current_loss_probability=0.36, current_ev=0.123, best_available_line=4.0, best_available_price=-105.0)
    _patch_current_execution_fixture(monkeypatch, tmp_path, artifact_row=artifact_row, current_quotes=current_quotes, fair_price_result=fair)

    payload = opportunities_route.get_opportunities(limit=10, best_lines_only=True, week=1)
    assert payload["count"] == 1
    opp = payload["opportunities"][0]

    expected_fractional = _expected_kelly20(win=0.62, push=0.02, loss=0.36, american_odds=-105.0)
    assert opp["originalCandidate"]["point"] == 3.0
    assert opp["originalCandidate"]["price"] == -110.0
    assert opp["currentExecution"]["point"] == 4.0
    assert opp["currentExecution"]["price"] == -105.0
    assert opp["currentSizing"]["status"] == "AVAILABLE"
    assert opp["artifactSizing"]["fractionalKellyFraction"] == 0.11
    assert opp["kelly20"] == expected_fractional
    assert opp["recommendedUnits"] == round(expected_fractional * 10.0, 2)
    assert opp["bankrollPercent"] == round(expected_fractional * 100.0, 2)


def test_improving_current_execution_increases_sizing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_row = _base_artifact_row()

    better_quotes = [_current_quote(point=4.5, price=105.0)]
    better_fair = _FakeFairPriceResult(current_win_probability=0.62, current_push_probability=0.02, current_loss_probability=0.36, current_ev=0.271, best_available_line=4.5, best_available_price=105.0)
    _patch_current_execution_fixture(monkeypatch, tmp_path, artifact_row=artifact_row, current_quotes=better_quotes, fair_price_result=better_fair)
    better = opportunities_route.get_opportunities(limit=10, best_lines_only=True, week=1)["opportunities"][0]

    worse_tmp = tmp_path / "worse"
    worse_tmp.mkdir()
    worse_quotes = [_current_quote(point=3.5, price=-125.0)]
    worse_fair = _FakeFairPriceResult(current_win_probability=0.58, current_push_probability=0.02, current_loss_probability=0.40, current_ev=0.022, best_available_line=3.5, best_available_price=-125.0)
    _patch_current_execution_fixture(monkeypatch, worse_tmp, artifact_row=artifact_row, current_quotes=worse_quotes, fair_price_result=worse_fair)
    worse = opportunities_route.get_opportunities(limit=10, best_lines_only=True, week=1)["opportunities"][0]

    assert better["currentSizing"]["status"] == "AVAILABLE"
    assert worse["currentSizing"]["status"] == "AVAILABLE"
    assert better["recommendedUnits"] > worse["recommendedUnits"]
    assert better["bankrollPercent"] > worse["bankrollPercent"]


def test_deteriorating_but_qualified_line_recomputes_sizing_instead_of_reusing_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_row = _base_artifact_row()
    current_quotes = [_current_quote(point=3.5, price=-125.0)]
    fair = _FakeFairPriceResult(current_win_probability=0.58, current_push_probability=0.02, current_loss_probability=0.40, current_ev=0.022, best_available_line=3.5, best_available_price=-125.0)
    _patch_current_execution_fixture(monkeypatch, tmp_path, artifact_row=artifact_row, current_quotes=current_quotes, fair_price_result=fair)

    opp = opportunities_route.get_opportunities(limit=10, best_lines_only=True, week=1)["opportunities"][0]
    expected_fractional = _expected_kelly20(win=0.58, push=0.02, loss=0.40, american_odds=-125.0)
    assert opp["currentSizing"]["status"] == "AVAILABLE"
    assert opp["artifactSizing"]["fractionalKellyFraction"] == 0.11
    assert opp["kelly20"] == expected_fractional
    assert opp["kelly20"] != opp["artifactSizing"]["fractionalKellyFraction"]
    assert opp["recommendedUnits"] == round(expected_fractional * 10.0, 2)


def test_dequalified_current_execution_has_no_sizing_and_no_game_detail_opportunity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_row = _base_artifact_row()
    current_quotes = [_current_quote(point=2.5, price=-145.0)]
    fair = _FakeFairPriceResult(current_win_probability=0.53, current_push_probability=0.02, current_loss_probability=0.45, current_ev=-0.011, best_available_line=2.5, best_available_price=-145.0)
    _patch_current_execution_fixture(monkeypatch, tmp_path, artifact_row=artifact_row, current_quotes=current_quotes, fair_price_result=fair)

    research_payload = opportunities_route.get_opportunities(limit=10, best_lines_only=True, include_experimental=True, week=1)
    opp = research_payload["opportunities"][0]
    assert opp["currentQualification"]["status"] == "NOT_QUALIFIED"
    assert opp["currentSizing"]["status"] == "UNAVAILABLE"
    assert opp["recommendedUnits"] is None
    assert opp["bankrollPercent"] is None

    game_detail_payload = opportunities_route._get_game_best_opportunity_payload("evt-sizing", include_best_by_market=True)
    assert game_detail_payload["opportunity"] is None


def test_stale_quote_has_no_sizing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_row = _base_artifact_row()
    current_quotes = [_current_quote(point=4.0, price=-105.0, minutes_old=45)]
    fair = _FakeFairPriceResult()
    _patch_current_execution_fixture(monkeypatch, tmp_path, artifact_row=artifact_row, current_quotes=current_quotes, fair_price_result=fair)

    opp = opportunities_route.get_opportunities(limit=10, best_lines_only=True, include_experimental=True, week=1)["opportunities"][0]
    assert opp["currentExecution"]["status"] == "STALE_APPROVED_MARKET"
    assert opp["currentSizing"]["status"] == "UNAVAILABLE"
    assert opp["recommendedUnits"] is None


def test_better_unapproved_sportsbook_is_ignored_for_current_sizing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_row = _base_artifact_row()
    current_quotes = [
        _current_quote(point=5.0, price=-102.0, sportsbook="LowVig.ag"),
        _current_quote(point=4.0, price=-110.0, sportsbook="DraftKings"),
    ]
    fair = _FakeFairPriceResult(current_win_probability=0.60, current_push_probability=0.02, current_loss_probability=0.38, current_ev=0.061, best_available_line=4.0, best_available_price=-110.0)
    _patch_current_execution_fixture(monkeypatch, tmp_path, artifact_row=artifact_row, current_quotes=current_quotes, fair_price_result=fair)

    opp = opportunities_route.get_opportunities(limit=10, best_lines_only=True, week=1)["opportunities"][0]
    assert opp["currentExecution"]["sportsbook"] == "DraftKings"
    assert opp["currentExecution"]["point"] == 4.0
    assert opp["currentExecution"]["price"] == -110.0
    assert opp["currentSizing"]["sportsbook"] == "DraftKings"


def test_no_approved_quote_has_no_sizing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_row = _base_artifact_row()
    current_quotes = [_current_quote(point=5.0, price=-102.0, sportsbook="LowVig.ag")]
    fair = _FakeFairPriceResult()
    _patch_current_execution_fixture(monkeypatch, tmp_path, artifact_row=artifact_row, current_quotes=current_quotes, fair_price_result=fair)

    opp = opportunities_route.get_opportunities(limit=10, best_lines_only=True, include_experimental=True, week=1)["opportunities"][0]
    assert opp["currentExecution"]["status"] == "UNAVAILABLE_APPROVED_MARKET"
    assert opp["currentSizing"]["status"] == "UNAVAILABLE"


def test_cross_surface_current_execution_and_sizing_are_consistent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_row = _base_artifact_row()
    current_quotes = [_current_quote(point=4.0, price=-105.0, sportsbook="FanDuel")]
    fair = _FakeFairPriceResult(current_win_probability=0.62, current_push_probability=0.02, current_loss_probability=0.36, current_ev=0.123, best_available_line=4.0, best_available_price=-105.0)
    _patch_current_execution_fixture(monkeypatch, tmp_path, artifact_row=artifact_row, current_quotes=current_quotes, fair_price_result=fair)

    opp = opportunities_route.get_opportunities(limit=10, best_lines_only=True, week=1)["opportunities"][0]
    game_detail = opportunities_route._get_game_best_opportunity_payload("evt-sizing", include_best_by_market=True)["opportunity"]
    games_payload = games_module.service.list_games(week=1)
    game_row = games_payload["games"][0]
    board = build_decision_board_payload([opp], limit=1)
    board_item = board["decisionBoard"][0]

    assert game_detail is not None
    assert opp["currentExecution"]["point"] == game_detail["currentExecution"]["point"] == game_row["bestOpportunityDetail"]["currentExecution"]["point"] == 4.0
    assert opp["currentExecution"]["price"] == game_detail["currentExecution"]["price"] == game_row["bestOpportunityDetail"]["currentExecution"]["price"] == -105.0
    assert opp["recommendedUnits"] == game_detail["recommendedUnits"] == game_row["recommendedUnits"] == board_item["recommendedUnits"]
    assert opp["bankrollPercent"] == game_detail["bankrollPercent"] == game_row["bankrollPercent"] == board_item["bankrollPercent"]


def test_personal_wager_tracking_requires_explicit_units_and_persists_current_units(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decision_ledger, "_DB_PATH", tmp_path / "ledger.db")

    with pytest.raises(ValueError, match="unitsRisked or amountRisked is required"):
        decision_ledger.record_personal_wager_from_payload(
            {
                "eventId": "evt-sizing",
                "market": "spread",
                "side": "away",
                "point": 4.0,
                "price": -105.0,
                "sportsbook": "FanDuel",
            },
            source_snapshot_id="snap-missing",
        )

    wager = decision_ledger.record_personal_wager_from_payload(
        {
            "eventId": "evt-sizing",
            "commenceTime": "2026-09-20T17:00:00+00:00",
            "awayTeam": "NO",
            "homeTeam": "ATL",
            "market": "spread",
            "side": "away",
            "point": 4.0,
            "price": -105.0,
            "sportsbook": "FanDuel",
            "amountRisked": 48.4,
            "unitsRisked": 0.48,
            "unitSizeAtBet": 100.0,
            "currentEV": 0.123,
            "calibratedProbability": 0.62,
            "impliedProbability": 0.512,
        },
        source_snapshot_id="snap-sized",
    )

    assert wager["unitsRisked"] == 0.484
    assert wager["amountRisked"] == 48.4
