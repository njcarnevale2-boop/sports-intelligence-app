import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.decision_change_engine import build_decision_timeline


def test_build_decision_timeline_returns_empty_payload_when_no_history_exists():
    result = build_decision_timeline({"id": "abc123"})

    assert result["timeline"] == []
    assert result["changeCount"] == 0
    assert result["recommendationChanged"] is False
    assert result["scoreHistory"] == []
    assert "No meaningful changes" in result["latestSummary"]


def test_build_decision_timeline_uses_provided_history():
    history = [
        {
            "timestamp": "09:10",
            "category": "Sports Intelligence Score",
            "oldValue": 81,
            "newValue": 84,
            "impact": "positive",
            "reason": "Model edge strengthened",
        },
        {
            "timestamp": "09:25",
            "category": "Injury",
            "oldValue": "No concern",
            "newValue": "Josh Allen downgraded",
            "impact": "negative",
            "reason": "Quarterback status changed",
        },
    ]

    result = build_decision_timeline({"id": "abc123"}, history=history)

    assert result["changeCount"] == 2
    assert result["timeline"][0]["category"] == "Sports Intelligence Score"
    assert result["timeline"][1]["category"] == "Injury"
    assert result["scoreHistory"][0]["score"] == 84
    assert result["recommendationChanged"] is False
