from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Optional

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.services import move_the_line
from app.routes import move_the_line as move_the_line_route


client = TestClient(app)


@dataclass
class FakeProbs:
    win: float
    push: float
    loss: float
    status: str = "AVAILABLE"
    reason: Optional[str] = None


def _base_context() -> dict:
    return {
        "eventId": "evt-1",
        "sourceMode": "LIVE",
        "sourceSnapshotId": "snap-live",
        "selection": "NYG +3",
        "market": "spread",
        "side": "home",
        "point": 3.0,
        "price": -115.0,
        "recommendation": "STRONG BET",
        "qualificationStatus": "QUALIFIED",
        "currentWinProbability": 0.669,
        "currentPushProbability": 0.025,
        "currentLossProbability": 0.306,
        "currentEV": 0.478,
        "impliedProbability": 53.5,
        "calibratedEdge": 0.134,
        "edge": 13.4,
        "fairLine": -1.5,
        "truePlayableTo": -5.0,
        "siScore": 86.0,
        "confidence": 84.0,
        "dataCompleteness": 97.0,
        "marketIntelligence": {"score": 7.0, "booksMoving": 4, "steamBooks": 1, "consensus": 0.0},
    }


def test_exact_current_line_playable(monkeypatch):
    monkeypatch.setattr(move_the_line, "_build_base_context", lambda event_id, snapshot_id: _base_context())
    monkeypatch.setattr(move_the_line, "_load_model_margin_home", lambda event_id: 1.5)
    monkeypatch.setattr(move_the_line, "spread_outcome_probabilities", lambda model_margin_home, side, spread_point: FakeProbs(win=0.669, push=0.025, loss=0.306))

    result = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=3.0, assumed_odds=-115)
    assert result["hypothetical"]["status"] == "PLAYABLE"
    assert result["hypothetical"]["insidePlayableRange"] is True
    assert result["hypothetical"]["hypotheticalSpread"] == 3.0


def test_half_point_better_line(monkeypatch):
    monkeypatch.setattr(move_the_line, "_build_base_context", lambda event_id, snapshot_id: _base_context())
    monkeypatch.setattr(move_the_line, "_load_model_margin_home", lambda event_id: 1.5)
    monkeypatch.setattr(move_the_line, "spread_outcome_probabilities", lambda model_margin_home, side, spread_point: FakeProbs(win=0.688, push=0.018, loss=0.294))

    result = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=3.5, assumed_odds=-115)
    assert result["hypothetical"]["status"] == "PLAYABLE"
    assert result["valueChange"]["probabilityChange"] > 0


def test_half_point_worse_line(monkeypatch):
    monkeypatch.setattr(move_the_line, "_build_base_context", lambda event_id, snapshot_id: _base_context())
    monkeypatch.setattr(move_the_line, "_load_model_margin_home", lambda event_id: 1.5)
    monkeypatch.setattr(move_the_line, "spread_outcome_probabilities", lambda model_margin_home, side, spread_point: FakeProbs(win=0.641, push=0.022, loss=0.337))

    result = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=2.5, assumed_odds=-115)
    assert result["hypothetical"]["status"] == "PLAYABLE"
    assert result["valueChange"]["probabilityChange"] < 0


def test_exact_playable_to_boundary(monkeypatch):
    monkeypatch.setattr(move_the_line, "_build_base_context", lambda event_id, snapshot_id: _base_context())
    monkeypatch.setattr(move_the_line, "_load_model_margin_home", lambda event_id: 1.5)
    monkeypatch.setattr(move_the_line, "spread_outcome_probabilities", lambda model_margin_home, side, spread_point: FakeProbs(win=0.535, push=0.015, loss=0.45))

    result = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=-5.0, assumed_odds=-115)
    assert result["hypothetical"]["insidePlayableRange"] is True
    assert result["hypothetical"]["atPlayableBoundary"] is True
    assert result["hypothetical"]["decisionStatus"] == "PLAYABLE"
    assert result["hypothetical"]["boundaryStatus"] == "AT_BOUNDARY"
    assert result["hypothetical"]["status"] == "PLAYABLE"


def test_half_point_beyond_playable_to(monkeypatch):
    monkeypatch.setattr(move_the_line, "_build_base_context", lambda event_id, snapshot_id: _base_context())
    monkeypatch.setattr(move_the_line, "_load_model_margin_home", lambda event_id: 1.5)
    monkeypatch.setattr(move_the_line, "spread_outcome_probabilities", lambda model_margin_home, side, spread_point: FakeProbs(win=0.525, push=0.015, loss=0.46))

    result = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=-5.5, assumed_odds=-115)
    assert result["hypothetical"]["insidePlayableRange"] is False
    assert result["hypothetical"]["decisionStatus"] == "PASS"
    assert result["hypothetical"]["boundaryStatus"] == "OUTSIDE"
    assert result["hypothetical"]["status"] == "PASS"
    assert "Outside" in result["hypothetical"]["statusReason"]


def test_canonical_decision_state_not_contradicted(monkeypatch):
    context = _base_context()
    monkeypatch.setattr(move_the_line, "_build_base_context", lambda event_id, snapshot_id: context)
    monkeypatch.setattr(move_the_line, "_load_model_margin_home", lambda event_id: 1.5)
    monkeypatch.setattr(move_the_line, "spread_outcome_probabilities", lambda model_margin_home, side, spread_point: FakeProbs(win=0.535, push=0.015, loss=0.45))

    result = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=-5.0, assumed_odds=-115)
    assert result["hypothetical"]["decisionStatus"] == "PLAYABLE"
    assert result["hypothetical"]["boundaryStatus"] == "AT_BOUNDARY"
    assert result["hypothetical"]["recommendation"] in {"ELITE BET", "STRONG BET", "BET", "LEAN", "PASS"}


def test_favorite_semantics_worse_line(monkeypatch):
    context = _base_context()
    context["selection"] = "KC -2"
    context["point"] = -2.0
    context["truePlayableTo"] = -3.0

    monkeypatch.setattr(move_the_line, "_build_base_context", lambda event_id, snapshot_id: context)
    monkeypatch.setattr(move_the_line, "_load_model_margin_home", lambda event_id: 2.2)
    monkeypatch.setattr(move_the_line, "spread_outcome_probabilities", lambda model_margin_home, side, spread_point: FakeProbs(win=0.52, push=0.02, loss=0.46))

    inside = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=-2.5, assumed_odds=-110)
    outside = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=-3.5, assumed_odds=-110)

    assert inside["hypothetical"]["status"] == "PLAYABLE"
    assert outside["hypothetical"]["status"] == "PASS"


def test_underdog_semantics_worse_line(monkeypatch):
    context = _base_context()
    context["selection"] = "NO +7"
    context["point"] = 7.0
    context["truePlayableTo"] = -5.0

    monkeypatch.setattr(move_the_line, "_build_base_context", lambda event_id, snapshot_id: context)
    monkeypatch.setattr(move_the_line, "_load_model_margin_home", lambda event_id: -1.5)
    monkeypatch.setattr(move_the_line, "spread_outcome_probabilities", lambda model_margin_home, side, spread_point: FakeProbs(win=0.6, push=0.03, loss=0.37))

    playable = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=2.0, assumed_odds=-110)
    passed = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=-5.5, assumed_odds=-110)

    assert playable["hypothetical"]["status"] == "PLAYABLE"
    assert passed["hypothetical"]["status"] == "PASS"


def test_crossing_zero_pk_format(monkeypatch):
    monkeypatch.setattr(move_the_line, "_build_base_context", lambda event_id, snapshot_id: _base_context())
    monkeypatch.setattr(move_the_line, "_load_model_margin_home", lambda event_id: 1.5)
    monkeypatch.setattr(move_the_line, "spread_outcome_probabilities", lambda model_margin_home, side, spread_point: FakeProbs(win=0.58, push=0.025, loss=0.395))

    pk = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=0.0, assumed_odds=-115)
    neg_half = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=-0.5, assumed_odds=-115)

    assert pk["hypothetical"]["selection"].endswith("PK")
    assert "+0" not in pk["hypothetical"]["selection"]
    assert "-0" not in pk["hypothetical"]["selection"]
    assert neg_half["hypothetical"]["selection"].endswith("-0.5")


def test_key_number_behavior_and_push_probability(monkeypatch):
    def fake_probs(model_margin_home, side, spread_point):
        if spread_point == 3.0:
            return FakeProbs(win=0.669, push=0.025, loss=0.306)
        if spread_point == 2.5:
            return FakeProbs(win=0.641, push=0.010, loss=0.349)
        if spread_point == 7.0:
            return FakeProbs(win=0.702, push=0.030, loss=0.268)
        if spread_point == 6.5:
            return FakeProbs(win=0.676, push=0.011, loss=0.313)
        return FakeProbs(win=0.60, push=0.02, loss=0.38)

    monkeypatch.setattr(move_the_line, "_build_base_context", lambda event_id, snapshot_id: _base_context())
    monkeypatch.setattr(move_the_line, "_load_model_margin_home", lambda event_id: 1.5)
    monkeypatch.setattr(move_the_line, "spread_outcome_probabilities", fake_probs)

    at_three = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=3.0, assumed_odds=-115)
    off_three = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=2.5, assumed_odds=-115)

    assert at_three["hypothetical"]["pushProbability"] > off_three["hypothetical"]["pushProbability"]

    context = _base_context()
    context["selection"] = "NO +7"
    context["point"] = 7.0
    monkeypatch.setattr(move_the_line, "_build_base_context", lambda event_id, snapshot_id: context)
    at_seven = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=7.0, assumed_odds=-115)
    off_seven = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=6.5, assumed_odds=-115)
    assert at_seven["hypothetical"]["pushProbability"] > off_seven["hypothetical"]["pushProbability"]


def test_assumed_odds_preserved(monkeypatch):
    monkeypatch.setattr(move_the_line, "_build_base_context", lambda event_id, snapshot_id: _base_context())
    monkeypatch.setattr(move_the_line, "_load_model_margin_home", lambda event_id: 1.5)
    monkeypatch.setattr(move_the_line, "spread_outcome_probabilities", lambda model_margin_home, side, spread_point: FakeProbs(win=0.66, push=0.02, loss=0.32))

    result = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=2.0, assumed_odds=-123)
    assert result["hypothetical"]["assumedOdds"] == -123.0
    assert result["current"]["assumedOdds"] == -123.0


def test_snapshot_id_preserved(monkeypatch):
    context = _base_context()
    context["sourceMode"] = "SNAPSHOT"
    context["sourceSnapshotId"] = "snap-123"

    monkeypatch.setattr(move_the_line, "_build_base_context", lambda event_id, snapshot_id: context)
    monkeypatch.setattr(move_the_line, "_load_model_margin_home", lambda event_id: 1.5)
    monkeypatch.setattr(move_the_line, "spread_outcome_probabilities", lambda model_margin_home, side, spread_point: FakeProbs(win=0.66, push=0.02, loss=0.32))

    result = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=2.0, assumed_odds=-115, snapshot_id="snap-123")
    assert result["contextMode"] == "SNAPSHOT"
    assert result["sourceSnapshotId"] == "snap-123"


def test_probability_engine_reused(monkeypatch):
    calls = {"count": 0, "spread": None}

    def fake_probs(model_margin_home, side, spread_point):
        calls["count"] += 1
        calls["spread"] = spread_point
        return FakeProbs(win=0.66, push=0.02, loss=0.32)

    monkeypatch.setattr(move_the_line, "_build_base_context", lambda event_id, snapshot_id: _base_context())
    monkeypatch.setattr(move_the_line, "_load_model_margin_home", lambda event_id: 1.5)
    monkeypatch.setattr(move_the_line, "spread_outcome_probabilities", fake_probs)

    move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=1.5, assumed_odds=-115)
    assert calls["count"] == 1
    assert calls["spread"] == 1.5


def test_no_mutation_of_base_context(monkeypatch):
    context = _base_context()
    original = dict(context)

    monkeypatch.setattr(move_the_line, "_build_base_context", lambda event_id, snapshot_id: context)
    monkeypatch.setattr(move_the_line, "_load_model_margin_home", lambda event_id: 1.5)
    monkeypatch.setattr(move_the_line, "spread_outcome_probabilities", lambda model_margin_home, side, spread_point: FakeProbs(win=0.66, push=0.02, loss=0.32))

    move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=1.5, assumed_odds=-115)
    assert context == original


def test_hypothetical_disclosure_present(monkeypatch):
    monkeypatch.setattr(move_the_line, "_build_base_context", lambda event_id, snapshot_id: _base_context())
    monkeypatch.setattr(move_the_line, "_load_model_margin_home", lambda event_id: 1.5)
    monkeypatch.setattr(move_the_line, "spread_outcome_probabilities", lambda model_margin_home, side, spread_point: FakeProbs(win=0.66, push=0.02, loss=0.32))

    result = move_the_line.evaluate_move_the_line(event_id="evt-1", hypothetical_spread=1.5, assumed_odds=-115)
    assert result["hypothetical"]["isHypothetical"] is True
    assert "holds the current price constant" in result["hypothetical"]["priceDisclosure"]


def test_api_route_works(monkeypatch):
    monkeypatch.setattr(
        move_the_line_route,
        "evaluate_move_the_line",
        lambda event_id, hypothetical_spread, assumed_odds, snapshot_id=None: {
            "eventId": event_id,
            "contextMode": "LIVE",
            "sourceSnapshotId": "snap-live",
            "current": {"selection": "NYG +3", "spread": 3.0, "recommendation": "STRONG BET"},
            "hypothetical": {
                "selection": "NYG +2.5",
                "hypotheticalSpread": 2.5,
                "assumedOdds": -115,
                "winProbability": 0.64,
                "pushProbability": 0.02,
                "lossProbability": 0.34,
                "pushAwareEV": 0.11,
                "marketImpliedProbability": 0.53,
                "edge": 0.11,
                "qualificationStatus": "QUALIFIED",
                "recommendation": "BET",
                "status": "PLAYABLE",
                "statusReason": "Still inside SIA's current playable range.",
                "decisionSummary": "YES",
                "priceDisclosure": "Move-the-Line holds the current price constant",
            },
            "valueChange": {},
        },
    )

    response = client.post(
        "/api/move-the-line",
        json={"eventId": "evt-1", "hypotheticalSpread": 2.5, "assumedOdds": -115},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["eventId"] == "evt-1"
    assert payload["hypothetical"]["status"] == "PLAYABLE"


def test_api_route_preserves_error_detail(monkeypatch):
    monkeypatch.setattr(
        move_the_line_route,
        "evaluate_move_the_line",
        lambda event_id, hypothetical_spread, assumed_odds, snapshot_id=None: (_ for _ in ()).throw(
            ValueError("Model spread context is unavailable for this game.")
        ),
    )

    response = client.post(
        "/api/move-the-line",
        json={"eventId": "evt-1", "hypotheticalSpread": -2.0, "assumedOdds": -105},
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"] == "Model spread context is unavailable for this game."


def test_no_det_boundary_completes_and_classifies_without_discontinuity():
    event_id = "c1d3fcec25aaeb06ebd2244d33d338e0"  # NO @ DET in canonical local data

    try:
        baseline = move_the_line.evaluate_move_the_line(
            event_id=event_id,
            hypothetical_spread=3.0,
            assumed_odds=-105,
        )
    except ValueError as exc:
        pytest.skip(f"NO @ DET baseline unavailable in this local dataset: {exc}")

    assert baseline["current"]["selection"].startswith("NO ")
    assert baseline["current"]["spread"] == 7.0
    assert baseline["current"]["truePlayableTo"] == -2.0

    cases = [
        (3.0, "PLAYABLE", "INSIDE", True),
        (-1.5, "PLAYABLE", "INSIDE", True),
        (-2.0, "PLAYABLE", "AT_BOUNDARY", True),
        (-2.5, "PASS", "OUTSIDE", False),
    ]

    for spread, expected_status, expected_boundary, expected_inside in cases:
        start = time.perf_counter()
        result = move_the_line.evaluate_move_the_line(
            event_id=event_id,
            hypothetical_spread=spread,
            assumed_odds=-105,
        )
        elapsed = time.perf_counter() - start

        # Guard against pathological runtime while allowing deterministic cold-cache cost.
        assert elapsed < 20.0

        hypothetical = result["hypothetical"]
        assert hypothetical["hypotheticalSpread"] == spread
        assert hypothetical["status"] == expected_status
        assert hypothetical["boundaryStatus"] == expected_boundary
        assert hypothetical["insidePlayableRange"] is expected_inside
        assert hypothetical["truePlayableTo"] == -2.0


def test_base_context_uses_game_payload_without_live_snapshot_lookup(monkeypatch):
    monkeypatch.setattr(
        move_the_line,
        "_live_snapshot_id",
        lambda event_id: (_ for _ in ()).throw(AssertionError("_live_snapshot_id should not be called")),
    )

    monkeypatch.setattr(
        move_the_line,
        "_get_game_best_opportunity_payload",
        lambda event_id, include_best_by_market=False: {
            "snapshotId": "snap-from-production-bundle",
            "opportunity": {
                "pick": "NO +7",
                "market": "spread",
                "side": "away",
                "point": 7.0,
                "price": -105.0,
                "recommendation": "STRONG BET",
                "qualificationStatus": "QUALIFIED",
                "currentWinProbability": 0.61,
                "currentPushProbability": 0.03,
                "currentLossProbability": 0.36,
                "currentEV": 0.09,
                "impliedProbability": 48.8,
                "calibratedEdge": 0.122,
                "edge": 12.2,
                "fairLine": -1.0,
                "truePlayableTo": -2.0,
                "sportsIntelligenceScore": {"score": 84.0},
                "confidence": 80.0,
                "dataCompleteness": 96.0,
                "marketIntelligence": {"score": 7.0, "booksMoving": 4, "steamBooks": 1, "consensus": 0.0},
            },
        },
    )

    base = move_the_line._build_base_context(event_id="evt-1", snapshot_id=None)
    assert base["sourceMode"] == "LIVE"
    assert base["sourceSnapshotId"] == "snap-from-production-bundle"
    assert base["selection"] == "NO +7"
    assert base["truePlayableTo"] == -2.0
