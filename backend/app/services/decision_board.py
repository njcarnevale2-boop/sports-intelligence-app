from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional


DecisionBoardLineShoppingFn = Callable[[dict[str, Any]], Optional[dict[str, Any]]]


def _parse_iso(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _derive_quote_freshness(last_updated: Any, now_utc: Optional[datetime] = None) -> str:
    now = now_utc or datetime.now(timezone.utc)
    ts = _parse_iso(last_updated)
    if ts is None:
        return "UNKNOWN"
    age_sec = (now - ts).total_seconds()
    if age_sec <= 300:
        return "FRESH"
    if age_sec <= 1800:
        return "WARM"
    return "STALE"


def _derive_market_depth(books_tracked: Any) -> str:
    try:
        count = int(books_tracked)
    except Exception:
        count = 0
    if count >= 6:
        return "DEEP"
    if count >= 3:
        return "MODERATE"
    if count == 2:
        return "THIN"
    if count == 1:
        return "SINGLE_BOOK"
    return "NO_BOOKS"


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _why_sia_likes_it(opp: dict[str, Any]) -> str:
    pick = str(opp.get("pick") or "This position")
    model_prob = _safe_float(opp.get("currentWinProbability"))
    market_prob = _safe_float(opp.get("marketNoVigProbability"))
    implied_prob_pct = _safe_float(opp.get("impliedProbability"))
    edge = _safe_float(opp.get("edge"))
    ev = _safe_float(opp.get("currentEV"))
    playable_to = opp.get("truePlayableTo")

    parts: list[str] = []
    if model_prob is not None:
        model_pct = model_prob * 100.0 if model_prob <= 1.0 else model_prob
        if market_prob is not None:
            market_pct = market_prob * 100.0 if market_prob <= 1.0 else market_prob
            parts.append(f"SIA projects {model_pct:.1f}% vs market {market_pct:.1f}% for {pick}.")
        elif implied_prob_pct is not None:
            parts.append(f"SIA projects {model_pct:.1f}% vs implied {implied_prob_pct:.1f}% for {pick}.")

    if edge is not None:
        parts.append(f"Current edge is {edge:.1f} percentage points.")
    if ev is not None:
        parts.append(f"Push-aware expected value is {ev:+.3f} per $1.")
    if playable_to is not None:
        parts.append(f"The position remains playable through {playable_to}.")

    if not parts:
        return "SIA retains a qualified spread edge at the currently executable price."
    return " ".join(parts)


def _risk_factors(opp: dict[str, Any], quote_freshness: str, market_depth: str) -> list[str]:
    factors: list[str] = []
    true_playable_to = opp.get("truePlayableTo")
    if true_playable_to is not None:
        factors.append(f"Line moving beyond {true_playable_to} would invalidate the playable threshold.")
    if quote_freshness == "STALE":
        factors.append("Quote freshness is stale; re-verify the market before placing a bet.")
    if market_depth in {"THIN", "SINGLE_BOOK", "NO_BOOKS"}:
        factors.append("Market depth is limited, which can reduce execution reliability.")
    injury_summary = str((opp.get("injuryContext") or {}).get("summary") or "").strip()
    if injury_summary:
        factors.append(f"Injury updates can change edge: {injury_summary}")
    if not factors:
        factors.append("Material injury, weather, or late market movement can invalidate the thesis.")
    return factors


def map_game_card_status(entry: dict[str, Any]) -> str:
    market_data_status = str(entry.get("marketDataStatus") or "").upper()
    recommendation = str(entry.get("recommendation") or "").upper()
    qualification = str(entry.get("qualificationStatus") or "").upper()
    production_eligible = bool(entry.get("productionEligible"))

    if market_data_status in {"UNAVAILABLE", "STALE"}:
        return "MARKET DATA LIMITED"
    if production_eligible and qualification == "QUALIFIED":
        return "SIA PLAY"
    if "LEAN" in recommendation:
        return "LEAN"
    if "WATCH" in recommendation:
        return "WATCH"
    return "NO EDGE"


def _closest_watch_item(opportunities: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    production_rows = [
        o for o in opportunities
        if bool(o.get("productionEligible")) and str(o.get("market") or "").lower() == "spread"
    ]
    if not production_rows:
        return None

    def _gap_value(opp: dict[str, Any]) -> float:
        current_ev = _safe_float(opp.get("currentEV"))
        min_ev = _safe_float(opp.get("minimumPlayableEV"))
        if current_ev is None or min_ev is None:
            return 9999.0
        return max(0.0, min_ev - current_ev)

    chosen = sorted(
        production_rows,
        key=lambda o: (
            _gap_value(o),
            int(o.get("rank") or 9999),
        ),
    )[0]

    gap = _gap_value(chosen)
    return {
        "eventId": chosen.get("eventId"),
        "selection": chosen.get("pick"),
        "marketFamily": str(chosen.get("marketType") or "").upper(),
        "distanceFromTrigger": None if gap >= 9999.0 else f"Needs +{gap:.3f} EV per $1 to qualify.",
    }


def _line_shopping_fallback(opp: dict[str, Any], now_utc: Optional[datetime]) -> dict[str, Any]:
    return {
        "bestMarketQuote": {
            "point": opp.get("point"),
            "americanPrice": opp.get("price"),
            "sportsbook": opp.get("book"),
            "quoteFreshness": _derive_quote_freshness(opp.get("marketLastUpdated"), now_utc=now_utc),
        },
        "bestPlayableQuote": {
            "point": opp.get("bestAvailableLine") if opp.get("bestAvailableLine") is not None else opp.get("point"),
            "americanPrice": opp.get("bestAvailablePrice") if opp.get("bestAvailablePrice") is not None else opp.get("price"),
            "sportsbook": opp.get("book"),
            "quoteFreshness": _derive_quote_freshness(opp.get("marketLastUpdated"), now_utc=now_utc),
        },
        "marketDepth": {
            "marketDepthStatus": _derive_market_depth(opp.get("booksTracked")),
            "bookCount": int(opp.get("booksTracked") or 0),
        },
        "status": "FALLBACK",
    }


def build_decision_board_payload(
    opportunities: list[dict[str, Any]],
    *,
    limit: int = 3,
    now_utc: Optional[datetime] = None,
    line_shopping_fn: Optional[DecisionBoardLineShoppingFn] = None,
) -> dict[str, Any]:
    now = now_utc or datetime.now(timezone.utc)

    official_candidates = [
        o for o in opportunities
        if bool(o.get("productionEligible"))
        and str(o.get("qualificationStatus") or "").upper() == "QUALIFIED"
    ]

    official_candidates.sort(key=lambda o: int(o.get("rank") or 9999))
    selected = official_candidates[: max(0, int(limit))]

    recommendations: list[dict[str, Any]] = []
    for index, opp in enumerate(selected, start=1):
        shopping = None
        if line_shopping_fn is not None:
            try:
                shopping = line_shopping_fn(opp)
            except Exception:
                shopping = None
        if not isinstance(shopping, dict):
            shopping = _line_shopping_fallback(opp, now)

        best_market = shopping.get("bestMarketQuote") or {}
        best_playable = shopping.get("bestPlayableQuote") or best_market
        market_depth_status = str((shopping.get("marketDepth") or {}).get("marketDepthStatus") or _derive_market_depth(opp.get("booksTracked")))
        quote_freshness = str(best_playable.get("quoteFreshness") or best_market.get("quoteFreshness") or _derive_quote_freshness(opp.get("marketLastUpdated"), now_utc=now))

        risk_factors = _risk_factors(opp, quote_freshness, market_depth_status)

        recommendation = {
            "rank": index,
            "eventId": opp.get("eventId"),
            "marketFamily": str(opp.get("marketType") or "").upper(),
            "selection": opp.get("pick"),
            "line": best_playable.get("point") if best_playable.get("point") is not None else opp.get("point"),
            "price": best_playable.get("americanPrice") if best_playable.get("americanPrice") is not None else opp.get("price"),
            "sportsbook": best_playable.get("sportsbook") or opp.get("book"),
            "bestAvailableLine": best_market.get("point") if best_market.get("point") is not None else opp.get("bestAvailableLine"),
            "bestAvailablePrice": best_market.get("americanPrice") if best_market.get("americanPrice") is not None else opp.get("bestAvailablePrice"),
            "bestAvailableSportsbook": best_market.get("sportsbook") or opp.get("book"),
            "playableTo": opp.get("truePlayableTo") if opp.get("truePlayableTo") is not None else opp.get("playableTo"),
            "modelProbability": opp.get("currentWinProbability") if opp.get("currentWinProbability") is not None else opp.get("rawModelProbability"),
            "marketImpliedProbability": opp.get("marketNoVigProbability"),
            "edge": opp.get("edge"),
            "expectedValue": opp.get("currentEV") if opp.get("currentEV") is not None else opp.get("evPerDollar"),
            "confidence": opp.get("confidence"),
            "marketDepth": market_depth_status,
            "quoteFreshness": quote_freshness,
            "gameStartTime": opp.get("commenceTime"),
            "recommendationStatus": opp.get("recommendation"),
            "productionEligible": bool(opp.get("productionEligible")),
            "whySiaLikesIt": _why_sia_likes_it(opp),
            "riskFactors": risk_factors,
            "invalidationReason": risk_factors[0] if risk_factors else None,
            "marketValidationStatus": opp.get("marketValidationStatus"),
            "qualificationStatus": opp.get("qualificationStatus"),
            "playableToStatus": opp.get("truePlayableToStatus") or opp.get("playableToStatus"),
            "quoteWarnings": {
                "isStale": quote_freshness == "STALE",
                "limitedDepth": market_depth_status in {"THIN", "SINGLE_BOOK", "NO_BOOKS"},
            },
        }
        recommendations.append(recommendation)

    no_bet_state = None
    if not recommendations:
        closest = _closest_watch_item(opportunities)
        no_bet_state = {
            "headline": "NO HIGH-CONVICTION BETS RIGHT NOW",
            "summary": "SIA scanned production-eligible opportunities and found no currently qualified bet at executable prices.",
            "closestOpportunity": closest,
        }

    return {
        "generatedAt": now.isoformat(),
        "decisionBoard": recommendations,
        "count": len(recommendations),
        "officialMarketsDisplayed": sorted({str(item.get("marketFamily") or "") for item in recommendations if str(item.get("marketFamily") or "")}),
        "noBetState": no_bet_state,
        "crossMarketComparable": False,
        "universalSia3": "DISABLED",
    }
