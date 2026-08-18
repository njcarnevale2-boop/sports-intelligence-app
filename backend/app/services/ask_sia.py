from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.routes.context import get_game_context
from app.routes.opportunities import get_game_best_opportunity, get_game_injury_context, get_game_weather, get_opportunities
from app.services.decision_ledger import get_latest_decision_by_snapshot_id
from app.services.games import service as games_service
from app.services.social_intelligence import social_intelligence_service


UNKNOWN_FALLBACK = "I don't have enough verified SIA data to answer that yet."


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _american_implied_probability(odds: float) -> float:
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def classify_intent(question: str) -> str:
    q = str(question or "").strip().lower()
    if not q:
        return "UNKNOWN"

    if "best sportsbook" in q or "best price" in q:
        return "BEST_SPORTSBOOK"
    if "playable to mean" in q or "what does playable" in q:
        return "PLAYABLE_TO_MEANING"
    if "still bet" in q or "still playable" in q or re.search(r"\bat\s*[+-]?\d", q):
        return "PLAYABLE_CHECK"
    if "biggest risk" in q:
        return "BIGGEST_RISK"
    if "what would make" in q and "pass" in q:
        return "PASS_CONDITION"
    if "what changes" in q and ("bet" in q or "decision" in q):
        return "PASS_CONDITION"
    if "against the market" in q or "higher than the market" in q or "probability higher" in q:
        return "MARKET_VS_MODEL"
    if "compare" in q or "other sia 3" in q or "which pick does sia like most" in q or "strong is this" in q:
        return "SIA3_COMPARE"
    if "line getting worse" in q or "line worse" in q:
        return "LINE_TREND"
    if "injur" in q:
        return "INJURY"
    if "weather" in q:
        return "WEATHER"
    if "why" in q:
        return "WHY"
    if "sia score" in q or ("score" in q and "sia" in q):
        return "SCORE"
    if "probability" in q:
        return "PROBABILITY"
    if "rank" in q and "sia 3" in q:
        return "RANK"
    if "bet or pass" in q or "bet/pass" in q or "pass" == q:
        return "BET_OR_PASS"
    return "UNKNOWN"


def _extract_hypothetical_value(question: str) -> Optional[float]:
    # Prefer signed values in betting contexts, fallback to first number.
    signed = re.findall(r"[+-]\d+(?:\.\d+)?", question)
    if signed:
        return _to_float(signed[0])

    plain = re.findall(r"\d+(?:\.\d+)?", question)
    if plain:
        return _to_float(plain[0])
    return None


def _playable_check(*, market: str, side: str, true_playable_to: Optional[float], hypothetical: Optional[float]) -> Optional[bool]:
    if true_playable_to is None or hypothetical is None:
        return None

    market_key = str(market or "").lower()
    side_key = str(side or "").lower()

    if market_key in {"spread", "spreads"}:
        # For spread bets, a higher number is always as-good-or-better for the bettor.
        return hypothetical >= true_playable_to

    if market_key in {"total", "totals"}:
        if side_key == "over":
            return hypothetical <= true_playable_to
        if side_key == "under":
            return hypothetical >= true_playable_to

    if market_key in {"moneyline", "h2h"}:
        return _american_implied_probability(hypothetical) <= _american_implied_probability(true_playable_to)

    return None


def _snapshot_note(snapshot_context: Optional[Dict[str, Any]], live_context: Optional[Dict[str, Any]]) -> Optional[str]:
    if not snapshot_context:
        return None

    snap_pick = snapshot_context.get("selection") or "Unknown selection"
    snap_price = snapshot_context.get("price")
    snap_book = snapshot_context.get("sportsbook") or "Unknown book"
    snap_part = f"AT PUBLICATION: {snap_pick} ({snap_price:+.0f}) at {snap_book}." if isinstance(snap_price, (int, float)) else f"AT PUBLICATION: {snap_pick} at {snap_book}."

    if not live_context:
        return snap_part

    live_pick = live_context.get("selection") or "Unknown selection"
    live_price = live_context.get("price")
    live_book = live_context.get("sportsbook") or "Unknown book"
    live_part = f"CURRENT LIVE MARKET: {live_pick} ({live_price:+.0f}) at {live_book}." if isinstance(live_price, (int, float)) else f"CURRENT LIVE MARKET: {live_pick} at {live_book}."

    return f"{snap_part} {live_part}"


def _build_structured_explanation(
    *,
    question: str,
    context: Dict[str, Any],
    intent: str,
    top_sia3: Optional[List[Dict[str, Any]]] = None,
    snapshot_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    missing_data: List[str] = []
    weather = context.get("weather")
    injury = context.get("injuryContext") or {}
    social = context.get("socialIntelligence") or {}

    if not weather or str((weather or {}).get("dataStatus", "")).upper() in {"UNAVAILABLE", ""}:
        missing_data.append("Weather data is not currently available for this matchup.")

    if social and social.get("isLive") is False:
        missing_data.append("Live social intelligence is not connected yet.")

    injury_summary = str(injury.get("summary") or "").strip()
    if not injury_summary or injury_summary.lower() in {"neutral", "no material edge"}:
        missing_data.append("SIA currently has no verified injury edge for this game.")

    selection = str(context.get("selection") or "this side")
    calibrated_prob = _to_float(context.get("calibratedProbability"))
    implied_prob = _to_float(context.get("impliedProbability"))
    calibrated_edge = _to_float(context.get("calibratedEdge"))
    current_ev = _to_float(context.get("currentEV"))
    true_playable_to = _to_float(context.get("truePlayableTo"))
    side = str(context.get("side") or "")
    market = str(context.get("market") or "")
    recommendation = str(context.get("recommendation") or "PASS")
    si_score = _to_float(context.get("siScore"))

    primary_reason = ""
    supporting_reasons: List[str] = []
    risk_factors: List[str] = []
    decision_boundary = ""
    market_context = ""
    confidence_summary = ""

    if calibrated_prob is not None and implied_prob is not None:
        supporting_reasons.append(
            f"Calibrated probability ({calibrated_prob * 100:.1f}%) is above market implied probability ({implied_prob:.1f}%)."
        )
    if calibrated_edge is not None:
        supporting_reasons.append(f"Calibrated edge is {calibrated_edge * 100:.1f} percentage points.")
    if current_ev is not None:
        supporting_reasons.append(f"Push-aware EV is {current_ev:+.3f} per $1.")
    if si_score is not None:
        supporting_reasons.append(f"SI Score is {si_score:.1f} ({recommendation}).")

    market_intel = context.get("marketIntelligence") or {}
    if market_intel:
        signal = market_intel.get("signal")
        books_moving = market_intel.get("booksMoving")
        books_tracked = market_intel.get("booksTracked")
        market_context = f"Market signal: {signal}. Books moving: {books_moving}/{books_tracked}."

    severity = str(injury.get("severity") or "").lower()
    if severity in {"moderate", "significant", "major"}:
        risk_factors.append("Injury context is a meaningful risk factor.")

    if weather and str(weather.get("dataStatus") or "").upper() not in {"UNAVAILABLE", ""}:
        if str(weather.get("summary") or "").strip():
            risk_factors.append("Weather could affect execution and volatility.")

    if not risk_factors:
        risk_factors.append("The biggest risk is price deterioration relative to SIA's playable boundary.")

    if true_playable_to is not None:
        decision_boundary = f"SIA's current True Playable-To is {true_playable_to:+g} for {selection}."
    else:
        decision_boundary = "I don't have enough verified SIA data to compute a Playable-To boundary right now."

    confidence_summary = f"SIA currently labels this as {recommendation}."

    answer = UNKNOWN_FALLBACK
    why = supporting_reasons[:3]
    what_changes = decision_boundary

    if intent == "WHY":
        answer = f"SIA currently favors {selection}."
        primary_reason = "Positive value based on calibrated probability versus price."

    elif intent == "BIGGEST_RISK":
        answer = risk_factors[0]
        primary_reason = "Risk concentration"

    elif intent == "PLAYABLE_CHECK":
        hypo = _extract_hypothetical_value(question)
        playable = _playable_check(market=market, side=side, true_playable_to=true_playable_to, hypothetical=hypo)
        if playable is None:
            answer = "I don't have enough verified SIA data to answer that yet."
        else:
            answer = (
                f"Yes — SIA still likes {selection} at {hypo:+g}."
                if playable
                else f"No — that price/line is outside SIA's current playable range for {selection}."
            )
            why = [
                f"This check uses the canonical True Playable-To threshold ({true_playable_to:+g}).",
            ]
            what_changes = f"At {hypo:+g}, this is {'inside' if playable else 'outside'} the current playable range."
        primary_reason = "Deterministic playable-to boundary check."

    elif intent == "PASS_CONDITION":
        answer = "SIA would move this to PASS if price/line moves outside the current playable boundary or if edge/EV deteriorates."
        primary_reason = "Boundary and value deterioration."

    elif intent == "MARKET_VS_MODEL":
        answer = "SIA is above market because the calibrated model probability is higher than implied market probability."
        primary_reason = "Calibrated probability disagreement with market."

    elif intent == "SIA3_COMPARE":
        if not top_sia3:
            answer = "I don't have enough verified SIA data to compare the current SIA 3 right now."
        else:
            ranked = sorted(top_sia3, key=lambda item: int(item.get("rank") or 999))
            best = ranked[0]
            answer = (
                f"SIA currently ranks {best.get('pick')} first in The SIA 3 "
                f"(SI Score {float((best.get('sportsIntelligenceScore') or {}).get('score') or 0):.1f}, "
                f"edge {float(best.get('calibratedEdge') or 0) * 100:.1f}pp, EV {float(best.get('currentEV') or 0):+.3f})."
            )
        primary_reason = "Canonical SIA 3 ranking."

    elif intent == "LINE_TREND":
        if market_intel and market_intel.get("booksMoving") is not None:
            answer = f"SIA sees current line movement signal as {market_intel.get('signal')} across {market_intel.get('booksMoving')}/{market_intel.get('booksTracked')} books."
        else:
            answer = "I don't have enough verified SIA data to confirm directional line movement right now."
        primary_reason = "Observed market movement metadata."

    elif intent == "INJURY":
        if injury_summary:
            answer = f"Injury context for this pick: {injury_summary}"
        else:
            answer = "SIA currently has no verified injury edge for this game."
        primary_reason = "Injury context summary."

    elif intent == "WEATHER":
        if weather and str(weather.get("dataStatus") or "").upper() not in {"UNAVAILABLE", ""}:
            answer = f"Weather context: {weather.get('summary') or 'Weather data is available and monitored for this game.'}"
        else:
            answer = "Weather data is not currently available for this matchup."
        primary_reason = "Weather availability check."

    elif intent == "PLAYABLE_TO_MEANING":
        answer = "Playable-To is SIA's current boundary where value remains acceptable for this exact recommendation."
        why = [
            "It is derived from the validated push-aware EV framework.",
            "If market price/line moves outside this boundary, the recommendation should be treated as PASS.",
        ]
        primary_reason = "Playable-To semantics."

    elif intent == "BEST_SPORTSBOOK":
        sportsbook = context.get("sportsbook")
        price = _to_float(context.get("price"))
        if sportsbook and price is not None:
            answer = f"The best current sportsbook price in SIA's canonical snapshot is {selection} ({price:+.0f}) at {sportsbook}."
        else:
            answer = "I don't have enough verified SIA data to identify the best sportsbook right now."
        primary_reason = "Canonical selected sportsbook for this recommendation."

    elif intent == "SCORE":
        if si_score is None:
            answer = "I don't have enough verified SIA data to provide the SI Score right now."
        else:
            answer = f"The current SI Score for this recommendation is {si_score:.1f}."
        primary_reason = "SI Score lookup."

    elif intent == "PROBABILITY":
        if calibrated_prob is None:
            answer = "I don't have enough verified SIA data to provide probability for this game right now."
        else:
            answer = f"SIA's calibrated probability is {calibrated_prob * 100:.1f}% (push {(_to_float(context.get('pushProbability')) or 0) * 100:.1f}%, loss {(_to_float(context.get('lossProbability')) or 0) * 100:.1f}%)."
        primary_reason = "Probability lookup."

    elif intent == "RANK":
        rank = context.get("rank")
        if rank is None:
            answer = "I don't have enough verified SIA data to provide SIA 3 rank for this game right now."
        else:
            answer = f"This recommendation is currently rank #{rank} in The SIA 3 board ordering."
        primary_reason = "Canonical ranking lookup."

    elif intent == "BET_OR_PASS":
        answer = f"SIA currently sees this as {recommendation}."
        primary_reason = "Current recommendation label."

    snapshot_note = _snapshot_note(snapshot_context=snapshot_context, live_context=context)

    return {
        "intent": intent,
        "answer": answer,
        "why": why,
        "whatChangesDecision": what_changes,
        "structured": {
            "primaryReason": primary_reason,
            "supportingReasons": supporting_reasons,
            "riskFactors": risk_factors,
            "decisionBoundary": decision_boundary,
            "missingData": missing_data,
            "marketContext": market_context,
            "confidenceSummary": confidence_summary,
        },
        "snapshotNote": snapshot_note,
        "missingData": missing_data,
        "citations": [
            "selection",
            "price",
            "sportsbook",
            "calibratedProbability",
            "pushProbability",
            "lossProbability",
            "calibratedEdge",
            "currentEV",
            "truePlayableTo",
            "siScore",
            "recommendation",
            "marketIntelligence",
            "injuryContext",
            "weather",
            "socialIntelligence",
            "qualificationReasons",
            "snapshotTimestamp",
        ],
    }


def _build_live_context(event_id: str) -> Dict[str, Any]:
    game_bundle = get_game_best_opportunity(event_id)
    opportunity = game_bundle.get("opportunity") or {}
    report = game_bundle.get("intelligenceReport") or {}

    games_payload = games_service.list_games()
    game_row = next((row for row in (games_payload.get("games") or []) if str(row.get("eventId")) == str(event_id)), {})

    context_payload = get_game_context(event_id)
    injuries_payload = get_game_injury_context(event_id)
    weather_payload = get_game_weather(event_id)
    social_payload = social_intelligence_service.get_game_social_context(event_id)

    week = game_row.get("week")
    opportunities_payload = get_opportunities(limit=100, best_lines_only=True, week=week)
    top_sia3 = (opportunities_payload.get("opportunities") or [])[:3]

    return {
        "eventId": event_id,
        "teams": {
            "awayTeam": opportunity.get("awayTeam") or game_row.get("awayAbbreviation") or game_row.get("awayTeam"),
            "homeTeam": opportunity.get("homeTeam") or game_row.get("homeAbbreviation") or game_row.get("homeTeam"),
        },
        "selection": opportunity.get("pick"),
        "market": opportunity.get("market"),
        "side": opportunity.get("side"),
        "point": opportunity.get("point"),
        "price": opportunity.get("price"),
        "sportsbook": opportunity.get("book"),
        "consensusLine": game_row.get("spread"),
        "rawProbability": _to_float(opportunity.get("rawModelProbability")) or (_to_float(opportunity.get("modelProbability")) or 0.0) / 100.0,
        "calibratedProbability": _to_float(opportunity.get("calibratedProbability") or opportunity.get("currentWinProbability")),
        "pushProbability": _to_float(opportunity.get("currentPushProbability")),
        "lossProbability": _to_float(opportunity.get("currentLossProbability")),
        "impliedProbability": _to_float(opportunity.get("impliedProbability")),
        "calibratedEdge": _to_float(opportunity.get("calibratedEdge")),
        "currentEV": _to_float(opportunity.get("currentEV")),
        "fairLine": _to_float(opportunity.get("fairLine")),
        "truePlayableTo": _to_float(opportunity.get("truePlayableTo")),
        "siScore": _to_float((opportunity.get("sportsIntelligenceScore") or {}).get("score")),
        "recommendation": opportunity.get("recommendation") or report.get("betStatus"),
        "marketIntelligence": opportunity.get("marketIntelligence"),
        "lineMovement": opportunity.get("marketIntelligence"),
        "restTravel": context_payload,
        "injuryContext": injuries_payload.get("injuryContext"),
        "weather": weather_payload.get("weather"),
        "socialIntelligence": social_payload,
        "qualificationReasons": opportunity.get("qualificationReasons") or report.get("qualificationReasons") or [],
        "snapshotTimestamp": opportunity.get("marketLastUpdated"),
        "rank": opportunity.get("rank"),
        "snapshotId": opportunities_payload.get("snapshotId"),
        "topSia3": top_sia3,
    }


def _build_snapshot_context(snapshot_id: str) -> Optional[Dict[str, Any]]:
    decision = get_latest_decision_by_snapshot_id(snapshot_id)
    if decision is None:
        return None
    return {
        "eventId": decision.get("eventId"),
        "selection": decision.get("selection"),
        "market": decision.get("market"),
        "side": decision.get("side"),
        "point": decision.get("point"),
        "price": decision.get("price"),
        "sportsbook": decision.get("sportsbook"),
        "calibratedProbability": decision.get("calibratedProbability"),
        "pushProbability": decision.get("pushProbability"),
        "lossProbability": decision.get("lossProbability"),
        "calibratedEdge": decision.get("calibratedEdge"),
        "currentEV": decision.get("currentEV"),
        "truePlayableTo": decision.get("truePlayableTo"),
        "siScore": decision.get("siScore"),
        "recommendation": decision.get("recommendation"),
        "snapshotTimestamp": decision.get("marketTimestamp") or decision.get("oddsTimestamp") or decision.get("publishedAtUTC"),
    }


def answer_from_context(
    *,
    event_id: str,
    question: str,
    live_context: Dict[str, Any],
    snapshot_id: Optional[str] = None,
) -> Dict[str, Any]:
    snapshot_context = _build_snapshot_context(snapshot_id) if snapshot_id else None
    intent = classify_intent(question)

    response = _build_structured_explanation(
        question=question,
        context=live_context,
        intent=intent,
        top_sia3=live_context.get("topSia3"),
        snapshot_context=snapshot_context,
    )

    return {
        "eventId": event_id,
        "question": question,
        "intent": intent,
        "contextMode": "SNAPSHOT_AND_LIVE" if snapshot_context else "LIVE",
        "snapshotId": snapshot_id,
        "answer": response["answer"],
        "why": response["why"],
        "whatChangesDecision": response["whatChangesDecision"],
        "snapshotNote": response["snapshotNote"],
        "structured": response["structured"],
        "missingData": response["missingData"],
        "citations": response["citations"],
        "context": {
            "eventId": live_context.get("eventId"),
            "teams": live_context.get("teams"),
            "selection": live_context.get("selection"),
            "market": live_context.get("market"),
            "bestPrice": live_context.get("price"),
            "sportsbook": live_context.get("sportsbook"),
            "consensusLine": live_context.get("consensusLine"),
            "rawProbability": live_context.get("rawProbability"),
            "calibratedProbability": live_context.get("calibratedProbability"),
            "pushProbability": live_context.get("pushProbability"),
            "lossProbability": live_context.get("lossProbability"),
            "calibratedEdge": live_context.get("calibratedEdge"),
            "pushAwareEV": live_context.get("currentEV"),
            "fairLine": live_context.get("fairLine"),
            "playableTo": live_context.get("truePlayableTo"),
            "siScore": live_context.get("siScore"),
            "recommendation": live_context.get("recommendation"),
            "marketIntelligence": live_context.get("marketIntelligence"),
            "lineMovement": live_context.get("lineMovement"),
            "restTravel": live_context.get("restTravel"),
            "injuries": live_context.get("injuryContext"),
            "weather": live_context.get("weather"),
            "socialIntelligence": live_context.get("socialIntelligence"),
            "qualificationReasons": live_context.get("qualificationReasons"),
            "snapshotTimestamp": live_context.get("snapshotTimestamp"),
            "snapshotId": live_context.get("snapshotId"),
        },
    }


def get_ask_sia_response(*, event_id: str, question: str, snapshot_id: Optional[str] = None) -> Dict[str, Any]:
    live_context = _build_live_context(event_id)
    return answer_from_context(
        event_id=event_id,
        question=question,
        live_context=live_context,
        snapshot_id=snapshot_id,
    )
