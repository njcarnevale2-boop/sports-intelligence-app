from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["schedule-context"])

MODEL_ROOT = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9"

SCHEDULE_CONTEXT = (
    MODEL_ROOT / "outputs" / "schedule_context_latest.csv"
)

RANKED_BET_BOARD = (
    MODEL_ROOT / "outputs" / "ranked_bet_board.csv"
)

GAME_PROJECTIONS = (
    MODEL_ROOT / "outputs" / "current_game_projections.csv"
)


def get_event_matchup(event_id: str):
    # Use game_projections.csv (all 272 games) so context works even without a ranked opportunity
    if GAME_PROJECTIONS.exists():
        try:
            df = pd.read_csv(GAME_PROJECTIONS)
            df["api_event_id"] = df["api_event_id"].astype(str)
            match = df[df["api_event_id"] == event_id]
            if not match.empty:
                row = match.iloc[0]
                return {
                    "eventId": event_id,
                    "gameday": str(row["commence_time"])[:10],
                    "awayTeam": str(row["away_team"]),
                    "homeTeam": str(row["home_team"]),
                }
        except Exception:
            pass

    # Fallback: ranked_bet_board (opportunities only)
    if RANKED_BET_BOARD.exists():
        df = pd.read_csv(RANKED_BET_BOARD)
        match = df[df["api_event_id"] == event_id]
        if not match.empty:
            row = match.iloc[0]
            return {
                "eventId": event_id,
                "gameday": str(row["commence_time"])[:10],
                "awayTeam": str(row["away_team"]),
                "homeTeam": str(row["home_team"]),
            }

    raise HTTPException(
        status_code=404,
        detail="Game not found",
    )


def safe_float(value):
    if pd.isna(value):
        return None

    return float(value)


def safe_int(value):
    if pd.isna(value):
        return None

    return int(value)


@router.get("/games/{event_id}/context")
def get_game_context(event_id: str):
    event = get_event_matchup(event_id)

    df = pd.read_csv(SCHEDULE_CONTEXT)

    match = df[
        (df["gameday"].astype(str) == event["gameday"])
        & (df["away_team"].astype(str) == event["awayTeam"])
        & (df["home_team"].astype(str) == event["homeTeam"])
    ]

    if match.empty:
        raise HTTPException(
            status_code=404,
            detail="Schedule context not found for this game",
        )

    row = match.iloc[0]

    home_rest_days = safe_float(row["home_rest_days"])
    away_rest_days = safe_float(row["away_rest_days"])

    is_week_one = int(row["week"]) == 1

    if is_week_one:
        rest_label = "Offseason / neutral rest"
    elif home_rest_days is None or away_rest_days is None:
        rest_label = "Rest data unavailable"
    elif home_rest_days > away_rest_days:
        rest_label = f'{event["homeTeam"]} rest advantage'
    elif away_rest_days > home_rest_days:
        rest_label = f'{event["awayTeam"]} rest advantage'
    else:
        rest_label = "Neutral rest"

    travel_miles = safe_float(
        row["away_travel_miles_proxy"]
    )

    timezone_shift = safe_float(
        row["away_timezone_shift_hours_proxy"]
    )

    short_rest_home = safe_int(
        row["short_rest_home"]
    )

    short_rest_away = safe_int(
        row["short_rest_away"]
    )

    long_rest_home = safe_int(
        row["long_rest_home"]
    )

    long_rest_away = safe_int(
        row["long_rest_away"]
    )

    return {
        "eventId": event_id,
        "gameId": str(row["game_id"]),
        "season": int(row["season"]),
        "week": int(row["week"]),
        "gameday": str(row["gameday"]),
        "matchup": (
            f'{event["awayTeam"]} @ {event["homeTeam"]}'
        ),
        "awayTeam": event["awayTeam"],
        "homeTeam": event["homeTeam"],

        "rest": {
            "homeDays": home_rest_days,
            "awayDays": away_rest_days,
            "advantageHomeDays": safe_float(
                row["rest_advantage_home"]
            ),
            "label": rest_label,
            "weekOneNeutralized": is_week_one,
            "shortRestHome": bool(short_rest_home),
            "shortRestAway": bool(short_rest_away),
            "longRestHome": bool(long_rest_home),
            "longRestAway": bool(long_rest_away),
        },

        "travel": {
            "awayMiles": (
                round(travel_miles, 1)
                if travel_miles is not None
                else None
            ),
            "awayTimezoneShiftHours": (
                round(timezone_shift, 1)
                if timezone_shift is not None
                else None
            ),
        },

        "source": str(SCHEDULE_CONTEXT),
    }