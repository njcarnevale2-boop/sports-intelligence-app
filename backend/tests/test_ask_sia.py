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
        "betStatus": "STRONG BET",
        "whySummary": "SIA identified a qualified edge based on model probability, price, and confidence.",
        "betTrigger": {"available": False, "message": "Actionable price not currently available"},
        "marketIntelligence": {"signal": "CONFIRMED", "booksMoving": 5, "booksTracked": 8, "steamBooks": 2},
        "lineMovement": {
            "signal": "CONFIRMED",
            "booksMoving": 5,
            "booksTracked": 8,
        },
        "marketDataStatus": "LIVE",
        "marketLastUpdated": "2026-09-13T15:00:00+00:00",
        "quoteFreshness": "FRESH",
        "bestAvailablePrice": -115.0,
        "bestAvailableLine": 7.0,
        "bestAvailableSportsbook": "Bovada",
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
        "bestByMarket": {
            "moneyline": {
                "pick": "NO",
                "market": "moneyline",
                "side": "away",
                "price": 130,
                "book": "DraftKings",
                "productionEligible": False,
                "marketValidationStatus": "SHADOW_VALIDATION",
                "quoteFreshness": "FRESH",
            },
            "total": {
                "pick": "OVER 45.5",
                "market": "total",
                "side": "over",
                "price": -110,
                "book": "FanDuel",
                "productionEligible": False,
                "marketValidationStatus": "SHADOW_VALIDATION",
                "quoteFreshness": "FRESH",
            },
        },
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


def test_cross_market_compare_discloses_shadow_validation():
    context = _base_live_context()
    context["bestByMarket"] = {
        "spread": {
            "pick": "NO +7",
            "market": "spread",
            "side": "away",
            "price": -115,
            "productionEligible": True,
            "marketValidationStatus": "PRODUCTION_VALIDATED",
        },
        "moneyline": {
            "pick": "NO",
            "market": "moneyline",
            "side": "away",
            "price": 130,
            "productionEligible": False,
            "marketValidationStatus": "SHADOW_VALIDATION",
        },
    }

    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Which is stronger, the spread or moneyline?",
        live_context=context,
    )

    assert result["intent"] == "CROSS_MARKET_COMPARE"
    assert "shadow validation" in result["answer"].lower()
    assert "not currently eligible to outrank a spread" in result["answer"].lower()


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


def test_move_the_line_why_still_playable_is_deterministic():
    move = {
        "current": {"selection": "NO +7", "truePlayableTo": -5.0, "winProbability": 0.61, "pushAwareEV": 0.18, "edge": 0.08},
        "hypothetical": {
            "selection": "NO +2",
            "status": "PLAYABLE",
            "statusReason": "Still inside SIA's current playable range.",
            "insidePlayableRange": True,
            "atPlayableBoundary": False,
            "truePlayableTo": -5.0,
            "winProbability": 0.59,
            "pushAwareEV": 0.11,
            "edge": 0.06,
        },
        "valueChange": {"probabilityChange": -0.02, "evChange": -0.07, "edgeChange": -0.02},
    }

    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Why is this still playable?",
        live_context=_base_live_context(),
        move_the_line=move,
    )
    assert result["intent"] == "WHY_STILL_PLAYABLE"
    assert "still PLAYABLE" in result["answer"]


def test_move_the_line_why_pass_is_deterministic():
    move = {
        "current": {"selection": "NO +7", "truePlayableTo": -5.0, "winProbability": 0.61, "pushAwareEV": 0.18, "edge": 0.08},
        "hypothetical": {
            "selection": "NO -5.5",
            "status": "PASS",
            "statusReason": "Outside SIA's current playable range.",
            "insidePlayableRange": False,
            "atPlayableBoundary": False,
            "truePlayableTo": -5.0,
            "winProbability": 0.51,
            "pushAwareEV": -0.02,
            "edge": -0.01,
        },
        "valueChange": {"probabilityChange": -0.1, "evChange": -0.2, "edgeChange": -0.09},
    }

    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Why does this become a pass?",
        live_context=_base_live_context(),
        move_the_line=move,
    )
    assert result["intent"] == "WHY_PASS"
    assert "outside SIA's current playable range" in result["answer"]


def test_move_the_line_value_lost_is_deterministic():
    move = {
        "current": {"selection": "NO +7", "truePlayableTo": -5.0, "winProbability": 0.61, "pushAwareEV": 0.18, "edge": 0.08},
        "hypothetical": {
            "selection": "NO +2",
            "status": "PLAYABLE",
            "statusReason": "Still inside SIA's current playable range.",
            "insidePlayableRange": True,
            "atPlayableBoundary": False,
            "truePlayableTo": -5.0,
            "winProbability": 0.59,
            "pushAwareEV": 0.11,
            "edge": 0.06,
        },
        "valueChange": {"probabilityChange": -0.02, "evChange": -0.07, "edgeChange": -0.02},
    }

    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="How much value did I lose?",
        live_context=_base_live_context(),
        move_the_line=move,
    )
    assert result["intent"] == "VALUE_LOST"
    assert "Value change versus original" in result["answer"]


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


def test_no_bet_question_uses_canonical_report():
    context = _base_live_context()
    context["betStatus"] = "NO QUALIFIED BET"
    context["recommendation"] = "PASS"
    context["whySummary"] = "SIA is passing because the current edge does not clear the qualification policy."
    context["betTrigger"] = {"available": False, "message": "Actionable price not currently available"}
    context["qualificationReasons"] = ["Current model edge and confidence do not meet SIA qualification thresholds."]

    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Why aren't you betting this?",
        live_context=context,
    )

    assert result["intent"] == "NO_BET_REASON"
    assert result["answer"].startswith("SIA is passing")
    assert "qualification thresholds" in " ".join(result["why"]).lower()
    assert result["whatChangesDecision"] == "Actionable price not currently available"


def test_playable_boundary_question_uses_canonical_boundary():
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="What line is too expensive?",
        live_context=_base_live_context(),
    )

    assert result["intent"] == "PLAYABLE_BOUNDARY"
    assert "Playable-To" in result["answer"]
    assert "NO -5" in result["answer"]


def test_best_sportsbook_marks_stale_quote():
    context = _base_live_context()
    context["quoteFreshness"] = "STALE"
    context["bestAvailablePrice"] = -120.0
    context["bestAvailableLine"] = 7.5
    context["bestAvailableSportsbook"] = "FanDuel"

    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Which sportsbook has the best line?",
        live_context=context,
    )

    assert result["intent"] == "BEST_SPORTSBOOK"
    assert "stale" in result["answer"].lower()
    assert "FanDuel" in result["answer"]


def test_market_firewall_for_shadow_market_research():
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="What about the moneyline?",
        live_context=_base_live_context(),
    )

    assert result["intent"] == "MARKET_FIREWALL"
    assert "shadow validation" in result["answer"].lower()
    assert "spread-only" in " ".join(result["why"]).lower()


def test_market_firewall_for_disabled_market_families():
    prop_result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="What about player props?",
        live_context=_base_live_context(),
    )
    team_total_result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="What about team totals?",
        live_context=_base_live_context(),
    )
    first_half_result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="What about first half?",
        live_context=_base_live_context(),
    )

    assert prop_result["intent"] == "MARKET_FIREWALL"
    assert "player-prop" in prop_result["answer"].lower()
    assert "team-total" in team_total_result["answer"].lower()
    assert "first-half" in first_half_result["answer"].lower()


def test_rest_travel_question_uses_existing_context():
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Is rest/travel important?",
        live_context=_base_live_context(),
    )

    assert result["intent"] == "REST_TRAVEL"
    assert "Travel is 220 miles" in result["answer"]


def test_follow_up_context_reuses_current_game_state():
    context = _base_live_context()
    first = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Why does SIA like this bet?",
        live_context=context,
    )
    second = ask_sia.answer_from_context(
        event_id="evt-1",
        question="What's the biggest risk?",
        live_context=context,
    )

    assert first["context"]["selection"] == second["context"]["selection"] == "NO +7"
    assert "NO +7" in first["answer"] or "NO +7" in " ".join(first["why"])
    assert second["intent"] == "BIGGEST_RISK"


def test_missing_optional_context_does_not_fabricate_zeroes():
    context = _base_live_context()
    context["truePlayableTo"] = None
    context["bestAvailablePrice"] = None
    context["bestAvailableLine"] = None
    context["bestAvailableSportsbook"] = ""
    context["marketIntelligence"] = {}
    context["injuryContext"] = {"summary": "", "severity": "neutral"}
    context["weather"] = {"dataStatus": "UNAVAILABLE"}
    context["socialIntelligence"] = {"isLive": False, "dataStatus": "MOCK"}

    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="What is the biggest risk?",
        live_context=context,
    )

    assert "0.0" not in result["answer"]
    assert "Weather data is not currently available." in result["missingData"]
    assert "Live social intelligence is not connected yet." in result["missingData"]


def test_game_detail_consistency_fields_match_canonical_context():
    result = ask_sia.answer_from_context(
        event_id="evt-1",
        question="Why does SIA like this bet?",
        live_context=_base_live_context(),
    )

    assert result["context"]["selection"] == "NO +7"
    assert result["context"]["bestPrice"] == -115.0
    assert result["context"]["playableTo"] == -5.0
    assert result["context"]["sportsbook"] == "Bovada"
