from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

from app.services.cross_market_normalization import attach_shadow_global_scores


RESEARCH_DIR = Path(__file__).resolve().parents[1] / "research"
if str(RESEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(RESEARCH_DIR))

import sia_cross_market_phase1_normalization as cm  # noqa: E402



def _synthetic_candidates() -> pd.DataFrame:
    rows = [
        {"season": 2026, "week": 1, "game_id": "g1", "marketFamily": "SPREAD", "side": "away", "line": 3.0, "price": -110, "model_prob_calibrated": 0.56, "market_prob_novig": 0.51, "edge": 0.05, "push_prob": 0.02, "ev": 0.06, "result": "WIN", "y_win": 1, "profit": 0.9091},
        {"season": 2026, "week": 1, "game_id": "g1", "marketFamily": "MONEYLINE", "side": "away", "line": None, "price": 135, "model_prob_calibrated": 0.48, "market_prob_novig": 0.44, "edge": 0.04, "push_prob": 0.0, "ev": 0.08, "result": "WIN", "y_win": 1, "profit": 1.35},
        {"season": 2026, "week": 1, "game_id": "g1", "marketFamily": "TOTAL", "side": "over", "line": 45.5, "price": -110, "model_prob_calibrated": 0.54, "market_prob_novig": 0.50, "edge": 0.04, "push_prob": 0.03, "ev": 0.04, "result": "PUSH", "y_win": 0, "profit": 0.0},
        {"season": 2026, "week": 2, "game_id": "g2", "marketFamily": "SPREAD", "side": "home", "line": -2.5, "price": -108, "model_prob_calibrated": 0.55, "market_prob_novig": 0.50, "edge": 0.05, "push_prob": 0.02, "ev": 0.05, "result": "LOSS", "y_win": 0, "profit": -1.0},
        {"season": 2026, "week": 2, "game_id": "g2", "marketFamily": "MONEYLINE", "side": "home", "line": None, "price": -145, "model_prob_calibrated": 0.60, "market_prob_novig": 0.57, "edge": 0.03, "push_prob": 0.0, "ev": 0.03, "result": "LOSS", "y_win": 0, "profit": -1.0},
        {"season": 2026, "week": 2, "game_id": "g2", "marketFamily": "TOTAL", "side": "under", "line": 44.0, "price": -105, "model_prob_calibrated": 0.53, "market_prob_novig": 0.50, "edge": 0.03, "push_prob": 0.02, "ev": 0.02, "result": "WIN", "y_win": 1, "profit": 0.9524},
    ]
    return pd.DataFrame(rows)



def test_candidate_normalization_deterministic() -> None:
    cands = cm._market_rank_frame(_synthetic_candidates())
    profiles = cm._historical_reliability(cands)
    reliab = cm._build_reliability_objects(profiles)

    first = cm._method_scored(cands, reliab)["C_ZSCORE"]["score"].tolist()
    second = cm._method_scored(cands, reliab)["C_ZSCORE"]["score"].tolist()
    assert first == second



def test_percentile_boundaries_and_sparse_market_stability() -> None:
    cands = cm._market_rank_frame(_synthetic_candidates().head(3))
    profiles = cm._historical_reliability(cands)
    reliab = cm._build_reliability_objects(profiles)

    scored = cm._method_scored(cands, reliab)["D_PERCENTILE"]
    assert scored["score"].between(0.0, 1.0).all()



def test_reliability_weights_bounded() -> None:
    profiles = {
        "SPREAD": {"derivedReliabilityWeight": 9.9, "uncertainty": 0.0},
        "MONEYLINE": {"derivedReliabilityWeight": -5.0, "uncertainty": 5.0},
        "TOTAL": {"derivedReliabilityWeight": 0.5, "uncertainty": 0.5},
    }
    reliab = cm._build_reliability_objects(profiles)
    assert 0.05 <= reliab["SPREAD"].weight <= 1.0
    assert 0.05 <= reliab["MONEYLINE"].weight <= 1.0
    assert 0.01 <= reliab["SPREAD"].uncertainty <= 2.0
    assert 0.01 <= reliab["MONEYLINE"].uncertainty <= 2.0



def test_shadow_global_score_keeps_correlation_metadata() -> None:
    rows = [
        {
            "candidateId": "c1",
            "eventId": "evt-1",
            "marketFamily": "MONEYLINE",
            "side": "away",
            "calibratedEdge": 0.04,
            "ev": 0.06,
            "qualificationStatus": "QUALIFIED",
            "correlationMetadata": {"eventExposure": "evt-1", "marketFamily": "MONEYLINE"},
        },
        {
            "candidateId": "c2",
            "eventId": "evt-1",
            "marketFamily": "TOTAL",
            "side": "over",
            "calibratedEdge": 0.03,
            "ev": 0.04,
            "qualificationStatus": "QUALIFIED",
            "correlationMetadata": {"eventExposure": "evt-1", "marketFamily": "TOTAL"},
        },
    ]

    out = attach_shadow_global_scores(rows)
    assert all("globalResearchScore" in r for r in out)
    assert all("globalResearchRank" in r for r in out)
    assert out[0]["correlationMetadata"]["eventExposure"] == "evt-1"



def test_moneyline_no_point_and_total_push_semantics() -> None:
    cands = _synthetic_candidates()
    ml = cands[cands["marketFamily"] == "MONEYLINE"]
    total_push = cands[(cands["marketFamily"] == "TOTAL") & (cands["result"] == "PUSH")]

    assert ml["line"].isna().all()
    assert not total_push.empty
    assert (total_push["profit"] == 0.0).all()



def test_shadow_scores_cannot_bypass_production_firewall(tmp_path, monkeypatch) -> None:
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    preview = {
        "publishedAtUTC": "2026-09-13T16:00:00+00:00",
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
                    "eventId": "evt-ml",
                    "commenceTime": "2026-09-13T17:00:00+00:00",
                    "awayTeam": "NO",
                    "homeTeam": "ATL",
                    "market": "moneyline",
                    "selection": "NO",
                    "side": "away",
                    "point": None,
                    "price": 130,
                    "sportsbook": "DraftKings",
                    "globalResearchScore": 9.99,
                    "globalResearchRank": 1,
                    "normalizationMethod": "METHOD_E_REL_EV",
                },
            }
        ],
    }

    with pytest.raises(ValueError, match="rejects non-production"):
        dl.publish_official_sia3_from_preview(preview)



def test_cross_market_comparable_stays_false(monkeypatch, tmp_path) -> None:
    import app.routes.opportunities as route
    from app.services.games import service as games_service

    ranked_board = tmp_path / "ranked.csv"
    pd.DataFrame(
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
        ]
    ).to_csv(ranked_board, index=False)

    projections = tmp_path / "proj.csv"
    pd.DataFrame(
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
        ]
    ).to_csv(projections, index=False)

    monkeypatch.setattr(route, "RANKED_BET_BOARD", ranked_board)
    monkeypatch.setattr(route, "GAME_PROJECTIONS", projections)
    monkeypatch.setattr(route.market_data_service, "metadata", lambda: {"provider": "test", "lastUpdated": "2026", "dataStatus": "FILE"})
    monkeypatch.setattr(route.market_data_service, "all_event_snapshots", lambda: {"evt-1": {"provider": "test", "lastUpdated": "2026", "dataStatus": "FILE", "booksTracked": 1}})
    monkeypatch.setattr(route.market_data_service, "load_normalized_market_rows", lambda: [])
    monkeypatch.setattr(
        games_service,
        "list_games",
        lambda week=None: {
            "availableWeeks": [1],
            "games": [{"eventId": "evt-1", "season": 2026}],
        },
    )

    payload = route.get_opportunities(limit=10, best_lines_only=True, include_experimental=True, week=1)
    assert payload["opportunities"]
    assert all(o.get("crossMarketComparable") is False for o in payload["opportunities"])
