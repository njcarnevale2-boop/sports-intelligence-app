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
from app.services.executive_analyst import generate_executive_analysis
from app.services.explainability import generate_explainability
from app.services.weather import WeatherAnalyzer
from app.services.market_data import market_data_service, select_best_line_row


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
    market_snapshot=None,
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
        "marketProvider": (
            market_snapshot.get("provider")
            if market_snapshot
            else None
        ),
        "marketLastUpdated": (
            market_snapshot.get("lastUpdated")
            if market_snapshot
            else None
        ),
        "marketDataStatus": (
            market_snapshot.get("dataStatus")
            if market_snapshot
            else "UNAVAILABLE"
        ),
        "booksTracked": (
            market_snapshot.get("booksTracked")
            if market_snapshot
            else 0
        ),
        "bestLineComparison": {
            "bestLine": {
                "awaySpread": market_snapshot.get("bestAwaySpread") if market_snapshot else None,
                "homeSpread": market_snapshot.get("bestHomeSpread") if market_snapshot else None,
                "awayMoneyline": market_snapshot.get("bestAwayMoneyline") if market_snapshot else None,
                "homeMoneyline": market_snapshot.get("bestHomeMoneyline") if market_snapshot else None,
                "over": market_snapshot.get("bestOver") if market_snapshot else None,
                "under": market_snapshot.get("bestUnder") if market_snapshot else None,
            },
            "bestPrice": {
                "awaySpread": market_snapshot.get("bestPriceAwaySpread") if market_snapshot else None,
                "homeSpread": market_snapshot.get("bestPriceHomeSpread") if market_snapshot else None,
                "awayMoneyline": market_snapshot.get("bestPriceAwayMoneyline") if market_snapshot else None,
                "homeMoneyline": market_snapshot.get("bestPriceHomeMoneyline") if market_snapshot else None,
                "over": market_snapshot.get("bestPriceOver") if market_snapshot else None,
                "under": market_snapshot.get("bestPriceUnder") if market_snapshot else None,
            },
        },
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
    return select_best_line_row(group)


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
    market_meta = market_data_service.metadata()

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
        market_snapshots = market_data_service.all_event_snapshots()

        df = (
            df
            .sort_values(
                "rank"
            )
            .head(limit)
        )

        opportunities = [
            row_to_opportunity(
                row,
                market_snapshot=market_snapshots.get(str(row["api_event_id"])),
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
            "provider": market_meta["provider"],
            "lastUpdated": market_meta["lastUpdated"],
            "dataStatus": market_meta["dataStatus"],

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
    market_snapshots = market_data_service.all_event_snapshots()

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
                market_snapshot=market_snapshots.get(str(selected["api_event_id"])),
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
        "provider": market_meta["provider"],
        "lastUpdated": market_meta["lastUpdated"],
        "dataStatus": market_meta["dataStatus"],

        "opportunities": (
            opportunities
        ),
    }


# ---------------------------------------------------------
# INDIVIDUAL OPPORTUNITY
# ---------------------------------------------------------


@router.get(
    "/opportunities/{opportunity_id}/analysis"
)
def get_opportunity_analysis(
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

    opportunity = (
        row_to_opportunity(
            selected,
            include_alternates=(
                alternates
            ),
            market_snapshot=market_data_service.event_market_snapshot(str(selected["api_event_id"])),
        )
    )

    market_intelligence = (
        get_market_intelligence(
            event_id=(
                opportunity["eventId"]
            ),
            market=opportunity[
                "market"
            ],
            side=opportunity[
                "side"
            ],
        )
    )

    injury_context = (
        InjuryMatchupContext().build_context(
            away_team=opportunity[
                "awayTeam"
            ],
            home_team=opportunity[
                "homeTeam"
            ],
        )
    )

    opportunity[
        "marketIntelligence"
    ] = market_intelligence
    opportunity[
        "injuryContext"
    ] = injury_context
    opportunity[
        "sportsIntelligenceScore"
    ] = calculate_sports_intelligence_score(
        opportunity=opportunity,
        market_intelligence=(
            market_intelligence
        ),
    )

    return {
        "opportunity": opportunity,
        "executiveAnalysis": (
            generate_executive_analysis(
                opportunity
            )
        ),
        "explainability": (
            generate_explainability(
                opportunity
            )
        ),
        "decisionTimeline": build_decision_timeline(opportunity),
    }


@router.get(
    "/opportunities/{opportunity_id}/timeline"
)
def get_opportunity_timeline(
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

    opportunity = (
        row_to_opportunity(
            selected,
            include_alternates=False,
            market_snapshot=market_data_service.event_market_snapshot(str(selected["api_event_id"])),
        )
    )

    return build_decision_timeline(opportunity)


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
            market_snapshot=market_data_service.event_market_snapshot(str(selected["api_event_id"])),
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
    "/games/{event_id}/weather"
)
def get_game_weather(
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
    weather = WeatherAnalyzer().analyze()

    return {
        "eventId": event_id,
        "awayTeam": str(
            row["away_team"]
        ),
        "homeTeam": str(
            row["home_team"]
        ),
        "weather": weather,
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
    market_meta = market_data_service.metadata()

    rows = market_data_service.load_normalized_market_rows()
    if steam_only:
        rows = [row for row in rows if row.get("steamFlag")]

    rows = rows[:limit]

    movements = []
    market_name_map = {
        "spread": "spreads",
        "total": "totals",
        "moneyline": "h2h",
    }

    for index, row in enumerate(rows):
        opening_point = row.get("openingPoint")
        latest_point = row.get("latestPoint")
        opening_price = row.get("openingOdds")
        latest_price = row.get("latestOdds")

        point_move = None
        if opening_point is not None and latest_point is not None:
            point_move = round(latest_point - opening_point, 3)

        price_move = None
        if opening_price is not None and latest_price is not None:
            price_move = round(latest_price - opening_price, 3)

        movements.append(
            {
                "id": f'{row["eventId"]}-{row.get("sportsbook", "unknown")}-{row.get("market", "unknown")}-{row.get("side", "unknown")}-{index}',
                "eventId": row.get("eventId"),
                "commenceTime": row.get("commenceTime"),
                "matchup": f'{row.get("awayTeam", "") } @ {row.get("homeTeam", "")}',
                "awayTeam": row.get("awayTeam"),
                "homeTeam": row.get("homeTeam"),
                "sportsbook": row.get("sportsbook"),
                "market": market_name_map.get(row.get("market"), row.get("market")),
                "side": row.get("side"),
                "firstSeen": row.get("firstSeen"),
                "lastSeen": row.get("lastSeen"),
                "openingPoint": opening_point,
                "latestPoint": latest_point,
                "pointMove": point_move,
                "openingPrice": opening_price,
                "latestPrice": latest_price,
                "priceMove": price_move,
                "steamFlag": bool(row.get("steamFlag", False)),
                "snapshots": row.get("snapshots"),
            }
        )

    steam_count = sum(1 for item in movements if item.get("steamFlag"))
    point_moves = [abs(item["pointMove"]) for item in movements if item.get("pointMove") is not None]
    biggest_point_move = max(point_moves) if point_moves else 0

    historical_snapshots = [item.get("snapshots") for item in movements if item.get("snapshots") is not None]
    opening_available = any(item.get("openingPoint") is not None or item.get("openingPrice") is not None for item in movements)

    return {
        "count": len(movements),
        "source": str(LINE_MOVEMENT_BOARD),
        "steamOnly": steam_only,
        "provider": market_meta["provider"],
        "lastUpdated": market_meta["lastUpdated"],
        "dataStatus": market_meta["dataStatus"],
        "summary": {
            "steamMoves": steam_count,
            "biggestPointMove": round(biggest_point_move, 1),
        },
        "lineHistory": {
            "openingLineAvailable": opening_available,
            "currentLineAvailable": bool(movements),
            "closingLineAvailable": False,
            "historicalSnapshots": max(historical_snapshots) if historical_snapshots else 0,
            "message": (
                "Opening and current lines are available from file snapshots; closing lines are not currently stored."
                if movements
                else "No line movement records available."
            ),
        },
        "movements": movements,
    }


@router.get(
    "/markets"
)
def get_markets(
    event_id: str | None = Query(default=None),
):
    meta = market_data_service.metadata()

    if event_id:
        snapshot = market_data_service.event_market_snapshot(event_id)
        return {
            "count": len(snapshot.get("records", [])),
            "provider": snapshot.get("provider", meta["provider"]),
            "lastUpdated": snapshot.get("lastUpdated", meta["lastUpdated"]),
            "dataStatus": snapshot.get("dataStatus", meta["dataStatus"]),
            "event": snapshot,
        }

    snapshots = market_data_service.all_event_snapshots()
    summaries = []
    for snapshot in snapshots.values():
        trimmed = dict(snapshot)
        trimmed.pop("records", None)
        summaries.append(trimmed)

    return {
        "count": len(summaries),
        "provider": meta["provider"],
        "lastUpdated": meta["lastUpdated"],
        "dataStatus": meta["dataStatus"],
        "events": summaries,
    }


@router.get(
    "/markets/{event_id}"
)
def get_market_for_event(event_id: str):
    snapshot = market_data_service.event_market_snapshot(event_id)
    return snapshot


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