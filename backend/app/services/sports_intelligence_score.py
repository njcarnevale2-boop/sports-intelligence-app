def clamp(value, minimum=0.0, maximum=100.0):
    return max(minimum, min(maximum, value))


def normalize_edge(edge_percent):
    """
    Converts model edge into a 0-100 component score.

    Rough interpretation:
    0% edge   -> 0
    5% edge   -> 25
    10% edge  -> 50
    15% edge  -> 75
    20%+ edge -> 100
    """

    edge = max(float(edge_percent or 0), 0)

    return clamp(
        (edge / 20.0) * 100
    )


def normalize_ev(ev_per_dollar):
    """
    Converts expected value per $1 wagered
    into a 0-100 component score.

    $0.00 EV -> 0
    $0.10 EV -> 20
    $0.25 EV -> 50
    $0.50+ EV -> 100
    """

    ev = max(float(ev_per_dollar or 0), 0)

    return clamp(
        (ev / 0.50) * 100
    )


def normalize_confidence(confidence):
    """
    Confidence is already represented
    on approximately a 0-100 scale.
    """

    return clamp(
        float(confidence or 0)
    )


def normalize_market_score(market_score):
    """
    Market Intelligence currently uses
    a 0-10 scale.

    Convert it to 0-100.
    """

    return clamp(
        float(market_score or 0) * 10
    )


def normalize_data_completeness(data_completeness):
    """
    Data completeness is already 0-100.
    """

    return clamp(
        float(data_completeness or 0)
    )


def score_to_grade(score):
    if score >= 92:
        return "A+"

    if score >= 88:
        return "A"

    if score >= 84:
        return "A-"

    if score >= 80:
        return "B+"

    if score >= 75:
        return "B"

    if score >= 70:
        return "B-"

    if score >= 65:
        return "C+"

    if score >= 60:
        return "C"

    if score >= 55:
        return "C-"

    if score >= 50:
        return "D"

    return "F"


def score_to_stars(score):
    if score >= 90:
        return 5

    if score >= 80:
        return 4

    if score >= 70:
        return 3

    if score >= 60:
        return 2

    return 1


def score_to_recommendation(score):
    if score >= 90:
        return "Elite Bet"

    if score >= 80:
        return "Strong Bet"

    if score >= 70:
        return "Bet"

    if score >= 60:
        return "Lean"

    return "Pass"


def normalize_injury_context(injury_context):
    """
    Convert matchup injury context into a 0-100 component score.

    Healthy advantage -> 100
    Small disadvantage -> 80
    Moderate disadvantage -> 60
    Significant disadvantage -> 35
    Major disadvantage -> 10
    """

    if not injury_context:
        return 100.0

    severity = str(injury_context.get("severity", "Neutral")).lower()

    if severity == "neutral":
        return 100.0
    if severity == "small":
        return 80.0
    if severity == "moderate":
        return 60.0
    if severity == "significant":
        return 35.0
    if severity == "major":
        return 10.0

    return 100.0


def build_reasons(
    edge,
    ev,
    confidence,
    market_intelligence,
    data_completeness,
    injury_context,
):
    reasons = []

    market_score = float(
        market_intelligence.get(
            "score",
            0,
        )
    )

    consensus = float(
        market_intelligence.get(
            "consensus",
            0,
        )
    )

    books_moving = int(
        market_intelligence.get(
            "booksMoving",
            0,
        )
    )

    steam_books = int(
        market_intelligence.get(
            "steamBooks",
            0,
        )
    )

    if edge >= 20:
        reasons.append(
            "Exceptional model edge versus the current market."
        )
    elif edge >= 12:
        reasons.append(
            "Strong model edge versus the current market."
        )
    elif edge >= 7:
        reasons.append(
            "Positive model edge is present."
        )
    elif edge < 3:
        reasons.append(
            "Model edge is limited."
        )

    if ev >= 0.40:
        reasons.append(
            "Expected value is exceptionally strong."
        )
    elif ev >= 0.20:
        reasons.append(
            "Expected value is strongly positive."
        )
    elif ev >= 0.08:
        reasons.append(
            "Expected value is positive."
        )
    elif ev <= 0:
        reasons.append(
            "Expected value does not support the position."
        )

    if confidence >= 85:
        reasons.append(
            "Model confidence is high."
        )
    elif confidence >= 70:
        reasons.append(
            "Model confidence is solid."
        )
    elif confidence < 55:
        reasons.append(
            "Model confidence is limited."
        )

    if market_score >= 8:
        reasons.append(
            "Sportsbook movement strongly confirms the model."
        )
    elif market_score >= 6:
        reasons.append(
            "Sportsbook movement provides market confirmation."
        )
    elif market_score <= 3:
        reasons.append(
            "The market has not yet confirmed the model signal."
        )

    if steam_books >= 3:
        reasons.append(
            f"Steam movement has appeared at {steam_books} sportsbooks."
        )
    elif steam_books > 0:
        reasons.append(
            f"Steam movement has appeared at {steam_books} sportsbook."
        )

    if books_moving >= 5:
        reasons.append(
            f"{books_moving} sportsbooks are showing meaningful movement."
        )

    if consensus >= 75:
        reasons.append(
            f"Observed market movement shows {consensus:.0f}% directional agreement."
        )

    if data_completeness >= 85:
        reasons.append(
            "Underlying data coverage is strong."
        )
    elif data_completeness < 60:
        reasons.append(
            "Data coverage is incomplete, reducing conviction."
        )

    if injury_context:
        severity = str(injury_context.get("severity", "Neutral")).lower()
        if severity == "neutral":
            reasons.append(
                "Injury context is neutral and does not materially change the play."
            )
        elif severity == "small":
            reasons.append(
                "Injury context slightly weakens the recommendation."
            )
        elif severity == "moderate":
            reasons.append(
                "Injury context materially affects the recommendation."
            )
        elif severity == "significant":
            reasons.append(
                "Injury context is a meaningful headwind for the recommendation."
            )
        elif severity == "major":
            reasons.append(
                "Injury context is a major concern and meaningfully cuts into conviction."
            )

    if not reasons:
        reasons.append(
            "The current signals do not show a major strength or weakness."
        )

    return reasons[:5]


def calculate_sports_intelligence_score(
    opportunity,
    market_intelligence,
):
    """
    Sports Intelligence Score

    Weighting:
    Model Edge           30%
    Expected Value       20%
    Confidence           20%
    Market Intelligence  20%
    Data Completeness    10%
    """

    edge = float(
        opportunity.get(
            "edge",
            0,
        )
    )

    ev = float(
        opportunity.get(
            "evPerDollar",
            0,
        )
    )

    confidence = float(
        opportunity.get(
            "confidence",
            0,
        )
    )

    data_completeness = float(
        opportunity.get(
            "dataCompleteness",
            0,
        )
    )

    market_score = float(
        market_intelligence.get(
            "score",
            0,
        )
    )

    injury_context = opportunity.get("injuryContext") or opportunity.get("injury_context")

    edge_component = normalize_edge(
        edge
    )

    ev_component = normalize_ev(
        ev
    )

    confidence_component = (
        normalize_confidence(
            confidence
        )
    )

    market_component = (
        normalize_market_score(
            market_score
        )
    )

    data_component = (
        normalize_data_completeness(
            data_completeness
        )
    )
    injury_component = normalize_injury_context(
        injury_context
    )

    weighted_score = (
        edge_component * 0.30
        + ev_component * 0.20
        + confidence_component * 0.15
        + market_component * 0.15
        + data_component * 0.10
        + injury_component * 0.10
    )

    final_score = round(
        clamp(weighted_score),
        1,
    )

    return {
        "score": final_score,
        "grade": score_to_grade(
            final_score
        ),
        "stars": score_to_stars(
            final_score
        ),
        "recommendation": (
            score_to_recommendation(
                final_score
            )
        ),
        "components": {
            "modelEdge": round(
                edge_component,
                1,
            ),
            "expectedValue": round(
                ev_component,
                1,
            ),
            "confidence": round(
                confidence_component,
                1,
            ),
            "marketIntelligence": round(
                market_component,
                1,
            ),
            "dataCompleteness": round(
                data_component,
                1,
            ),
            "injuryContext": round(
                injury_component,
                1,
            ),
        },
        "weights": {
            "modelEdge": 30,
            "expectedValue": 20,
            "confidence": 15,
            "marketIntelligence": 15,
            "dataCompleteness": 10,
            "injuryContext": 10,
        },
        "reasons": build_reasons(
            edge=edge,
            ev=ev,
            confidence=confidence,
            market_intelligence=market_intelligence,
            data_completeness=data_completeness,
            injury_context=injury_context,
        ),
    }