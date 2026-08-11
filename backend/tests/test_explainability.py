import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.explainability import generate_explainability


def test_generate_explainability_returns_expected_sections():
    opportunity = {
        "edge": 8.4,
        "evPerDollar": 0.24,
        "confidence": 82,
        "marketIntelligence": {"score": 74, "signal": "confirming", "booksMoving": 2, "consensus": 68},
        "injuryContext": {"severity": "neutral", "summary": "No major injury concerns"},
        "weatherContext": {"impactScore": 61, "summary": "Mild wind support"},
        "sportsIntelligenceScore": {
            "score": 86.2,
            "grade": "A",
            "recommendation": "STRONG BET",
            "components": {
                "modelEdge": 82,
                "expectedValue": 74,
                "confidence": 88,
                "marketIntelligence": 72,
                "dataCompleteness": 79,
                "injuryContext": 73,
            },
        },
        "executiveAnalysis": {"summary": "Good setup"},
    }

    explanation = generate_explainability(opportunity)

    assert explanation["overallSummary"]
    assert explanation["strengths"]
    assert explanation["weaknesses"]
    assert explanation["confidenceExplanation"]
    assert explanation["marketExplanation"]
    assert explanation["injuryExplanation"]
    assert explanation["weatherExplanation"]
    assert explanation["keyReasons"]
    assert explanation["whatCouldImprove"]
    assert explanation["riskFactors"]
