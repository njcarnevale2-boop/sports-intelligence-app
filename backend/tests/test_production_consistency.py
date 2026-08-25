from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
ADMIN_HEADERS = {"x-admin-token": "dev-admin-token"}


def _write_game_projections(path: Path, event_id: str = "evt-nyg") -> None:
    pd.DataFrame(
        [
            {
                "api_event_id": event_id,
                "commence_time": "2026-09-14T00:20:00+00:00",
                "away_team": "DAL",
                "home_team": "NYG",
                "market_home_spread": 2.67,
                "market_total": 45.5,
                "model_margin_home": 1.2,
                "model_total_baseline": 45.1,
            }
        ]
    ).to_csv(path, index=False)


def _write_ranked_board(path: Path, event_id: str = "evt-nyg") -> None:
    pd.DataFrame(
        [
            {
                "api_event_id": event_id,
                "commence_time": "2026-09-14T00:20:00+00:00",
                "away_team": "DAL",
                "home_team": "NYG",
                "market": "spread",
                "side": "home",
                "point": 2.5,
                "sportsbook": "BookA",
                "price": -110,
                "model_prob": 0.61,
                "implied_prob_raw": 0.55,
                "fair_odds": -122,
                "edge_pp": 0.06,
                "ev_per_dollar": 0.05,
                "kelly_full": 0.03,
                "kelly_20pct": 0.006,
                "recommendation": "STRONG BET",
                "confidence_score": 82,
                "data_completeness": 0.94,
                "market_confidence": 0.8,
                "model_confidence": 0.79,
                "rank": 1,
            },
            {
                "api_event_id": event_id,
                "commence_time": "2026-09-14T00:20:00+00:00",
                "away_team": "DAL",
                "home_team": "NYG",
                "market": "spread",
                "side": "home",
                "point": 3.0,
                "sportsbook": "BookB",
                "price": -115,
                "model_prob": 0.61,
                "implied_prob_raw": 0.55,
                "fair_odds": -122,
                "edge_pp": 0.06,
                "ev_per_dollar": 0.05,
                "kelly_full": 0.03,
                "kelly_20pct": 0.006,
                "recommendation": "STRONG BET",
                "confidence_score": 82,
                "data_completeness": 0.94,
                "market_confidence": 0.8,
                "model_confidence": 0.79,
                "rank": 2,
            },
        ]
    ).to_csv(path, index=False)


def test_games_recommendation_uses_team_abbreviation_and_no_duplicate_label(tmp_path, monkeypatch):
    import app.services.games as games_module

    projections = tmp_path / "current_game_projections.csv"
    board = tmp_path / "ranked_bet_board.csv"
    _write_game_projections(projections)
    _write_ranked_board(board)

    monkeypatch.setattr(games_module, "GAME_PROJECTIONS", projections)
    monkeypatch.setattr(games_module, "RANKED_BET_BOARD", board)

    games_module.service._opportunities_cache = {}
    games_module.service._schedule_context_cache = {}

    payload = games_module.service.list_games()
    assert payload["count"] == 1

    game = payload["games"][0]
    assert game["recommendation"] == "STRONG BET"
    assert game["bestOpportunity"] == "NYG +3"
    assert "STRONG BET:" not in game["bestOpportunity"]
    assert "Home" not in game["bestOpportunity"]
    assert "Away" not in game["bestOpportunity"]

    detail = game.get("bestOpportunityDetail") or {}
    assert detail.get("pick") == "NYG +3"
    assert detail.get("price") == -115.0
    assert detail.get("sportsbook") == "BookB"


def test_canonical_payload_consistency_across_views_and_ledger_preview():
    opps_response = client.get("/api/opportunities?limit=100")
    assert opps_response.status_code == 200
    opps_payload = opps_response.json()
    opps = opps_payload.get("opportunities") or []
    assert opps

    week = opps_payload.get("week")
    assert week is not None

    games_response = client.get(f"/api/games?week={week}")
    assert games_response.status_code == 200
    games_payload = games_response.json()
    games_by_event = {g["eventId"]: g for g in games_payload.get("games") or []}

    preview_response = client.get(f"/api/admin/ledger/official-sia3/preview?week={week}", headers=ADMIN_HEADERS)
    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload.get("snapshotId") == opps_payload.get("snapshotId")

    preview_by_event = {}
    for slot in preview_payload.get("slots") or []:
        decision = slot.get("decision")
        if decision and decision.get("eventId"):
            preview_by_event[decision["eventId"]] = decision

    for opp in opps[:3]:
        event_id = opp["eventId"]
        game = games_by_event.get(event_id)
        assert game is not None

        detail = game.get("bestOpportunityDetail") or {}
        assert detail.get("pick") == opp.get("pick")
        assert float(detail.get("point")) == float(opp.get("point"))
        assert float(detail.get("price")) == float(opp.get("price"))
        assert detail.get("sportsbook") == opp.get("book")

        gi_response = client.get(f"/api/games/{event_id}/opportunity")
        assert gi_response.status_code == 200
        gi_payload = gi_response.json()
        gi_opp = gi_payload.get("opportunity")
        assert gi_opp is not None

        assert gi_opp.get("eventId") == opp.get("eventId")
        assert gi_opp.get("pick") == opp.get("pick")
        assert float(gi_opp.get("point")) == float(opp.get("point"))
        assert float(gi_opp.get("price")) == float(opp.get("price"))
        assert gi_opp.get("book") == opp.get("book")
        assert abs(float(gi_opp.get("currentWinProbability") or 0.0) - float(opp.get("currentWinProbability") or 0.0)) < 1e-9
        assert abs(float(gi_opp.get("currentPushProbability") or 0.0) - float(opp.get("currentPushProbability") or 0.0)) < 1e-9
        assert abs(float(gi_opp.get("currentEV") or 0.0) - float(opp.get("currentEV") or 0.0)) < 1e-9
        assert abs(float(gi_opp.get("calibratedEdge") or 0.0) - float(opp.get("calibratedEdge") or 0.0)) < 1e-9
        assert abs(float((gi_opp.get("sportsIntelligenceScore") or {}).get("score") or 0.0) - float((opp.get("sportsIntelligenceScore") or {}).get("score") or 0.0)) < 1e-9
        assert gi_opp.get("recommendation") == opp.get("recommendation")
        assert float(gi_opp.get("truePlayableTo")) == float(opp.get("truePlayableTo"))

        preview_decision = preview_by_event.get(event_id)
        assert preview_decision is not None
        assert preview_decision.get("eventId") == opp.get("eventId")
        assert preview_decision.get("selection") == opp.get("pick")
        assert float(preview_decision.get("point")) == float(opp.get("point"))
        assert float(preview_decision.get("price")) == float(opp.get("price"))
        assert preview_decision.get("sportsbook") == opp.get("book")
        assert abs(float(preview_decision.get("calibratedProbability") or 0.0) - float(opp.get("calibratedProbability") or 0.0)) < 1e-9
        assert abs(float(preview_decision.get("pushProbability") or 0.0) - float(opp.get("currentPushProbability") or 0.0)) < 1e-9
        assert abs(float(preview_decision.get("currentEV") or 0.0) - float(opp.get("currentEV") or 0.0)) < 1e-9
        assert abs(float(preview_decision.get("calibratedEdge") or 0.0) - float(opp.get("calibratedEdge") or 0.0)) < 1e-9
        assert abs(float(preview_decision.get("siScore") or 0.0) - float((opp.get("sportsIntelligenceScore") or {}).get("score") or 0.0)) < 1e-9
        assert preview_decision.get("recommendation") == opp.get("recommendation")
        assert float(preview_decision.get("truePlayableTo")) == float(opp.get("truePlayableTo"))
        assert preview_decision.get("sourceSnapshotId")


def test_frontend_label_and_timezone_policy_regression_guards():
    repo_root = Path(__file__).resolve().parents[2]
    games_intel_page = (repo_root / "app" / "games" / "[eventId]" / "page.tsx").read_text(encoding="utf-8")
    time_format = (repo_root / "app" / "lib" / "time-format.ts").read_text(encoding="utf-8")

    assert "SIA&apos;s TAKE" in games_intel_page
    assert "Execution Panel" in games_intel_page
    assert "Research-only alternates" in games_intel_page
    assert "Invalidation trigger" in games_intel_page
    assert "Playable-To EV floor:" in games_intel_page
    assert "Minimum required EV:" not in games_intel_page
    assert "America/New_York" in time_format
