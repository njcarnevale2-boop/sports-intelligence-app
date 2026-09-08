from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.routes import opportunities
from app.services.decision_ledger import build_official_sia3_preview, publish_official_sia3_from_preview
from app.services.fair_price import build_fair_price_result
from app.services.market_data import select_best_line_row
from app.services.probability_engine import HistoricalResiduals
from app.services.sportsbook_policy import filter_current_market_sportsbook_rows, is_current_market_sportsbook_allowed


def _mock_residuals() -> HistoricalResiduals:
    return HistoricalResiduals(
        margin_residuals=np.array([-3.0, -1.0, 0.0, 1.0, 3.0]),
        total_residuals=np.array([-4.0, -2.0, 0.0, 2.0, 4.0]),
        sample_size=1000,
    )


def _current_board_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "api_event_id": "evt-lowvig",
                "rank": 1,
                "market": "spread",
                "side": "away",
                "point": 3.0,
                "price": -105,
                "model_prob": 0.774,
                "implied_prob_raw": 0.512,
                "recommendation": "STRONG BET",
                "qualification_status": "QUALIFIED",
                "qualification_reasons": ["Current model edge and confidence meet SIA qualification thresholds."],
                "confidence_score": 86,
                "data_completeness": 1.0,
                "edge_pp": 0.262,
                "ev_per_dollar": 0.51,
                "kelly_full": 0.54,
                "kelly_20pct": 0.11,
                "sportsbook": "LowVig.ag",
                "away_team": "NO",
                "home_team": "ATL",
                "market_no_vig_prob": 0.52,
            },
            {
                "api_event_id": "evt-lowvig",
                "rank": 2,
                "market": "spread",
                "side": "away",
                "point": 3.0,
                "price": -110,
                "model_prob": 0.62,
                "implied_prob_raw": 0.5238,
                "recommendation": "QUALIFIED",
                "qualification_status": "QUALIFIED",
                "qualification_reasons": ["Current model edge and confidence meet SIA qualification thresholds."],
                "confidence_score": 78,
                "data_completeness": 1.0,
                "edge_pp": 0.0962,
                "ev_per_dollar": 0.12,
                "kelly_full": 0.15,
                "kelly_20pct": 0.03,
                "sportsbook": "DraftKings",
                "away_team": "NO",
                "home_team": "ATL",
                "market_no_vig_prob": 0.52,
            },
        ]
    )


def test_current_market_policy_filters_raw_history_without_mutating_source() -> None:
    raw = pd.DataFrame(
        [
            {"sportsbook": "LowVig.ag", "price": -105},
            {"sportsbook": "DraftKings", "price": -110},
        ]
    )
    original = raw.copy(deep=True)

    filtered = filter_current_market_sportsbook_rows(raw)

    assert is_current_market_sportsbook_allowed("DraftKings") is True
    assert is_current_market_sportsbook_allowed("LowVig.ag") is False
    assert is_current_market_sportsbook_allowed("low vig ag") is False
    assert is_current_market_sportsbook_allowed("LOW-VIG.AG") is False
    assert list(filtered["sportsbook"]) == ["DraftKings"]
    assert raw.equals(original)


def test_select_best_line_row_ignores_lowvig_even_when_it_has_better_odds() -> None:
    group = pd.DataFrame(
        [
            {"sportsbook": "LowVig.ag", "market": "spread", "side": "away", "point": 3.0, "price": -105},
            {"sportsbook": "DraftKings", "market": "spread", "side": "away", "point": 3.0, "price": -110},
            {"sportsbook": "FanDuel", "market": "spread", "side": "away", "point": 2.5, "price": -115},
        ]
    )

    selected = select_best_line_row(group)

    assert selected is not None
    assert selected["sportsbook"] == "DraftKings"


def test_non_lowvig_selection_is_preserved() -> None:
    group = pd.DataFrame(
        [
            {"sportsbook": "DraftKings", "market": "spread", "side": "away", "point": 3.0, "price": -110},
            {"sportsbook": "FanDuel", "market": "spread", "side": "away", "point": 3.0, "price": -115},
        ]
    )

    selected = select_best_line_row(group)

    assert selected is not None
    assert selected["sportsbook"] == "DraftKings"


def test_make_alternate_and_all_available_books_exclude_lowvig() -> None:
    group = pd.DataFrame(
        [
            {"sportsbook": "DraftKings", "market": "spread", "side": "away", "point": 3.0, "price": -110, "edge_pp": 0.10, "ev_per_dollar": 0.12},
            {"sportsbook": "LowVig.ag", "market": "spread", "side": "away", "point": 3.0, "price": -105, "edge_pp": 0.26, "ev_per_dollar": 0.51},
            {"sportsbook": "BetRivers", "market": "spread", "side": "away", "point": 2.5, "price": -112, "edge_pp": 0.08, "ev_per_dollar": 0.09},
        ]
    )
    selected = group.iloc[0]

    alternates = opportunities.make_alternate_books(group, selected)
    all_books = opportunities.make_all_available_books(group, selected)

    assert all(item["book"] != "LowVig.ag" for item in alternates)
    assert all(item["book"] != "LowVig.ag" for item in all_books)
    assert all_books[0]["book"] == "DraftKings"


def test_build_fair_price_result_fails_closed_for_excluded_sportsbook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.probability_engine.load_historical_residuals", _mock_residuals)

    row = pd.Series(
        {
            "sportsbook": "LowVig.ag",
            "market": "spread",
            "side": "away",
            "model_prob": 0.774,
            "ev_per_dollar": 0.51,
            "point": 3.0,
            "price": -105,
        }
    )

    group = pd.DataFrame(
        [
            {"sportsbook": "LowVig.ag", "market": "spread", "side": "away", "point": 3.0, "price": -105, "ev_per_dollar": 0.51},
            {"sportsbook": "DraftKings", "market": "spread", "side": "away", "point": 3.0, "price": -110, "ev_per_dollar": 0.12},
        ]
    )

    projection = pd.Series({"model_margin_home": 2.7})

    result = build_fair_price_result(
        row=row,
        group_rows=group,
        game_projection_row=projection,
        minimum_playable_ev=0.02,
    )

    assert result.current_win_probability is None
    assert result.current_push_probability is None
    assert result.current_loss_probability is None
    assert result.current_ev is None
    assert result.fair_price is None
    assert result.true_playable_to is None
    assert result.worst_observed_playable_price == 3.0
    assert result.playable_to == 3.0
    assert result.playable_to_status == "AVAILABLE"


def test_current_opportunities_skip_lowvig_and_recompute_from_remaining_quotes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    board_path = tmp_path / "ranked_bet_board.csv"
    _current_board_rows().to_csv(board_path, index=False)

    monkeypatch.setattr(opportunities, "RANKED_BET_BOARD", board_path)
    monkeypatch.setattr(opportunities.market_data_service, "metadata", lambda: {"provider": "line_movement_board", "lastUpdated": "2026-09-07T00:00:00+00:00", "dataStatus": "FILE"})
    monkeypatch.setattr(
        opportunities.market_data_service,
        "all_event_snapshots",
        lambda: {
            "evt-lowvig": {
                "provider": "line_movement_board",
                "lastUpdated": "2026-09-07T00:00:00+00:00",
                "dataStatus": "FILE",
                "booksTracked": 2,
                "bestAwaySpread": {"sportsbook": "DraftKings", "line": 3.0, "price": -110, "lastUpdated": "2026-09-07T00:00:00+00:00"},
                "bestHomeSpread": None,
                "bestAwayMoneyline": None,
                "bestHomeMoneyline": None,
                "bestOver": None,
                "bestUnder": None,
                "bestPriceAwaySpread": {"sportsbook": "DraftKings", "line": 3.0, "price": -110, "lastUpdated": "2026-09-07T00:00:00+00:00"},
                "bestPriceHomeSpread": None,
                "bestPriceAwayMoneyline": None,
                "bestPriceHomeMoneyline": None,
                "bestPriceOver": None,
                "bestPriceUnder": None,
                "consensusSpread": 3.0,
                "consensusTotal": None,
                "consensusMoneyline": None,
            }
        },
    )
    monkeypatch.setattr(opportunities, "load_game_projection_lookup", lambda: {"evt-lowvig": {"model_margin_home": 2.7, "model_total_baseline": 47.5}})
    monkeypatch.setattr(opportunities, "_build_generated_multimarket_candidates", lambda **kwargs: [])
    monkeypatch.setattr(opportunities, "get_market_intelligence", lambda **kwargs: {"booksTracked": 2, "booksMoving": 1, "signal": "CONFIRMED"})

    class _FakeInjuryContext:
        def build_context(self, away_team: str, home_team: str) -> dict[str, str]:
            return {"summary": f"{away_team} vs {home_team} injury context"}

    monkeypatch.setattr(opportunities, "InjuryMatchupContext", _FakeInjuryContext)
    monkeypatch.setattr("app.services.games.service.list_games", lambda week=None, game_date=None: {"availableWeeks": [1], "games": [{"eventId": "evt-lowvig", "season": 2026, "week": 1}]})
    monkeypatch.setattr("app.services.probability_engine.load_historical_residuals", _mock_residuals)

    payload = opportunities.get_opportunities(limit=10, best_lines_only=True, week=1)

    assert payload["count"] == 1
    opp = payload["opportunities"][0]
    assert opp["book"] == "DraftKings"
    assert opp["point"] == 3.0
    assert opp["price"] == -110.0
    assert round(float(opp["evPerDollar"]), 3) == -0.036
    assert opp["kelly20"] == 0.03
    assert opp["allAvailableBooks"][0]["book"] == "DraftKings"
    assert all(book["book"] != "LowVig.ag" for book in opp["allAvailableBooks"])


def test_lowvig_only_current_opportunity_cannot_remain_actionable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    board_path = tmp_path / "ranked_bet_board.csv"
    pd.DataFrame(
        [
            {
                "api_event_id": "evt-lowvig-only",
                "rank": 1,
                "market": "spread",
                "side": "away",
                "point": 3.0,
                "price": -105,
                "model_prob": 0.774,
                "implied_prob_raw": 0.512,
                "recommendation": "STRONG BET",
                "qualification_status": "QUALIFIED",
                "qualification_reasons": ["Current model edge and confidence meet SIA qualification thresholds."],
                "confidence_score": 86,
                "data_completeness": 1.0,
                "edge_pp": 0.262,
                "ev_per_dollar": 0.51,
                "kelly_full": 0.54,
                "kelly_20pct": 0.11,
                "sportsbook": "LowVig.ag",
                "away_team": "NO",
                "home_team": "ATL",
                "market_no_vig_prob": 0.52,
            }
        ]
    ).to_csv(board_path, index=False)

    monkeypatch.setattr(opportunities, "RANKED_BET_BOARD", board_path)
    monkeypatch.setattr(opportunities.market_data_service, "metadata", lambda: {"provider": "line_movement_board", "lastUpdated": "2026-09-07T00:00:00+00:00", "dataStatus": "FILE"})
    monkeypatch.setattr(opportunities.market_data_service, "all_event_snapshots", lambda: {})
    monkeypatch.setattr(opportunities, "load_game_projection_lookup", lambda: {})
    monkeypatch.setattr(opportunities, "_build_generated_multimarket_candidates", lambda **kwargs: [])
    monkeypatch.setattr(opportunities, "get_market_intelligence", lambda **kwargs: {"booksTracked": 0, "booksMoving": 0, "signal": "UNSET"})
    monkeypatch.setattr(opportunities, "InjuryMatchupContext", lambda: type("_FakeInjuryContext", (), {"build_context": lambda self, away_team, home_team: {"summary": "none"}})())
    monkeypatch.setattr("app.services.games.service.list_games", lambda week=None, game_date=None: {"availableWeeks": [1], "games": [{"eventId": "evt-lowvig-only", "season": 2026, "week": 1}]})

    payload = opportunities.get_opportunities(limit=10, best_lines_only=True, week=1)

    assert payload["count"] == 0
    assert payload["opportunities"] == []


def test_official_preview_excludes_lowvig_and_publish_rejects_excluded_quotes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opportunities_list = [
        {
            "eventId": "evt-preview",
            "book": "LowVig.ag",
            "market": "spread",
            "side": "away",
            "pick": "NO +3",
            "point": 3.0,
            "price": -105,
            "qualificationStatus": "QUALIFIED",
            "productionEligible": True,
        },
        {
            "eventId": "evt-preview",
            "book": "DraftKings",
            "market": "spread",
            "side": "away",
            "pick": "NO +3",
            "point": 3.0,
            "price": -110,
            "qualificationStatus": "QUALIFIED",
            "productionEligible": True,
        },
    ]

    preview = build_official_sia3_preview(opportunities_list, season=2026, week=1)
    assert preview["slots"][0]["decision"]["sportsbook"] == "DraftKings"
    assert all(slot.get("decision") is None or slot["decision"].get("sportsbook") != "LowVig.ag" for slot in preview["slots"])

    blocked_preview = {
        "publishedAtUTC": "2026-09-07T16:00:00+00:00",
        "season": 2026,
        "week": 1,
        "staleSlotCount": 0,
        "missingSnapshotLinkageCount": 0,
        "slots": [
            {
                "rank": 1,
                "slotLabel": "BET",
                "qualificationStatus": "QUALIFIED",
                "decision": {
                    "eventId": "evt-preview",
                    "market": "spread",
                    "book": "LowVig.ag",
                    "selection": "NO +3",
                    "point": 3.0,
                    "price": -105,
                },
            }
        ],
    }

    with pytest.raises(ValueError, match="excluded sportsbook"):
        publish_official_sia3_from_preview(blocked_preview)