from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.services.probability_engine import ev_per_dollar_with_push, spread_outcome_probabilities
from app.services.sports_intelligence_score import calculate_sports_intelligence_score


@dataclass
class SpreadDecisionBoundaries:
    recommended_playable_to: Optional[float]
    recommended_playable_to_status: str
    recommended_playable_to_reason: Optional[str]
    stages: List[Dict[str, Any]]


def _round_half(value: float) -> float:
    return round(value * 2.0) / 2.0


def _normalize_signed_zero(value: float) -> float:
    return 0.0 if abs(value) < 1e-9 else value


def _recommendation_label(score_payload: Dict[str, Any]) -> str:
    label = str(score_payload.get("recommendation") or "Pass").upper()
    if label == "ELITE BET":
        return "ELITE BET"
    if label == "STRONG BET":
        return "STRONG BET"
    if label == "BET":
        return "BET"
    if label == "LEAN":
        return "LEAN"
    return "PASS"


def _qualification_from_recommendation(recommendation: str) -> str:
    label = str(recommendation or "").strip().upper()
    if not label:
        return "NOT_QUALIFIED"
    if "PASS" in label or "LEAN" in label or "WATCH" in label:
        return "NOT_QUALIFIED"
    return "QUALIFIED"


def build_spread_decision_boundaries(
    *,
    model_margin_home: Optional[float],
    side: str,
    current_point: Optional[float],
    price: Optional[float],
    true_playable_to: Optional[float],
    confidence: float,
    data_completeness: float,
    market_intelligence: Dict[str, Any],
) -> SpreadDecisionBoundaries:
    if model_margin_home is None:
        return SpreadDecisionBoundaries(
            recommended_playable_to=None,
            recommended_playable_to_status="UNAVAILABLE",
            recommended_playable_to_reason="Model spread context is unavailable.",
            stages=[],
        )

    if current_point is None or price is None:
        return SpreadDecisionBoundaries(
            recommended_playable_to=None,
            recommended_playable_to_status="UNAVAILABLE",
            recommended_playable_to_reason="Current spread/price context is unavailable.",
            stages=[],
        )

    if true_playable_to is None:
        return SpreadDecisionBoundaries(
            recommended_playable_to=None,
            recommended_playable_to_status="UNAVAILABLE",
            recommended_playable_to_reason="Mathematical EV boundary is unavailable.",
            stages=[],
        )

    start = _normalize_signed_zero(_round_half(float(current_point)))
    boundary = _normalize_signed_zero(_round_half(float(true_playable_to)))

    points: List[float] = []
    cursor = start
    guard = 0
    while cursor >= boundary - 1e-9 and guard < 160:
        points.append(_normalize_signed_zero(cursor))
        cursor = _normalize_signed_zero(_round_half(cursor - 0.5))
        guard += 1

    outside = _normalize_signed_zero(_round_half(boundary - 0.5))
    if not points or abs(points[-1] - outside) > 1e-9:
        points.append(outside)

    rows: List[Dict[str, Any]] = []
    for point in points:
        probs = spread_outcome_probabilities(
            model_margin_home=float(model_margin_home),
            side=str(side or "").lower(),
            spread_point=float(point),
        )
        if probs.status != "AVAILABLE":
            continue

        push_aware_ev = ev_per_dollar_with_push(probs.win, probs.push, float(price))
        market_implied_probability = abs(float(price)) / (abs(float(price)) + 100.0) if float(price) < 0 else 100.0 / (float(price) + 100.0)
        edge = probs.win - market_implied_probability

        score_payload = calculate_sports_intelligence_score(
            opportunity={
                "edge": round(edge * 100, 1),
                "evPerDollar": round(push_aware_ev, 3),
                "confidence": float(confidence),
                "dataCompleteness": float(data_completeness),
                "injuryContext": {},
            },
            market_intelligence=market_intelligence or {},
        )
        recommendation = _recommendation_label(score_payload)
        qualification_status = _qualification_from_recommendation(recommendation)
        boundary_status = "INSIDE" if point > boundary else ("AT_BOUNDARY" if abs(point - boundary) < 1e-9 else "OUTSIDE")

        rows.append(
            {
                "spread": point,
                "recommendation": recommendation,
                "qualificationStatus": qualification_status,
                "boundaryStatus": boundary_status,
                "status": "PLAYABLE" if boundary_status in {"INSIDE", "AT_BOUNDARY"} else "PASS",
            }
        )

    if not rows:
        return SpreadDecisionBoundaries(
            recommended_playable_to=None,
            recommended_playable_to_status="UNAVAILABLE",
            recommended_playable_to_reason="Probability engine is unavailable for this line range.",
            stages=[],
        )

    qualified_recs = {"ELITE BET", "STRONG BET", "BET"}
    strong_recs = {"ELITE BET", "STRONG BET"}

    def worst_spread(predicate):
        hits = [row["spread"] for row in rows if predicate(row)]
        return min(hits) if hits else None

    recommended_to = worst_spread(lambda row: row["recommendation"] in qualified_recs and row["qualificationStatus"] == "QUALIFIED")
    strong_to = worst_spread(lambda row: row["recommendation"] in strong_recs and row["qualificationStatus"] == "QUALIFIED")
    lean_at = next((row["spread"] for row in rows if row["recommendation"] == "LEAN"), None)
    pass_at = next((row["spread"] for row in rows if row["recommendation"] == "PASS"), None)

    by_spread = {row["spread"]: row for row in rows}

    def stage(label: str, spread: Optional[float]) -> Optional[Dict[str, Any]]:
        if spread is None:
            return None
        row = by_spread.get(spread)
        if not row:
            return None
        return {
            "label": label,
            "spread": spread,
            "recommendation": row["recommendation"],
            "qualificationStatus": row["qualificationStatus"],
            "status": row["status"],
            "boundaryStatus": row["boundaryStatus"],
        }

    ordered_points = []
    for point in [start, strong_to, recommended_to, lean_at, pass_at, boundary]:
        if point is None:
            continue
        if not any(abs(point - seen) < 1e-9 for seen in ordered_points):
            ordered_points.append(point)

    label_by_point = {
        start: "Current line",
        strong_to: "Strong Bet through",
        recommended_to: "Official bet through",
        lean_at: "Lean starts",
        pass_at: "Pass starts",
        boundary: "Mathematical EV boundary",
    }

    stages: List[Dict[str, Any]] = []
    for point in ordered_points:
        staged = stage(label_by_point.get(point, "Stage"), point)
        if staged is not None:
            stages.append(staged)

    reason = None
    if recommended_to is None:
        reason = "No spread in the evaluated range remains both BET/STRONG BET and QUALIFIED."

    return SpreadDecisionBoundaries(
        recommended_playable_to=recommended_to,
        recommended_playable_to_status="AVAILABLE" if recommended_to is not None else "UNAVAILABLE",
        recommended_playable_to_reason=reason,
        stages=stages,
    )
