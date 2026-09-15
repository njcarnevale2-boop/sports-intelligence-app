from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
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
    import app.routes.opportunities as opportunities_route

    projections = tmp_path / "current_game_projections.csv"
    board = tmp_path / "ranked_bet_board.csv"
    _write_game_projections(projections)
    _write_ranked_board(board)

    monkeypatch.setattr(games_module, "GAME_PROJECTIONS", projections)
    monkeypatch.setattr(games_module, "RANKED_BET_BOARD", board)
    monkeypatch.setattr(games_module.market_data_service, "metadata", lambda: {"provider": "line_movement_board", "lastUpdated": "2026-09-14T00:00:00+00:00", "dataStatus": "FILE"})
    monkeypatch.setattr(games_module.market_data_service, "all_event_snapshots", lambda: {"evt-nyg": {"provider": "line_movement_board", "lastUpdated": "2026-09-14T00:00:00+00:00", "dataStatus": "FILE", "booksTracked": 6, "consensusSpread": 2.5, "consensusTotal": 45.5, "consensusMoneyline": None}})
    monkeypatch.setattr(
        opportunities_route,
        "_get_opportunities_payload",
        lambda **kwargs: {
            "opportunities": [
                {
                    "eventId": "evt-nyg",
                    "pick": "NYG +3",
                    "market": "spread",
                    "side": "home",
                    "point": 3.0,
                    "price": -115.0,
                    "book": "FanDuel",
                    "recommendation": "STRONG BET",
                    "qualificationStatus": "QUALIFIED",
                    "qualificationReasons": ["Current model edge and confidence meet SIA qualification thresholds."],
                    "productionRank": 1,
                    "currentQualification": {"status": "QUALIFIED", "recommendation": "STRONG BET", "actionable": True},
                    "currentExecution": {"status": "AVAILABLE", "sportsbook": "FanDuel", "point": 3.0, "price": -115.0},
                    "originalCandidate": {"sportsbook": "DraftKings", "point": 2.5, "price": -110.0},
                    "executionDrift": {"originalCandidatePoint": 2.5, "currentExecutionPoint": 3.0, "lineDriftPoints": 0.5},
                    "sportsIntelligenceScore": {"score": 88.0},
                    "marketIntelligence": {"booksTracked": 6},
                }
            ]
        },
    )

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
    assert detail.get("sportsbook") == "FanDuel"
    assert detail.get("currentExecution", {}).get("sportsbook") == "FanDuel"
    assert detail.get("originalCandidate", {}).get("sportsbook") == "DraftKings"


def _write_single_game_projection(path: Path, *, event_id: str, away_team: str, home_team: str) -> None:
    pd.DataFrame(
        [
            {
                "api_event_id": event_id,
                "commence_time": "2026-09-20T17:00:00+00:00",
                "away_team": away_team,
                "home_team": home_team,
                "market_home_spread": -2.5,
                "market_total": 45.5,
                "model_margin_home": -1.0,
                "model_total_baseline": 45.1,
            }
        ]
    ).to_csv(path, index=False)


def _patch_games_shared_lookup(monkeypatch, tmp_path: Path, *, event_id: str, away_team: str, home_team: str, opportunities: list[dict], books_tracked: int = 6):
    import app.services.games as games_module
    import app.routes.opportunities as opportunities_route

    projections = tmp_path / f"{event_id}-current_game_projections.csv"
    _write_single_game_projection(projections, event_id=event_id, away_team=away_team, home_team=home_team)

    monkeypatch.setattr(games_module, "GAME_PROJECTIONS", projections)
    monkeypatch.setattr(games_module.market_data_service, "metadata", lambda: {"provider": "line_movement_board", "lastUpdated": "2026-09-15T13:54:11.761388+00:00", "dataStatus": "FILE"})
    monkeypatch.setattr(games_module.market_data_service, "all_event_snapshots", lambda: {event_id: {"provider": "line_movement_board", "lastUpdated": "2026-09-15T13:54:11.761388+00:00", "dataStatus": "FILE", "booksTracked": books_tracked, "consensusSpread": -2.5, "consensusTotal": 45.5, "consensusMoneyline": None}})
    monkeypatch.setattr(opportunities_route, "_get_opportunities_payload", lambda **kwargs: {"opportunities": list(opportunities)})
    monkeypatch.setattr(
        games_module.service,
        "_load_schedule_context_lookup",
        lambda: {("2026-09-20", away_team, home_team): (2026, 2)},
    )
    games_module.service._schedule_context_cache = {}
    games_module.service._schedule_context_mtime = None
    return games_module.service


@pytest.mark.parametrize(
    ("event_id", "away_team", "home_team", "opportunity", "expected_pick", "expected_book", "expected_point", "expected_price", "expected_drift"),
    [
        (
            "evt-nyg",
            "NYG",
            "LAR",
            {
                "eventId": "evt-nyg",
                "pick": "NYG +7.5",
                "market": "spread",
                "side": "away",
                "point": 7.5,
                "price": -120.0,
                "book": "FanDuel",
                "recommendation": "STRONG BET",
                "qualificationStatus": "QUALIFIED",
                "qualificationReasons": ["Current model edge and confidence meet SIA qualification thresholds."],
                "productionRank": 1,
                "currentQualification": {"status": "QUALIFIED", "recommendation": "STRONG BET", "actionable": True},
                "currentExecution": {"status": "AVAILABLE", "sportsbook": "FanDuel", "point": 7.5, "price": -120.0, "sportsbookCanonicalKey": "fanduel"},
                "originalCandidate": {"sportsbook": "DraftKings", "point": 8.5, "price": -110.0},
                "executionDrift": {"originalCandidatePoint": 8.5, "currentExecutionPoint": 7.5, "lineDriftPoints": -1.0},
                "sportsIntelligenceScore": {"score": 92.0},
                "marketIntelligence": {"booksTracked": 5},
            },
            "NYG +7.5",
            "FanDuel",
            7.5,
            -120.0,
            -1.0,
        ),
        (
            "evt-mia",
            "MIA",
            "SF",
            {
                "eventId": "evt-mia",
                "pick": "MIA +13.5",
                "market": "spread",
                "side": "away",
                "point": 13.5,
                "price": -110.0,
                "book": "BetMGM",
                "recommendation": "STRONG BET",
                "qualificationStatus": "QUALIFIED",
                "qualificationReasons": ["Current model edge and confidence meet SIA qualification thresholds."],
                "productionRank": 2,
                "currentQualification": {"status": "QUALIFIED", "recommendation": "STRONG BET", "actionable": True},
                "currentExecution": {"status": "AVAILABLE", "sportsbook": "BetMGM", "point": 13.5, "price": -110.0, "sportsbookCanonicalKey": "betmgm"},
                "originalCandidate": {"sportsbook": "DraftKings", "point": 10.5, "price": -110.0},
                "executionDrift": {"originalCandidatePoint": 10.5, "currentExecutionPoint": 13.5, "lineDriftPoints": 3.0},
                "sportsIntelligenceScore": {"score": 95.0},
                "marketIntelligence": {"booksTracked": 6},
            },
            "MIA +13.5",
            "BetMGM",
            13.5,
            -110.0,
            3.0,
        ),
        (
            "evt-no",
            "NO",
            "BAL",
            {
                "eventId": "evt-no",
                "pick": "NO +8.5",
                "market": "spread",
                "side": "away",
                "point": 8.5,
                "price": -109.0,
                "book": "Caesars",
                "recommendation": "STRONG BET",
                "qualificationStatus": "QUALIFIED",
                "qualificationReasons": ["Current model edge and confidence meet SIA qualification thresholds."],
                "productionRank": 3,
                "currentQualification": {"status": "QUALIFIED", "recommendation": "STRONG BET", "actionable": True},
                "currentExecution": {"status": "AVAILABLE", "sportsbook": "Caesars", "point": 8.5, "price": -109.0, "sportsbookCanonicalKey": "caesars"},
                "originalCandidate": {"sportsbook": "DraftKings", "point": 7.5, "price": -110.0},
                "executionDrift": {"originalCandidatePoint": 7.5, "currentExecutionPoint": 8.5, "lineDriftPoints": 1.0},
                "sportsIntelligenceScore": {"score": 91.0},
                "marketIntelligence": {"booksTracked": 6},
            },
            "NO +8.5",
            "Caesars",
            8.5,
            -109.0,
            1.0,
        ),
    ],
)
def test_games_mirrors_actionable_opportunity_semantics(monkeypatch, tmp_path, event_id, away_team, home_team, opportunity, expected_pick, expected_book, expected_point, expected_price, expected_drift):
    service = _patch_games_shared_lookup(
        monkeypatch,
        tmp_path,
        event_id=event_id,
        away_team=away_team,
        home_team=home_team,
        opportunities=[opportunity],
    )

    payload = service.list_games(week=2)
    game = payload["games"][0]
    detail = game["bestOpportunityDetail"]

    assert game["bestOpportunity"] == expected_pick
    assert game["recommendation"] == "STRONG BET"
    assert game["qualificationStatus"] == "QUALIFIED"
    assert game["betStatus"] == "STRONG BET"
    assert detail["pick"] == expected_pick
    assert detail["sportsbook"] == expected_book
    assert detail["point"] == expected_point
    assert detail["price"] == expected_price
    assert detail["currentExecution"] == opportunity["currentExecution"]
    assert detail["currentQualification"] == opportunity["currentQualification"]
    assert detail["originalCandidate"] == opportunity["originalCandidate"]
    assert detail["executionDrift"]["lineDriftPoints"] == expected_drift
    assert game["currentExecution"] == opportunity["currentExecution"]
    assert game["currentQualification"] == opportunity["currentQualification"]
    assert game["productionRank"] == opportunity["productionRank"]


@pytest.mark.parametrize(
    ("label", "opportunities", "books_tracked"),
    [
        ("stale approved market", [], 6),
        ("no approved market", [], 6),
        ("current opportunity dequalifies", [], 6),
    ],
)
def test_games_fail_closed_when_no_current_actionable_opportunity(monkeypatch, tmp_path, label, opportunities, books_tracked):
    service = _patch_games_shared_lookup(
        monkeypatch,
        tmp_path,
        event_id="evt-fail-closed",
        away_team="NYG",
        home_team="DAL",
        opportunities=opportunities,
        books_tracked=books_tracked,
    )

    payload = service.list_games(week=2)
    game = payload["games"][0]
    assert game["bestOpportunity"] is None, label
    assert game["bestOpportunityDetail"] is None, label
    assert game["qualificationStatus"] == "NOT_QUALIFIED", label
    assert game["betStatus"] == "NO QUALIFIED BET", label
    assert game["currentExecution"] is None, label
    assert game["currentQualification"] is None, label


def test_games_ignore_unapproved_better_quote_by_mirroring_approved_current_execution(monkeypatch, tmp_path):
    approved_opportunity = {
        "eventId": "evt-unapproved",
        "pick": "NYG +7.5",
        "market": "spread",
        "side": "away",
        "point": 7.5,
        "price": -120.0,
        "book": "FanDuel",
        "recommendation": "STRONG BET",
        "qualificationStatus": "QUALIFIED",
        "qualificationReasons": ["Current model edge and confidence meet SIA qualification thresholds."],
        "productionRank": 1,
        "currentQualification": {"status": "QUALIFIED", "recommendation": "STRONG BET", "actionable": True},
        "currentExecution": {"status": "AVAILABLE", "sportsbook": "FanDuel", "point": 7.5, "price": -120.0, "sportsbookCanonicalKey": "fanduel"},
        "originalCandidate": {"sportsbook": "BetUS", "point": 9.5, "price": -110.0},
        "executionDrift": {"originalCandidatePoint": 9.5, "currentExecutionPoint": 7.5, "lineDriftPoints": -2.0},
        "sportsIntelligenceScore": {"score": 90.0},
        "marketIntelligence": {"booksTracked": 5},
    }

    service = _patch_games_shared_lookup(
        monkeypatch,
        tmp_path,
        event_id="evt-unapproved",
        away_team="NYG",
        home_team="LAR",
        opportunities=[approved_opportunity],
    )

    game = service.list_games(week=2)["games"][0]
    detail = game["bestOpportunityDetail"]
    assert game["bestOpportunity"] == "NYG +7.5"
    assert detail["sportsbook"] == "FanDuel"
    assert detail["currentExecution"]["sportsbook"] == "FanDuel"
    assert detail["originalCandidate"]["sportsbook"] == "BetUS"


def test_games_and_opportunities_share_same_actionable_semantics(monkeypatch, tmp_path):
    shared_opportunity = {
        "eventId": "evt-shared",
        "pick": "NO +8.5",
        "market": "spread",
        "side": "away",
        "point": 8.5,
        "price": -109.0,
        "book": "Caesars",
        "recommendation": "STRONG BET",
        "qualificationStatus": "QUALIFIED",
        "qualificationReasons": ["Current model edge and confidence meet SIA qualification thresholds."],
        "productionRank": 3,
        "currentQualification": {"status": "QUALIFIED", "recommendation": "STRONG BET", "actionable": True},
        "currentExecution": {"status": "AVAILABLE", "sportsbook": "Caesars", "point": 8.5, "price": -109.0, "sportsbookCanonicalKey": "caesars"},
        "originalCandidate": {"sportsbook": "DraftKings", "point": 7.5, "price": -110.0},
        "executionDrift": {"originalCandidatePoint": 7.5, "currentExecutionPoint": 8.5, "lineDriftPoints": 1.0},
        "sportsIntelligenceScore": {"score": 91.0},
        "marketIntelligence": {"booksTracked": 6},
    }

    service = _patch_games_shared_lookup(
        monkeypatch,
        tmp_path,
        event_id="evt-shared",
        away_team="NO",
        home_team="BAL",
        opportunities=[shared_opportunity],
    )

    game = service.list_games(week=2)["games"][0]
    detail = game["bestOpportunityDetail"]
    assert game["bestOpportunity"] == shared_opportunity["pick"]
    assert detail["point"] == shared_opportunity["point"]
    assert detail["price"] == shared_opportunity["price"]
    assert detail["sportsbook"] == shared_opportunity["book"]
    assert detail["currentExecution"] == shared_opportunity["currentExecution"]
    assert detail["currentQualification"] == shared_opportunity["currentQualification"]
    assert detail["executionDrift"] == shared_opportunity["executionDrift"]


def test_canonical_payload_consistency_across_views_and_ledger_preview(monkeypatch, tmp_path):
    import app.services.games as games_module
    import app.routes.opportunities as opportunities_route
    import app.routes.decision_ledger as ledger_route

    projections = tmp_path / "fixture-current_game_projections.csv"
    _write_single_game_projection(projections, event_id="evt-shared", away_team="NO", home_team="BAL")

    shared_opportunity = {
        "id": "evt-shared-spread-away",
        "eventId": "evt-shared",
        "pick": "NO +8.5",
        "market": "spread",
        "side": "away",
        "point": 8.5,
        "price": -109.0,
        "book": "Caesars",
        "recommendation": "STRONG BET",
        "qualificationStatus": "QUALIFIED",
        "qualificationReasons": ["Current model edge and confidence meet SIA qualification thresholds."],
        "productionRank": 1,
        "currentQualification": {"status": "QUALIFIED", "recommendation": "STRONG BET", "actionable": True},
        "currentExecution": {"status": "AVAILABLE", "sportsbook": "Caesars", "point": 8.5, "price": -109.0, "sportsbookCanonicalKey": "caesars"},
        "originalCandidate": {"sportsbook": "DraftKings", "point": 7.5, "price": -110.0},
        "executionDrift": {"originalCandidatePoint": 7.5, "currentExecutionPoint": 8.5, "lineDriftPoints": 1.0},
        "sportsIntelligenceScore": {"score": 91.0},
        "marketIntelligence": {"booksTracked": 6},
        "currentWinProbability": 0.763828,
        "currentPushProbability": 0.0,
        "currentEV": 0.123,
        "calibratedEdge": 0.242297,
        "calibratedProbability": 0.763828,
        "truePlayableTo": 8.0,
        "commenceTime": "2026-09-20T17:00:00+00:00",
        "awayTeam": "NO",
        "homeTeam": "BAL",
    }

    monkeypatch.setattr(games_module, "GAME_PROJECTIONS", projections)
    monkeypatch.setattr(games_module.market_data_service, "metadata", lambda: {"provider": "line_movement_board", "lastUpdated": "2026-09-15T13:54:11.761388+00:00", "dataStatus": "FILE"})
    monkeypatch.setattr(games_module.market_data_service, "all_event_snapshots", lambda: {"evt-shared": {"provider": "line_movement_board", "lastUpdated": "2026-09-15T13:54:11.761388+00:00", "dataStatus": "FILE", "booksTracked": 6, "consensusSpread": -2.5, "consensusTotal": 45.5, "consensusMoneyline": None}})
    monkeypatch.setattr(games_module.service, "_load_schedule_context_lookup", lambda: {("2026-09-20", "NO", "BAL"): (2026, 2)})
    monkeypatch.setattr(opportunities_route, "GAME_PROJECTIONS", projections)
    monkeypatch.setattr(opportunities_route, "_get_opportunities_payload", lambda **kwargs: {"week": 2, "snapshotId": "snap-test", "lastUpdated": "2026-09-15T13:54:11.761388+00:00", "dataStatus": "FILE", "opportunities": [dict(shared_opportunity)]})
    monkeypatch.setattr(ledger_route, "get_opportunities", lambda **kwargs: {"week": 2, "snapshotId": "snap-test", "lastUpdated": "2026-09-15T13:54:11.761388+00:00", "dataStatus": "FILE", "opportunities": [dict(shared_opportunity)]})

    games_response = client.get("/api/games?week=2")
    assert games_response.status_code == 200
    game = games_response.json()["games"][0]
    detail = game.get("bestOpportunityDetail") or {}
    assert detail.get("pick") == shared_opportunity["pick"]
    assert float(detail.get("point")) == float(shared_opportunity["point"])
    assert float(detail.get("price")) == float(shared_opportunity["price"])
    assert detail.get("sportsbook") == shared_opportunity["book"]

    gi_response = client.get("/api/games/evt-shared/opportunity")
    assert gi_response.status_code == 200
    gi_opp = gi_response.json().get("opportunity")
    assert gi_opp is not None
    assert gi_opp.get("pick") == shared_opportunity["pick"]
    assert float(gi_opp.get("point")) == float(shared_opportunity["point"])
    assert float(gi_opp.get("price")) == float(shared_opportunity["price"])
    assert gi_opp.get("book") == shared_opportunity["book"]

    preview_response = client.get("/api/admin/ledger/official-sia3/preview?week=2", headers=ADMIN_HEADERS)
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview.get("snapshotId") == "snap-test"
    decision = next(slot.get("decision") for slot in preview.get("slots") or [] if slot.get("decision"))
    assert decision.get("selection") == shared_opportunity["pick"]
    assert float(decision.get("point")) == float(shared_opportunity["point"])
    assert float(decision.get("price")) == float(shared_opportunity["price"])
    assert decision.get("sportsbook") == shared_opportunity["book"]


def test_frontend_label_and_timezone_policy_regression_guards():
    repo_root = Path(__file__).resolve().parents[2]
    games_intel_page = (repo_root / "app" / "games" / "[eventId]" / "page.tsx").read_text(encoding="utf-8")
    time_format = (repo_root / "app" / "lib" / "time-format.ts").read_text(encoding="utf-8")

    assert "SIA&apos;s TAKE" in games_intel_page
    assert "Execution Panel" in games_intel_page
    assert "Research-only alternates" in games_intel_page
    assert "Invalidation trigger" in games_intel_page
    assert "Why does SIA like this?" in games_intel_page
    assert "What's the biggest risk?" in games_intel_page
    assert "What would make SIA pass?" in games_intel_page
    assert "Why isn't SIA betting this?" in games_intel_page
    assert "Minimum EV floor for modeled boundary:" in games_intel_page
    assert "What would make this a no-bet?" not in games_intel_page
    assert "Minimum required EV:" not in games_intel_page
    assert "America/New_York" in time_format
