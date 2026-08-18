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
        "selection": "NO +7",
        "market": "spread",
        "side": "away",
        "point": 7.0,
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
        "marketIntelligence": {"signal": "CONFIRMED", "booksMoving": 5, "booksTracked": 8, "steamBooks": 2},
        "lineMovement": {
            "signal": "CONFIRMED",
            "booksMoving": 5,
            "booksTracked": 8,
        },
        "restTravel": {"rest": {"advantageHomeDays": 0.0}, "travel": {"awayMiles": 220.0, "awayTimezoneShiftHours": 0.0}},
        "injuryContext": {"summary": "Neutral", "severity": "neutral"},
        "weather": {"dataStatus": "UNAVAILABLE"},
        "socialIntelligence": {"isLive": False, "dataStatus": "MOCK"},
        "qualificationReasons": ["Current model edge and confidence meet SIA qualification thresholds."],
        "snapshotTimestamp": "2026-09-13T15:00:00+00:00",
        "rank": 2,
        "snapshotId": "snap-live",
        "topSia3": [
            {
                "rank": 1,
                "eventId": "evt-2",
                "pick": "NYG +3",
                "currentEV": 0.08,
                "calibratedEdge": 0.06,
                "calibratedProbability": 0.61,
                "impliedProbability": 55.0,
                "recommendation": "STRONG BET",
                "qualificationStatus": "QUALIFIED",
                "sportsIntelligenceScore": {"score": 81.8},
            },
            {
                "rank": 2,
                "eventId": "evt-1",
                "pick": "NO +7",
                "currentEV": 0.07,
                "calibratedEdge": 0.05,
                "calibratedProbability": 0.60,
                "impliedProbability": 54.0,
                "recommendation": "STRONG BET",
                "qualificationStatus": "QUALIFIED",
                "sportsIntelligenceScore": {"score": 80.2},
            },
            {
                "rank": 3,
                "eventId": "evt-3",
                "pick": "DEN +2.5",
                "currentEV": 0.05,
                "calibratedEdge": 0.04,
                "calibratedProbability": 0.57,
                "impliedProbability": 53.0,
                "recommendation": "BET",
                "qualificationStatus": "QUALIFIED",
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
    context = _base_live_context()
    context["marketIntelligence"] = {"signal": "RESISTANCE", "booksMoving": 1, "booksTracked": 9}
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="What is the biggest risk?",
        live_context=context,
    )
    assert "market resistance" in result["answer"].lower()
    assert result["intent"] == "BIGGEST_RISK"
    assert "Weather data is not currently available." in result["missingData"]
    assert "Live social intelligence is not connected yet." in result["missingData"]


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
    assert "Current recommendation: NO +7" in result["why"]
    assert "Playable-To" in result["why"][1]
    assert result["missingData"] == []


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


def test_sia3_comparison_rank_2_context_and_full_list():
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Compare SIA 3 Picks",
        live_context=_base_live_context(),
    )
    assert result["intent"] == "SIA3_COMPARE"
    assert "NO +7 currently ranks #2 of 3" in result["answer"]
    assert "#1 NYG +3" in result["answer"]
    assert "#2 NO +7" in result["answer"]
    assert "#3 DEN +2.5" in result["answer"]
    comp = result["structured"]["comparison"]
    assert comp["currentRank"] == 2
    assert comp["totalQualified"] == 3
    assert len(comp["rankings"]) == 3
    assert "NO +7" in comp["currentPickReason"]


def test_sia3_comparison_rank_1_context():
    context = _base_live_context()
    context["eventId"] = "evt-2"
    context["selection"] = "NYG +3"
    context["recommendation"] = "STRONG BET"

    result = ask_sia.answer_from_context(
        event_id="evt-2",
        question="Compare SIA 3 Picks",
        live_context=context,
    )
    assert "currently ranks #1 of 3" in result["answer"]
    assert "This is currently SIA's #1 ranked selection." in result["answer"]


def test_sia3_comparison_rank_3_context():
    context = _base_live_context()
    context["eventId"] = "evt-3"
    context["selection"] = "DEN +2.5"
    context["recommendation"] = "BET"

    result = ask_sia.answer_from_context(
        event_id="evt-3",
        question="Compare SIA 3 Picks",
        live_context=context,
    )
    assert "currently ranks #3 of 3" in result["answer"]
    assert "BOTTOM LINE" in result["answer"]


def test_sia3_comparison_dynamic_ranking_not_hardcoded():
    context = _base_live_context()
    context["topSia3"] = [
        {
            "rank": 1,
            "eventId": "evt-x",
            "pick": "BUF +1.5",
            "sportsIntelligenceScore": {"score": 90.1},
            "recommendation": "STRONG BET",
            "calibratedProbability": 0.65,
            "impliedProbability": 56.0,
            "calibratedEdge": 0.09,
            "currentEV": 0.11,
            "qualificationStatus": "QUALIFIED",
        },
        {
            "rank": 2,
            "eventId": "evt-1",
            "pick": "NO +7",
            "sportsIntelligenceScore": {"score": 80.2},
            "recommendation": "STRONG BET",
            "calibratedProbability": 0.60,
            "impliedProbability": 54.0,
            "calibratedEdge": 0.06,
            "currentEV": 0.07,
            "qualificationStatus": "QUALIFIED",
        },
    ]

    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Compare SIA 3 Picks",
        live_context=context,
    )
    assert "#1 BUF +1.5" in result["answer"]
    assert "#2 NO +7" in result["answer"]


def test_sia3_comparison_with_fewer_than_three_qualified():
    context = _base_live_context()
    context["topSia3"] = context["topSia3"][:2]

    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Compare SIA 3 Picks",
        live_context=context,
    )
    assert "of 2" in result["answer"]
    assert "#3" not in result["answer"]


def test_comparison_no_mixed_context_text():
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Compare SIA 3 Picks",
        live_context=_base_live_context(),
    )
    why_text = " ".join(result["why"])
    assert "calibrated probability" not in why_text.lower()
    assert "push-aware EV is" not in why_text.lower()


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


def test_no_verified_risk_fallback_safe_and_not_treat_missing_as_risk():
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="What is the biggest risk?",
        live_context=_base_live_context(),
    )
    assert result["answer"] == "No major game-specific risk is currently verified."
    assert "weather" not in result["answer"].lower()
    assert "social" not in result["answer"].lower()


def test_missing_data_disclosures_only_when_relevant():
    playable = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Still playable at +2?",
        live_context=_base_live_context(),
    )
    why = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Why does SIA like this?",
        live_context=_base_live_context(),
    )

    assert playable["missingData"] == []
    assert why["missingData"] == []


def test_what_changes_the_bet_uses_canonical_playable_to():
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="What changes the bet?",
        live_context=_base_live_context(),
    )
    assert "moved beyond its current Playable-To" in result["answer"]
    assert "NO -5" in result["answer"]
    assert "CURRENT BET: NO +7" in result["why"]


def test_no_fabricated_risk():
    context = _base_live_context()
    context["injuryContext"] = {"summary": "", "severity": "neutral"}
    context["marketIntelligence"] = {"signal": "UNSET", "booksMoving": 5, "booksTracked": 8}
    context["weather"] = {"dataStatus": "UNAVAILABLE"}
    context["socialIntelligence"] = {"isLive": False, "dataStatus": "MOCK"}

    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="What is the biggest risk?",
        live_context=context,
    )
    assert "injury" not in result["answer"].lower()
    assert "weather" not in result["answer"].lower()
    assert "social" not in result["answer"].lower()


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
    assert payload["context"]["selection"] == "NO +7"
