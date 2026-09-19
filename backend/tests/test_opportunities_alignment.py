from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest


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
                "away_power": 0.0,
                "home_power": 0.0,
                "model_margin_home": -1.0,
                "market_margin_home": -2.5,
                "market_home_spread": -2.5,
                "spread_edge_points": 0.0,
                "home_cover_prob_est": 0.5,
                "home_cover_fair_odds": -100.0,
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
        opportunities_route.market_data_service,
        "records_for_event",
        lambda event_id: [
            {
                "eventId": str(r["api_event_id"]),
                "market": str(r.get("market") or "spread"),
                "side": str(r.get("side") or "away"),
                "point": float(r.get("point") or 0.0),
                "americanOdds": float(r.get("price") or -110),
                "sportsbook": str(r.get("sportsbook") or "DraftKings"),
                "lastUpdated": datetime.now(timezone.utc).isoformat(),
            }
            for r in rows
            if str(r.get("api_event_id")) == str(event_id)
        ],
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
    assert payload["modelVersion"]
    assert payload["probabilityEngineVersion"]
    assert payload["calibrationVersion"]
    assert payload["rankingVersion"]
    assert payload["qualificationPolicyVersion"]

    opps = payload["opportunities"]
    assert opps[0]["eventId"] == "evt-2"
    assert opps[0]["rank"] == 1
    assert opps[0]["rawRank"] == 2
    assert opps[0]["modelVersion"]
    assert opps[0]["probabilityEngineVersion"]
    assert opps[0]["calibrationVersion"]
    assert opps[0]["rankingVersion"]
    assert opps[0]["qualificationPolicyVersion"]
    assert opps[0]["modelTimestamp"]
    assert opps[1]["eventId"] == "evt-1"

    # Advanced probability and boundary fields remain exposed for deep analytics.
    required_fields = [
        "rawModelProbability",
        "calibratedProbability",
        "currentWinProbability",
        "currentPushProbability",
        "currentLossProbability",
        "currentEV",
        "edge",
        "calibratedEdge",
        "fairLine",
        "truePlayableTo",
        "recommendedPlayableTo",
    ]
    for field in required_fields:
        assert field in opps[0]


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

    assert opp["qualificationStatus"] == "QUALIFIED"
    assert opp["qualificationReasons"]
    assert opp["currentQualification"]["actionable"] is True

    # push-aware fair-price EV is canonical input now
    assert opp["currentEV"] == 0.123
    assert opp["evPerDollar"] == 0.123

    # edge now tracks current calibrated win probability vs implied probability
    assert opp["edge"] == 9.6
    assert round(float(opp["calibratedEdge"]), 6) == 0.09619

    # SI expected value component should reflect 0.123 EV, not raw board EV.
    si = opp["sportsIntelligenceScore"]
    assert abs(float(si["components"]["expectedValue"]) - 24.6) < 0.2


def test_model_timestamp_for_ranked_rows_uses_artifact_time_and_not_api_now(tmp_path, monkeypatch):
    rows = [
        {
            "api_event_id": "evt-ts-1",
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

    artifact_epoch = 1756720800
    os.utime(opportunities_route.RANKED_BET_BOARD, (artifact_epoch, artifact_epoch))
    expected_model_timestamp = datetime.fromtimestamp(artifact_epoch, tz=timezone.utc).isoformat()

    class _FakeDateTime:
        _idx = 0
        _values = [
            "2026-09-16T10:00:00+00:00",
            "2026-09-16T10:05:00+00:00",
        ]

        @classmethod
        def now(cls, tz=None):
            value = cls._values[min(cls._idx, len(cls._values) - 1)]
            cls._idx += 1
            return datetime.fromisoformat(value)

        @classmethod
        def fromisoformat(cls, value: str):
            return datetime.fromisoformat(value)

        @classmethod
        def fromtimestamp(cls, ts: float, tz=None):
            return datetime.fromtimestamp(ts, tz=tz)

    monkeypatch.setattr(opportunities_route, "datetime", _FakeDateTime)

    payload1 = opportunities_route.get_opportunities(limit=10, best_lines_only=True, week=1)
    payload2 = opportunities_route.get_opportunities(limit=10, best_lines_only=True, week=1)

    opp1 = payload1["opportunities"][0]
    opp2 = payload2["opportunities"][0]

    assert opp1["rawModelProbability"] == opp2["rawModelProbability"]
    assert opp1["calibratedProbability"] == opp2["calibratedProbability"]
    assert opp1["modelTimestamp"] == expected_model_timestamp
    assert opp2["modelTimestamp"] == expected_model_timestamp
    assert opp1["modelTimestamp"] != opp1["marketLastUpdated"]


def test_model_timestamp_changes_when_new_ranked_artifact_is_generated(tmp_path, monkeypatch):
    rows = [
        {
            "api_event_id": "evt-ts-regen",
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

    first_epoch = 1756720800
    second_epoch = 1756724400
    os.utime(opportunities_route.RANKED_BET_BOARD, (first_epoch, first_epoch))

    first = opportunities_route.get_opportunities(limit=10, best_lines_only=True, week=1)
    first_opp = first["opportunities"][0]

    regenerated_rows = [dict(rows[0])]
    regenerated_rows[0]["model_prob"] = 0.61
    _write_ranked_board(opportunities_route.RANKED_BET_BOARD, regenerated_rows)
    os.utime(opportunities_route.RANKED_BET_BOARD, (second_epoch, second_epoch))

    second = opportunities_route.get_opportunities(limit=10, best_lines_only=True, week=1)
    second_opp = second["opportunities"][0]

    assert first_opp["rawModelProbability"] != second_opp["rawModelProbability"]
    assert first_opp["modelTimestamp"] == datetime.fromtimestamp(first_epoch, tz=timezone.utc).isoformat()
    assert second_opp["modelTimestamp"] == datetime.fromtimestamp(second_epoch, tz=timezone.utc).isoformat()


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


def test_opportunity_exposes_original_candidate_and_current_execution_drift(tmp_path, monkeypatch):
    rows = [
        {
            "api_event_id": "evt-drift-1",
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
    monkeypatch.setattr(
        opportunities_route.market_data_service,
        "records_for_event",
        lambda event_id: [
            {
                "eventId": "evt-drift-1",
                "market": "spread",
                "side": "away",
                "point": 2.5,
                "americanOdds": -112,
                "sportsbook": "DraftKings",
                "lastUpdated": datetime.now(timezone.utc).isoformat(),
            }
        ]
        if str(event_id) == "evt-drift-1"
        else [],
    )

    payload = opportunities_route.get_opportunities(limit=10, best_lines_only=True, week=1)
    opp = payload["opportunities"][0]

    assert opp["point"] == 2.5
    assert opp["price"] == -112.0
    assert opp["currentExecution"]["status"] == "AVAILABLE"
    assert opp["currentExecution"]["point"] == 2.5
    assert opp["currentExecution"]["price"] == -112.0
    assert opp["originalCandidate"]["point"] == 3.0
    assert opp["originalCandidate"]["price"] == -110.0
    assert opp["executionDrift"]["originalCandidatePoint"] == 3.0
    assert opp["executionDrift"]["currentExecutionPoint"] == 2.5
    assert opp["executionDrift"]["lineDriftPoints"] == -0.5


def test_ranked_candidate_without_fresh_approved_quote_fails_closed_but_preserves_original_candidate(tmp_path, monkeypatch):
    rows = [
        {
            "api_event_id": "evt-failclosed-1",
            "commence_time": "2026-09-13T17:00:00+00:00",
            "away_team": "NYG",
            "home_team": "DAL",
            "market": "spread",
            "side": "away",
            "point": 9.5,
            "sportsbook": "BetUS",
            "price": -110,
            "model_prob": 0.6,
            "implied_prob_raw": 0.52,
            "fair_odds": -120,
            "edge_pp": 0.08,
            "ev_per_dollar": 0.1,
            "kelly_full": 0.04,
            "kelly_20pct": 0.008,
            "recommendation": "BET",
            "confidence_score": 70,
            "data_completeness": 0.95,
            "market_confidence": 0.8,
            "model_confidence": 0.7,
            "rank": 1,
        }
    ]

    opportunities_route = _patch_dependencies(monkeypatch, tmp_path, rows)
    monkeypatch.setattr(
        opportunities_route.market_data_service,
        "records_for_event",
        lambda event_id: [
            {
                "eventId": "evt-failclosed-1",
                "market": "spread",
                "side": "away",
                "point": 7.0,
                "americanOdds": -108,
                "sportsbook": "Fanatics Sportsbook",
                "lastUpdated": "2020-01-01T00:00:00+00:00",
            },
            {
                "eventId": "evt-failclosed-1",
                "market": "spread",
                "side": "away",
                "point": 10.0,
                "americanOdds": -105,
                "sportsbook": "BetOnline",
                "lastUpdated": datetime.now(timezone.utc).isoformat(),
            },
        ]
        if str(event_id) == "evt-failclosed-1"
        else [],
    )

    prod_payload = opportunities_route.get_opportunities(limit=10, best_lines_only=True, week=1)
    assert prod_payload["count"] == 1
    assert prod_payload["productionCount"] == 1
    prod_opp = prod_payload["opportunities"][0]
    assert prod_opp["currentExecution"]["status"] == "STALE_APPROVED_MARKET"
    assert prod_opp["qualificationStatus"] == "QUALIFIED"
    assert prod_opp["currentQualification"]["actionable"] is False

    audit_payload = opportunities_route.get_opportunities(limit=10, best_lines_only=True, include_experimental=True, week=1)
    assert audit_payload["count"] == 1
    assert audit_payload["productionCount"] == 1
    assert audit_payload["experimentalCount"] == 0
    opp = audit_payload["opportunities"][0]
    assert opp["currentExecution"]["status"] == "STALE_APPROVED_MARKET"
    assert opp["qualificationStatus"] == "QUALIFIED"
    assert opp["book"] is None
    assert opp["point"] is None
    assert opp["price"] is None
    assert opp["currentQualification"]["actionable"] is False
    assert opp["originalCandidate"]["sportsbook"] == "BetUS"
    assert opp["originalCandidate"]["point"] == 9.5
    assert opp["originalCandidate"]["price"] == -110.0


def test_deterministic_week2_discrepancy_fixture_prefers_fresh_approved_quotes_and_ignores_unapproved(tmp_path, monkeypatch):
    rows = [
        {
            "api_event_id": "evt-nyg",
            "commence_time": "2026-09-20T17:00:00+00:00",
            "away_team": "NYG",
            "home_team": "DAL",
            "market": "spread",
            "side": "away",
            "point": 9.5,
            "sportsbook": "BetUS",
            "price": -110,
            "model_prob": 0.59,
            "implied_prob_raw": 0.52,
            "fair_odds": -118,
            "edge_pp": 0.07,
            "ev_per_dollar": 0.08,
            "kelly_full": 0.03,
            "kelly_20pct": 0.006,
            "recommendation": "BET",
            "confidence_score": 70,
            "data_completeness": 0.95,
            "market_confidence": 0.8,
            "model_confidence": 0.7,
            "rank": 1,
        },
        {
            "api_event_id": "evt-mia",
            "commence_time": "2026-09-20T20:00:00+00:00",
            "away_team": "MIA",
            "home_team": "BUF",
            "market": "spread",
            "side": "away",
            "point": 10.5,
            "sportsbook": "DraftKings",
            "price": -110,
            "model_prob": 0.6,
            "implied_prob_raw": 0.52,
            "fair_odds": -119,
            "edge_pp": 0.08,
            "ev_per_dollar": 0.09,
            "kelly_full": 0.04,
            "kelly_20pct": 0.008,
            "recommendation": "BET",
            "confidence_score": 72,
            "data_completeness": 0.95,
            "market_confidence": 0.8,
            "model_confidence": 0.7,
            "rank": 2,
        },
        {
            "api_event_id": "evt-no",
            "commence_time": "2026-09-20T23:00:00+00:00",
            "away_team": "NO",
            "home_team": "ATL",
            "market": "spread",
            "side": "away",
            "point": 7.5,
            "sportsbook": "DraftKings",
            "price": -110,
            "model_prob": 0.58,
            "implied_prob_raw": 0.52,
            "fair_odds": -117,
            "edge_pp": 0.06,
            "ev_per_dollar": 0.07,
            "kelly_full": 0.03,
            "kelly_20pct": 0.006,
            "recommendation": "BET",
            "confidence_score": 69,
            "data_completeness": 0.95,
            "market_confidence": 0.8,
            "model_confidence": 0.7,
            "rank": 3,
        },
    ]

    opportunities_route = _patch_dependencies(monkeypatch, tmp_path, rows)

    def _records_for_event(event_id: str):
        now = datetime.now(timezone.utc).isoformat()
        if str(event_id) == "evt-nyg":
            return [
                {"eventId": "evt-nyg", "market": "spread", "side": "away", "point": 7.0, "americanOdds": -110, "sportsbook": "Fanatics Sportsbook", "lastUpdated": now},
                {"eventId": "evt-nyg", "market": "spread", "side": "away", "point": 10.0, "americanOdds": -105, "sportsbook": "BetUS", "lastUpdated": now},
                {"eventId": "evt-nyg", "market": "spread", "side": "away", "point": 10.5, "americanOdds": -102, "sportsbook": "Bovada", "lastUpdated": now},
            ]
        if str(event_id) == "evt-mia":
            return [
                {"eventId": "evt-mia", "market": "spread", "side": "away", "point": 13.0, "americanOdds": -111, "sportsbook": "Fanatics Sportsbook", "lastUpdated": now},
                {"eventId": "evt-mia", "market": "spread", "side": "away", "point": 14.0, "americanOdds": -105, "sportsbook": "BetOnline", "lastUpdated": now},
            ]
        if str(event_id) == "evt-no":
            return [
                {"eventId": "evt-no", "market": "spread", "side": "away", "point": 8.5, "americanOdds": -109, "sportsbook": "Fanatics Sportsbook", "lastUpdated": now},
                {"eventId": "evt-no", "market": "spread", "side": "away", "point": 9.5, "americanOdds": -103, "sportsbook": "LowVig.ag", "lastUpdated": now},
            ]
        return []

    monkeypatch.setattr(opportunities_route.market_data_service, "records_for_event", _records_for_event)

    payload = opportunities_route.get_opportunities(limit=10, best_lines_only=True, include_experimental=True, week=1)
    assert payload["count"] == 3
    assert payload["productionCount"] == 3

    by_event = {o["eventId"]: o for o in payload["opportunities"]}

    nyg = by_event["evt-nyg"]
    assert nyg["originalCandidate"]["point"] == 9.5
    assert nyg["originalCandidate"]["sportsbook"] == "BetUS"
    assert nyg["point"] == 7.0
    assert nyg["book"] == "Fanatics Sportsbook"
    assert nyg["currentExecution"]["sportsbookCanonicalKey"] == "fanatics"
    assert nyg["executionDrift"]["lineDriftPoints"] == -2.5
    assert nyg["currentQualification"]["actionable"] is True

    mia = by_event["evt-mia"]
    assert mia["originalCandidate"]["point"] == 10.5
    assert mia["originalCandidate"]["sportsbook"] == "DraftKings"
    assert mia["point"] == 13.0
    assert mia["book"] == "Fanatics Sportsbook"
    assert mia["currentExecution"]["sportsbookCanonicalKey"] == "fanatics"
    assert mia["executionDrift"]["lineDriftPoints"] == 2.5
    assert mia["currentQualification"]["actionable"] is True

    no = by_event["evt-no"]
    assert no["originalCandidate"]["point"] == 7.5
    assert no["originalCandidate"]["sportsbook"] == "DraftKings"
    assert no["point"] == 8.5
    assert no["book"] == "Fanatics Sportsbook"
    assert no["currentExecution"]["sportsbookCanonicalKey"] == "fanatics"
    assert no["executionDrift"]["lineDriftPoints"] == 1.0
    assert no["currentQualification"]["actionable"] is True


def test_week2_corrected_margin_reference_parity_complete():
    import app.routes.opportunities as opportunities_route

    expected = {
        "DET@BUF": 6.334767,
        "CAR@ATL": 4.975323,
        "CIN@HOU": 1.855269,
        "CLE@TB": 4.313074,
        "GB@NYJ": -6.461671,
        "MIN@CHI": -1.071322,
        "NO@BAL": 0.814307,
        "PHI@TEN": -5.147469,
        "PIT@NE": 6.787993,
        "JAX@DEN": -4.768764,
        "LV@LAC": 3.242472,
        "MIA@SF": 4.579205,
        "SEA@ARI": -7.157223,
        "WAS@DAL": 0.712522,
        "IND@KC": 3.819167,
        "NYG@LAR": 0.885611,
    }

    actual = opportunities_route.PHASE2E19_WEEK2_MARGIN_REFERENCE_2026
    assert set(actual.keys()) == set(expected.keys())
    max_abs_delta = max(abs(float(actual[k]) - float(expected[k])) for k in expected)
    assert max_abs_delta <= 1e-6


def test_load_game_projection_lookup_applies_week2_corrected_margin(tmp_path, monkeypatch):
    import app.routes.opportunities as opportunities_route

    projections = tmp_path / "current_game_projections.csv"
    pd.DataFrame(
        [
            {
                "api_event_id": "evt-mia",
                "commence_time": "2026-09-20T20:25:00+00:00",
                "away_team": "MIA",
                "home_team": "SF",
                "away_power": 0.0,
                "home_power": 0.0,
                "model_margin_home": 2.19,
                "market_margin_home": -10.5,
                "market_home_spread": -10.5,
                "spread_edge_points": 0.0,
                "home_cover_prob_est": 0.5,
                "home_cover_fair_odds": -100.0,
                "market_total": 46.5,
                "model_total_baseline": 46.5,
            },
            {
                "api_event_id": "evt-car",
                "commence_time": "2026-09-20T17:00:00+00:00",
                "away_team": "CAR",
                "home_team": "ATL",
                "away_power": 0.0,
                "home_power": 0.0,
                "model_margin_home": 1.0,
                "market_margin_home": -2.5,
                "market_home_spread": -2.5,
                "spread_edge_points": 0.0,
                "home_cover_prob_est": 0.5,
                "home_cover_fair_odds": -100.0,
                "market_total": 44.0,
                "model_total_baseline": 44.0,
            },
        ]
    ).to_csv(projections, index=False)

    monkeypatch.setattr(opportunities_route, "GAME_PROJECTIONS", projections)

    week2 = opportunities_route.load_game_projection_lookup(
        resolved_week=2,
        week_event_ids={"evt-mia", "evt-car"},
    )
    assert float(week2["evt-mia"]["model_margin_home"]) == pytest.approx(4.579205, abs=1e-6)
    assert str(week2["evt-mia"]["model_margin_source"]) == "PHASE2E19_WEEK2_REFERENCE"
    assert float(week2["evt-car"]["model_margin_home"]) == pytest.approx(4.975323, abs=1e-6)

    week3 = opportunities_route.load_game_projection_lookup(
        resolved_week=3,
        week_event_ids={"evt-mia"},
    )
    assert float(week3["evt-mia"]["model_margin_home"]) == pytest.approx(2.19, abs=1e-9)
    assert str(week3["evt-mia"]["model_margin_source"]) == "CURRENT_GAME_PROJECTIONS"


def test_game_projection_market_uses_current_execution_source(tmp_path, monkeypatch):
    rows = [
        {
            "api_event_id": "evt-market-source",
            "commence_time": "2026-09-20T17:00:00+00:00",
            "away_team": "NO",
            "home_team": "ATL",
            "market": "spread",
            "side": "away",
            "point": 3.0,
            "sportsbook": "DraftKings",
            "price": -110,
            "model_prob": 0.61,
            "implied_prob_raw": 0.53,
            "fair_odds": -120,
            "edge_pp": 0.08,
            "ev_per_dollar": 0.09,
            "kelly_full": 0.05,
            "kelly_20pct": 0.01,
            "recommendation": "BET",
            "confidence_score": 71,
            "data_completeness": 0.95,
            "market_confidence": 0.8,
            "model_confidence": 0.7,
            "rank": 1,
        }
    ]

    opportunities_route = _patch_dependencies(monkeypatch, tmp_path, rows)
    monkeypatch.setattr(
        opportunities_route.market_data_service,
        "records_for_event",
        lambda event_id: [
            {
                "eventId": "evt-market-source",
                "market": "spread",
                "side": "away",
                "point": 4.5,
                "americanOdds": -107,
                "sportsbook": "FanDuel",
                "lastUpdated": datetime.now(timezone.utc).isoformat(),
            }
        ]
        if str(event_id) == "evt-market-source"
        else [],
    )

    projection = opportunities_route.get_game_projection("evt-market-source")
    opp_payload = opportunities_route.get_game_best_opportunity("evt-market-source")
    opp = opp_payload["opportunity"]

    assert projection["market"]["provenance"]["source"] == "CURRENT_APPROVED_MARKET_EXECUTION"
    assert projection["market"]["currentExecution"]["sportsbook"] == opp["currentExecution"]["sportsbook"]
    assert projection["market"]["currentExecution"]["price"] == opp["currentExecution"]["price"]
    assert projection["market"]["currentExecution"]["spread"] == opp["currentExecution"]["point"]
    assert projection["market"]["provenance"]["executionStatus"] == opp["currentExecution"]["status"]


def test_home_decision_board_top3_while_opportunities_return_full_qualified_set(tmp_path, monkeypatch):
    rows = []
    for idx in range(1, 6):
        rows.append(
            {
                "api_event_id": f"evt-top3-{idx}",
                "commence_time": "2026-09-20T17:00:00+00:00",
                "away_team": "NO",
                "home_team": "ATL",
                "market": "spread",
                "side": "away",
                "point": 3.0 + idx,
                "sportsbook": "DraftKings",
                "price": -110,
                "model_prob": 0.60 + (idx * 0.005),
                "implied_prob_raw": 0.52,
                "fair_odds": -120,
                "edge_pp": 0.08,
                "ev_per_dollar": 0.09,
                "kelly_full": 0.04,
                "kelly_20pct": 0.008,
                "recommendation": "BET",
                "confidence_score": 70 + idx,
                "data_completeness": 0.95,
                "market_confidence": 0.8,
                "model_confidence": 0.7,
                "rank": idx,
            }
        )

    opportunities_route = _patch_dependencies(monkeypatch, tmp_path, rows)
    full = opportunities_route.get_opportunities(limit=100, best_lines_only=True, week=1)
    board = opportunities_route.get_decision_board(limit=3, week=1)

    assert full["count"] == 5
    assert full["productionCount"] == 5
    assert board["count"] == 3
