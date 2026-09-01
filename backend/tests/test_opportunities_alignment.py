from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


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


def _write_ranked_board(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_game_projections(path: Path, event_ids: list[str]) -> None:
    rows = []
    for eid in event_ids:
        rows.append(
            {
                "api_event_id": eid,
                "commence_time": "2026-09-13T17:00:00+00:00",
                "away_team": "NO",
                "home_team": "ATL",
                "model_margin_home": -1.0,
                "market_home_spread": -2.5,
                "model_total_baseline": 45.0,
                "market_total": 44.0,
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)


def _patch_dependencies(monkeypatch, tmp_path: Path, rows: list[dict]):
    import app.routes.opportunities as opportunities_route
    from app.services.games import service as games_service

    ranked_board = tmp_path / "ranked_bet_board.csv"
    projections = tmp_path / "current_game_projections.csv"
    _write_ranked_board(ranked_board, rows)
    _write_game_projections(projections, [str(r["api_event_id"]) for r in rows])

    monkeypatch.setattr(opportunities_route, "RANKED_BET_BOARD", ranked_board)
    monkeypatch.setattr(opportunities_route, "GAME_PROJECTIONS", projections)

    monkeypatch.setattr(
        opportunities_route,
        "get_market_intelligence",
        lambda event_id, market, side: {
            "score": 7.0,
            "signal": "CONFIRMED",
            "steamBooks": 1,
            "booksMoving": 3,
            "booksTracked": 8,
            "consensus": 70,
        },
    )

    class _FakeInjuryContext:
        def build_context(self, away_team: str, home_team: str):
            return {"severity": "neutral", "summary": "neutral"}

    monkeypatch.setattr(opportunities_route, "InjuryMatchupContext", _FakeInjuryContext)

    monkeypatch.setattr(
        opportunities_route,
        "build_fair_price_result",
        lambda row, group_rows, game_projection_row, minimum_playable_ev: _FakeFairPriceResult(),
    )

    monkeypatch.setattr(
        opportunities_route.market_data_service,
        "metadata",
        lambda: {
            "provider": "line_movement_board",
            "lastUpdated": "2026-09-13T15:00:00+00:00",
            "dataStatus": "FILE",
        },
    )
    monkeypatch.setattr(
        opportunities_route.market_data_service,
        "all_event_snapshots",
        lambda: {
            str(r["api_event_id"]): {
                "provider": "line_movement_board",
                "lastUpdated": "2026-09-13T15:00:00+00:00",
                "dataStatus": "FILE",
                "booksTracked": 8,
                "bestAwaySpread": None,
                "bestHomeSpread": None,
                "bestAwayMoneyline": None,
                "bestHomeMoneyline": None,
                "bestOver": None,
                "bestUnder": None,
                "bestPriceAwaySpread": None,
                "bestPriceHomeSpread": None,
                "bestPriceAwayMoneyline": None,
                "bestPriceHomeMoneyline": None,
                "bestPriceOver": None,
                "bestPriceUnder": None,
            }
            for r in rows
        },
    )

    monkeypatch.setattr(
        games_service,
        "list_games",
        lambda week=None: {
            "availableWeeks": [1],
            "games": [
                {"eventId": str(r["api_event_id"]), "season": 2026}
                for r in rows
            ],
        },
    )

    return opportunities_route


def test_opportunities_rank_by_calibrated_edge_and_emit_snapshot_metadata(tmp_path, monkeypatch):
    rows = [
        {
            "api_event_id": "evt-1",
            "commence_time": "2026-09-13T17:00:00+00:00",
            "away_team": "NO",
            "home_team": "ATL",
            "market": "spread",
            "side": "away",
            "point": 3.0,
            "sportsbook": "DraftKings",
            "price": -110,
            "model_prob": 0.58,
            "implied_prob_raw": 0.55,
            "fair_odds": -120,
            "edge_pp": 0.03,
            "ev_per_dollar": 0.04,
            "kelly_full": 0.03,
            "kelly_20pct": 0.006,
            "recommendation": "BET",
            "confidence_score": 68,
            "data_completeness": 0.95,
            "market_confidence": 0.8,
            "model_confidence": 0.7,
            "rank": 1,
        },
        {
            "api_event_id": "evt-2",
            "commence_time": "2026-09-13T20:00:00+00:00",
            "away_team": "DEN",
            "home_team": "KC",
            "market": "spread",
            "side": "away",
            "point": 4.0,
            "sportsbook": "DraftKings",
            "price": -110,
            "model_prob": 0.67,
            "implied_prob_raw": 0.55,
            "fair_odds": -128,
            "edge_pp": 0.12,
            "ev_per_dollar": 0.09,
            "kelly_full": 0.06,
            "kelly_20pct": 0.012,
            "recommendation": "BET",
            "confidence_score": 72,
            "data_completeness": 0.95,
            "market_confidence": 0.8,
            "model_confidence": 0.7,
            "rank": 2,
        },
    ]

    opportunities_route = _patch_dependencies(monkeypatch, tmp_path, rows)
    payload = opportunities_route.get_opportunities(limit=10, best_lines_only=True, week=1)

    assert payload["snapshotId"]
    assert payload["calibrationStatus"] == "ACTIVE"
    assert payload["calibrationMethod"] == "GUARDED_ISOTONIC"
    assert payload["calibrationVersion"]
    assert payload["rankingVersion"]
    assert payload["qualificationPolicyVersion"]

    opps = payload["opportunities"]
    assert opps[0]["eventId"] == "evt-2"
    assert opps[0]["rank"] == 1
    assert opps[0]["rawRank"] == 2
    assert opps[1]["eventId"] == "evt-1"


def test_opportunity_qualification_and_si_inputs_use_push_aware_semantics(tmp_path, monkeypatch):
    rows = [
        {
            "api_event_id": "evt-lean-1",
            "commence_time": "2026-09-13T17:00:00+00:00",
            "away_team": "NYG",
            "home_team": "DAL",
            "market": "spread",
            "side": "away",
            "point": 3.0,
            "sportsbook": "DraftKings",
            "price": -110,
            "model_prob": 0.62,
            "implied_prob_raw": 0.55,
            "fair_odds": -121,
            "edge_pp": 0.07,
            "ev_per_dollar": 0.01,
            "kelly_full": 0.01,
            "kelly_20pct": 0.002,
            "recommendation": "LEAN",
            "confidence_score": 61,
            "data_completeness": 0.9,
            "market_confidence": 0.7,
            "model_confidence": 0.6,
            "rank": 1,
        }
    ]

    opportunities_route = _patch_dependencies(monkeypatch, tmp_path, rows)
    payload = opportunities_route.get_opportunities(limit=10, best_lines_only=True, week=1)
    opp = payload["opportunities"][0]

    assert opp["qualificationStatus"] == "NOT_QUALIFIED"
    assert opp["qualificationReasons"]

    # push-aware fair-price EV is canonical input now
    assert opp["currentEV"] == 0.123
    assert opp["evPerDollar"] == 0.123

    # edge now tracks current calibrated win probability vs implied probability
    assert opp["edge"] == 7.0
    assert round(float(opp["calibratedEdge"]), 6) == 0.07

    # SI expected value component should reflect 0.123 EV, not raw board EV.
    si = opp["sportsIntelligenceScore"]
    assert abs(float(si["components"]["expectedValue"]) - 24.6) < 0.2


def test_spread_opportunity_emits_boundary_research_metadata(tmp_path, monkeypatch):
    rows = [
        {
            "api_event_id": "evt-boundary-1",
            "commence_time": "2026-09-13T17:00:00+00:00",
            "away_team": "NO",
            "home_team": "ATL",
            "market": "spread",
            "side": "away",
            "point": 3.0,
            "sportsbook": "DraftKings",
            "price": -110,
            "model_prob": 0.58,
            "implied_prob_raw": 0.55,
            "fair_odds": -120,
            "edge_pp": 0.03,
            "ev_per_dollar": 0.04,
            "kelly_full": 0.03,
            "kelly_20pct": 0.006,
            "recommendation": "BET",
            "confidence_score": 68,
            "data_completeness": 0.95,
            "market_confidence": 0.8,
            "model_confidence": 0.7,
            "rank": 1,
        }
    ]

    opportunities_route = _patch_dependencies(monkeypatch, tmp_path, rows)
    payload = opportunities_route.get_opportunities(limit=10, best_lines_only=True, week=1)
    opp = payload["opportunities"][0]

    research = opp["executionBoundaryResearch"]
    assert research["mode"] == "OBSERVED_PLUS_MODEL_SIMULATION"
    assert research["observedExecution"]["quoteObserved"] is True
    assert research["observedExecution"]["line"] == 3.0
    assert research["theoreticalBoundary"]["status"] in {"AVAILABLE", "UNAVAILABLE"}
    assert research["theoreticalBoundary"]["distanceBucket"] in {"3.0+", "2.5", "2.0", "1.5", "1.0", "0.5", "0.0", "UNAVAILABLE"}
    assert isinstance(research["transitionFlags"]["crossesZero"], bool)
    assert isinstance(research["degradationPath"], list)
    assert research["degradationPath"][0]["quoteObserved"] is True
