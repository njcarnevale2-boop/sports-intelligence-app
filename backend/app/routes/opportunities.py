from pathlib import Path
import hashlib
import json

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
from app.services.decision_change_engine import build_decision_timeline
from app.services.weather import WeatherAnalyzer
from app.services.market_data import market_data_service, select_best_line_row
from app.services.fair_price import build_fair_price_result
from app.services.calibration import apply_guarded_isotonic, calibration_info
from app.config import settings


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
# TEAM METADATA
# ---------------------------------------------------------

TEAM_META = {
    "ARI": {"name": "Arizona Cardinals", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ari.png"},
    "ATL": {"name": "Atlanta Falcons", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/atl.png"},
    "BAL": {"name": "Baltimore Ravens", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/bal.png"},
    "BUF": {"name": "Buffalo Bills", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/buf.png"},
    "CAR": {"name": "Carolina Panthers", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/car.png"},
    "CHI": {"name": "Chicago Bears", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/chi.png"},
    "CIN": {"name": "Cincinnati Bengals", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/cin.png"},
    "CLE": {"name": "Cleveland Browns", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/cle.png"},
    "DAL": {"name": "Dallas Cowboys", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/dal.png"},
    "DEN": {"name": "Denver Broncos", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/den.png"},
    "DET": {"name": "Detroit Lions", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/det.png"},
    "GB": {"name": "Green Bay Packers", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/gb.png"},
    "HOU": {"name": "Houston Texans", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/hou.png"},
    "IND": {"name": "Indianapolis Colts", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ind.png"},
    "JAX": {"name": "Jacksonville Jaguars", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/jax.png"},
    "KC": {"name": "Kansas City Chiefs", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/kc.png"},
    "LAC": {"name": "Los Angeles Chargers", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/lac.png"},
    "LAR": {"name": "Los Angeles Rams", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/lar.png"},
    "LV": {"name": "Las Vegas Raiders", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/lv.png"},
    "MIA": {"name": "Miami Dolphins", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/mia.png"},
    "MIN": {"name": "Minnesota Vikings", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/min.png"},
    "NE": {"name": "New England Patriots", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ne.png"},
    "NO": {"name": "New Orleans Saints", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/no.png"},
    "NYG": {"name": "New York Giants", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/nyg.png"},
    "NYJ": {"name": "New York Jets", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/nyj.png"},
    "PHI": {"name": "Philadelphia Eagles", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/phi.png"},
    "PIT": {"name": "Pittsburgh Steelers", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/pit.png"},
    "SEA": {"name": "Seattle Seahawks", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/sea.png"},
    "SF": {"name": "San Francisco 49ers", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/sf.png"},
    "TB": {"name": "Tampa Bay Buccaneers", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/tb.png"},
    "TEN": {"name": "Tennessee Titans", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ten.png"},
    "WAS": {"name": "Washington Commanders", "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png"},
}

TEAM_CODE_ALIASES = {
    "LA": "LAR",
    "JAC": "JAX",
}


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------


def normalize_team_code(team_code: str) -> str:
    """Normalize team code to standard abbreviation."""
    code = str(team_code or "").strip().upper()
    return TEAM_CODE_ALIASES.get(code, code)


def get_team_logo(team_code: str) -> str | None:
    """Get team logo URL by team code."""
    normalized = normalize_team_code(team_code)
    return TEAM_META.get(normalized, {}).get("logo")


def safe_float(value):
    if pd.isna(value):
        return None

    return float(value)


def safe_int(value):
    if pd.isna(value):
        return None

    return int(value)


def _clamp_probability(value: float) -> float:
    return max(1e-6, min(1 - 1e-6, value))


def _unit_probability(value: float | None) -> float | None:
    if value is None:
        return None
    p = float(value)
    if p > 1.0:
        p /= 100.0
    return _clamp_probability(p)


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _qualification_from_recommendation(recommendation: str | None) -> tuple[str, list[str]]:
    label = str(recommendation or "").strip().upper()
    if not label:
        return "NOT_QUALIFIED", ["No actionable recommendation was produced."]
    if "WATCH" in label:
        return "NOT_QUALIFIED", ["Recommendation is watch-only at current market conditions."]
    if "LEAN" in label:
        return "NOT_QUALIFIED", ["Lean recommendations are tracked but not counted as qualified bets."]
    return "QUALIFIED", ["Current model edge and confidence meet SIA qualification thresholds."]


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


def classify_bet_status(recommendation: str | None) -> str:
    label = str(recommendation or "").strip().upper()
    if not label:
        return "NO QUALIFIED BET"
    if "STRONG" in label or "ELITE" in label:
        return "STRONG BET"
    if "LEAN" in label:
        return "LEAN"
    return "QUALIFIED"


def derive_game_lean(game_row: pd.Series | None) -> str:
    if game_row is None:
        return "NO LEAN"

    away_team = str(game_row.get("away_team", "")).strip()
    home_team = str(game_row.get("home_team", "")).strip()
    model_margin_home = safe_float(game_row.get("model_margin_home"))
    market_home_spread = safe_float(game_row.get("market_home_spread"))
    model_total = safe_float(game_row.get("model_total_baseline"))
    market_total = safe_float(game_row.get("market_total"))

    if model_margin_home is not None and abs(model_margin_home) >= 0.25:
        team = home_team if model_margin_home > 0 else away_team
        return f"{team} SIDE"

    if model_total is not None and market_total is not None:
        total_diff = model_total - market_total
        if abs(total_diff) >= 0.75:
            return "TOTAL OVER" if total_diff > 0 else "TOTAL UNDER"

    if market_home_spread is not None:
        if market_home_spread < 0:
            return f"{home_team} SIDE"
        if market_home_spread > 0:
            return f"{away_team} SIDE"

    return "NO LEAN"


def build_intelligence_report(
    event_id: str,
    opportunity: dict | None,
    game_row: pd.Series | None,
    market_snapshot: dict | None,
) -> dict:
    books_tracked = int((market_snapshot or {}).get("booksTracked") or 0)
    consensus_spread = (market_snapshot or {}).get("consensusSpread")
    if consensus_spread is None and game_row is not None:
        consensus_spread = safe_float(game_row.get("market_home_spread"))
    consensus_total = (market_snapshot or {}).get("consensusTotal")
    if consensus_total is None and game_row is not None:
        consensus_total = safe_float(game_row.get("market_total"))

    if opportunity is not None:
        recommendation = opportunity.get("recommendation")
        return {
            "eventId": event_id,
            "betStatus": classify_bet_status(recommendation),
            "qualificationStatus": "QUALIFIED",
            "qualificationReasons": ["Current model edge and confidence meet SIA qualification thresholds."],
            "currentLean": str(opportunity.get("pick") or "NO LEAN").upper(),
            "confidence": opportunity.get("confidence"),
            "currentMarket": {
                "spread": opportunity.get("pick") if opportunity.get("market") == "spread" else None,
                "total": consensus_total,
                "sportsbook": opportunity.get("book"),
                "price": opportunity.get("price"),
            },
            "whySummary": "SIA identified a qualified edge based on model probability, price, and confidence.",
            "betTrigger": {
                "available": False,
                "message": "Actionable price not currently available",
                "monitor": None,
                "qualifiedAt": None,
            },
        }

    if game_row is None:
        return {
            "eventId": event_id,
            "betStatus": "INSUFFICIENT DATA",
            "qualificationStatus": "INSUFFICIENT_DATA",
            "qualificationReasons": ["Game projection data is unavailable for this matchup."],
            "currentLean": "NO LEAN",
            "confidence": None,
            "currentMarket": {
                "spread": None,
                "total": None,
                "sportsbook": None,
                "price": None,
            },
            "whySummary": "SIA cannot determine a qualified bet without a complete game projection.",
            "betTrigger": {
                "available": False,
                "message": "Actionable price not currently available",
                "monitor": None,
                "qualifiedAt": None,
            },
        }

    if books_tracked == 0:
        return {
            "eventId": event_id,
            "betStatus": "INSUFFICIENT DATA",
            "qualificationStatus": "INSUFFICIENT_DATA",
            "qualificationReasons": ["Insufficient market data to evaluate a qualified bet."],
            "currentLean": derive_game_lean(game_row),
            "confidence": None,
            "currentMarket": {
                "spread": consensus_spread,
                "total": consensus_total,
                "sportsbook": None,
                "price": None,
            },
            "whySummary": "SIA has not received enough market coverage to publish a qualified bet recommendation.",
            "betTrigger": {
                "available": False,
                "message": "Actionable price not currently available",
                "monitor": None,
                "qualifiedAt": None,
            },
        }

    return {
        "eventId": event_id,
        "betStatus": "NO QUALIFIED BET",
        "qualificationStatus": "NOT_QUALIFIED",
        "qualificationReasons": ["Current edge and confidence do not meet SIA qualification thresholds."],
        "currentLean": derive_game_lean(game_row),
        "confidence": None,
        "currentMarket": {
            "spread": consensus_spread,
            "total": consensus_total,
            "sportsbook": None,
            "price": None,
        },
        "whySummary": "SIA analyzed this game but no market/side currently qualifies as an actionable bet.",
        "betTrigger": {
            "available": False,
            "message": "Actionable price not currently available",
            "monitor": None,
            "qualifiedAt": None,
        },
    }


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
    injury_ctx=None,
    group_rows=None,
    game_projection_row=None,
):
    away_code = normalize_team_code(row.get("away_team", ""))
    home_code = normalize_team_code(row.get("home_team", ""))
    raw_model_prob = _unit_probability(safe_float(row.get("model_prob")))
    implied_prob = _unit_probability(safe_float(row.get("implied_prob_raw")))
    calibrated_prob = apply_guarded_isotonic(raw_model_prob)
    calibrated_edge = None
    if calibrated_prob is not None and implied_prob is not None:
        calibrated_edge = calibrated_prob - implied_prob

    raw_edge = safe_float(row.get("edge_pp"))
    if raw_edge is not None and raw_edge > 1.0:
        raw_edge = raw_edge / 100.0

    quality_status, quality_reasons = _qualification_from_recommendation(row.get("recommendation"))
    cinfo = calibration_info()
    
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

        "awayAbbreviation": away_code,
        "homeAbbreviation": home_code,
        "awayLogo": get_team_logo(away_code),
        "homeLogo": get_team_logo(home_code),

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
            float(raw_model_prob or 0.0) * 100,
            1,
        ),

        "rawModelProbability": raw_model_prob,

        "impliedProbability": round(
            float(implied_prob or 0.0) * 100,
            1,
        ),

        "calibratedProbability": calibrated_prob,

        "fairOdds": round(
            float(
                row["fair_odds"]
            )
        ),

        "edge": round(
            float(calibrated_edge or 0.0) * 100,
            1,
        ),

        "rawEdge": round(float(raw_edge or 0.0) * 100, 1),

        "calibratedEdge": calibrated_edge,

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
        "rawRank": int(row["rank"]),
        "qualificationStatus": quality_status,
        "qualificationReasons": quality_reasons,
        "qualificationPolicyVersion": settings.DEFAULT_QUALIFICATION_POLICY_VERSION,
        "rankingVersion": settings.DEFAULT_RANKING_VERSION,
        "calibrationStatus": cinfo.status,
        "calibrationMethod": cinfo.method,
        "calibrationVersion": cinfo.version,
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

    # Reuse the caller-supplied context to avoid one ESPN fetch per row.
    injury_context = (
        injury_ctx.build_context(
            away_team=str(row["away_team"]),
            home_team=str(row["home_team"]),
        )
        if injury_ctx is not None
        else InjuryMatchupContext().build_context(
            away_team=str(row["away_team"]),
            home_team=str(row["home_team"]),
        )
    )
    result["injuryContext"] = injury_context

    fair_price_result = build_fair_price_result(
        row=row,
        group_rows=group_rows,
        game_projection_row=game_projection_row,
        minimum_playable_ev=settings.MIN_PLAYABLE_EV,
    )

    result["fairPrice"] = fair_price_result.fair_price
    result["fairLine"] = fair_price_result.fair_line
    result["truePlayableTo"] = fair_price_result.true_playable_to
    result["truePlayableToStatus"] = fair_price_result.true_playable_to_status
    result["truePlayableToReason"] = fair_price_result.true_playable_to_reason
    result["worstObservedPlayablePrice"] = fair_price_result.worst_observed_playable_price
    result["worstObservedPlayablePriceStatus"] = fair_price_result.worst_observed_playable_price_status
    result["worstObservedPlayablePriceReason"] = fair_price_result.worst_observed_playable_price_reason
    result["playableTo"] = fair_price_result.playable_to
    result["playableToStatus"] = fair_price_result.playable_to_status
    result["playableToReason"] = fair_price_result.playable_to_reason
    result["currentWinProbability"] = fair_price_result.current_win_probability
    result["currentPushProbability"] = fair_price_result.current_push_probability
    result["currentLossProbability"] = fair_price_result.current_loss_probability
    result["currentEV"] = fair_price_result.current_ev
    result["minimumPlayableEV"] = fair_price_result.minimum_playable_ev
    result["bestAvailablePrice"] = fair_price_result.best_available_price
    result["bestAvailableLine"] = fair_price_result.best_available_line
    result["pushAwareEV"] = fair_price_result.current_ev

    if result["currentWinProbability"] is not None and implied_prob is not None:
        result["edge"] = round((float(result["currentWinProbability"]) - implied_prob) * 100, 1)
        result["calibratedEdge"] = float(result["currentWinProbability"]) - implied_prob

    if result["currentEV"] is not None:
        result["evPerDollar"] = round(float(result["currentEV"]), 3)

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


def load_game_projection_lookup() -> dict[str, pd.Series]:
    if not GAME_PROJECTIONS.exists():
        return {}

    df = pd.read_csv(GAME_PROJECTIONS)
    if "api_event_id" not in df.columns:
        return {}

    df = df.copy()
    df["api_event_id"] = df["api_event_id"].astype(str)
    return {str(row["api_event_id"]): row for _, row in df.iterrows()}


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
    week: int | None = Query(default=None),
):
    from app.services.games import service as games_service

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

    # Resolve week: default to first available week when no week param given
    all_games_payload = games_service.list_games()
    available_weeks: list[int] = all_games_payload.get("availableWeeks", [])
    resolved_week: int = week if week is not None else (available_weeks[0] if available_weeks else 1)

    # Filter to only eventIds belonging to the resolved week
    week_games_payload = games_service.list_games(week=resolved_week)
    week_event_ids: set[str] = {g["eventId"] for g in week_games_payload.get("games", [])}
    week_scheduled_games: int = len(week_event_ids)

    df["api_event_id"] = df["api_event_id"].astype(str)
    df = df[df["api_event_id"].isin(week_event_ids)]

    # One InjuryMatchupContext per request — one ESPN fetch total.
    shared_injury_ctx = InjuryMatchupContext()

    cinfo = calibration_info()

    if not best_lines_only:
        market_snapshots = market_data_service.all_event_snapshots()

        df = (
            df
            .sort_values(
                "rank"
            )
            .head(limit)
        )

        opportunities = []
        for week_rank, (_, row) in enumerate(df.iterrows(), start=1):
            opp = row_to_opportunity(
                row,
                market_snapshot=market_snapshots.get(str(row["api_event_id"])),
                injury_ctx=shared_injury_ctx,
            )
            opp["weekRank"] = week_rank
            opportunities.append(opp)

        return {
            "count": len(opportunities),
            "week": resolved_week,
            "weekScheduledGames": week_scheduled_games,
            "weekQualifiedOpportunities": len(opportunities),
            "availableWeeks": available_weeks,
            "source": str(RANKED_BET_BOARD),
            "bestLinesOnly": False,
            "provider": market_meta["provider"],
            "lastUpdated": market_meta["lastUpdated"],
            "dataStatus": market_meta["dataStatus"],
            "calibrationStatus": cinfo.status,
            "calibrationMethod": cinfo.method,
            "calibrationVersion": cinfo.version,
            "opportunities": opportunities,
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

    market_snapshots = market_data_service.all_event_snapshots()
    projection_lookup = load_game_projection_lookup()

    # Collect best pandas rows per group; track group's minimum rank for correct ordering
    raw_best_rows = []
    raw_alternates_map = {}
    raw_group_map = {}
    raw_group_min_rank: dict[int, int] = {}
    for group_key, group in grouped:
        selected = best_line_for_group(group)
        group_min_rank = int(group["rank"].min())
        raw_best_rows.append(selected)
        raw_alternates_map[id(selected)] = make_alternate_books(group, selected)
        raw_group_map[id(selected)] = group
        raw_group_min_rank[id(selected)] = group_min_rank

    candidate_rows = []
    for selected in raw_best_rows:
        model_prob = _unit_probability(safe_float(selected.get("model_prob")))
        implied_prob = _unit_probability(safe_float(selected.get("implied_prob_raw")))
        calibrated_prob = apply_guarded_isotonic(model_prob)
        calibrated_edge = (calibrated_prob - implied_prob) if calibrated_prob is not None and implied_prob is not None else -999.0
        candidate_rows.append(
            {
                "selected": selected,
                "groupMinRank": raw_group_min_rank[id(selected)],
                "calibratedEdge": float(calibrated_edge),
                "ev": float(safe_float(selected.get("ev_per_dollar")) or 0.0),
                "confidence": float(safe_float(selected.get("confidence_score")) or 0.0),
                "eventId": str(selected.get("api_event_id") or ""),
                "market": str(selected.get("market") or ""),
                "side": str(selected.get("side") or ""),
            }
        )

    # Canonical SIA3 ordering: calibrated edge first, then deterministic tie-breakers.
    candidate_rows.sort(
        key=lambda r: (
            -r["calibratedEdge"],
            -r["ev"],
            -r["confidence"],
            r["groupMinRank"],
            r["eventId"],
            r["market"],
            r["side"],
        )
    )
    candidate_rows = candidate_rows[:limit]

    best_rows = []
    for week_rank, candidate in enumerate(candidate_rows, start=1):
        selected = candidate["selected"]
        item = row_to_opportunity(
            selected,
            include_alternates=raw_alternates_map[id(selected)],
            market_snapshot=market_snapshots.get(str(selected["api_event_id"])),
            injury_ctx=shared_injury_ctx,
            group_rows=raw_group_map[id(selected)],
            game_projection_row=projection_lookup.get(str(selected["api_event_id"])),
        )
        # weekRank is sequential position on the filtered week board; rank is the model's row rank
        item["weekRank"] = week_rank
        item["rank"] = week_rank
        best_rows.append(item)

    snapshot_payload = {
        "week": resolved_week,
        "source": str(RANKED_BET_BOARD),
        "lastUpdated": market_meta.get("lastUpdated"),
        "opportunities": [
            {
                "id": o.get("id"),
                "eventId": o.get("eventId"),
                "market": o.get("market"),
                "side": o.get("side"),
                "point": o.get("point"),
                "price": o.get("price"),
                "calibratedProbability": o.get("calibratedProbability"),
                "currentWinProbability": o.get("currentWinProbability"),
                "impliedProbability": o.get("impliedProbability"),
                "calibratedEdge": o.get("calibratedEdge"),
                "pushAwareEV": o.get("pushAwareEV"),
                "rank": o.get("rank"),
                "weekRank": o.get("weekRank"),
                "qualificationStatus": o.get("qualificationStatus"),
            }
            for o in best_rows
        ],
    }
    snapshot_id = _sha256(_canonical_json(snapshot_payload))

    return {
        "count": len(best_rows),
        "week": resolved_week,
        "weekScheduledGames": week_scheduled_games,
        "weekQualifiedOpportunities": len(best_rows),
        "availableWeeks": available_weeks,
        "source": str(RANKED_BET_BOARD),
        "bestLinesOnly": True,
        "provider": market_meta["provider"],
        "lastUpdated": market_meta["lastUpdated"],
        "dataStatus": market_meta["dataStatus"],
        "snapshotId": snapshot_id,
        "calibrationStatus": cinfo.status,
        "calibrationMethod": cinfo.method,
        "calibrationVersion": cinfo.version,
        "rankingVersion": settings.DEFAULT_RANKING_VERSION,
        "qualificationPolicyVersion": settings.DEFAULT_QUALIFICATION_POLICY_VERSION,
        "opportunities": best_rows,
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

    projection_lookup = load_game_projection_lookup()

    opportunity = (
        row_to_opportunity(
            selected,
            include_alternates=(
                alternates
            ),
            market_snapshot=market_data_service.event_market_snapshot(str(selected["api_event_id"])),
            group_rows=match,
            game_projection_row=projection_lookup.get(str(selected["api_event_id"])),
        )
    )

    market_intelligence = (
        get_market_intelligence(
            event_id=opportunity["eventId"],
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


@router.get("/games/{event_id}/opportunity")
def get_game_best_opportunity(event_id: str):
    """Return the top-ranked SIA opportunity for this game, or null if none qualifies."""
    game_row = None
    if GAME_PROJECTIONS.exists():
        game_df = pd.read_csv(GAME_PROJECTIONS)
        game_df["api_event_id"] = game_df["api_event_id"].astype(str)
        game_match = game_df[game_df["api_event_id"] == event_id]
        if not game_match.empty:
            game_row = game_match.iloc[0]

    market_snapshot = market_data_service.event_market_snapshot(event_id)

    if not RANKED_BET_BOARD.exists():
        return {
            "eventId": event_id,
            "opportunity": None,
            "intelligenceReport": build_intelligence_report(
                event_id=event_id,
                opportunity=None,
                game_row=game_row,
                market_snapshot=market_snapshot,
            ),
        }

    df = pd.read_csv(RANKED_BET_BOARD)
    df["api_event_id"] = df["api_event_id"].astype(str)
    match = df[df["api_event_id"] == event_id]

    if match.empty:
        return {
            "eventId": event_id,
            "opportunity": None,
            "intelligenceReport": build_intelligence_report(
                event_id=event_id,
                opportunity=None,
                game_row=game_row,
                market_snapshot=market_snapshot,
            ),
        }

    # Identify the top-ranked market/side for this game
    match = match.sort_values("rank")
    top_row = match.iloc[0]
    top_market = top_row["market"]
    top_side = top_row["side"]

    # Select best available line for that market/side (same logic as main opportunities board)
    group = match[(match["market"] == top_market) & (match["side"] == top_side)]
    selected = best_line_for_group(group)
    alternates = make_alternate_books(group, selected)
    opportunity = row_to_opportunity(
        selected,
        include_alternates=alternates,
        market_snapshot=market_snapshot,
        injury_ctx=InjuryMatchupContext(),
        group_rows=group,
        game_projection_row=game_row,
    )
    return {
        "eventId": event_id,
        "opportunity": opportunity,
        "intelligenceReport": build_intelligence_report(
            event_id=event_id,
            opportunity=opportunity,
            game_row=game_row,
            market_snapshot=market_snapshot,
        ),
    }


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

    home_team = str(row["home_team"])
    away_team = str(row["away_team"])
    commence_time_str = str(row.get("commence_time", ""))

    # Parse kickoff so the weather provider can look up the correct forecast window
    kickoff_dt = None
    if commence_time_str:
        try:
            parsed = pd.to_datetime(commence_time_str, utc=True, errors="coerce")
            if parsed is not None and not pd.isna(parsed):
                kickoff_dt = parsed.to_pydatetime()
        except Exception:
            pass

    weather = WeatherAnalyzer(home_team=home_team, kickoff=kickoff_dt).analyze()

    return {
        "eventId": event_id,
        "awayTeam": away_team,
        "homeTeam": home_team,
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