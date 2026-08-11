from __future__ import annotations

from typing import Any, Dict, List, Optional


def generate_executive_analysis(opportunity: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generate deterministic executive-level analysis from the opportunity data.

    This is intentionally rule-based and does not depend on any external AI APIs.
    """

    opportunity = opportunity or {}

    sports_score = opportunity.get("sportsIntelligenceScore") or {}
    market_intelligence = opportunity.get("marketIntelligence") or {}
    injury_context = opportunity.get("injuryContext") or {}

    model_edge = float(opportunity.get("edge", 0) or 0)
    expected_value = float(opportunity.get("evPerDollar", 0) or 0)
    confidence = float(opportunity.get("confidence", 0) or 0)

    score = float(sports_score.get("score", 0) or 0)
    recommendation = str(sports_score.get("recommendation", "Pass") or "Pass")
    components = sports_score.get("components") or {}

    headline = _build_headline(score, recommendation, model_edge)
    strengths = _build_strengths(model_edge, expected_value, confidence, components, market_intelligence)
    risks = _build_risks(model_edge, expected_value, confidence, components, injury_context)
    watch_items = _build_watch_items(market_intelligence, injury_context, confidence)
    summary = _build_summary(score, recommendation, model_edge, expected_value, injury_context)
    stake_recommendation = _build_stake_recommendation(score, model_edge, confidence, injury_context)
    best_price_summary = _build_best_price_summary(opportunity)

    return {
        "headline": headline,
        "recommendation": recommendation,
        "summary": summary,
        "strengths": strengths,
        "risks": risks,
        "watchItems": watch_items,
        "stakeRecommendation": stake_recommendation,
        "bestPriceSummary": best_price_summary,
    }


def _build_headline(score: float, recommendation: str, model_edge: float) -> str:
    if score >= 90:
        return f"This is a high-conviction {recommendation.lower()} with a clear edge over the market."
    if score >= 75:
        return f"The position carries a credible {recommendation.lower()} profile supported by favorable model and market signals."
    if score >= 60:
        return f"The opportunity merits attention, though the edge is narrower and execution should remain disciplined."
    return "The signal is limited and the position does not currently justify material exposure."


def _build_strengths(model_edge: float, expected_value: float, confidence: float, components: Dict[str, Any], market_intelligence: Dict[str, Any]) -> List[str]:
    strengths: List[str] = []

    if model_edge >= 8:
        strengths.append("The model carries a meaningful edge over the current market price.")
    elif model_edge >= 4:
        strengths.append("The model holds a modest but useful edge over the market.")

    if expected_value >= 0.2:
        strengths.append("Expected value is constructive and supports a positive risk-adjusted outcome.")
    elif expected_value >= 0.08:
        strengths.append("Expected value is positive but should be treated as a secondary signal.")

    if confidence >= 80:
        strengths.append("Confidence is strong enough to support a direct recommendation.")
    elif confidence >= 65:
        strengths.append("Confidence is adequate, though the position still requires careful monitoring.")

    if components.get("marketIntelligence", 0) >= 70:
        strengths.append("Market movement is confirming the model rather than contradicting it.")

    if market_intelligence.get("consensus", 0) >= 70:
        strengths.append("The market is showing broad agreement around the direction of the signal.")

    if not strengths:
        strengths.append("The current signal is directionally favorable but not yet robust enough to be decisive.")

    return strengths[:4]


def _build_risks(model_edge: float, expected_value: float, confidence: float, components: Dict[str, Any], injury_context: Dict[str, Any]) -> List[str]:
    risks: List[str] = []

    if model_edge < 4:
        risks.append("The edge is narrow enough that small pricing changes could eliminate the advantage.")

    if expected_value <= 0:
        risks.append("Expected value does not currently support the position.")

    if confidence < 60:
        risks.append("Confidence is limited, which increases the importance of execution discipline.")

    if components.get("dataCompleteness", 0) < 70:
        risks.append("Data completeness is not strong enough to justify oversized conviction.")

    severity = str(injury_context.get("severity", "Neutral")).lower()
    if severity == "moderate":
        risks.append("Injury context is moderately adverse and should be weighted in the final decision.")
    elif severity == "significant":
        risks.append("Injury context is a meaningful headwind and reduces confidence in the setup.")
    elif severity == "major":
        risks.append("Injury context is a major concern and materially limits the investment case.")

    if not risks:
        risks.append("No material structural risk is apparent from the available evidence.")

    return risks[:4]


def _build_watch_items(market_intelligence: Dict[str, Any], injury_context: Dict[str, Any], confidence: float) -> List[str]:
    watch_items: List[str] = []

    if market_intelligence.get("booksMoving", 0):
        watch_items.append("Monitor line movement across the available books for fresh confirmation or reversal.")

    if injury_context:
        severity = str(injury_context.get("severity", "Neutral")).lower()
        if severity != "neutral":
            watch_items.append("Track the most relevant injury developments before committing to size.")

    if confidence < 70:
        watch_items.append("Reassess the position if model confidence deteriorates further.")

    if not watch_items:
        watch_items.append("No immediate watch item is apparent from the current snapshot.")

    return watch_items[:3]


def _build_summary(score: float, recommendation: str, model_edge: float, expected_value: float, injury_context: Dict[str, Any]) -> str:
    severity = str(injury_context.get("severity", "Neutral")).lower()

    injury_note = ""
    if severity == "neutral":
        injury_note = " Injury context is neutral and does not materially change the play."
    elif severity == "small":
        injury_note = " Injury context is mildly adverse but not decisive."
    elif severity == "moderate":
        injury_note = " Injury context is a meaningful consideration."
    elif severity == "significant":
        injury_note = " Injury context is a material headwind."
    elif severity == "major":
        injury_note = " Injury context is a major concern."

    if score >= 85:
        return f"The opportunity presents a strong {recommendation.lower()} case, supported by favorable edge, positive expected value, and disciplined market confirmation.{injury_note}"
    if score >= 70:
        return f"The opportunity is attractive on the current data, with a healthy edge and acceptable risk-adjusted return profile.{injury_note}"
    if score >= 55:
        return f"The setup is workable but should be sized conservatively until the signal becomes clearer.{injury_note}"
    return f"The position is not compelling enough to justify a meaningful commitment under the current conditions.{injury_note}"


def _build_stake_recommendation(score: float, model_edge: float, confidence: float, injury_context: Dict[str, Any]) -> str:
    severity = str(injury_context.get("severity", "Neutral")).lower()

    if score >= 85 and model_edge >= 8 and confidence >= 80:
        return "Full size is reasonable only if the price remains at or better than the current best line."
    if score >= 70 and confidence >= 70 and severity in {"neutral", "small"}:
        return "A moderate stake is appropriate given the quality of the signal and the current price."
    if severity in {"significant", "major"}:
        return "Reduce position size materially until injury developments and market movement are clearer."
    return "Keep exposure limited until the price and broader market context improve."


def _build_best_price_summary(opportunity: Dict[str, Any]) -> str:
    pick = str(opportunity.get("pick", ""))
    book = str(opportunity.get("book", ""))
    price = opportunity.get("price", 0)
    market = str(opportunity.get("market", "")).lower()

    if not pick:
        return "The current best price is not yet available."

    if market == "spread":
        return f"The current best available price is {pick} at {book} at {price:+.0f}."
    return f"The current best available price is {pick} at {book} at {price:+.0f}."
