from __future__ import annotations

from typing import Any, Dict, List


def generate_explainability(opportunity: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate deterministic, human-readable explanation content for a Sports Intelligence Score.

    This service does not use any AI APIs. It converts the existing opportunity, score,
    market, injury, weather, and executive analysis data into explanation blocks that can be
    rendered directly in the full analysis experience.
    """

    score_payload = opportunity.get("sportsIntelligenceScore") or {}
    market_intelligence = opportunity.get("marketIntelligence") or {}
    injury_context = opportunity.get("injuryContext") or {}
    weather_context = opportunity.get("weatherContext") or {}
    executive_analysis = opportunity.get("executiveAnalysis") or {}

    model_edge = float(opportunity.get("edge", 0) or 0)
    expected_value = float(opportunity.get("evPerDollar", 0) or 0)
    confidence = float(opportunity.get("confidence", 0) or 0)
    score = float(score_payload.get("score", 0) or 0)
    recommendation = str(score_payload.get("recommendation", "Pass") or "Pass")
    components = score_payload.get("components") or {}

    strengths: List[str] = []
    weaknesses: List[str] = []
    key_reasons: List[str] = []
    what_could_improve: List[str] = []
    risk_factors: List[str] = []

    if model_edge >= 8:
        strengths.append("Exceptional model edge")
        key_reasons.append("The model is finding a meaningful price edge over the current market.")
    elif model_edge >= 4:
        strengths.append("Solid model edge")
        key_reasons.append("The model is holding a modest but useful edge over the market.")
    else:
        weaknesses.append("Model edge is not yet strong enough to carry a high-conviction case")
        risk_factors.append("Small price changes could erase the edge")

    if expected_value >= 0.2:
        strengths.append("Strong expected value")
        key_reasons.append("Expected value is constructive and supports a positive risk-adjusted outcome.")
    elif expected_value >= 0.08:
        strengths.append("Positive expected value")
    else:
        weaknesses.append("Expected value is limited")
        what_could_improve.append("A better price or cleaner market structure would strengthen the case")

    if confidence >= 80:
        strengths.append("High confidence signal")
    elif confidence >= 65:
        strengths.append("Moderate confidence signal")
    else:
        weaknesses.append("Confidence remains limited")
        risk_factors.append("A weaker signal increases the need for discipline")

    market_score = float(market_intelligence.get("score", 0) or 0)
    market_signal = str(market_intelligence.get("signal", "") or "")
    books_moving = int(market_intelligence.get("booksMoving", 0) or 0)
    consensus = float(market_intelligence.get("consensus", 0) or 0)

    if market_score >= 70:
        strengths.append("Market confirmation is improving")
        key_reasons.append("The market is showing support for the direction of the model.")
    else:
        weaknesses.append("Market has not confirmed strongly")
        what_could_improve.append("Additional sharp market confirmation would improve conviction")

    if books_moving >= 2:
        key_reasons.append("Multiple books are moving, which adds weight to the signal.")
    elif books_moving == 1:
        key_reasons.append("One book is moving, but confirmation is still limited.")
    else:
        what_could_improve.append("More line movement would provide stronger confirmation")

    if consensus >= 70:
        strengths.append("Broad market agreement")
    elif consensus < 50:
        weaknesses.append("Market consensus is fragmented")

    injury_severity = str(injury_context.get("severity", "Neutral") or "Neutral").lower()
    injury_summary = str(injury_context.get("summary", "") or "")
    if injury_severity in {"neutral", "small"}:
        strengths.append("Neutral injury outlook")
        key_reasons.append("Injury context is not a meaningful headwind for this setup.")
    elif injury_severity == "moderate":
        weaknesses.append("Injury context is a moderate concern")
        risk_factors.append("Late injury news could change the outlook")
    else:
        weaknesses.append("Injury context is a material concern")
        risk_factors.append("A meaningful injury update would be a major swing factor")

    if injury_summary:
        key_reasons.append(injury_summary)

    weather_impact = float(weather_context.get("impactScore", 0) or 0)
    weather_summary = str(weather_context.get("summary", "") or "")
    if weather_impact >= 70:
        strengths.append("Weather is supportive")
        key_reasons.append("Weather conditions appear favorable for the projected edge.")
    elif weather_impact >= 40:
        strengths.append("Weather is neutral")
    else:
        what_could_improve.append("Weather advantage could improve the setup")

    if weather_summary:
        key_reasons.append(weather_summary)

    executive_summary = str(executive_analysis.get("summary", "") or "")
    if executive_summary:
        key_reasons.append(executive_summary)

    overall_summary = _build_overall_summary(score, recommendation, model_edge, expected_value, market_score, injury_severity)
    confidence_explanation = _build_confidence_explanation(confidence, components)
    market_explanation = _build_market_explanation(market_score, market_signal, books_moving)
    injury_explanation = _build_injury_explanation(injury_context)
    weather_explanation = _build_weather_explanation(weather_context)

    if not weaknesses:
        weaknesses.append("The setup still depends on continued market confirmation and fresh information")
        what_could_improve.append("Additional confirmation would improve conviction")

    if not risk_factors:
        risk_factors.append("A late market move or new information could change the outlook")

    return {
        "overallSummary": overall_summary,
        "strengths": strengths[:5],
        "weaknesses": weaknesses[:5],
        "confidenceExplanation": confidence_explanation,
        "marketExplanation": market_explanation,
        "injuryExplanation": injury_explanation,
        "weatherExplanation": weather_explanation,
        "keyReasons": key_reasons[:6],
        "whatCouldImprove": what_could_improve[:4],
        "riskFactors": risk_factors[:4],
    }


def _build_overall_summary(score: float, recommendation: str, model_edge: float, expected_value: float, market_score: float, injury_severity: str) -> str:
    if score >= 85:
        return f"The {recommendation.lower()} is driven by exceptional model edge and strong expected value. Market confirmation is improving, though the score is still constrained by the current market context."
    if score >= 70:
        return f"The {recommendation.lower()} is supported by a respectable edge and positive expected value. The setup remains viable, but it is not yet operating at elite conviction."
    if score >= 55:
        return f"The {recommendation.lower()} is workable, but the signal is not strong enough to justify a high-confidence commitment without additional confirmation."

    injury_note = "" if injury_severity in {"neutral", "small"} else " Injury context is a meaningful headwind."
    return f"The {recommendation.lower()} does not currently carry sufficient conviction to justify a strong commitment." + injury_note


def _build_confidence_explanation(confidence: float, components: Dict[str, Any]) -> str:
    if confidence >= 80:
        return "Confidence is strong because the model, price edge, and expected value are all aligned."
    if confidence >= 65:
        return "Confidence is moderate because the edge is present but the setup still depends on continued market or information confirmation."
    return "Confidence is limited because the signal is not yet robust enough to justify aggressive positioning."


def _build_market_explanation(market_score: float, market_signal: str, books_moving: int) -> str:
    if market_score >= 70:
        return f"The market is confirming the model with {books_moving} moving books and a {market_signal or 'positive'} signal."
    if books_moving >= 2:
        return "The market is moving, but the broader confirmation is still incomplete."
    return "The market has not yet provided strong confirmation for the recommendation."


def _build_injury_explanation(injury_context: Dict[str, Any]) -> str:
    severity = str(injury_context.get("severity", "Neutral") or "Neutral").lower()
    summary = str(injury_context.get("summary", "") or "")
    if severity == "neutral":
        return "Injury context is neutral and is not materially changing the setup."
    if severity in {"small", "moderate"}:
        return summary or "Injury context is mildly adverse and should be monitored closely."
    return summary or "Injury context is a meaningful risk factor for the recommendation."


def _build_weather_explanation(weather_context: Dict[str, Any]) -> str:
    impact = float(weather_context.get("impactScore", 0) or 0)
    summary = str(weather_context.get("summary", "") or "")
    if impact >= 70:
        return summary or "Weather conditions are supportive of the model edge."
    if impact >= 40:
        return summary or "Weather is mostly neutral and does not materially change the case."
    return summary or "Weather does not appear to be a meaningful edge driver."
