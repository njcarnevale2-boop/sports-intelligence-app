from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from app.services.market_intelligence import (
    get_market_intelligence,
)

from app.services.sports_intelligence_score import (
    calculate_sports_intelligence_score,
)
from app.services.injury_matchup import InjuryMatchupContext


router = APIRouter(
    prefix="/api",
    tags=["sports-intelligence"],
)


MODEL_ROOT = (
    Path.home()
    / "Downloads"
    / "NFL_Analytics_OS_v1_9"
)


RANKED_BET_BOARD = (
    MODEL_ROOT
    / "outputs"
    / "ranked_bet_board.csv"
)


PORTFOLIO_RECOMMENDATIONS = (
    MODEL_ROOT
    / "outputs"
    / "portfolio_recommendations.csv"
)


GAME_PROJECTIONS = (
    MODEL_ROOT
    / "outputs"
    / "current_game_projections.csv"
)


LINE_MOVEMENT_BOARD = (
    MODEL_ROOT
    / "outputs"
    / "line_movement_board.csv"
)


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------


def safe_float(value):
    if pd.isna(value):
        return None

    return float(value)


def safe_int(value):
    if pd.isna(value):
        return None

    return int(value)


def format_pick(row):
    away_team = str(
        row["away_team"]
    )

    home_team = str(
        row["home_team"]
    )

    side = str(
        row["side"]
    )

    market = str(
        row["market"]
    )

    point = float(
        row["point"]
    )

    if market == "spread":
        team = (
            home_team
            if side == "home"
            else away_team
        )

        point_text = (
            f"+{point:g}"
            if point > 0
            else f"{point:g}"
        )

        return f"{team} {point_text}"

    if market == "total":
        return (
            f"{side.title()} {point:g}"
        )

    return (
        f"{side.title()} {point:g}"
    )


def build_id(
    row,
    suffix=None,
):
    base = (
        f'{row["api_event_id"]}-'
        f'{row["market"]}-'
        f'{row["side"]}'
    )

    if suffix:
        return (
            f"{base}-{suffix}"
        )

    return base


# ---------------------------------------------------------
# OPPORTUNITY NORMALIZATION
# ---------------------------------------------------------


def row_to_opportunity(
    row,
    include_alternates=None,
):
    result = {
        "id": build_id(row),

        "eventId": (
            row["api_event_id"]
        ),

        "commenceTime": (
            row["commence_time"]
        ),

        "matchup": (
            f'{row["away_team"]} @ '
            f'{row["home_team"]}'
        ),

        "awayTeam": (
            row["away_team"]
        ),

        "homeTeam": (
            row["home_team"]
        ),

        "pick": format_pick(row),

        "book": (
            row["sportsbook"]
        ),

        "market": (
            row["market"]
        ),

        "side": (
            row["side"]
        ),

        "point": float(
            row["point"]
        ),

        "price": float(
            row["price"]
        ),

        "modelProbability": round(
            float(
                row["model_prob"]
            )
            * 100,
            1,
        ),

        "impliedProbability": round(
            float(
                row["implied_prob_raw"]
            )
            * 100,
            1,
        ),

        "fairOdds": round(
            float(
                row["fair_odds"]
            )
        ),

        "edge": round(
            float(
                row["edge_pp"]
            )
            * 100,
            1,
        ),

        "evPerDollar": round(
            float(
                row["ev_per_dollar"]
            ),
            3,
        ),

        "kellyFull": round(
            float(
                row["kelly_full"]
            ),
            3,
        ),

        "kelly20": round(
            float(
                row["kelly_20pct"]
            ),
            3,
        ),

        "recommendation": (
            row["recommendation"]
        ),

        "confidence": int(
            round(
                float(
                    row[
                        "confidence_score"
                    ]
                )
            )
        ),

        "dataCompleteness": round(
            float(
                row[
                    "data_completeness"
                ]
            )
            * 100,
            1,
        ),

        "marketConfidence": round(
            float(
                row[
                    "market_confidence"
                ]
            )
            * 100,
            1,
        ),

        "modelConfidence": round(
            float(
                row[
                    "model_confidence"
                ]
            )
            * 100,
            1,
        ),

        "rank": int(
            row["rank"]
        ),
    }

    # -----------------------------------------------------
    # MARKET INTELLIGENCE
    # -----------------------------------------------------

    market_intelligence = (
        get_market_intelligence(
            event_id=(
                row["api_event_id"]
            ),
            market=row["market"],
            side=row["side"],
        )
    )

    result[
        "marketIntelligence"
    ] = market_intelligence

    # -----------------------------------------------------
    # INJURY MATCHUP CONTEXT
    # -----------------------------------------------------

    injury_context = (
        InjuryMatchupContext().build_context(
            away_team=str(
                row["away_team"]
            ),
            home_team=str(
                row["home_team"]
            ),
        )
    )
    result["injuryContext"] = injury_context

    # -----------------------------------------------------
    # SPORTS INTELLIGENCE SCORE
    # -----------------------------------------------------

    result[
        "sportsIntelligenceScore"
    ] = (
        calculate_sports_intelligence_score(
            opportunity=result,
            market_intelligence=(
                market_intelligence
            ),
        )
    )

    if (
        include_alternates
        is not None
    ):
        result[
            "alternateBooks"
        ] = include_alternates

    return result


# ---------------------------------------------------------
# BEST LINE LOGIC
# ---------------------------------------------------------


def best_line_for_group(
    group,
):
    market = str(
        group.iloc[0][
            "market"
        ]
    )

    side = str(
        group.iloc[0][
            "side"
        ]
    )

    if market == "spread":
        best_point = (
            group[
                "point"
            ].max()
        )

        candidates = group[
            group[
                "point"
            ]
            == best_point
        ]

        best_price = (
            candidates[
                "price"
            ].max()
        )

        return candidates[
            candidates[
                "price"
            ]
            == best_price
        ].iloc[0]

    if market == "total":

        if (
            side.lower()
            == "over"
        ):
            best_point = (
                group[
                    "point"
                ].min()
            )

            candidates = group[
                group[
                    "point"
                ]
                == best_point
            ]

            best_price = (
                candidates[
                    "price"
                ].max()
            )

            return candidates[
                candidates[
                    "price"
                ]
                == best_price
            ].iloc[0]

        if (
            side.lower()
            == "under"
        ):
            best_point = (
                group[
                    "point"
                ].max()
            )

            candidates = group[
                group[
                    "point"
                ]
                == best_point
            ]

            best_price = (
                candidates[
                    "price"
                ].max()
            )

            return candidates[
                candidates[
                    "price"
                ]
                == best_price
            ].iloc[0]

    return group.sort_values(
        [
            "ev_per_dollar",
            "edge_pp",
            "price",
        ],
        ascending=[
            False,
            False,
            False,
        ],
    ).iloc[0]


# ---------------------------------------------------------
# ALTERNATE SPORTSBOOKS
# ---------------------------------------------------------


def make_alternate_books(
    group,
    selected_row,
):
    alternates = []

    for _, row in (
        group.iterrows()
    ):
        if (
            str(
                row[
                    "sportsbook"
                ]
            )
            == str(
                selected_row[
                    "sportsbook"
                ]
            )
            and float(
                row["point"]
            )
            == float(
                selected_row[
                    "point"
                ]
            )
            and float(
                row["price"]
            )
            == float(
                selected_row[
                    "price"
                ]
            )
        ):
            continue

        alternates.append(
            {
                "book": (
                    row[
                        "sportsbook"
                    ]
                ),

                "point": float(
                    row["point"]
                ),

                "price": float(
                    row["price"]
                ),

                "edge": round(
                    float(
                        row[
                            "edge_pp"
                        ]
                    )
                    * 100,
                    1,
                ),

                "evPerDollar": round(
                    float(
                        row[
                            "ev_per_dollar"
                        ]
                    ),
                    3,
                ),
            }
        )

    alternates.sort(
        key=lambda item: (
            item["point"],
            item["price"],
            item[
                "evPerDollar"
            ],
        ),
        reverse=True,
    )

    return alternates[:5]


# ---------------------------------------------------------
# OPPORTUNITIES
# ---------------------------------------------------------


@router.get(
    "/opportunities"
)
def get_opportunities(
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
    best_lines_only: bool = True,
):
    if (
        not RANKED_BET_BOARD.exists()
    ):
        raise HTTPException(
            status_code=500,
            detail=(
                "Ranked bet board "
                "not found"
            ),
        )

    df = pd.read_csv(
        RANKED_BET_BOARD
    )

    if not best_lines_only:
        df = (
            df
            .sort_values(
                "rank"
            )
            .head(limit)
        )

        opportunities = [
            row_to_opportunity(
                row
            )
            for _, row
            in df.iterrows()
        ]

        return {
            "count": len(
                opportunities
            ),

            "source": str(
                RANKED_BET_BOARD
            ),

            "bestLinesOnly": (
                False
            ),

            "opportunities": (
                opportunities
            ),
        }

    grouped = df.groupby(
        [
            "api_event_id",
            "market",
            "side",
        ],
        dropna=False,
        sort=False,
    )

    best_rows = []

    for _, group in grouped:
        selected = (
            best_line_for_group(
                group
            )
        )

        alternates = (
            make_alternate_books(
                group,
                selected,
            )
        )

        item = (
            row_to_opportunity(
                selected,
                include_alternates=(
                    alternates
                ),
            )
        )

        best_rows.append(
            item
        )

    best_rows.sort(
        key=lambda item: (
            item["rank"],
            -item["edge"],
            -item[
                "evPerDollar"
            ],
        )
    )

    opportunities = (
        best_rows[:limit]
    )

    return {
        "count": len(
            opportunities
        ),

        "source": str(
            RANKED_BET_BOARD
        ),

        "bestLinesOnly": True,

        "opportunities": (
            opportunities
        ),
    }


# ---------------------------------------------------------
# INDIVIDUAL OPPORTUNITY
# ---------------------------------------------------------


@router.get(
    "/opportunities/{opportunity_id}"
)
def get_opportunity(
    opportunity_id: str,
):
    if (
        not RANKED_BET_BOARD.exists()
    ):
        raise HTTPException(
            status_code=500,
            detail=(
                "Ranked bet board "
                "not found"
            ),
        )

    df = pd.read_csv(
        RANKED_BET_BOARD
    )

    df[
        "generated_id"
    ] = df.apply(
        lambda row: (
            build_id(row)
        ),
        axis=1,
    )

    match = df[
        df[
            "generated_id"
        ]
        == opportunity_id
    ]

    if match.empty:
        raise HTTPException(
            status_code=404,
            detail=(
                "Opportunity "
                "not found"
            ),
        )

    selected = (
        best_line_for_group(
            match
        )
    )

    alternates = (
        make_alternate_books(
            match,
            selected,
        )
    )

    return (
        row_to_opportunity(
            selected,
            include_alternates=(
                alternates
            ),
        )
    )


# ---------------------------------------------------------
# GAME PROJECTION
# ---------------------------------------------------------


@router.get(
    "/games/{event_id}/injuries"
)
def get_game_injury_context(
    event_id: str,
):
    if (
        not GAME_PROJECTIONS.exists()
    ):
        raise HTTPException(
            status_code=500,
            detail=(
                "Game projections "
                "file not found"
            ),
        )

    df = pd.read_csv(
        GAME_PROJECTIONS
    )

    match = df[
        df[
            "api_event_id"
        ]
        == event_id
    ]

    if match.empty:
        raise HTTPException(
            status_code=404,
            detail=(
                "Game projection "
                "not found"
            ),
        )

    row = match.iloc[0]
    away_team = str(
        row["away_team"]
    )
    home_team = str(
        row["home_team"]
    )

    context = (
        InjuryMatchupContext().build_context(
            away_team,
            home_team,
        )
    )

    return {
        "eventId": event_id,
        "awayTeam": away_team,
        "homeTeam": home_team,
        "injuryContext": context,
    }


@router.get(
    "/games/{event_id}"
)
def get_game_projection(
    event_id: str,
):
    if (
        not GAME_PROJECTIONS.exists()
    ):
        raise HTTPException(
            status_code=500,
            detail=(
                "Game projections "
                "file not found"
            ),
        )

    df = pd.read_csv(
        GAME_PROJECTIONS
    )

    match = df[
        df[
            "api_event_id"
        ]
        == event_id
    ]

    if match.empty:
        raise HTTPException(
            status_code=404,
            detail=(
                "Game projection "
                "not found"
            ),
        )

    row = match.iloc[0]

    model_margin_home = float(
        row[
            "model_margin_home"
        ]
    )

    model_total = float(
        row[
            "model_total_baseline"
        ]
    )

    projected_home_score = (
        model_total
        + model_margin_home
    ) / 2

    projected_away_score = (
        model_total
        - model_margin_home
    ) / 2

    return {
        "eventId": (
            row[
                "api_event_id"
            ]
        ),

        "commenceTime": (
            row[
                "commence_time"
            ]
        ),

        "matchup": (
            f'{row["away_team"]} @ '
            f'{row["home_team"]}'
        ),

        "awayTeam": (
            row["away_team"]
        ),

        "homeTeam": (
            row["home_team"]
        ),

        "teamPower": {
            "away": round(
                float(
                    row[
                        "away_power"
                    ]
                ),
                2,
            ),

            "home": round(
                float(
                    row[
                        "home_power"
                    ]
                ),
                2,
            ),

            "differenceHomeMinusAway": round(
                float(
                    row[
                        "home_power"
                    ]
                )
                - float(
                    row[
                        "away_power"
                    ]
                ),
                2,
            ),
        },

        "model": {
            "marginHome": round(
                model_margin_home,
                2,
            ),

            "total": round(
                model_total,
                1,
            ),

            "projectedScore": {
                "away": round(
                    projected_away_score,
                    1,
                ),

                "home": round(
                    projected_home_score,
                    1,
                ),
            },
        },

        "market": {
            "marginHome": round(
                float(
                    row[
                        "market_margin_home"
                    ]
                ),
                2,
            ),

            "homeSpread": float(
                row[
                    "market_home_spread"
                ]
            ),

            "total": float(
                row[
                    "market_total"
                ]
            ),
        },

        "spreadAnalysis": {
            "edgePoints": round(
                float(
                    row[
                        "spread_edge_points"
                    ]
                ),
                2,
            ),

            "homeCoverProbability": round(
                float(
                    row[
                        "home_cover_prob_est"
                    ]
                )
                * 100,
                1,
            ),

            "homeCoverFairOdds": round(
                float(
                    row[
                        "home_cover_fair_odds"
                    ]
                )
            ),
        },

        "source": str(
            GAME_PROJECTIONS
        ),
    }


# ---------------------------------------------------------
# LINE MOVEMENT
# ---------------------------------------------------------


@router.get(
    "/line-movement"
)
def get_line_movement(
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
    ),
    steam_only: bool = False,
):
    if (
        not LINE_MOVEMENT_BOARD.exists()
    ):
        return {
            "count": 0,

            "source": str(
                LINE_MOVEMENT_BOARD
            ),

            "steamOnly": (
                steam_only
            ),

            "summary": {
                "steamMoves": 0,
                "biggestPointMove": 0,
            },

            "movements": [],
        }

    try:
        df = pd.read_csv(
            LINE_MOVEMENT_BOARD
        )

    except (
        pd.errors.EmptyDataError
    ):
        return {
            "count": 0,

            "source": str(
                LINE_MOVEMENT_BOARD
            ),

            "steamOnly": (
                steam_only
            ),

            "summary": {
                "steamMoves": 0,
                "biggestPointMove": 0,
            },

            "movements": [],
        }

    if df.empty:
        return {
            "count": 0,

            "source": str(
                LINE_MOVEMENT_BOARD
            ),

            "steamOnly": (
                steam_only
            ),

            "summary": {
                "steamMoves": 0,
                "biggestPointMove": 0,
            },

            "movements": [],
        }

    if steam_only:
        df = df[
            df[
                "steam_flag"
            ]
            == True
        ]

    df = df.head(
        limit
    )

    movements = []

    for (
        index,
        row,
    ) in df.iterrows():

        point_move = safe_float(
            row[
                "point_move"
            ]
        )

        price_move = safe_float(
            row[
                "price_move"
            ]
        )

        opening_point = (
            safe_float(
                row[
                    "opening_point_observed"
                ]
            )
        )

        latest_point = (
            safe_float(
                row[
                    "latest_point"
                ]
            )
        )

        opening_price = (
            safe_float(
                row[
                    "opening_price_observed"
                ]
            )
        )

        latest_price = (
            safe_float(
                row[
                    "latest_price"
                ]
            )
        )

        movement = {
            "id": (
                f'{row["api_event_id"]}-'
                f'{row["sportsbook"]}-'
                f'{row["market"]}-'
                f'{row["side"]}-'
                f'{index}'
            ),

            "eventId": (
                row[
                    "api_event_id"
                ]
            ),

            "commenceTime": (
                row[
                    "commence_time"
                ]
            ),

            "matchup": (
                f'{row["away_team"]} @ '
                f'{row["home_team"]}'
            ),

            "awayTeam": (
                row[
                    "away_team"
                ]
            ),

            "homeTeam": (
                row[
                    "home_team"
                ]
            ),

            "sportsbook": (
                row[
                    "sportsbook"
                ]
            ),

            "market": (
                row[
                    "market"
                ]
            ),

            "side": (
                row[
                    "side"
                ]
            ),

            "firstSeen": (
                row[
                    "first_seen"
                ]
            ),

            "lastSeen": (
                row[
                    "last_seen"
                ]
            ),

            "openingPoint": (
                opening_point
            ),

            "latestPoint": (
                latest_point
            ),

            "pointMove": (
                point_move
            ),

            "openingPrice": (
                opening_price
            ),

            "latestPrice": (
                latest_price
            ),

            "priceMove": (
                price_move
            ),

            "steamFlag": bool(
                row[
                    "steam_flag"
                ]
            ),

            "snapshots": (
                safe_int(
                    row[
                        "snapshots"
                    ]
                )
            ),
        }

        movements.append(
            movement
        )

    steam_count = sum(
        1
        for item
        in movements
        if item[
            "steamFlag"
        ]
    )

    point_moves = [
        abs(
            item[
                "pointMove"
            ]
        )
        for item
        in movements
        if item[
            "pointMove"
        ]
        is not None
    ]

    biggest_point_move = (
        max(
            point_moves
        )
        if point_moves
        else 0
    )

    return {
        "count": len(
            movements
        ),

        "source": str(
            LINE_MOVEMENT_BOARD
        ),

        "steamOnly": (
            steam_only
        ),

        "summary": {
            "steamMoves": (
                steam_count
            ),

            "biggestPointMove": round(
                biggest_point_move,
                1,
            ),
        },

        "movements": (
            movements
        ),
    }


# ---------------------------------------------------------
# PORTFOLIO
# ---------------------------------------------------------


@router.get(
    "/portfolio"
)
def get_portfolio():
    if (
        not PORTFOLIO_RECOMMENDATIONS.exists()
    ):
        return {
            "count": 0,

            "source": str(
                PORTFOLIO_RECOMMENDATIONS
            ),

            "summary": {
                "totalRecommendedUnits": 0,
                "averageEdge": 0,
                "averageModelProbability": 0,
                "expectedValueUnits": 0,
            },

            "portfolio": [],
        }

    df = pd.read_csv(
        PORTFOLIO_RECOMMENDATIONS
    )

    portfolio = []

    for (
        index,
        row,
    ) in df.iterrows():

        portfolio.append(
            {
                "id": build_id(
                    row,
                    suffix=(
                        f"portfolio-"
                        f"{index + 1}"
                    ),
                ),

                "eventId": (
                    row[
                        "api_event_id"
                    ]
                ),

                "commenceTime": (
                    row[
                        "commence_time"
                    ]
                ),

                "matchup": (
                    f'{row["away_team"]} @ '
                    f'{row["home_team"]}'
                ),

                "awayTeam": (
                    row[
                        "away_team"
                    ]
                ),

                "homeTeam": (
                    row[
                        "home_team"
                    ]
                ),

                "pick": (
                    format_pick(
                        row
                    )
                ),

                "book": (
                    row[
                        "sportsbook"
                    ]
                ),

                "market": (
                    row[
                        "market"
                    ]
                ),

                "side": (
                    row[
                        "side"
                    ]
                ),

                "point": float(
                    row[
                        "point"
                    ]
                ),

                "price": float(
                    row[
                        "price"
                    ]
                ),

                "modelProbability": round(
                    float(
                        row[
                            "model_prob"
                        ]
                    )
                    * 100,
                    1,
                ),

                "impliedProbability": round(
                    float(
                        row[
                            "implied_prob_raw"
                        ]
                    )
                    * 100,
                    1,
                ),

                "fairOdds": round(
                    float(
                        row[
                            "fair_odds"
                        ]
                    )
                ),

                "edge": round(
                    float(
                        row[
                            "edge_pp"
                        ]
                    )
                    * 100,
                    1,
                ),

                "evPerDollar": round(
                    float(
                        row[
                            "ev_per_dollar"
                        ]
                    ),
                    3,
                ),

                "kellyFull": round(
                    float(
                        row[
                            "kelly_full"
                        ]
                    ),
                    3,
                ),

                "kelly20": round(
                    float(
                        row[
                            "kelly_20pct"
                        ]
                    ),
                    3,
                ),

                "recommendation": (
                    row[
                        "recommendation"
                    ]
                ),

                "rawUnits": float(
                    row[
                        "raw_units"
                    ]
                ),

                "recommendedUnits": float(
                    row[
                        "recommended_units"
                    ]
                ),
            }
        )

    total_units = sum(
        item[
            "recommendedUnits"
        ]
        for item
        in portfolio
    )

    average_edge = (
        sum(
            item["edge"]
            for item
            in portfolio
        )
        / len(
            portfolio
        )
        if portfolio
        else 0
    )

    average_model_probability = (
        sum(
            item[
                "modelProbability"
            ]
            for item
            in portfolio
        )
        / len(
            portfolio
        )
        if portfolio
        else 0
    )

    expected_value_units = sum(
        item[
            "recommendedUnits"
        ]
        * item[
            "evPerDollar"
        ]
        for item
        in portfolio
    )

    return {
        "count": len(
            portfolio
        ),

        "source": str(
            PORTFOLIO_RECOMMENDATIONS
        ),

        "summary": {
            "totalRecommendedUnits": round(
                total_units,
                2,
            ),

            "averageEdge": round(
                average_edge,
                1,
            ),

            "averageModelProbability": round(
                average_model_probability,
                1,
            ),

            "expectedValueUnits": round(
                expected_value_units,
                3,
            ),
        },

        "portfolio": (
            portfolio
        ),
    }