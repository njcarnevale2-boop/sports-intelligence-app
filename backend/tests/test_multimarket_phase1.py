from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class _FakeFairPriceResult:
    fair_price: float | None = -118.0
    fair_line: float | None = None
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
    best_available_line: float | None = None


class _FakeInjuryContext:
    def build_context(self, away_team: str, home_team: str):
        return {"severity": "neutral", "summary": "neutral"}


def _write_ranked_board(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_game_projections(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def test_row_to_opportunity_moneyline_has_no_point(monkeypatch):
    import app.routes.opportunities as route

    monkeypatch.setattr(
        route,
        "get_market_intelligence",
        lambda event_id, market, side: {
            "score": 7.0,
            "signal": "CONFIRMED",
            "steamBooks": 1,
            "booksMoving": 2,
            "booksTracked": 8,
            "consensus": 70,
        },
    )
    monkeypatch.setattr(route, "InjuryMatchupContext", _FakeInjuryContext)
    monkeypatch.setattr(
        route,
        "build_fair_price_result",
        lambda row, group_rows, game_projection_row, minimum_playable_ev: _FakeFairPriceResult(),
    )

    row = pd.Series(
        {
            "api_event_id": "evt-ml-1",
            "commence_time": "2026-09-13T17:00:00+00:00",
            "away_team": "NYG",
            "home_team": "DAL",
            "market": "moneyline",
            "side": "away",
            "point": None,
            "sportsbook": "DraftKings",
            "price": 135,
            "model_prob": 0.48,
            "implied_prob_raw": 0.44,
            "fair_odds": 108,
            "edge_pp": 0.04,
            "ev_per_dollar": 0.05,
            "kelly_full": 0.02,
            "kelly_20pct": 0.004,
            "recommendation": "BET",
            "confidence_score": 66,
            "data_completeness": 0.95,
            "market_confidence": 0.8,
            "model_confidence": 0.7,
            "rank": 1,
        }
    )

    opp = route.row_to_opportunity(
        row,
        market_snapshot={"provider": "line_movement_board", "lastUpdated": "2026-09-13T15:00:00+00:00", "dataStatus": "FILE", "booksTracked": 8},
        injury_ctx=_FakeInjuryContext(),
    )

    assert opp["market"] == "moneyline"
    assert opp["marketType"] == "MONEYLINE"
    assert opp["point"] is None
    assert opp["productionEligible"] is False
    assert opp["marketValidationStatus"] == "SHADOW_VALIDATION"
    assert opp["correlationMetadata"]["eventExposure"] == "evt-ml-1"
    assert opp["correlationMetadata"]["marketFamily"] == "MONEYLINE"
    assert opp["correlationMetadata"]["marketDirection"] == "away"
    assert opp["correlationMetadata"]["teamExposure"] == ["NYG"]
    assert opp["correlationMetadata"]["correlationGroupId"].startswith("evt-ml-1:MONEYLINE:away")


def test_get_opportunities_generates_moneyline_and_total_candidates(tmp_path, monkeypatch):
    import app.routes.opportunities as route
    from app.services.games import service as games_service

    ranked_board = tmp_path / "ranked_bet_board.csv"
    projections = tmp_path / "current_game_projections.csv"

    _write_ranked_board(
        ranked_board,
        [
            {
                "api_event_id": "evt-1",
                "commence_time": "2026-09-13T17:00:00+00:00",
                "away_team": "NYG",
                "home_team": "DAL",
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
        ],
    )

    _write_game_projections(
        projections,
        [
            {
                "api_event_id": "evt-1",
                "commence_time": "2026-09-13T17:00:00+00:00",
                "away_team": "NYG",
                "home_team": "DAL",
                "model_margin_home": -2.5,
                "market_home_spread": -3.0,
                "model_total_baseline": 46.5,
                "market_total": 45.5,
            }
        ],
    )

    monkeypatch.setattr(route, "RANKED_BET_BOARD", ranked_board)
    monkeypatch.setattr(route, "GAME_PROJECTIONS", projections)

    monkeypatch.setattr(
        route,
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
    monkeypatch.setattr(route, "InjuryMatchupContext", _FakeInjuryContext)

    monkeypatch.setattr(
        route.market_data_service,
        "metadata",
        lambda: {
            "provider": "line_movement_board",
            "lastUpdated": "2026-09-13T15:00:00+00:00",
            "dataStatus": "FILE",
        },
    )
    monkeypatch.setattr(
        route.market_data_service,
        "all_event_snapshots",
        lambda: {
            "evt-1": {
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
        },
    )
    monkeypatch.setattr(
        route.market_data_service,
        "load_normalized_market_rows",
        lambda: [
            {
                "eventId": "evt-1",
                "commenceTime": "2026-09-13T17:00:00+00:00",
                "awayTeam": "NYG",
                "homeTeam": "DAL",
                "sportsbook": "DraftKings",
                "market": "moneyline",
                "side": "away",
                "point": None,
                "americanOdds": 135,
                "lastUpdated": "2026-09-13T15:00:00+00:00",
            },
            {
                "eventId": "evt-1",
                "commenceTime": "2026-09-13T17:00:00+00:00",
                "awayTeam": "NYG",
                "homeTeam": "DAL",
                "sportsbook": "DraftKings",
                "market": "moneyline",
                "side": "home",
                "point": None,
                "americanOdds": -155,
                "lastUpdated": "2026-09-13T15:00:00+00:00",
            },
            {
                "eventId": "evt-1",
                "commenceTime": "2026-09-13T17:00:00+00:00",
                "awayTeam": "NYG",
                "homeTeam": "DAL",
                "sportsbook": "DraftKings",
                "market": "total",
                "side": "over",
                "point": 45.5,
                "americanOdds": -110,
                "lastUpdated": "2026-09-13T15:00:00+00:00",
            },
            {
                "eventId": "evt-1",
                "commenceTime": "2026-09-13T17:00:00+00:00",
                "awayTeam": "NYG",
                "homeTeam": "DAL",
                "sportsbook": "DraftKings",
                "market": "total",
                "side": "under",
                "point": 45.5,
                "americanOdds": -110,
                "lastUpdated": "2026-09-13T15:00:00+00:00",
            },
        ],
    )

    monkeypatch.setattr(
        games_service,
        "list_games",
        lambda week=None: {
            "availableWeeks": [1],
            "games": [{"eventId": "evt-1", "season": 2026}],
        },
    )

    payload = route.get_opportunities(limit=25, best_lines_only=True, include_experimental=True, week=1)
    markets = {o["market"] for o in payload["opportunities"]}
    assert "spread" in markets
    assert "moneyline" in markets
    assert "total" in markets

    by_market = {o["market"]: o for o in payload["opportunities"]}
    assert by_market["spread"]["productionEligible"] is True
    assert by_market["spread"]["marketValidationStatus"] == "PRODUCTION_VALIDATED"
    assert by_market["moneyline"]["productionEligible"] is False
    assert by_market["moneyline"]["marketValidationStatus"] == "SHADOW_VALIDATION"
    assert by_market["total"]["productionEligible"] is False
    assert by_market["total"]["marketValidationStatus"] == "SHADOW_VALIDATION"

    assert by_market["spread"]["productionRank"] is not None
    assert by_market["moneyline"]["productionRank"] is None
    assert by_market["total"]["productionRank"] is None

    assert by_market["moneyline"]["qualificationStatus"] in {"QUALIFIED", "NOT_QUALIFIED"}
    assert by_market["moneyline"]["productionEligible"] is False

    keys = {(o["eventId"], o["market"], o["side"]) for o in payload["opportunities"]}
    assert len(keys) == len(payload["opportunities"])
