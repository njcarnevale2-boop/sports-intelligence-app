from __future__ import annotations

from dataclasses import dataclass

from app.services import decision_profile


@dataclass
class FakeProbs:
    win: float
    push: float
    loss: float
    status: str = "AVAILABLE"
    reason: str | None = None


def test_recommended_boundary_separate_from_mathematical_boundary(monkeypatch):
    def fake_probs(model_margin_home, side, spread_point):
        table = {
            7.0: FakeProbs(win=0.77, push=0.02, loss=0.21),
            6.5: FakeProbs(win=0.76, push=0.02, loss=0.22),
            6.0: FakeProbs(win=0.75, push=0.02, loss=0.23),
            5.5: FakeProbs(win=0.74, push=0.02, loss=0.24),
            5.0: FakeProbs(win=0.73, push=0.02, loss=0.25),
            4.5: FakeProbs(win=0.72, push=0.02, loss=0.26),
            4.0: FakeProbs(win=0.71, push=0.02, loss=0.27),
            3.5: FakeProbs(win=0.70, push=0.02, loss=0.28),
            3.0: FakeProbs(win=0.69, push=0.02, loss=0.29),
            2.5: FakeProbs(win=0.67, push=0.02, loss=0.31),
            2.0: FakeProbs(win=0.65, push=0.02, loss=0.33),
            1.5: FakeProbs(win=0.64, push=0.02, loss=0.34),
            1.0: FakeProbs(win=0.62, push=0.03, loss=0.35),
            0.5: FakeProbs(win=0.61, push=0.03, loss=0.36),
            0.0: FakeProbs(win=0.59, push=0.04, loss=0.37),
            -0.5: FakeProbs(win=0.56, push=0.04, loss=0.40),
            -1.0: FakeProbs(win=0.54, push=0.05, loss=0.41),
            -1.5: FakeProbs(win=0.52, push=0.04, loss=0.44),
            -2.0: FakeProbs(win=0.51, push=0.03, loss=0.46),
            -2.5: FakeProbs(win=0.49, push=0.03, loss=0.48),
        }
        return table[float(spread_point)]

    def fake_score(opportunity, market_intelligence):
        ev = float(opportunity.get("evPerDollar") or 0.0)
        if ev >= 0.45:
            return {"recommendation": "STRONG BET"}
        if ev >= 0.30:
            return {"recommendation": "BET"}
        if ev >= 0.20:
            return {"recommendation": "LEAN"}
        return {"recommendation": "PASS"}

    monkeypatch.setattr(decision_profile, "spread_outcome_probabilities", fake_probs)
    monkeypatch.setattr(decision_profile, "calculate_sports_intelligence_score", fake_score)

    result = decision_profile.build_spread_decision_boundaries(
        model_margin_home=-3.2,
        side="away",
        current_point=7.0,
        price=-105.0,
        true_playable_to=-2.0,
        confidence=86.0,
        data_completeness=97.0,
        market_intelligence={"score": 2.0},
    )

    assert result.recommended_playable_to == 2.5
    assert result.recommended_playable_to_status == "AVAILABLE"
    labels = [stage["label"] for stage in result.stages]
    assert "Current line" in labels
    assert "Theoretical model boundary" in labels
    assert "Lean starts" in labels
    assert "Pass starts" in labels
    assert "Theoretical EV boundary" in labels


def test_unavailable_context_returns_unavailable_status():
    result = decision_profile.build_spread_decision_boundaries(
        model_margin_home=None,
        side="away",
        current_point=7.0,
        price=-105.0,
        true_playable_to=-2.0,
        confidence=86.0,
        data_completeness=97.0,
        market_intelligence={"score": 2.0},
    )

    assert result.recommended_playable_to is None
    assert result.recommended_playable_to_status == "UNAVAILABLE"
    assert result.stages == []
