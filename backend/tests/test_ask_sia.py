from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from app.main import app
from app.services import ask_sia


client = TestClient(app)


def _base_live_context() -> dict:
    return {
        "eventId": "evt-1",
        "teams": {"awayTeam": "DAL", "homeTeam": "NYG"},
        "selection": "NYG +3",
        "market": "spread",
        "side": "home",
        "point": 3.0,
        "price": -115.0,
        "sportsbook": "Bovada",
        "consensusLine": 2.67,
        "rawProbability": 0.58,
        "calibratedProbability": 0.61,
        "pushProbability": 0.02,
        "lossProbability": 0.37,
        "impliedProbability": 55.0,
        "calibratedEdge": 0.06,
        "currentEV": 0.08,
        "fairLine": -128.0,
        "truePlayableTo": -5.0,
        "siScore": 81.8,
        "recommendation": "STRONG BET",
        "marketIntelligence": {
            "signal": "CONFIRMED",
            "booksMoving": 5,
            "booksTracked": 8,
            "steamBooks": 2,
        },
        "lineMovement": {
            "signal": "CONFIRMED",
            "booksMoving": 5,
            "booksTracked": 8,
        },
        "restTravel": {},
        "injuryContext": {"summary": "Neutral", "severity": "neutral"},
        "weather": {"dataStatus": "UNAVAILABLE"},
        "socialIntelligence": {"isLive": False, "dataStatus": "MOCK"},
        "qualificationReasons": ["Current model edge and confidence meet SIA qualification thresholds."],
        "snapshotTimestamp": "2026-09-13T15:00:00+00:00",
        "rank": 1,
        "snapshotId": "snap-live",
        "topSia3": [
            {
                "rank": 1,
                "pick": "NYG +3",
                "currentEV": 0.08,
                "calibratedEdge": 0.06,
                "sportsIntelligenceScore": {"score": 81.8},
            },
            {
                "rank": 2,
                "pick": "NO +7",
                "currentEV": 0.07,
                "calibratedEdge": 0.05,
                "sportsIntelligenceScore": {"score": 80.2},
            },
            {
                "rank": 3,
                "pick": "DEN +2.5",
                "currentEV": 0.05,
                "calibratedEdge": 0.04,
                "sportsIntelligenceScore": {"score": 73.3},
            },
        ],
    }


def test_why_sia_likes_pick():
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Why does SIA like NYG?",
        live_context=_base_live_context(),
    )
    assert "favors" in result["answer"].lower()
    assert result["intent"] == "WHY"


def test_biggest_risk_question():
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="What is the biggest risk?",
        live_context=_base_live_context(),
    )
    assert "risk" in result["answer"].lower()
    assert result["intent"] == "BIGGEST_RISK"


def test_playable_to_inside_threshold_underdog_direction():
    context = _base_live_context()
    context["selection"] = "NO +7"
    context["side"] = "away"
    context["truePlayableTo"] = -5.0

    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Would SIA still bet this at +2?",
        live_context=context,
    )
    assert result["intent"] == "PLAYABLE_CHECK"
    assert result["answer"].startswith("Yes")


def test_playable_to_exact_threshold_is_playable():
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Would SIA still bet this at -5?",
        live_context=_base_live_context(),
    )
    assert result["answer"].startswith("Yes")


def test_playable_to_outside_threshold_is_pass():
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Would SIA still bet this at -5.5?",
        live_context=_base_live_context(),
    )
    assert result["answer"].startswith("No")


def test_playable_to_favorite_direction():
    context = _base_live_context()
    context["selection"] = "KC -3"
    context["side"] = "home"
    context["point"] = -3.0
    context["truePlayableTo"] = -5.0

    inside = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Still playable at -4?",
        live_context=context,
    )
    outside = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Still playable at -5.5?",
        live_context=context,
    )

    assert inside["answer"].startswith("Yes")
    assert outside["answer"].startswith("No")


def test_best_sportsbook_deterministic_answer():
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="What sportsbook has the best price?",
        live_context=_base_live_context(),
    )
    assert result["intent"] == "BEST_SPORTSBOOK"
    assert "Bovada" in result["answer"]


def test_sia3_comparison_uses_canonical_rank():
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="How strong is this compared with the other SIA 3 picks?",
        live_context=_base_live_context(),
    )
    assert result["intent"] == "SIA3_COMPARE"
    assert "ranks" in result["answer"].lower()


def test_missing_weather_disclosure():
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Is weather important?",
        live_context=_base_live_context(),
    )
    assert "Weather data is not currently available for this matchup." in result["missingData"]


def test_missing_injuries_disclosure():
    context = _base_live_context()
    context["injuryContext"] = {"summary": "", "severity": "neutral"}

    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Are injuries affecting this pick?",
        live_context=context,
    )
    assert "SIA currently has no verified injury edge for this game." in result["missingData"]


def test_mock_social_intelligence_disclosure():
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="What social signals matter here?",
        live_context=_base_live_context(),
    )
    assert "Live social intelligence is not connected yet." in result["missingData"]


def test_snapshot_specific_answer_note(monkeypatch):
    snapshot_context = {
        "eventId": "evt-1",
        "selection": "NYG +3",
        "price": -110.0,
        "sportsbook": "DraftKings",
        "market": "spread",
        "side": "home",
    }

    monkeypatch.setattr(ask_sia, "_build_snapshot_context", lambda sid: deepcopy(snapshot_context))

    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Why is this in The SIA 3?",
        live_context=_base_live_context(),
        snapshot_id="snap-123",
    )
    assert result["contextMode"] == "SNAPSHOT_AND_LIVE"
    assert result["snapshotNote"] is not None
    assert "AT PUBLICATION" in result["snapshotNote"]
    assert "CURRENT LIVE MARKET" in result["snapshotNote"]


def test_live_current_answer_mode(monkeypatch):
    monkeypatch.setattr(ask_sia, "_build_live_context", lambda event_id: _base_live_context())

    response = ask_sia.get_ask_sia_response(event_id="evt-1", question="Why does SIA like this?")
    assert response["contextMode"] == "LIVE"


def test_unknown_question_safe_fallback_no_fabrication():
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Will this definitely win?",
        live_context=_base_live_context(),
    )
    assert result["answer"] == "I don't have enough verified SIA data to answer that yet."


def test_endpoint_accepts_snapshot_and_returns_context(monkeypatch):
    monkeypatch.setattr(ask_sia, "_build_live_context", lambda event_id: _base_live_context())
    monkeypatch.setattr(ask_sia, "_build_snapshot_context", lambda sid: {"selection": "NYG +3", "price": -110.0, "sportsbook": "DraftKings"})

    response = client.post(
        "/api/ask-sia",
        json={"eventId": "evt-1", "question": "Why does SIA like NYG?", "snapshotId": "snap-123"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["eventId"] == "evt-1"
    assert payload["context"]["selection"] == "NYG +3"
