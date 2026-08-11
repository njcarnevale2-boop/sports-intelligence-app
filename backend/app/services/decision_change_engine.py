from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_decision_timeline(opportunity: Dict[str, Any], history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Build a deterministic decision timeline from an opportunity and optional history.

    The engine does not fabricate history. When no history is supplied, it returns
    an empty timeline with a clear placeholder summary so the UI can render an
    empty state without guessing.
    """

    if history is None:
        history = []

    timeline = []
    score_history: List[Dict[str, Any]] = []
    recommendation_changed = False
    biggest_change: Optional[Dict[str, Any]] = None

    for event in history:
        timestamp = str(event.get("timestamp") or "")
        category = str(event.get("category") or "Change")
        old_value = event.get("oldValue")
        new_value = event.get("newValue")
        impact = str(event.get("impact") or "neutral")
        reason = str(event.get("reason") or "")

        if category.lower().startswith("sports intelligence"):
            score_history.append({"timestamp": timestamp, "score": new_value})

        if category.lower() == "recommendation":
            recommendation_changed = True

        change_entry = {
            "timestamp": timestamp,
            "category": category,
            "oldValue": old_value,
            "newValue": new_value,
            "impact": impact,
            "reason": reason,
        }
        timeline.append(change_entry)

        if biggest_change is None or _change_weight(change_entry) > _change_weight(biggest_change):
            biggest_change = change_entry

    if not timeline:
        latest_summary = "No meaningful changes have occurred yet."
    else:
        latest = timeline[-1]
        latest_summary = f"Latest change: {latest['category']} at {latest['timestamp']}"

    return {
        "timeline": sorted(timeline, key=lambda item: str(item.get("timestamp", ""))),
        "latestSummary": latest_summary,
        "biggestChange": biggest_change,
        "recommendationChanged": recommendation_changed,
        "scoreHistory": score_history,
        "changeCount": len(timeline),
    }


def _change_weight(change: Dict[str, Any]) -> int:
    impact = str(change.get("impact") or "neutral").lower()
    if impact == "negative":
        return 2
    if impact == "positive":
        return 3
    return 1
