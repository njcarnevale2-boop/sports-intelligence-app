from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from app.config import settings
from app.routes.opportunities import get_game_best_opportunity, get_opportunities
from app.services.decision_ledger import get_latest_decision_by_snapshot_id
from app.services.games import service as games_service
from app.services.probability_engine import (
    ev_per_dollar_with_push,
    fair_price_from_win_push,
    spread_outcome_probabilities,
    true_playable_to_spread,
)
from app.services.sports_intelligence_score import calculate_sports_intelligence_score


MODEL_ROOT = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9"
GAME_PROJECTIONS = MODEL_ROOT / "outputs" / "current_game_projections.csv"


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


def _normalize_signed_zero(value: float) -> float:
    return 0.0 if abs(value) < 1e-9 else value


def _round_half(value: float) -> float:
    return round(value * 2.0) / 2.0


def _spread_display(value: float) -> str:
    normalized = _normalize_signed_zero(value)
    if abs(normalized) < 1e-9:
        return "PK"
    return f"{normalized:+g}"


def _selection_for_line(base_selection: str, spread: float) -> str:
    team = str(base_selection or "").split(" ")[0] or "Selection"
    return f"{team} {_spread_display(spread)}"


def _is_inside_spread_playable_range(hypothetical_spread: float, true_playable_to: Optional[float]) -> Optional[bool]:
    if true_playable_to is None:
        return None
    return hypothetical_spread >= true_playable_to


def _is_boundary(hypothetical_spread: float, true_playable_to: Optional[float]) -> bool:
    if true_playable_to is None:
        return False
    return abs(hypothetical_spread - true_playable_to) < 1e-9


def _qualification_from_recommendation(recommendation: str) -> str:
    label = str(recommendation or "").strip().upper()
    if not label:
        return "NOT_QUALIFIED"
    if "PASS" in label or "LEAN" in label or "WATCH" in label:
        return "NOT_QUALIFIED"
    return "QUALIFIED"


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


def _load_model_margin_home(event_id: str) -> Optional[float]:
    if not GAME_PROJECTIONS.exists():
        return None

    try:
        df = pd.read_csv(GAME_PROJECTIONS)
    except (OSError, pd.errors.EmptyDataError):
        return None

    if "api_event_id" not in df.columns:
        return None

    match = df[df["api_event_id"].astype(str) == str(event_id)]
    if match.empty:
        return None

    return _to_float(match.iloc[0].get("model_margin_home"))


def _live_snapshot_id(event_id: str) -> Optional[str]:
    games_payload = games_service.list_games()
    game_row = next((g for g in (games_payload.get("games") or []) if str(g.get("eventId")) == str(event_id)), None)
    if game_row is None:
        return None

    week = game_row.get("week")
    opportunities_payload = get_opportunities(limit=100, best_lines_only=True, week=week)
    return opportunities_payload.get("snapshotId")


def _build_base_context(event_id: str, snapshot_id: Optional[str]) -> Dict[str, Any]:
    source_mode = "LIVE"
    source_snapshot_id = _live_snapshot_id(event_id)

    if snapshot_id:
        decision = get_latest_decision_by_snapshot_id(snapshot_id)
        if decision and str(decision.get("eventId") or "") == str(event_id):
            source_mode = "SNAPSHOT"
            source_snapshot_id = snapshot_id
            return {
                "eventId": event_id,
                "sourceMode": source_mode,
                "sourceSnapshotId": source_snapshot_id,
                "selection": decision.get("selection"),
                "market": decision.get("market"),
                "side": decision.get("side"),
                "point": _to_float(decision.get("point")),
                "price": _to_float(decision.get("price")),
                "recommendation": decision.get("recommendation") or "PASS",
                "qualificationStatus": decision.get("qualificationStatus") or "NOT_QUALIFIED",
                "currentWinProbability": _to_float(decision.get("calibratedProbability")),
                "currentPushProbability": _to_float(decision.get("pushProbability")),
                "currentLossProbability": _to_float(decision.get("lossProbability")),
                "currentEV": _to_float(decision.get("currentEV")),
                "impliedProbability": _american_implied_probability(float(decision.get("price"))) * 100 if _to_float(decision.get("price")) is not None else None,
                "calibratedEdge": _to_float(decision.get("calibratedEdge")),
                "edge": _to_float(decision.get("calibratedEdge")) * 100 if _to_float(decision.get("calibratedEdge")) is not None else None,
                "fairLine": _to_float(decision.get("fairLine")),
                "truePlayableTo": _to_float(decision.get("truePlayableTo")),
                "siScore": _to_float(decision.get("siScore")),
                "confidence": 75.0,
                "dataCompleteness": 100.0,
                "marketIntelligence": {"score": 0.0, "booksMoving": 0, "steamBooks": 0, "consensus": 0.0},
            }

    game_bundle = get_game_best_opportunity(event_id)
    opportunity = game_bundle.get("opportunity") or {}

    if not opportunity:
        raise ValueError("No qualifying opportunity available for this game.")

    return {
        "eventId": event_id,
        "sourceMode": source_mode,
        "sourceSnapshotId": source_snapshot_id,
        "selection": opportunity.get("pick"),
        "market": opportunity.get("market"),
        "side": opportunity.get("side"),
        "point": _to_float(opportunity.get("point")),
        "price": _to_float(opportunity.get("price")),
        "recommendation": opportunity.get("recommendation") or "PASS",
        "qualificationStatus": opportunity.get("qualificationStatus") or "NOT_QUALIFIED",
        "currentWinProbability": _to_float(opportunity.get("currentWinProbability")),
        "currentPushProbability": _to_float(opportunity.get("currentPushProbability")),
        "currentLossProbability": _to_float(opportunity.get("currentLossProbability")),
        "currentEV": _to_float(opportunity.get("currentEV")),
        "impliedProbability": _to_float(opportunity.get("impliedProbability")),
        "calibratedEdge": _to_float(opportunity.get("calibratedEdge")),
        "edge": _to_float(opportunity.get("edge")),
        "fairLine": _to_float(opportunity.get("fairLine")),
        "truePlayableTo": _to_float(opportunity.get("truePlayableTo")),
        "siScore": _to_float((opportunity.get("sportsIntelligenceScore") or {}).get("score")),
        "confidence": _to_float(opportunity.get("confidence")) or 75.0,
        "dataCompleteness": _to_float(opportunity.get("dataCompleteness")) or 100.0,
        "marketIntelligence": opportunity.get("marketIntelligence") or {"score": 0.0, "booksMoving": 0, "steamBooks": 0, "consensus": 0.0},
    }


def _decision_summary(selection: str, inside_playable: Optional[bool], at_boundary: bool, ev_change: Optional[float]) -> str:
    if inside_playable is False:
        return f"PASS - {selection} is beyond SIA's current playable range."

    if inside_playable is True and at_boundary:
        return f"YES - SIA would still play {selection} at the assumed price, and this sits exactly at the current playable boundary."

    if inside_playable is True and ev_change is not None and ev_change <= -0.08:
        return f"CAUTION - {selection} remains playable at the assumed price, but value has deteriorated materially."

    if inside_playable is True:
        return f"YES - SIA would still play {selection} at the assumed price."

    return "I don't have enough verified SIA data to determine playable status for this hypothetical line."


def _decision_status(inside_playable: Optional[bool]) -> str:
    if inside_playable is False:
        return "PASS"
    if inside_playable is True:
        return "PLAYABLE"
    return "UNKNOWN"


def _boundary_status(at_boundary: bool, inside_playable: Optional[bool]) -> str:
    if at_boundary and inside_playable is True:
        return "AT_BOUNDARY"
    if inside_playable is True:
        return "INSIDE"
    if inside_playable is False:
        return "OUTSIDE"
    return "UNKNOWN"


def evaluate_move_the_line(
    *,
    event_id: str,
    hypothetical_spread: float,
    assumed_odds: float,
    snapshot_id: Optional[str] = None,
) -> Dict[str, Any]:
    base = _build_base_context(event_id=event_id, snapshot_id=snapshot_id)

    market = str(base.get("market") or "").lower()
    if market != "spread":
        raise ValueError("Move-the-Line currently supports spread recommendations only.")

    side = str(base.get("side") or "").lower()
    if side not in {"home", "away"}:
        raise ValueError("Unsupported side for spread recommendation.")

    model_margin_home = _load_model_margin_home(event_id)
    if model_margin_home is None:
        raise ValueError("Model spread context is unavailable for this game.")

    original_point = _to_float(base.get("point"))
    if original_point is None:
        raise ValueError("Current recommendation spread is unavailable.")

    base_selection = str(base.get("selection") or "")
    rounded_hypo = _normalize_signed_zero(_round_half(float(hypothetical_spread)))
    rounded_assumed_odds = float(round(float(assumed_odds)))

    probs = spread_outcome_probabilities(
        model_margin_home=model_margin_home,
        side=side,
        spread_point=rounded_hypo,
    )
    if probs.status != "AVAILABLE":
        raise ValueError(probs.reason or "Probability engine unavailable for this line.")

    market_implied_probability = _american_implied_probability(rounded_assumed_odds)
    edge = probs.win - market_implied_probability
    push_aware_ev = ev_per_dollar_with_push(probs.win, probs.push, rounded_assumed_odds)
    fair_price = fair_price_from_win_push(probs.win, probs.push)
    fair_line = -model_margin_home if side == "home" else model_margin_home

    true_playable_to = _to_float(base.get("truePlayableTo"))
    if true_playable_to is None:
        threshold = true_playable_to_spread(
            model_margin_home=model_margin_home,
            side=side,
            start_point=original_point,
            price=rounded_assumed_odds,
            minimum_playable_ev=settings.MIN_PLAYABLE_EV,
        )
        true_playable_to = threshold.playable_to if threshold.status == "AVAILABLE" else None

    inside_playable = _is_inside_spread_playable_range(rounded_hypo, true_playable_to)
    at_boundary = _is_boundary(rounded_hypo, true_playable_to)

    score_payload = calculate_sports_intelligence_score(
        opportunity={
            "edge": round(edge * 100, 1),
            "evPerDollar": round(push_aware_ev, 3),
            "confidence": _to_float(base.get("confidence")) or 75.0,
            "dataCompleteness": _to_float(base.get("dataCompleteness")) or 100.0,
            "injuryContext": {},
        },
        market_intelligence=base.get("marketIntelligence") or {},
    )
    recommendation = _recommendation_label(score_payload)

    if inside_playable is False:
        recommendation = "PASS"

    qualification_status = _qualification_from_recommendation(recommendation)

    original_win = _to_float(base.get("currentWinProbability"))
    original_push = _to_float(base.get("currentPushProbability"))
    original_ev = _to_float(base.get("currentEV"))
    original_edge = _to_float(base.get("calibratedEdge"))

    probability_change = (probs.win - original_win) if original_win is not None else None
    push_change = (probs.push - original_push) if original_push is not None else None
    ev_change = (push_aware_ev - original_ev) if original_ev is not None else None
    edge_change = (edge - original_edge) if original_edge is not None else None

    hypothetical_selection = _selection_for_line(base_selection, rounded_hypo)
    original_selection = _selection_for_line(base_selection, original_point)

    return {
        "eventId": event_id,
        "sourceSnapshotId": base.get("sourceSnapshotId"),
        "contextMode": "SNAPSHOT" if base.get("sourceMode") == "SNAPSHOT" else "LIVE",
        "hypothetical": {
            "selection": hypothetical_selection,
            "hypotheticalSpread": rounded_hypo,
            "assumedOdds": rounded_assumed_odds,
            "lineDisplay": _spread_display(rounded_hypo),
            "priceAssumption": f"{rounded_assumed_odds:+.0f}",
            "isHypothetical": True,
            "priceDisclosure": "Move-the-Line holds the current price constant to isolate the effect of changing the spread. This does not represent a currently available sportsbook quote.",
            "winProbability": round(probs.win, 6),
            "pushProbability": round(probs.push, 6),
            "lossProbability": round(probs.loss, 6),
            "pushAwareEV": round(push_aware_ev, 3),
            "marketImpliedProbability": round(market_implied_probability, 6),
            "edge": round(edge, 6),
            "fairLine": round(fair_line, 2),
            "fairPrice": fair_price,
            "truePlayableTo": round(true_playable_to, 2) if true_playable_to is not None else None,
            "insidePlayableRange": inside_playable,
            "atPlayableBoundary": at_boundary,
            "qualificationStatus": qualification_status,
            "recommendation": recommendation,
            "decisionStatus": _decision_status(inside_playable),
            "boundaryStatus": _boundary_status(at_boundary, inside_playable),
            "status": _decision_status(inside_playable),
            "statusReason": "At SIA's current boundary." if at_boundary else ("Still inside SIA's current playable range." if inside_playable else "Outside SIA's current playable range."),
            "decisionSummary": _decision_summary(hypothetical_selection, inside_playable, at_boundary, ev_change),
        },
        "current": {
            "selection": original_selection,
            "spread": original_point,
            "assumedOdds": rounded_assumed_odds,
            "recommendation": str(base.get("recommendation") or "PASS").upper(),
            "qualificationStatus": base.get("qualificationStatus"),
            "winProbability": original_win,
            "pushProbability": original_push,
            "lossProbability": _to_float(base.get("currentLossProbability")),
            "pushAwareEV": original_ev,
            "marketImpliedProbability": round(_american_implied_probability(rounded_assumed_odds), 6),
            "edge": original_edge,
            "fairLine": _to_float(base.get("fairLine")),
            "truePlayableTo": true_playable_to,
        },
        "valueChange": {
            "probabilityChange": round(probability_change, 6) if probability_change is not None else None,
            "pushProbabilityChange": round(push_change, 6) if push_change is not None else None,
            "evChange": round(ev_change, 3) if ev_change is not None else None,
            "edgeChange": round(edge_change, 6) if edge_change is not None else None,
        },
    }
