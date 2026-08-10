from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["sports-intelligence"])

MODEL_ROOT = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9"

RANKED_BET_BOARD = MODEL_ROOT / "outputs" / "ranked_bet_board.csv"
PORTFOLIO_RECOMMENDATIONS = (
    MODEL_ROOT / "outputs" / "portfolio_recommendations.csv"
)


def format_pick(row):
    away_team = str(row["away_team"])
    home_team = str(row["home_team"])
    side = str(row["side"])
    market = str(row["market"])
    point = float(row["point"])

    if market == "spread":
        team = home_team if side == "home" else away_team
        point_text = f"+{point:g}" if point > 0 else f"{point:g}"
        return f"{team} {point_text}"

    if market == "total":
        return f"{side.title()} {point:g}"

    return f"{side.title()} {point:g}"


def row_to_opportunity(row):
    return {
        "id": f'{row["api_event_id"]}-{int(row["rank"])}',
        "eventId": row["api_event_id"],
        "commenceTime": row["commence_time"],
        "matchup": f'{row["away_team"]} @ {row["home_team"]}',
        "awayTeam": row["away_team"],
        "homeTeam": row["home_team"],
        "pick": format_pick(row),
        "book": row["sportsbook"],
        "market": row["market"],
        "side": row["side"],
        "point": float(row["point"]),
        "price": float(row["price"]),
        "modelProbability": round(float(row["model_prob"]) * 100, 1),
        "impliedProbability": round(
            float(row["implied_prob_raw"]) * 100,
            1,
        ),
        "fairOdds": round(float(row["fair_odds"])),
        "edge": round(float(row["edge_pp"]) * 100, 1),
        "evPerDollar": round(float(row["ev_per_dollar"]), 3),
        "kellyFull": round(float(row["kelly_full"]), 3),
        "kelly20": round(float(row["kelly_20pct"]), 3),
        "recommendation": row["recommendation"],
        "confidence": int(round(float(row["confidence_score"]))),
        "dataCompleteness": round(float(row["data_completeness"]) * 100, 1),
        "marketConfidence": round(float(row["market_confidence"]) * 100, 1),
        "modelConfidence": round(float(row["model_confidence"]) * 100, 1),
        "rank": int(row["rank"]),
    }


@router.get("/opportunities")
def get_opportunities(limit: int = 10):
    df = pd.read_csv(RANKED_BET_BOARD)

    df = df.sort_values("rank").head(limit)

    opportunities = [
        row_to_opportunity(row)
        for _, row in df.iterrows()
    ]

    return {
        "count": len(opportunities),
        "source": str(RANKED_BET_BOARD),
        "opportunities": opportunities,
    }


@router.get("/opportunities/{opportunity_id}")
def get_opportunity(opportunity_id: str):
    df = pd.read_csv(RANKED_BET_BOARD)

    df["generated_id"] = df.apply(
        lambda row: f'{row["api_event_id"]}-{int(row["rank"])}',
        axis=1,
    )

    match = df[df["generated_id"] == opportunity_id]

    if match.empty:
        raise HTTPException(
            status_code=404,
            detail="Opportunity not found",
        )

    row = match.iloc[0]

    return row_to_opportunity(row)


@router.get("/portfolio")
def get_portfolio():
    df = pd.read_csv(PORTFOLIO_RECOMMENDATIONS)

    portfolio = []

    for index, row in df.iterrows():
        portfolio.append(
            {
                "id": f'{row["api_event_id"]}-portfolio-{index + 1}',
                "eventId": row["api_event_id"],
                "commenceTime": row["commence_time"],
                "matchup": f'{row["away_team"]} @ {row["home_team"]}',
                "awayTeam": row["away_team"],
                "homeTeam": row["home_team"],
                "pick": format_pick(row),
                "book": row["sportsbook"],
                "market": row["market"],
                "side": row["side"],
                "point": float(row["point"]),
                "price": float(row["price"]),
                "modelProbability": round(
                    float(row["model_prob"]) * 100,
                    1,
                ),
                "impliedProbability": round(
                    float(row["implied_prob_raw"]) * 100,
                    1,
                ),
                "fairOdds": round(float(row["fair_odds"])),
                "edge": round(float(row["edge_pp"]) * 100, 1),
                "evPerDollar": round(
                    float(row["ev_per_dollar"]),
                    3,
                ),
                "kellyFull": round(
                    float(row["kelly_full"]),
                    3,
                ),
                "kelly20": round(
                    float(row["kelly_20pct"]),
                    3,
                ),
                "recommendation": row["recommendation"],
                "rawUnits": float(row["raw_units"]),
                "recommendedUnits": float(
                    row["recommended_units"]
                ),
            }
        )

    total_units = sum(
        item["recommendedUnits"]
        for item in portfolio
    )

    average_edge = (
        sum(item["edge"] for item in portfolio)
        / len(portfolio)
        if portfolio
        else 0
    )

    average_model_probability = (
        sum(
            item["modelProbability"]
            for item in portfolio
        )
        / len(portfolio)
        if portfolio
        else 0
    )

    expected_value_units = sum(
        item["recommendedUnits"] * item["evPerDollar"]
        for item in portfolio
    )

    return {
        "count": len(portfolio),
        "source": str(PORTFOLIO_RECOMMENDATIONS),
        "summary": {
            "totalRecommendedUnits": round(total_units, 2),
            "averageEdge": round(average_edge, 1),
            "averageModelProbability": round(
                average_model_probability,
                1,
            ),
            "expectedValueUnits": round(
                expected_value_units,
                3,
            ),
        },
        "portfolio": portfolio,
    }