from pathlib import Path

import pandas as pd
from fastapi import APIRouter

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])

MODEL_ROOT = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9"
RANKED_BET_BOARD = MODEL_ROOT / "outputs" / "ranked_bet_board.csv"


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


@router.get("")
def get_opportunities(limit: int = 10):
    df = pd.read_csv(RANKED_BET_BOARD)

    df = df.sort_values("rank").head(limit)

    opportunities = []

    for _, row in df.iterrows():
        opportunities.append(
            {
                "id": f'{row["api_event_id"]}-{int(row["rank"])}',
                "eventId": row["api_event_id"],
                "commenceTime": row["commence_time"],
                "matchup": f'{row["away_team"]} @ {row["home_team"]}',
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
                "rank": int(row["rank"]),
            }
        )

    return {
        "count": len(opportunities),
        "source": str(RANKED_BET_BOARD),
        "opportunities": opportunities,
    }