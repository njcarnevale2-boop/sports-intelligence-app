from pathlib import Path
import hashlib
import json
from typing import Any

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
from app.services.decision_board import build_decision_board_payload
from app.services.probability_engine import (
    ev_per_dollar_with_push,
    fair_price_from_win_push,
    moneyline_outcome_probabilities,
    total_outcome_probabilities,
)
from app.config import settings
from app.runtime_paths import runtime_paths


router = APIRouter(
    prefix="/api",
    tags=["sports-intelligence"],
)


def _decision_board_line_shopping(opp: dict[str, Any]) -> dict[str, Any] | None:
    try:
        from app.services.shadow_markets import line_shopping_market_view
    except Exception:
        return None

    market_family = str(opp.get("marketType") or "").upper()
    side = str(opp.get("side") or "").lower()
    team_code = None
    if market_family in {"SPREAD", "MONEYLINE"}:
        if side == "home":
            team_code = str(opp.get("homeAbbreviation") or "").upper() or None
        elif side == "away":
            team_code = str(opp.get("awayAbbreviation") or "").upper() or None

    try:
        return line_shopping_market_view(
            event_id=str(opp.get("eventId") or ""),
            market_family=market_family,
            side=side,
            period="FULL_GAME",
            phase="PREGAME",
            team_code=team_code,
            selection=str(opp.get("pick") or "") or None,
            playable_to_line=safe_float(opp.get("truePlayableTo")) if market_family in {"SPREAD", "TOTAL"} else None,
            playable_to_price=safe_float(opp.get("worstObservedPlayablePrice")),
        )
    except Exception:
        return None


MODEL_ROOT = runtime_paths.root


RANKED_BET_BOARD = runtime_paths.ranked_bet_board_csv


PORTFOLIO_RECOMMENDATIONS = runtime_paths.portfolio_recommendations_csv


GAME_PROJECTIONS = runtime_paths.current_game_projections_csv


LINE_MOVEMENT_BOARD = runtime_paths.line_movement_board_csv


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


MARKET_QUALIFICATION_POLICY = {
    "spread": {"minEdge": 0.0, "minEV": float(settings.MIN_PLAYABLE_EV), "minConfidence": 60.0},
    "moneyline": {"minEdge": 0.015, "minEV": max(0.01, float(settings.MIN_PLAYABLE_EV)), "minConfidence": 60.0},
    "total": {"minEdge": 0.015, "minEV": max(0.01, float(settings.MIN_PLAYABLE_EV)), "minConfidence": 60.0},
}


MARKET_VALIDATION_STATUS = {
    "spread": "PRODUCTION_VALIDATED",
    "moneyline": "SHADOW_VALIDATION",
    "total": "SHADOW_VALIDATION",
}


def _market_eligibility(market: str) -> tuple[bool, str, str]:
    key = _market_key(market)
    status = MARKET_VALIDATION_STATUS.get(key, "UNKNOWN")
    if key == "spread":
        return True, "Spread market is currently validated for production SIA 3.", status
    if key == "moneyline":
        return False, "Moneyline is in shadow validation and is not production-eligible yet.", status
    if key == "total":
        return False, "Total is in shadow validation and is not production-eligible yet.", status
    return False, "Market family is not production-eligible.", status


def _market_key(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw == "spreads":
        return "spread"
    if raw == "totals":
        return "total"
    if raw == "h2h":
        return "moneyline"
    return raw


def _implied_probability_from_american(price: float | None) -> float | None:
    if price is None:
        return None
    odds = float(price)
    if odds == 0:
        return None
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def _devig_two_way(price_a: float | None, price_b: float | None) -> tuple[float | None, float | None]:
    pa = _implied_probability_from_american(price_a)
    pb = _implied_probability_from_american(price_b)
    if pa is None or pb is None:
        return None, None
    total = pa + pb
    if total <= 0:
        return None, None
    return pa / total, pb / total


def _market_family_label(market: str) -> str:
    key = _market_key(market)
    if key == "spread":
        return "SPREAD"
    if key == "moneyline":
        return "MONEYLINE"
    if key == "total":
        return "TOTAL"
    return key.upper()


def _qualify_market_candidate(
    market: str,
    calibrated_edge: float | None,
    current_ev: float | None,
    confidence_score: float | None,
) -> tuple[str, str, list[str]]:
    key = _market_key(market)
    policy = MARKET_QUALIFICATION_POLICY.get(key, MARKET_QUALIFICATION_POLICY["spread"])

    edge_value = float(calibrated_edge or 0.0)
    ev_value = float(current_ev or 0.0)
    conf_value = float(confidence_score or 0.0)

    reasons: list[str] = []
    if edge_value < float(policy["minEdge"]):
        reasons.append(f"Calibrated edge {edge_value:.3f} is below {key} threshold {policy['minEdge']:.3f}.")
    if ev_value < float(policy["minEV"]):
        reasons.append(f"Push-aware EV {ev_value:.3f} is below {key} threshold {policy['minEV']:.3f}.")
    if conf_value < float(policy["minConfidence"]):
        reasons.append(f"Confidence {conf_value:.1f} is below {key} threshold {policy['minConfidence']:.1f}.")

    if reasons:
        return "PASS", "NOT_QUALIFIED", reasons

    recommendation = "STRONG BET" if (edge_value >= float(policy["minEdge"]) + 0.03 and ev_value >= float(policy["minEV"]) + 0.05) else "BET"
    return recommendation, "QUALIFIED", [f"{key.title()} candidate meets explicit SIA market-family qualification thresholds."]


def format_pick(row):
    away_team = str(row.get("away_team") or "")
    home_team = str(row.get("home_team") or "")
    side = str(row.get("side") or "").lower()
    market = _market_key(str(row.get("market") or ""))
    point = safe_float(row.get("point"))

    if market == "moneyline":
        return home_team if side == "home" else away_team

    if market == "spread" and point is not None:
        team = home_team if side == "home" else away_team
        point_text = f"+{point:g}" if point > 0 else f"{point:g}"
        return f"{team} {point_text}"

    if market == "total" and point is not None:
        return f"{side.title()} {point:g}"

    if point is not None:
        return f"{side.title()} {point:g}"

    return side.title() or "Unavailable"


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
    market_key = _market_key(str(row.get("market") or ""))
    point_value = safe_float(row.get("point"))

    raw_model_prob = _unit_probability(safe_float(row.get("model_prob")))
    implied_prob = _unit_probability(safe_float(row.get("implied_prob_raw")))
    calibrated_prob = apply_guarded_isotonic(raw_model_prob)
    calibrated_edge = None
    if calibrated_prob is not None and implied_prob is not None:
        calibrated_edge = calibrated_prob - implied_prob

    raw_edge = safe_float(row.get("edge_pp"))
    if raw_edge is not None and raw_edge > 1.0:
        raw_edge = raw_edge / 100.0

    quality_status = str(row.get("qualification_status") or "").upper()
    quality_reasons = row.get("qualification_reasons")
    if quality_status not in {"QUALIFIED", "NOT_QUALIFIED", "INSUFFICIENT_DATA"}:
        quality_status, quality_reasons = _qualification_from_recommendation(row.get("recommendation"))
    elif not isinstance(quality_reasons, list):
        quality_reasons = [str(quality_reasons)] if quality_reasons else ["Qualification metadata not provided."]

    cinfo = calibration_info()

    fair_odds = safe_float(row.get("fair_odds"))
    ev_per_dollar = safe_float(row.get("ev_per_dollar"))
    kelly_full = safe_float(row.get("kelly_full"))
    kelly_20 = safe_float(row.get("kelly_20pct"))

    result = {
        "id": build_id(row),
        "eventId": str(row.get("api_event_id") or ""),
        "commenceTime": row.get("commence_time"),
        "matchup": f'{row.get("away_team")} @ {row.get("home_team")}',
        "awayTeam": row.get("away_team"),
        "homeTeam": row.get("home_team"),
        "awayAbbreviation": away_code,
        "homeAbbreviation": home_code,
        "awayLogo": get_team_logo(away_code),
        "homeLogo": get_team_logo(home_code),
        "pick": format_pick(row),
        "book": row.get("sportsbook"),
        "market": market_key,
        "marketType": _market_family_label(market_key),
        "side": str(row.get("side") or "").lower(),
        "point": point_value if market_key != "moneyline" else None,
        "price": float(safe_float(row.get("price")) or 0.0),
        "modelProbability": round(float(raw_model_prob or 0.0) * 100, 1),
        "rawModelProbability": raw_model_prob,
        "impliedProbability": round(float(implied_prob or 0.0) * 100, 1),
        "marketNoVigProbability": _unit_probability(safe_float(row.get("market_no_vig_prob"))) or implied_prob,
        "calibratedProbability": calibrated_prob,
        "fairOdds": round(float(fair_odds)) if fair_odds is not None else None,
        "edge": round(float(calibrated_edge or 0.0) * 100, 1),
        "rawEdge": round(float(raw_edge or 0.0) * 100, 1),
        "calibratedEdge": calibrated_edge,
        "evPerDollar": round(float(ev_per_dollar), 3) if ev_per_dollar is not None else None,
        "kellyFull": round(float(kelly_full), 3) if kelly_full is not None else 0.0,
        "kelly20": round(float(kelly_20), 3) if kelly_20 is not None else 0.0,
        "recommendation": row.get("recommendation"),
        "confidence": int(round(float(safe_float(row.get("confidence_score")) or 0.0))),
        "dataCompleteness": round(float(safe_float(row.get("data_completeness")) or 0.0) * 100, 1),
        "marketConfidence": round(float(safe_float(row.get("market_confidence")) or 0.0) * 100, 1),
        "modelConfidence": round(float(safe_float(row.get("model_confidence")) or 0.0) * 100, 1),
        "rank": int(safe_float(row.get("rank")) or 0),
        "rawRank": int(safe_float(row.get("rank")) or 0),
        "qualificationStatus": quality_status,
        "qualificationReasons": quality_reasons,
        "marketQualificationPolicy": MARKET_QUALIFICATION_POLICY.get(market_key),
        "qualificationPolicyVersion": settings.DEFAULT_QUALIFICATION_POLICY_VERSION,
        "rankingVersion": settings.DEFAULT_RANKING_VERSION,
        "calibrationStatus": cinfo.status,
        "calibrationMethod": cinfo.method,
        "calibrationVersion": cinfo.version,
        "marketProvider": market_snapshot.get("provider") if market_snapshot else None,
        "marketLastUpdated": market_snapshot.get("lastUpdated") if market_snapshot else None,
        "marketDataStatus": market_snapshot.get("dataStatus") if market_snapshot else "UNAVAILABLE",
        "booksTracked": market_snapshot.get("booksTracked") if market_snapshot else 0,
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

    production_eligible, eligibility_reason, validation_status = _market_eligibility(market_key)
    result["productionEligible"] = production_eligible
    result["eligibilityReason"] = eligibility_reason
    result["marketValidationStatus"] = validation_status

    # -----------------------------------------------------
    # MARKET INTELLIGENCE
    # -----------------------------------------------------

    market_intelligence = (
        get_market_intelligence(
            event_id=(
                row["api_event_id"]
            ),
            market=market_key,
            side=str(row.get("side") or "").lower(),
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
            away_team=str(row.get("away_team") or ""),
            home_team=str(row.get("home_team") or ""),
        )
        if injury_ctx is not None
        else InjuryMatchupContext().build_context(
            away_team=str(row.get("away_team") or ""),
            home_team=str(row.get("home_team") or ""),
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

    correlation_direction = str(row.get("side") or "").lower()
    team_exposure: list[str] = []
    if market_key in {"spread", "moneyline"}:
        if correlation_direction == "home":
            team_exposure = [home_code]
        elif correlation_direction == "away":
            team_exposure = [away_code]
    elif market_key == "total":
        team_exposure = [away_code, home_code]

    result["correlationMetadata"] = {
        "eventExposure": result["eventId"],
        "teamExposure": team_exposure,
        "marketFamily": _market_family_label(market_key),
        "marketDirection": correlation_direction,
        "correlationGroupId": f"{result['eventId']}:{_market_family_label(market_key)}:{correlation_direction or 'unknown'}",
    }

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


def _build_generated_multimarket_candidates(
    week_event_ids: set[str],
    projection_lookup: dict[str, pd.Series],
    market_snapshots: dict[str, dict],
) -> list[dict]:
    records = [
        row
        for row in market_data_service.load_normalized_market_rows()
        if str(row.get("eventId") or "") in week_event_ids and str(row.get("market") or "") in {"moneyline", "total"}
    ]
    if not records:
        return []

    df = pd.DataFrame(records)
    if df.empty:
        return []

    df = df.copy()
    df["api_event_id"] = df["eventId"].astype(str)
    df["commence_time"] = df.get("commenceTime")
    df["away_team"] = df.get("awayTeam")
    df["home_team"] = df.get("homeTeam")
    df["sportsbook"] = df.get("sportsbook")
    df["price"] = pd.to_numeric(df.get("americanOdds"), errors="coerce")
    df["point"] = pd.to_numeric(df.get("point"), errors="coerce")

    grouped = df.groupby(["api_event_id", "market", "side"], dropna=False, sort=False)
    selected_rows: list[pd.Series] = []
    group_map: dict[int, pd.DataFrame] = {}
    selection_prices: dict[tuple[str, str, str], float] = {}

    for _, group in grouped:
        selected = best_line_for_group(group)
        selected_rows.append(selected)
        group_map[id(selected)] = group.copy()
        price = safe_float(selected.get("price"))
        if price is not None:
            selection_prices[(str(selected.get("api_event_id") or ""), _market_key(str(selected.get("market") or "")), str(selected.get("side") or "").lower())] = float(price)

    candidates: list[dict] = []
    for selected in selected_rows:
        event_id = str(selected.get("api_event_id") or "")
        market = _market_key(str(selected.get("market") or ""))
        side = str(selected.get("side") or "").lower()
        price = safe_float(selected.get("price"))
        point = safe_float(selected.get("point"))

        projection = projection_lookup.get(event_id)
        model_margin = safe_float(projection.get("model_margin_home")) if projection is not None else None
        model_total = safe_float(projection.get("model_total_baseline")) if projection is not None else None

        if market == "moneyline":
            probs = moneyline_outcome_probabilities(model_margin_home=model_margin, side=side)
        elif market == "total":
            probs = total_outcome_probabilities(model_total=model_total, side=side, total_point=point)
        else:
            continue

        if probs.status != "AVAILABLE" or price is None:
            continue

        raw_model_prob = _unit_probability(probs.win)
        calibrated_prob = apply_guarded_isotonic(raw_model_prob)

        opposite_side = "away" if side == "home" else "home" if side == "away" else "under" if side == "over" else "over"
        opposite_price = selection_prices.get((event_id, market, opposite_side))

        no_vig_self, _ = _devig_two_way(price, opposite_price)
        implied_prob_raw = no_vig_self if no_vig_self is not None else _implied_probability_from_american(price)
        implied_prob_unit = _unit_probability(implied_prob_raw)

        calibrated_edge = None
        if calibrated_prob is not None and implied_prob_unit is not None:
            calibrated_edge = calibrated_prob - implied_prob_unit

        ev = ev_per_dollar_with_push(
            win_probability=float(probs.win),
            push_probability=float(probs.push),
            american_odds=float(price),
        )
        fair_odds = fair_price_from_win_push(win_probability=float(probs.win), push_probability=float(probs.push))

        snapshot = market_snapshots.get(event_id, {})
        books_tracked = int(snapshot.get("booksTracked") or 0)
        confidence_score = max(55.0, min(90.0, 55.0 + (books_tracked * 3.0)))

        recommendation, quality_status, quality_reasons = _qualify_market_candidate(
            market=market,
            calibrated_edge=calibrated_edge,
            current_ev=ev,
            confidence_score=confidence_score,
        )

        # Populate group EV for alternate-book display and observed threshold logic.
        group = group_map[id(selected)].copy()
        if market == "moneyline":
            group["ev_per_dollar"] = group["price"].apply(
                lambda p: ev_per_dollar_with_push(float(probs.win), float(probs.push), float(p)) if not pd.isna(p) else None
            )
        else:
            def _group_total_ev(row: pd.Series) -> float | None:
                p_point = safe_float(row.get("point"))
                p_price = safe_float(row.get("price"))
                if p_point is None or p_price is None:
                    return None
                p_probs = total_outcome_probabilities(model_total=model_total, side=side, total_point=p_point)
                if p_probs.status != "AVAILABLE":
                    return None
                return ev_per_dollar_with_push(float(p_probs.win), float(p_probs.push), float(p_price))

            group["ev_per_dollar"] = group.apply(_group_total_ev, axis=1)

        enriched = {
            "api_event_id": event_id,
            "commence_time": selected.get("commence_time"),
            "away_team": selected.get("away_team"),
            "home_team": selected.get("home_team"),
            "market": market,
            "side": side,
            "point": point,
            "sportsbook": selected.get("sportsbook"),
            "price": price,
            "model_prob": raw_model_prob,
            "implied_prob_raw": implied_prob_unit,
            "market_no_vig_prob": implied_prob_unit,
            "fair_odds": fair_odds,
            "edge_pp": calibrated_edge,
            "ev_per_dollar": ev,
            "kelly_full": 0.0,
            "kelly_20pct": 0.0,
            "recommendation": recommendation,
            "confidence_score": confidence_score,
            "data_completeness": 1.0 if projection is not None else 0.75,
            "market_confidence": max(0.0, min(1.0, books_tracked / 10.0)),
            "model_confidence": 0.7,
            "rank": 9999,
            "qualification_status": quality_status,
            "qualification_reasons": quality_reasons,
        }

        candidates.append(
            {
                "selected": pd.Series(enriched),
                "group": group,
                "groupMinRank": 9999,
            }
        )

    return candidates


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

    selected_point = safe_float(selected_row.get("point"))
    selected_price = safe_float(selected_row.get("price"))

    for _, row in (
        group.iterrows()
    ):
        row_point = safe_float(row.get("point"))
        row_price = safe_float(row.get("price"))
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
            and row_point == selected_point
            and row_price == selected_price
        ):
            continue

        edge_value = safe_float(row.get("edge_pp"))
        if edge_value is not None and edge_value > 1.0:
            edge_value = edge_value / 100.0

        ev_value = safe_float(row.get("ev_per_dollar"))

        alternates.append(
            {
                "book": (
                    row[
                        "sportsbook"
                    ]
                ),

                "point": row_point,

                "price": row_price,

                "edge": round(float(edge_value or 0.0) * 100, 1),

                "evPerDollar": round(float(ev_value), 3) if ev_value is not None else None,
            }
        )

    alternates.sort(
        key=lambda item: (
            float(item["point"]) if item["point"] is not None else float("-inf"),
            float(item["price"]) if item["price"] is not None else float("-inf"),
            float(item["evPerDollar"]) if item["evPerDollar"] is not None else float("-inf"),
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
    include_experimental: bool = False,
    week: int | None = Query(default=None),
):
    from app.services.games import service as games_service

    market_meta = market_data_service.metadata()
    if RANKED_BET_BOARD.exists():
        df = pd.read_csv(RANKED_BET_BOARD)
    else:
        df = pd.DataFrame()

    # Resolve week: default to first available week when no week param given
    all_games_payload = games_service.list_games()
    available_weeks: list[int] = all_games_payload.get("availableWeeks", [])
    resolved_week: int = week if week is not None else (available_weeks[0] if available_weeks else 1)

    # Filter to only eventIds belonging to the resolved week
    week_games_payload = games_service.list_games(week=resolved_week)
    week_event_ids: set[str] = {g["eventId"] for g in week_games_payload.get("games", [])}
    week_scheduled_games: int = len(week_event_ids)

    if not df.empty and "api_event_id" in df.columns:
        df["api_event_id"] = df["api_event_id"].astype(str)
        df = df[df["api_event_id"].isin(week_event_ids)]

    # One InjuryMatchupContext per request — one ESPN fetch total.
    shared_injury_ctx = InjuryMatchupContext()

    cinfo = calibration_info()
    market_snapshots = market_data_service.all_event_snapshots()
    projection_lookup = load_game_projection_lookup()

    if not best_lines_only:
        if df.empty:
            return {
                "count": 0,
                "week": resolved_week,
                "weekScheduledGames": week_scheduled_games,
                "weekQualifiedOpportunities": 0,
                "availableWeeks": available_weeks,
                "source": str(RANKED_BET_BOARD),
                "bestLinesOnly": False,
                "provider": market_meta["provider"],
                "lastUpdated": market_meta["lastUpdated"],
                "dataStatus": market_meta["dataStatus"],
                "calibrationStatus": cinfo.status,
                "calibrationMethod": cinfo.method,
                "calibrationVersion": cinfo.version,
                "opportunities": [],
            }

        df = df.sort_values("rank").head(limit)

        opportunities = []
        for week_rank, (_, row) in enumerate(df.iterrows(), start=1):
            opp = row_to_opportunity(
                row,
                market_snapshot=market_snapshots.get(str(row["api_event_id"])),
                injury_ctx=shared_injury_ctx,
                group_rows=df[(df["api_event_id"] == row["api_event_id"]) & (df["market"] == row["market"]) & (df["side"] == row["side"])],
                game_projection_row=projection_lookup.get(str(row["api_event_id"])),
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

    candidate_rows = []
    if not df.empty:
        grouped = df.groupby(
            [
                "api_event_id",
                "market",
                "side",
            ],
            dropna=False,
            sort=False,
        )

        for _, group in grouped:
            selected = best_line_for_group(group)
            group_min_rank = int(group["rank"].min()) if "rank" in group.columns else 9999
            model_prob = _unit_probability(safe_float(selected.get("model_prob")))
            implied_prob = _unit_probability(safe_float(selected.get("implied_prob_raw")))
            calibrated_prob = apply_guarded_isotonic(model_prob)
            calibrated_edge = (calibrated_prob - implied_prob) if calibrated_prob is not None and implied_prob is not None else -999.0
            candidate_rows.append(
                {
                    "selected": selected,
                    "group": group,
                    "alternates": make_alternate_books(group, selected),
                    "groupMinRank": group_min_rank,
                    "calibratedEdge": float(calibrated_edge),
                    "ev": float(safe_float(selected.get("ev_per_dollar")) or 0.0),
                    "confidence": float(safe_float(selected.get("confidence_score")) or 0.0),
                    "eventId": str(selected.get("api_event_id") or ""),
                    "market": _market_key(str(selected.get("market") or "")),
                    "side": str(selected.get("side") or ""),
                }
            )

    generated_candidates = _build_generated_multimarket_candidates(
        week_event_ids=week_event_ids,
        projection_lookup=projection_lookup,
        market_snapshots=market_snapshots,
    )

    existing_keys = {
        (
            str(item["selected"].get("api_event_id") or ""),
            _market_key(str(item["selected"].get("market") or "")),
            str(item["selected"].get("side") or "").lower(),
        )
        for item in candidate_rows
    }

    for gen in generated_candidates:
        selected = gen["selected"]
        key = (
            str(selected.get("api_event_id") or ""),
            _market_key(str(selected.get("market") or "")),
            str(selected.get("side") or "").lower(),
        )
        if key in existing_keys:
            continue
        model_prob = _unit_probability(safe_float(selected.get("model_prob")))
        implied_prob = _unit_probability(safe_float(selected.get("implied_prob_raw")))
        calibrated_prob = apply_guarded_isotonic(model_prob)
        calibrated_edge = (calibrated_prob - implied_prob) if calibrated_prob is not None and implied_prob is not None else -999.0
        candidate_rows.append(
            {
                "selected": selected,
                "group": gen["group"],
                "alternates": make_alternate_books(gen["group"], selected),
                "groupMinRank": int(gen.get("groupMinRank") or 9999),
                "calibratedEdge": float(calibrated_edge),
                "ev": float(safe_float(selected.get("ev_per_dollar")) or 0.0),
                "confidence": float(safe_float(selected.get("confidence_score")) or 0.0),
                "eventId": str(selected.get("api_event_id") or ""),
                "market": _market_key(str(selected.get("market") or "")),
                "side": str(selected.get("side") or ""),
            }
        )

    # Keep spread-first ordering for continuity; rank within each family by calibrated edge.
    market_priority = {"spread": 0, "moneyline": 1, "total": 2}
    candidate_rows.sort(
        key=lambda r: (
            market_priority.get(r["market"], 3),
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

    all_rows = []
    for week_rank, candidate in enumerate(candidate_rows, start=1):
        selected = candidate["selected"]
        item = row_to_opportunity(
            selected,
            include_alternates=candidate["alternates"],
            market_snapshot=market_snapshots.get(str(selected["api_event_id"])),
            injury_ctx=shared_injury_ctx,
            group_rows=candidate["group"],
            game_projection_row=projection_lookup.get(str(selected["api_event_id"])),
        )
        # globalResearchRank is fallback ordering for research (not validated cross-market quality).
        item["globalResearchRank"] = week_rank
        item["globalResearchRankingMethod"] = "MARKET_PRECEDENCE_FALLBACK"
        item["rank"] = week_rank
        item["weekRank"] = week_rank
        all_rows.append(item)

    by_market: dict[str, list[dict]] = {}
    for item in all_rows:
        key = str(item.get("market") or "")
        by_market.setdefault(key, []).append(item)

    for market_rows in by_market.values():
        market_rows.sort(key=lambda r: int(r.get("rank") or 9999))
        for idx, item in enumerate(market_rows, start=1):
            item["marketRank"] = idx

    for item in all_rows:
        item["crossMarketComparable"] = False
        item["normalizedRankingScore"] = (item.get("sportsIntelligenceScore") or {}).get("score")

    production_rows = [item for item in all_rows if bool(item.get("productionEligible"))]
    production_rows.sort(key=lambda r: int(r.get("globalResearchRank") or 9999))
    production_ids = {id(item) for item in production_rows}
    for idx, item in enumerate(production_rows, start=1):
        item["productionRank"] = idx
    for item in all_rows:
        if id(item) not in production_ids:
            item["productionRank"] = None

    best_rows = all_rows if include_experimental else production_rows
    for idx, item in enumerate(best_rows, start=1):
        item["rank"] = idx
        item["weekRank"] = idx

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
                "productionEligible": o.get("productionEligible"),
                "productionRank": o.get("productionRank"),
                "globalResearchRank": o.get("globalResearchRank"),
            }
            for o in best_rows
        ],
    }
    snapshot_id = _sha256(_canonical_json(snapshot_payload))

    for item in best_rows:
        item["snapshotId"] = snapshot_id
        item["snapshotTimestamp"] = market_meta.get("lastUpdated")

    return {
        "count": len(best_rows),
        "productionCount": len(production_rows),
        "experimentalCount": len(all_rows) - len(production_rows),
        "week": resolved_week,
        "weekScheduledGames": week_scheduled_games,
        "weekQualifiedOpportunities": len(best_rows),
        "availableWeeks": available_weeks,
        "source": str(RANKED_BET_BOARD),
        "bestLinesOnly": True,
        "includeExperimental": include_experimental,
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


@router.get("/decision-board")
def get_decision_board(
    limit: int = Query(default=3, ge=1, le=3),
    week: int | None = Query(default=None),
):
    payload = get_opportunities(limit=500, best_lines_only=True, week=week)
    opportunities = list(payload.get("opportunities") or [])
    board = build_decision_board_payload(
        opportunities,
        limit=limit,
        line_shopping_fn=_decision_board_line_shopping,
    )

    return {
        "week": payload.get("week"),
        "dataStatus": payload.get("dataStatus"),
        "lastUpdated": payload.get("lastUpdated"),
        "snapshotId": payload.get("snapshotId"),
        **board,
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
    from app.services.games import service as games_service

    game_row = None
    if GAME_PROJECTIONS.exists():
        game_df = pd.read_csv(GAME_PROJECTIONS)
        game_df["api_event_id"] = game_df["api_event_id"].astype(str)
        game_match = game_df[game_df["api_event_id"] == event_id]
        if not game_match.empty:
            game_row = game_match.iloc[0]

    market_snapshot = market_data_service.event_market_snapshot(event_id)

    target_week = None
    all_games = games_service.list_games()
    for week in all_games.get("availableWeeks", []):
        weekly = games_service.list_games(week=week)
        if any(str(g.get("eventId") or "") == str(event_id) for g in weekly.get("games", [])):
            target_week = week
            break

    production_bundle = get_opportunities(limit=500, best_lines_only=True, week=target_week)
    event_opportunities = [
        o for o in production_bundle.get("opportunities", [])
        if str(o.get("eventId") or "") == str(event_id)
    ]

    mixed_bundle = get_opportunities(limit=500, best_lines_only=True, include_experimental=True, week=target_week)
    mixed_event_opportunities = [
        o for o in mixed_bundle.get("opportunities", [])
        if str(o.get("eventId") or "") == str(event_id)
    ]

    if not event_opportunities:
        return {
            "eventId": event_id,
            "opportunity": None,
            "bestByMarket": {},
            "intelligenceReport": build_intelligence_report(
                event_id=event_id,
                opportunity=None,
                game_row=game_row,
                market_snapshot=market_snapshot,
            ),
        }

    event_opportunities.sort(key=lambda o: int(o.get("rank") or 9999))
    opportunity = event_opportunities[0]

    best_by_market: dict[str, dict] = {}
    for market in ["spread", "moneyline", "total"]:
        per_market = [o for o in mixed_event_opportunities if str(o.get("market") or "") == market]
        if not per_market:
            continue
        per_market.sort(key=lambda o: int(o.get("globalResearchRank") or o.get("rank") or 9999))
        best_by_market[market] = per_market[0]

    return {
        "eventId": event_id,
        "opportunity": opportunity,
        "bestByMarket": best_by_market,
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