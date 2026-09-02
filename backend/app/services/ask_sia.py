from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional

from app.routes.context import get_game_context
from app.routes.opportunities import get_game_best_opportunity, get_game_injury_context, get_game_weather, get_opportunities
from app.services.decision_ledger import get_latest_decision_by_snapshot_id
from app.services.games import service as games_service
from app.services.social_intelligence import social_intelligence_service


UNKNOWN_FALLBACK = "I don't have enough verified SIA data to answer that yet."


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _american_implied_probability(odds: float) -> float:
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def _quote_freshness(last_updated: Any) -> str:
    text = str(last_updated or "").strip()
    if not text:
        return "UNKNOWN"
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return "UNKNOWN"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    age_seconds = (now - parsed.astimezone(timezone.utc)).total_seconds()
    if age_seconds <= 300:
        return "FRESH"
    if age_seconds <= 1800:
        return "WARM"
    return "STALE"


def classify_intent(question: str) -> str:
    q = str(question or "").strip().lower()
    if not q:
        return "UNKNOWN"

    if "stronger" in q and (("spread" in q and "moneyline" in q) or ("spread" in q and "total" in q) or ("moneyline" in q and "total" in q)):
        return "CROSS_MARKET_COMPARE"

    if any(term in q for term in ["player prop", "player props", "prop", "team total", "first half", "1h"]):
        return "MARKET_FIREWALL"

    if any(term in q for term in ["moneyline", "total"]):
        if any(term in q for term in ["what about", "how about", "where", "best", "line", "bet", "price", "playable"]):
            return "MARKET_FIREWALL"

    if "best sportsbook" in q or "best price" in q:
        return "BEST_SPORTSBOOK"
    if "where should i bet" in q or "which book" in q or "best line" in q:
        return "BEST_SPORTSBOOK"
    if "value" in q and ("lost" in q or "lose" in q):
        return "VALUE_LOST"
    if "why is this still playable" in q or "why still playable" in q or "why does the model still" in q:
        return "WHY_STILL_PLAYABLE"
    if "how far can i bet this down" in q or "what is the worst line i should take" in q:
        return "PLAYABLE_BOUNDARY"
    if "what if this moves to" in q or "if the line moves" in q or "line movement" in q:
        return "PLAYABLE_CHECK"
    if "when does the model stop qualifying" in q or "model stop qualifying" in q:
        return "PASS_CONDITION"
    if "why aren" in q and ("bet" in q or "betting" in q or "wager" in q):
        return "NO_BET_REASON"
    if "why no bet" in q or "why not bet" in q or "why isn" in q and "bet" in q:
        return "NO_BET_REASON"
    if "why does" in q and "pass" in q:
        return "WHY_PASS"
    if "social" in q or "news" in q:
        return "SOCIAL"
    if "playable to mean" in q or "what does playable" in q:
        return "PLAYABLE_TO_MEANING"
    if "too expensive" in q or "too much" in q or "too high" in q or "current line" in q:
        return "PLAYABLE_BOUNDARY"
    if "still bet" in q or "still playable" in q or re.search(r"\bat\s*[+-]?\d", q):
        return "PLAYABLE_CHECK"
    if "what scares you" in q or "biggest risk" in q or "could this bet lose" in q:
        return "BIGGEST_RISK"
    if "what would make" in q and "pass" in q:
        return "PASS_CONDITION"
    if "what would make" in q and "qualify" in q:
        return "PASS_CONDITION"
    if "what changes" in q and ("bet" in q or "decision" in q):
        return "PASS_CONDITION"
    if "against the market" in q or "higher than the market" in q or "probability higher" in q:
        return "MARKET_VS_MODEL"
    if "has the line moved" in q or "line moved" in q or "moving toward" in q:
        return "LINE_TREND"
    if "compare" in q or "other sia 3" in q or "which pick does sia like most" in q or "strong is this" in q:
        return "SIA3_COMPARE"
    if "line getting worse" in q or "line worse" in q:
        return "LINE_TREND"
    if "injur" in q:
        return "INJURY"
    if "weather" in q:
        return "WEATHER"
    if "rest" in q or "travel" in q or "timezone" in q:
        return "REST_TRAVEL"
    if "why" in q:
        return "WHY"
    if "sia score" in q or ("score" in q and "sia" in q):
        return "SCORE"
    if "probability" in q:
        return "PROBABILITY"
    if "rank" in q and "sia 3" in q:
        return "RANK"
    if "bet or pass" in q or "bet/pass" in q or "pass" == q:
        return "BET_OR_PASS"
    return "UNKNOWN"


def _extract_hypothetical_value(question: str) -> Optional[float]:
    # Prefer signed values in betting contexts, fallback to first number.
    signed = re.findall(r"[+-]\d+(?:\.\d+)?", question)
    if signed:
        return _to_float(signed[0])

    plain = re.findall(r"\d+(?:\.\d+)?", question)
    if plain:
        return _to_float(plain[0])
    return None


def _playable_check(*, market: str, side: str, true_playable_to: Optional[float], hypothetical: Optional[float]) -> Optional[bool]:
    if true_playable_to is None or hypothetical is None:
        return None

    market_key = str(market or "").lower()
    side_key = str(side or "").lower()

    if market_key in {"spread", "spreads"}:
        # For spread bets, a higher number is always as-good-or-better for the bettor.
        return hypothetical >= true_playable_to

    if market_key in {"total", "totals"}:
        if side_key == "over":
            return hypothetical <= true_playable_to
        if side_key == "under":
            return hypothetical >= true_playable_to

    if market_key in {"moneyline", "h2h"}:
        return _american_implied_probability(hypothetical) <= _american_implied_probability(true_playable_to)

    return None


def _snapshot_note(snapshot_context: Optional[Dict[str, Any]], live_context: Optional[Dict[str, Any]]) -> Optional[str]:
    if not snapshot_context:
        return None

    snap_pick = snapshot_context.get("selection") or "Unknown selection"
    snap_price = snapshot_context.get("price")
    snap_book = snapshot_context.get("sportsbook") or "Unknown book"
    snap_part = f"AT PUBLICATION: {snap_pick} ({snap_price:+.0f}) at {snap_book}." if isinstance(snap_price, (int, float)) else f"AT PUBLICATION: {snap_pick} at {snap_book}."

    if not live_context:
        return snap_part

    live_pick = live_context.get("selection") or "Unknown selection"
    live_price = live_context.get("price")
    live_book = live_context.get("sportsbook") or "Unknown book"
    live_part = f"CURRENT LIVE MARKET: {live_pick} ({live_price:+.0f}) at {live_book}." if isinstance(live_price, (int, float)) else f"CURRENT LIVE MARKET: {live_pick} at {live_book}."

    return f"{snap_part} {live_part}"


def _missing_flags(context: Dict[str, Any]) -> Dict[str, bool]:
    weather = context.get("weather") or {}
    social = context.get("socialIntelligence") or {}
    injury = context.get("injuryContext") or {}

    weather_missing = str(weather.get("dataStatus") or "").upper() in {"UNAVAILABLE", ""}
    social_missing = bool(social) and social.get("isLive") is False
    injury_missing = str(injury.get("summary") or "").strip() == ""

    return {
        "weatherMissing": weather_missing,
        "socialMissing": social_missing,
        "injuryMissing": injury_missing,
    }


def _missing_messages_for_intent(intent: str, context: Dict[str, Any]) -> List[str]:
    flags = _missing_flags(context)
    messages: List[str] = []

    if intent == "WEATHER" and flags["weatherMissing"]:
        messages.append("Weather data is not currently available for this matchup.")
    if intent == "SOCIAL" and flags["socialMissing"]:
        messages.append("Live social intelligence is not connected yet.")
    if intent == "INJURY" and flags["injuryMissing"]:
        messages.append("SIA currently has no verified injury edge for this game.")
    if intent == "BIGGEST_RISK":
        if flags["weatherMissing"]:
            messages.append("Weather data is not currently available.")
        if flags["socialMissing"]:
            messages.append("Live social intelligence is not connected yet.")
    if intent == "REST_TRAVEL":
        rest_travel = context.get("restTravel") or {}
        if not rest_travel:
            messages.append("SIA doesn't currently have enough verified rest/travel context for this game.")

    return messages


def _no_bet_summary(context: Dict[str, Any]) -> tuple[str, List[str], str]:
    report_status = str(context.get("betStatus") or context.get("recommendation") or "").upper()
    reasons = [str(reason) for reason in (context.get("qualificationReasons") or []) if str(reason).strip()]
    why_summary = str(context.get("whySummary") or "").strip()
    trigger = (context.get("betTrigger") or {}).get("message") if isinstance(context.get("betTrigger"), dict) else None

    if report_status in {"NO QUALIFIED BET", "NO BET", "PASS", "INSUFFICIENT DATA"}:
        answer = why_summary or "SIA is passing on this game right now."
    else:
        answer = f"SIA currently sees this as {context.get('recommendation') or 'PASS'}."

    why = reasons[:3]
    if not why:
        why = ["The current market, price, and confidence do not clear SIA's qualification policy."]
    if trigger and trigger not in why:
        why.append(str(trigger))

    return answer, why[:3], trigger or "I don't have enough verified SIA data to identify a qualified bet right now."


def _shadow_market_answer(context: Dict[str, Any], question: str) -> tuple[str, List[str], str]:
    q = str(question or "").lower()
    market = str(context.get("market") or "").lower()
    selection = str(context.get("selection") or "that market")
    sportsbook = context.get("sportsbook")
    price = _to_float(context.get("price"))
    quote_freshness = str(context.get("quoteFreshness") or "UNKNOWN")

    if any(term in q for term in ["player prop", "player props", "prop"]):
        return (
            "SIA is collecting and analyzing player-prop data, but it does not currently issue validated player-prop recommendations.",
            ["Player props remain outside the validated production recommendation set."],
            "Validated player-prop recommendations are disabled.",
        )
    if "team total" in q:
        return (
            "SIA is collecting and analyzing team-total data, but it does not currently issue validated team-total recommendations.",
            ["Team totals remain outside the validated production recommendation set."],
            "Validated team-total recommendations are disabled.",
        )
    if "first half" in q or "1h" in q:
        return (
            "SIA is collecting and analyzing first-half data, but it does not currently issue validated first-half recommendations.",
            ["First-half markets remain outside the validated production recommendation set."],
            "Validated first-half recommendations are disabled.",
        )

    if market in {"moneyline", "total"}:
        if sportsbook and price is not None:
            line_text = f"{selection} ({price:+.0f}) at {sportsbook}"
        else:
            line_text = selection
        answer = f"{market.title()} is still shadow validation and not an official SIA bet."
        if quote_freshness == "STALE":
            answer += " The current quote is stale and should be re-verified before betting."
        if line_text:
            answer += f" Research view: {line_text}."
        why = [
            "Official production SIA3 remains spread-only.",
            f"{market.title()} is not currently production-eligible.",
        ]
        return answer, why, "Only the spread is eligible for production SIA3 right now."

    return (
        "SIA cannot promote that market into an official recommendation.",
        ["The market family is not production-eligible."],
        "That market family is not production-eligible.",
    )


def _format_playable_to_with_selection(selection: str, playable_to: Optional[float]) -> str:
    if playable_to is None:
        return "Unavailable"
    team = str(selection or "").split(" ")[0] or "Selection"
    return f"{team} {playable_to:+g}"


def _selection_at_hypothetical(selection: str, hypothetical: Optional[float]) -> str:
    team = str(selection or "").split(" ")[0] or "Selection"
    if hypothetical is None:
        return team
    return f"{team} {hypothetical:+g}"


def _is_qualified_pick(item: Dict[str, Any]) -> bool:
    q = str(item.get("qualificationStatus") or "").upper()
    if q:
        return q == "QUALIFIED"
    rec = str(item.get("recommendation") or "").upper()
    return "LEAN" not in rec and "WATCH" not in rec and rec != ""


def _build_sia3_rankings(top_sia3: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    rows = [item for item in (top_sia3 or []) if _is_qualified_pick(item)]
    rows = sorted(rows, key=lambda item: int(item.get("rank") or 999))
    rankings: List[Dict[str, Any]] = []
    for item in rows:
        score = _to_float((item.get("sportsIntelligenceScore") or {}).get("score"))
        rankings.append(
            {
                "rank": int(item.get("rank") or 0),
                "eventId": item.get("eventId"),
                "pick": item.get("pick"),
                "siScore": score,
                "recommendation": item.get("recommendation"),
                "calibratedProbability": _to_float(item.get("calibratedProbability") or item.get("currentWinProbability")),
                "impliedProbability": _to_float(item.get("impliedProbability")),
                "calibratedEdge": _to_float(item.get("calibratedEdge")),
                "pushAwareEV": _to_float(item.get("currentEV")),
            }
        )
    return rankings


def _comparison_structured(context: Dict[str, Any], rankings: List[Dict[str, Any]]) -> Dict[str, Any]:
    selection = str(context.get("selection") or "this pick")
    current_event = str(context.get("eventId") or "")
    current_pick = None
    for item in rankings:
        if str(item.get("eventId") or "") == current_event:
            current_pick = item
            break
        if str(item.get("pick") or "") == selection:
            current_pick = item
            break

    leader = rankings[0] if rankings else None

    current_rank = int(current_pick.get("rank")) if current_pick else None
    total = len(rankings)

    if current_pick is None:
        current_pick_reason = "This game is not currently in the qualified SIA 3 set."
    elif current_rank == 1:
        current_pick_reason = "This is currently SIA's #1 ranked selection."
    else:
        current_pick_reason = (
            f"{selection} has strong value signals, but {leader.get('pick')} currently has the higher overall SI Score and ranks ahead."
            if leader is not None
            else f"{selection} is currently ranked #{current_rank}."
        )

    leader_reason = ""
    if leader is not None and current_pick is not None and leader is not current_pick:
        leader_reason = f"{leader.get('pick')} leads due to stronger combined SI Score and value profile."
    elif leader is not None and current_pick is leader:
        leader_reason = "It leads on the current SI Score/value profile versus the other qualified picks."

    if current_pick is None:
        bottom_line = "This game is not currently one of the qualified SIA 3 picks."
    else:
        bottom_line = f"{selection} remains a {current_pick.get('recommendation')} in the current SIA 3 board."

    return {
        "currentPick": selection,
        "currentRank": current_rank,
        "totalQualified": total,
        "rankings": rankings,
        "currentPickReason": current_pick_reason,
        "leaderReason": leader_reason,
        "bottomLine": bottom_line,
    }


def _format_comparison_answer(structured: Dict[str, Any]) -> str:
    current_pick = structured.get("currentPick") or "This pick"
    current_rank = structured.get("currentRank")
    total = int(structured.get("totalQualified") or 0)
    rankings = structured.get("rankings") or []

    if total == 0:
        return "I don't have enough verified SIA data to compare qualified SIA 3 picks right now."

    if current_rank is None:
        headline = f"{current_pick} is not currently one of the qualified SIA 3 picks."
    else:
        headline = f"{current_pick} currently ranks #{current_rank} of {total} in The SIA 3."

    lines = [headline, "", "SIA 3 RANKING", ""]
    for item in rankings:
        si = _to_float(item.get("siScore"))
        score_text = f"{si:.1f}" if si is not None else "N/A"
        lines.append(f"#{item.get('rank')} {item.get('pick')} — SI Score {score_text} — {item.get('recommendation')}")

    lines.extend(
        [
            "",
            "WHY THIS PICK RANKS HERE",
            "",
            str(structured.get("currentPickReason") or ""),
        ]
    )

    leader_reason = str(structured.get("leaderReason") or "").strip()
    if leader_reason:
        lines.append(leader_reason)

    lines.extend(
        [
            "",
            "BOTTOM LINE",
            "",
            str(structured.get("bottomLine") or ""),
        ]
    )
    return "\n".join(lines)


def _verified_game_specific_risk(context: Dict[str, Any]) -> Optional[str]:
    selection = str(context.get("selection") or "this pick")
    side = str(context.get("side") or "").lower()
    market_intel = context.get("marketIntelligence") or {}
    injury = context.get("injuryContext") or {}
    rest = (context.get("restTravel") or {}).get("rest") or {}
    travel = (context.get("restTravel") or {}).get("travel") or {}
    weather = context.get("weather") or {}
    social = context.get("socialIntelligence") or {}

    severity = str(injury.get("severity") or "").lower()
    if severity in {"moderate", "significant", "major"}:
        return f"The biggest verified risk is injury pressure on {selection}."

    books_moving = _to_float(market_intel.get("booksMoving"))
    books_tracked = _to_float(market_intel.get("booksTracked"))
    if books_moving is not None and books_tracked and books_tracked > 0 and books_moving <= 1:
        return f"The biggest verified risk is market resistance. Only {int(books_moving)} of {int(books_tracked)} tracked books are moving with this side."

    rest_adv_home = _to_float(rest.get("advantageHomeDays"))
    if rest_adv_home is not None:
        if side == "home" and rest_adv_home < -0.5:
            return "The biggest verified risk is a rest disadvantage for the selected side."
        if side == "away" and rest_adv_home > 0.5:
            return "The biggest verified risk is a rest disadvantage for the selected side."

    away_miles = _to_float(travel.get("awayMiles"))
    tz_shift = _to_float(travel.get("awayTimezoneShiftHours"))
    if side == "away" and ((away_miles is not None and away_miles >= 1000) or (tz_shift is not None and abs(tz_shift) >= 2)):
        return "The biggest verified risk is travel burden for the selected side."

    weather_text = str(weather.get("summary") or "").lower()
    if str(weather.get("dataStatus") or "").upper() not in {"UNAVAILABLE", ""}:
        if any(token in weather_text for token in ["wind", "rain", "snow", "storm", "extreme"]):
            return "The biggest verified risk is weather volatility for this matchup."

    key_signals = social.get("keySignals") if isinstance(social, dict) else None
    if isinstance(key_signals, list):
        verified = [
            s
            for s in key_signals
            if str(s.get("status") or "").upper() in {"CORROBORATED", "OFFICIAL"}
            and _to_float(s.get("estimatedPointImpact")) is not None
        ]
        if verified:
            return "The biggest verified risk is a corroborated social signal that could move availability or pricing."

    return None


def _decision_boundary_text(context: Dict[str, Any]) -> str:
    selection = str(context.get("selection") or "Current pick")
    recommended_playable_to = _to_float(context.get("recommendedPlayableTo"))
    playable_to = _to_float(context.get("truePlayableTo"))
    decision_degradation = context.get("decisionDegradation") if isinstance(context.get("decisionDegradation"), dict) else {}
    stages = decision_degradation.get("stages") if isinstance(decision_degradation, dict) else []
    if recommended_playable_to is None and playable_to is None:
        return (
            "SIA does not currently publish an execution-validated worst line for this recommendation. "
            "The current executable recommendation is tied to the observed sportsbook quote."
        )

    team = str(selection or "").split(" ")[0] or "Selection"
    if recommended_playable_to is not None and playable_to is not None:
        transition_text = ""
        if isinstance(stages, list) and stages:
            ordered = []
            for stage in stages:
                rec = str(stage.get("recommendation") or "").upper()
                if rec and rec not in ordered:
                    ordered.append(rec)
            if ordered:
                transition_text = f" Model classification typically degrades as {' -> '.join(ordered)} as hypothetical lines worsen."
        return (
            f"The current executable recommendation is {selection} at the observed sportsbook quote. "
            f"SIA can simulate a theoretical model boundary near {team} {recommended_playable_to:+g} and a theoretical EV boundary near {team} {playable_to:+g}. "
            f"Those boundaries are model simulations, not execution recommendations and not observed sportsbook quotes.{transition_text}"
        )
    if recommended_playable_to is not None:
        return (
            f"The current executable recommendation is {selection} at the observed sportsbook quote. "
            f"SIA can simulate a theoretical model boundary near {team} {recommended_playable_to:+g}, but that is not an execution recommendation."
        )

    return (
        f"The current executable recommendation is {selection} at the observed sportsbook quote. "
        f"SIA can simulate a theoretical EV boundary near {_format_playable_to_with_selection(selection, playable_to)}, "
        "but that boundary is not execution-validated betting advice."
    )


def _move_value_summary(move: Dict[str, Any]) -> Dict[str, Any]:
    current = move.get("current") or {}
    hypothetical = move.get("hypothetical") or {}
    value_change = move.get("valueChange") or {}
    return {
        "selection": hypothetical.get("selection") or current.get("selection") or "this line",
        "status": hypothetical.get("status"),
        "statusReason": hypothetical.get("statusReason"),
        "inside": hypothetical.get("insidePlayableRange"),
        "boundary": hypothetical.get("atPlayableBoundary"),
        "playableTo": hypothetical.get("truePlayableTo") or current.get("truePlayableTo"),
        "currentWin": current.get("winProbability"),
        "hypoWin": hypothetical.get("winProbability"),
        "currentEv": current.get("pushAwareEV"),
        "hypoEv": hypothetical.get("pushAwareEV"),
        "currentEdge": current.get("edge"),
        "hypoEdge": hypothetical.get("edge"),
        "probabilityChange": value_change.get("probabilityChange"),
        "evChange": value_change.get("evChange"),
        "edgeChange": value_change.get("edgeChange"),
    }


def _build_structured_explanation(
    *,
    question: str,
    context: Dict[str, Any],
    intent: str,
    top_sia3: Optional[List[Dict[str, Any]]] = None,
    snapshot_context: Optional[Dict[str, Any]] = None,
    move_the_line: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    weather = context.get("weather") or {}
    injury = context.get("injuryContext") or {}
    social = context.get("socialIntelligence") or {}
    injury_summary = str(injury.get("summary") or "").strip()

    selection = str(context.get("selection") or "this side")
    calibrated_prob = _to_float(context.get("calibratedProbability"))
    implied_prob = _to_float(context.get("impliedProbability"))
    calibrated_edge = _to_float(context.get("calibratedEdge"))
    current_ev = _to_float(context.get("currentEV"))
    true_playable_to = _to_float(context.get("truePlayableTo"))
    side = str(context.get("side") or "")
    market = str(context.get("market") or "")
    recommendation = str(context.get("recommendation") or "PASS")
    si_score = _to_float(context.get("siScore"))
    production_eligible = bool(context.get("productionEligible")) if context.get("productionEligible") is not None else (market.lower() in {"spread", "spreads"})
    validation_status = str(context.get("marketValidationStatus") or "UNKNOWN")
    bet_status = str(context.get("betStatus") or "").upper()
    why_summary = str(context.get("whySummary") or "").strip()
    quote_freshness = str(context.get("quoteFreshness") or "UNKNOWN")
    best_available_price = _to_float(context.get("bestAvailablePrice"))
    best_available_line = _to_float(context.get("bestAvailableLine"))
    best_available_sportsbook = str(context.get("bestAvailableSportsbook") or context.get("sportsbook") or "").strip()

    primary_reason = ""
    supporting_reasons: List[str] = []
    risk_factors: List[str] = []
    biggest_reason_to_hesitate = ""
    decision_boundary = ""
    market_context = ""
    confidence_summary = ""
    comparison_structured = None

    if calibrated_prob is not None and implied_prob is not None:
        supporting_reasons.append(
            f"Calibrated probability ({calibrated_prob * 100:.1f}%) is above market implied probability ({implied_prob:.1f}%)."
        )
    if calibrated_edge is not None:
        supporting_reasons.append(f"Calibrated edge is {calibrated_edge * 100:.1f} percentage points.")
    if current_ev is not None:
        supporting_reasons.append(f"Push-aware EV is {current_ev:+.3f} per $1.")
    if si_score is not None:
        supporting_reasons.append(f"SI Score is {si_score:.1f} ({recommendation}).")
    if why_summary:
        supporting_reasons.append(why_summary)

    market_intel = context.get("marketIntelligence") or {}
    if market_intel:
        signal = market_intel.get("signal")
        books_moving = market_intel.get("booksMoving")
        books_tracked = market_intel.get("booksTracked")
        market_context = f"Market signal: {signal}. Books moving: {books_moving}/{books_tracked}."

    verified_risk = _verified_game_specific_risk(context)
    if verified_risk:
        risk_factors.append(verified_risk)
        biggest_reason_to_hesitate = verified_risk

    if not risk_factors:
        risk_factors.append("No major game-specific risk is currently verified.")
    if not biggest_reason_to_hesitate:
        biggest_reason_to_hesitate = risk_factors[0]

    decision_boundary = _decision_boundary_text(context)

    confidence_summary = f"SIA currently labels this as {recommendation}."

    answer = UNKNOWN_FALLBACK
    why = supporting_reasons[:3]
    what_changes = decision_boundary
    move_summary = _move_value_summary(move_the_line) if isinstance(move_the_line, dict) else None

    if intent == "NO_BET_REASON":
        answer = why_summary or "SIA is passing on this game right now."
        why = [reason for reason in (context.get("qualificationReasons") or []) if str(reason).strip()][:3]
        if not why:
            why = ["The current market, price, and confidence do not clear SIA's qualification policy."]
        trigger = context.get("betTrigger") or {}
        trigger_text = None
        if isinstance(trigger, dict) and str(trigger.get("message") or "").strip():
            trigger_text = str(trigger.get("message") or "").strip()
            if trigger_text not in why:
                why.append(trigger_text)
        if trigger_text:
            what_changes = trigger_text
        else:
            what_changes = decision_boundary
        primary_reason = "Canonical no-bet explanation."

    elif intent == "MARKET_FIREWALL":
        q = str(question or "").lower()
        if any(term in q for term in ["player prop", "player props", "prop"]):
            answer = "SIA is collecting and analyzing player-prop data, but it does not currently issue validated player-prop recommendations."
            why = ["Player props remain outside the validated production recommendation set."]
            what_changes = "Validated player-prop recommendations are disabled."
        elif "team total" in q:
            answer = "SIA is collecting and analyzing team-total data, but it does not currently issue validated team-total recommendations."
            why = ["Team totals remain outside the validated production recommendation set."]
            what_changes = "Validated team-total recommendations are disabled."
        elif "first half" in q or "1h" in q:
            answer = "SIA is collecting and analyzing first-half data, but it does not currently issue validated first-half recommendations."
            why = ["First-half markets remain outside the validated production recommendation set."]
            what_changes = "Validated first-half recommendations are disabled."
        else:
            answer = f"{market.title()} is still shadow validation and not an official SIA bet."
            if quote_freshness == "STALE":
                answer += " The current quote is stale and should be re-verified before betting."
            if best_available_sportsbook and best_available_price is not None:
                line_part = f" {best_available_line:+g}" if best_available_line is not None and market.lower() in {"spread", "total"} else ""
                answer += f" Research view: {selection}{line_part} ({best_available_price:+.0f}) at {best_available_sportsbook}."
            why = ["Official production SIA3 remains spread-only.", f"{market.title()} is not currently production-eligible."]
            what_changes = "Only the spread is eligible for production SIA3 right now."
        primary_reason = "Production firewall disclosure."

    if move_summary and intent == "WHY_STILL_PLAYABLE":
        if move_summary.get("inside"):
            selection_line = str(move_summary.get("selection") or selection)
            answer = (
                f"SIA currently recommends {selection} at the observed quote. "
                f"At hypothetical {selection_line}, the model would still classify this as BET under current assumptions. "
                "That result is a model simulation, not an execution recommendation."
            )
            why = [
                "Move-the-Line evaluates hypothetical spreads under a constant-price assumption.",
                f"Line-specific win probability is {(_to_float(move_summary.get('hypoWin')) or 0.0) * 100:.1f}% and push-aware EV is {(_to_float(move_summary.get('hypoEv')) or 0.0):+.3f} per $1.",
            ]
            what_changes = "If the hypothetical line worsens enough, the model eventually reclassifies from BET to LEAN/PASS under the same assumptions."
        else:
            answer = (
                f"SIA currently recommends {selection} at the observed quote. "
                "At this hypothetical line, the model no longer classifies the setup as a BET under current assumptions. "
                "That is a simulation output, not sportsbook execution guidance."
            )
            why = ["Deterministic model-classification status for the selected hypothetical line is PASS."]
        primary_reason = "Move-the-Line deterministic boundary check."

    elif move_summary and intent == "WHY_PASS":
        if move_summary.get("inside"):
            answer = (
                "At this hypothetical line, the model still classifies the setup as BET under current assumptions. "
                "That does not confirm a currently available sportsbook quote."
            )
            why = ["Deterministic model-classification status is BET for this line at the assumed price."]
        else:
            answer = (
                "At this hypothetical line, the model no longer qualifies the setup under current assumptions. "
                "The executable recommendation remains the observed sportsbook quote."
            )
            why = [
                "Status is determined directly from model simulation at the selected hypothetical spread and assumed price.",
                "Hypothetical classification is not execution-validated betting advice.",
            ]
        primary_reason = "Move-the-Line deterministic PASS status."

    elif move_summary and intent == "VALUE_LOST":
        prob_change = _to_float(move_summary.get("probabilityChange"))
        ev_change = _to_float(move_summary.get("evChange"))
        edge_change = _to_float(move_summary.get("edgeChange"))
        prob_text = f"{(prob_change or 0.0) * 100:+.1f} pts"
        ev_text = f"{(ev_change or 0.0):+.3f} per $1"
        edge_text = f"{(edge_change or 0.0) * 100:+.1f} pts"
        answer = f"Value change versus original: cover probability {prob_text}, EV {ev_text}, edge {edge_text}."
        why = [
            "These deltas come from canonical Move-the-Line engine outputs at the selected hypothetical spread and assumed odds.",
            f"Deterministic status remains {move_summary.get('status') or 'UNKNOWN'} for this line.",
        ]
        what_changes = "As the hypothetical line worsens, model probability/edge/EV can deteriorate until the model no longer qualifies the setup."
        primary_reason = "Move-the-Line value deterioration metrics."

    elif intent == "WHY":
        if bet_status in {"NO QUALIFIED BET", "INSUFFICIENT DATA", "PASS"} or "PASS" in recommendation.upper() or not production_eligible:
            answer = why_summary or "SIA is passing on this game right now."
            why = [reason for reason in (context.get("qualificationReasons") or []) if str(reason).strip()][:3]
            if not why:
                why = ["The current market, price, and confidence do not clear SIA's qualification policy."]
            primary_reason = "No-qualified-bet explanation."
        else:
            answer = f"SIA currently favors {selection} because this line still clears SIA's official bet standards."
            primary_reason = "Positive value based on calibrated probability versus price."
            why = []
            if calibrated_edge is not None:
                why.append(f"Model vs market: SIA remains {calibrated_edge * 100:.1f} points above market expectation on this side.")
            if current_ev is not None:
                why.append("Price quality: the current quote still clears SIA's official value threshold.")
            market_intel = context.get("marketIntelligence") or {}
            books_moving = _to_float(market_intel.get("booksMoving"))
            books_tracked = _to_float(market_intel.get("booksTracked"))
            signal = str(market_intel.get("signal") or "").strip()
            if books_moving is not None and books_tracked and books_tracked > 0:
                why.append(f"Market context: {int(books_moving)} of {int(books_tracked)} books are moving ({signal or 'signal unavailable'}).")
            recommended_playable_to = _to_float(context.get("recommendedPlayableTo"))
            current_point = _to_float(context.get("point"))
            team = selection.split(" ")[0] if selection else "Selection"
            if recommended_playable_to is not None and current_point is not None:
                why.append(
                    f"Model simulation: a theoretical model boundary is near {team} {recommended_playable_to:+g}, but executable recommendations are based on observed sportsbook quotes."
                )
            if len(why) < 2 and calibrated_prob is not None and implied_prob is not None:
                why.append(f"SIA probability remains above market implied probability for this selection.")
            why = why[:4]
            if not production_eligible:
                why.append("This market is currently in shadow validation and is not eligible for The SIA 3.")

    elif intent == "BIGGEST_RISK":
        if verified_risk:
            answer = verified_risk
            why = [
                "This is a verified risk from current SIA context, not a hypothetical scenario.",
            ]
        else:
            answer = "No major game-specific risk is currently verified."
            why = [
                "The primary measurable risk is model-value deterioration as the line and price move away from the observed quote.",
            ]
        primary_reason = "Risk concentration"

    elif intent == "PLAYABLE_CHECK":
        if move_summary:
            inside = move_summary.get("inside")
            selection_line = str(move_summary.get("selection") or selection)
            current_selection = str(context.get("selection") or selection)
            if inside is True:
                answer = (
                    f"SIA currently recommends {current_selection} at the observed sportsbook quote. "
                    f"At hypothetical {selection_line}, the model would still classify this as BET under current assumptions. "
                    "That is model simulation output, not an execution recommendation."
                )
            elif inside is False:
                answer = (
                    f"SIA currently recommends {current_selection} at the observed sportsbook quote. "
                    f"At hypothetical {selection_line}, the model would no longer classify this as BET under current assumptions. "
                    "That is model simulation output, not an execution recommendation."
                )
            else:
                answer = "I don't have enough verified SIA data to answer that yet."
            why = [
                f"Current observed executable recommendation: {current_selection}",
                "Move-the-Line uses a hypothetical spread with constant assumed price to isolate model behavior.",
            ]
            what_changes = (
                "Model still qualifies this hypothetical line under current assumptions."
                if inside is True
                else "Model no longer qualifies this hypothetical line under current assumptions."
                if inside is False
                else "Model classification changes as hypothetical lines and pricing assumptions worsen."
            )
            primary_reason = "Deterministic model-classification check."
            missing_data = _missing_messages_for_intent(intent, context)
            snapshot_note = _snapshot_note(snapshot_context=snapshot_context, live_context=context)

            return {
                "intent": intent,
                "answer": answer,
                "why": why,
                "whatChangesDecision": what_changes,
                "biggestReasonToHesitate": biggest_reason_to_hesitate,
                "structured": {
                    "primaryReason": primary_reason,
                    "supportingReasons": supporting_reasons,
                    "riskFactors": risk_factors,
                    "decisionBoundary": decision_boundary,
                    "missingData": missing_data,
                    "marketContext": market_context,
                    "confidenceSummary": confidence_summary,
                    "comparison": comparison_structured,
                },
                "snapshotNote": snapshot_note,
                "missingData": missing_data,
                "citations": [
                    "selection",
                    "price",
                    "sportsbook",
                    "calibratedProbability",
                    "pushProbability",
                    "lossProbability",
                    "calibratedEdge",
                    "currentEV",
                    "truePlayableTo",
                    "siScore",
                    "recommendation",
                    "marketIntelligence",
                    "injuryContext",
                    "weather",
                    "socialIntelligence",
                    "qualificationReasons",
                    "snapshotTimestamp",
                ],
            }

        hypo = _extract_hypothetical_value(question)
        playable = _playable_check(market=market, side=side, true_playable_to=true_playable_to, hypothetical=hypo)
        if playable is None:
            answer = "I don't have enough verified SIA data to answer that yet."
        else:
            hypothetical_selection = _selection_at_hypothetical(selection, hypo)
            if playable:
                answer = (
                    f"SIA currently recommends {selection} at the observed sportsbook quote. "
                    f"At hypothetical {hypothetical_selection}, the model would still classify this as BET under current assumptions. "
                    "That is model simulation output, not an execution recommendation."
                )
            else:
                answer = (
                    f"SIA currently recommends {selection} at the observed sportsbook quote. "
                    f"At hypothetical {hypothetical_selection}, the model would no longer classify this as BET under current assumptions. "
                    "That is model simulation output, not an execution recommendation."
                )
            why = [
                f"Current observed executable recommendation: {selection}",
                "Hypothetical line checks describe model behavior under current assumptions, not sportsbook quote availability.",
            ]
            what_changes = f"At hypothetical {hypothetical_selection}, the model is {'inside' if playable else 'outside'} the current theoretical qualification range."
        primary_reason = "Deterministic model-classification check."

    elif intent == "PLAYABLE_BOUNDARY":
        answer = (
            "SIA does not currently publish an execution-validated worst line for this bet. "
            f"The current executable recommendation is {selection} at the observed sportsbook quote. "
            "SIA can simulate model behavior at hypothetical lines, but those outputs are theoretical and not execution recommendations."
        )
        why = [
            "Observed sportsbook quotes determine executable recommendations.",
            "Theoretical boundaries are model diagnostics and are not validated as executable line advice.",
        ]
        what_changes = "If the market line/price changes, SIA must observe and re-evaluate that quote before treating it as executable guidance."
        primary_reason = "Execution recommendation is observed-quote-only for Week 1."

    elif intent == "PASS_CONDITION":
        answer = (
            f"The current executable recommendation is {selection} at the observed sportsbook quote. "
            "If line/price conditions worsen, model simulation can shift from BET to LEAN/PASS, but hypothetical thresholds are not execution recommendations."
        )
        why = [
            f"CURRENT BET: {selection}",
            "Model simulation can estimate where classification weakens under current assumptions.",
        ]
        what_changes = "SIA only treats an observed sportsbook quote as executable after re-evaluating that exact line and price."
        primary_reason = "Observed execution vs theoretical simulation distinction."

    elif intent == "MARKET_VS_MODEL":
        answer = "SIA is above market because the calibrated model probability is higher than implied market probability."
        primary_reason = "Calibrated probability disagreement with market."

    elif intent == "SIA3_COMPARE":
        rankings = _build_sia3_rankings(top_sia3)
        comparison_structured = _comparison_structured(context, rankings)
        answer = _format_comparison_answer(comparison_structured)
        why = [str(comparison_structured.get("currentPickReason") or "")]
        what_changes = "Ranking order can change as SI Score, calibrated edge, and EV update."
        primary_reason = "Canonical SIA 3 ranking."

    elif intent == "CROSS_MARKET_COMPARE":
        answer = (
            "SIA can compare the underlying metrics, but moneyline and totals are still in shadow validation "
            "and are not currently eligible to outrank a spread in The SIA 3."
        )
        why = [
            "Cross-market comparability is not yet statistically validated for production ranking.",
            "Production SIA 3 ranking currently evaluates only production-eligible market families.",
        ]
        what_changes = "Universal cross-market ranking requires validated prospective market-family comparability research."
        primary_reason = "Shadow-validation disclosure."

    elif intent == "LINE_TREND":
        if market_intel and market_intel.get("booksMoving") is not None:
            answer = f"SIA sees current line movement signal as {market_intel.get('signal')} across {market_intel.get('booksMoving')}/{market_intel.get('booksTracked')} books."
        else:
            answer = "I don't have enough verified SIA data to confirm directional line movement right now."
        primary_reason = "Observed market movement metadata."

    elif intent == "REST_TRAVEL":
        rest_travel = context.get("restTravel") or {}
        if not rest_travel:
            answer = "I don't have enough verified SIA data to answer that reliably."
            why = ["Verified rest/travel context is missing for this game."]
        else:
            rest = rest_travel.get("rest") or {}
            travel = rest_travel.get("travel") or {}
            parts: List[str] = []
            rest_text = str(rest.get("label") or rest.get("summary") or "").strip()
            if rest_text:
                parts.append(rest_text)
            travel_miles = _to_float(travel.get("awayMiles"))
            if travel_miles is not None:
                parts.append(f"Travel is {travel_miles:.0f} miles.")
            tz_shift = _to_float(travel.get("awayTimezoneShiftHours"))
            if tz_shift is not None:
                parts.append(f"Timezone shift is {tz_shift:+.1f} hours.")
            answer = " ".join(parts) if parts else "I don't have enough verified SIA data to answer that reliably."
            if not parts:
                why = ["Verified rest/travel context is missing for this game."]
        primary_reason = "Schedule context lookup."

    elif intent == "INJURY":
        if injury_summary:
            answer = f"Injury context for this pick: {injury_summary}"
        else:
            answer = "SIA currently has no verified injury edge for this game."
        primary_reason = "Injury context summary."

    elif intent == "WEATHER":
        if weather and str(weather.get("dataStatus") or "").upper() not in {"UNAVAILABLE", ""}:
            answer = f"Weather context: {weather.get('summary') or 'Weather data is available and monitored for this game.'}"
        else:
            answer = "Weather data is not currently available for this matchup."
        primary_reason = "Weather availability check."

    elif intent == "SOCIAL":
        if social and social.get("isLive") is False:
            answer = "Live social intelligence is not connected yet."
        else:
            summary = str(social.get("summary") or "").strip()
            answer = f"Social context: {summary}" if summary else "I don't have enough verified SIA social intelligence data to answer that yet."
        primary_reason = "Social intelligence availability check."

    elif intent == "PLAYABLE_TO_MEANING":
        answer = (
            "SIA does not currently publish an execution-validated Playable-To number. "
            "The executable recommendation is tied to the observed sportsbook quote. "
            "Boundary-style outputs are theoretical model simulations used for research."
        )
        why = [
            "The model can simulate hypothetical spreads and prices under current assumptions.",
            "A simulated boundary is not an observed sportsbook quote and not execution guidance.",
        ]
        what_changes = "Execution guidance changes only when SIA observes and re-evaluates the updated sportsbook quote."
        primary_reason = "Week 1 execution-safety semantics."

    elif intent == "BEST_SPORTSBOOK":
        sportsbook = best_available_sportsbook or context.get("sportsbook")
        price = best_available_price if best_available_price is not None else _to_float(context.get("price"))
        if sportsbook and price is not None:
            if best_available_line is not None and market.lower() in {"spread", "total"}:
                answer = f"The best current sportsbook price in SIA's canonical snapshot is {selection} {best_available_line:+g} ({price:+.0f}) at {sportsbook}."
            else:
                answer = f"The best current sportsbook price in SIA's canonical snapshot is {selection} ({price:+.0f}) at {sportsbook}."
            if quote_freshness == "STALE":
                answer += " The quote looks stale, so re-check it before betting."
        else:
            answer = "I don't have enough verified SIA data to identify the best sportsbook right now."
        primary_reason = "Canonical selected sportsbook for this recommendation."

    elif intent == "SCORE":
        if si_score is None:
            answer = "I don't have enough verified SIA data to provide the SI Score right now."
        else:
            answer = f"The current SI Score for this recommendation is {si_score:.1f}."
        primary_reason = "SI Score lookup."

    elif intent == "PROBABILITY":
        if calibrated_prob is None:
            answer = "I don't have enough verified SIA data to provide probability for this game right now."
        else:
            implied_text = f"{implied_prob:.1f}%" if implied_prob is not None else "the market implied probability"
            answer = f"SIA gives {selection} a {calibrated_prob * 100:.1f}% win/cover probability versus {implied_text}."
        primary_reason = "Probability lookup."

    elif intent == "RANK":
        rank = context.get("rank")
        if rank is None:
            answer = "I don't have enough verified SIA data to provide SIA 3 rank for this game right now."
        else:
            answer = f"This recommendation is currently rank #{rank} in The SIA 3 board ordering."
        primary_reason = "Canonical ranking lookup."

    elif intent == "BET_OR_PASS":
        answer = f"SIA currently sees this as {recommendation}."
        primary_reason = "Current recommendation label."

    if not production_eligible and intent in {"WHY", "PLAYABLE_CHECK", "PROBABILITY", "BET_OR_PASS", "RANK"}:
        what_changes = (
            f"{what_changes} This market remains {validation_status} and is not currently production-eligible for The SIA 3."
        ).strip()

    missing_data = _missing_messages_for_intent(intent, context)
    snapshot_note = _snapshot_note(snapshot_context=snapshot_context, live_context=context)

    return {
        "intent": intent,
        "answer": answer,
        "why": why,
        "whatChangesDecision": what_changes,
        "biggestReasonToHesitate": biggest_reason_to_hesitate,
        "structured": {
            "primaryReason": primary_reason,
            "supportingReasons": supporting_reasons,
            "riskFactors": risk_factors,
            "decisionBoundary": decision_boundary,
            "missingData": missing_data,
            "marketContext": market_context,
            "confidenceSummary": confidence_summary,
            "comparison": comparison_structured,
        },
        "snapshotNote": snapshot_note,
        "missingData": missing_data,
        "citations": [
            "selection",
            "price",
            "sportsbook",
            "calibratedProbability",
            "pushProbability",
            "lossProbability",
            "calibratedEdge",
            "currentEV",
            "truePlayableTo",
            "siScore",
            "recommendation",
            "marketIntelligence",
            "injuryContext",
            "weather",
            "socialIntelligence",
            "qualificationReasons",
            "snapshotTimestamp",
        ],
    }


def _build_live_context(event_id: str) -> Dict[str, Any]:
    game_bundle = get_game_best_opportunity(event_id)
    opportunity = game_bundle.get("opportunity") or {}
    best_by_market = game_bundle.get("bestByMarket") or {}
    report = game_bundle.get("intelligenceReport") or {}

    games_payload = games_service.list_games()
    game_row = next((row for row in (games_payload.get("games") or []) if str(row.get("eventId")) == str(event_id)), {})

    context_payload = get_game_context(event_id)
    injuries_payload = get_game_injury_context(event_id)
    weather_payload = get_game_weather(event_id)
    social_payload = social_intelligence_service.get_game_social_context(event_id)

    week = game_row.get("week")
    opportunities_payload = get_opportunities(limit=100, best_lines_only=True, week=week)
    top_sia3 = (opportunities_payload.get("opportunities") or [])[:3]
    bundle_snapshot_id = game_bundle.get("snapshotId") or opportunities_payload.get("snapshotId")

    return {
        "eventId": event_id,
        "teams": {
            "awayTeam": opportunity.get("awayTeam") or game_row.get("awayAbbreviation") or game_row.get("awayTeam"),
            "homeTeam": opportunity.get("homeTeam") or game_row.get("homeAbbreviation") or game_row.get("homeTeam"),
        },
        "selection": opportunity.get("pick"),
        "market": opportunity.get("market"),
        "side": opportunity.get("side"),
        "point": opportunity.get("point"),
        "price": opportunity.get("price"),
        "sportsbook": opportunity.get("book"),
        "consensusLine": game_row.get("spread"),
        "rawProbability": _to_float(opportunity.get("rawModelProbability")) or (_to_float(opportunity.get("modelProbability")) or 0.0) / 100.0,
        "calibratedProbability": _to_float(opportunity.get("calibratedProbability") or opportunity.get("currentWinProbability")),
        "pushProbability": _to_float(opportunity.get("currentPushProbability")),
        "lossProbability": _to_float(opportunity.get("currentLossProbability")),
        "impliedProbability": _to_float(opportunity.get("impliedProbability")),
        "calibratedEdge": _to_float(opportunity.get("calibratedEdge")),
        "currentEV": _to_float(opportunity.get("currentEV")),
        "fairLine": _to_float(opportunity.get("fairLine")),
        "truePlayableTo": _to_float(opportunity.get("truePlayableTo")),
        "siScore": _to_float((opportunity.get("sportsIntelligenceScore") or {}).get("score")),
        "recommendation": opportunity.get("recommendation") or report.get("betStatus"),
        "betStatus": report.get("betStatus"),
        "whySummary": report.get("whySummary"),
        "betTrigger": report.get("betTrigger"),
        "marketIntelligence": opportunity.get("marketIntelligence"),
        "decisionDegradation": opportunity.get("decisionDegradation"),
        "lineMovement": opportunity.get("marketIntelligence"),
        "restTravel": context_payload,
        "injuryContext": injuries_payload.get("injuryContext"),
        "weather": weather_payload.get("weather"),
        "socialIntelligence": social_payload,
        "qualificationReasons": opportunity.get("qualificationReasons") or report.get("qualificationReasons") or [],
        "snapshotTimestamp": opportunity.get("marketLastUpdated"),
        "marketLastUpdated": opportunity.get("marketLastUpdated"),
        "marketDataStatus": opportunity.get("marketDataStatus"),
        "quoteFreshness": _quote_freshness(opportunity.get("marketLastUpdated")),
        "bestAvailablePrice": opportunity.get("bestAvailablePrice"),
        "bestAvailableLine": opportunity.get("bestAvailableLine"),
        "bestAvailableSportsbook": opportunity.get("book"),
        "recommendedPlayableTo": _to_float(opportunity.get("recommendedPlayableTo")),
        "recommendedPlayableToStatus": opportunity.get("recommendedPlayableToStatus"),
        "recommendedPlayableToReason": opportunity.get("recommendedPlayableToReason"),
        "rank": opportunity.get("rank"),
        "snapshotId": bundle_snapshot_id,
        "topSia3": top_sia3,
        "bestByMarket": best_by_market,
        "marketValidationStatus": opportunity.get("marketValidationStatus"),
        "productionEligible": opportunity.get("productionEligible"),
    }


def _market_hint_from_question(question: str) -> Optional[str]:
    q = str(question or "").lower()
    if "moneyline" in q or "ml" in q:
        return "moneyline"
    if "total" in q or "over" in q or "under" in q:
        return "total"
    if "spread" in q:
        return "spread"
    return None


def _context_for_market(live_context: Dict[str, Any], market_key: Optional[str]) -> Dict[str, Any]:
    if not market_key:
        return live_context

    best_by_market = live_context.get("bestByMarket") or {}
    selected = best_by_market.get(market_key)
    if not isinstance(selected, dict):
        return live_context

    merged = dict(live_context)
    merged.update(
        {
            "selection": selected.get("pick"),
            "market": selected.get("market"),
            "side": selected.get("side"),
            "point": selected.get("point"),
            "price": selected.get("price"),
            "sportsbook": selected.get("book"),
            "calibratedProbability": selected.get("calibratedProbability") or selected.get("currentWinProbability"),
            "pushProbability": selected.get("currentPushProbability"),
            "lossProbability": selected.get("currentLossProbability"),
            "impliedProbability": selected.get("impliedProbability"),
            "calibratedEdge": selected.get("calibratedEdge"),
            "currentEV": selected.get("currentEV"),
            "fairLine": selected.get("fairLine"),
            "truePlayableTo": selected.get("truePlayableTo"),
            "siScore": (selected.get("sportsIntelligenceScore") or {}).get("score"),
            "recommendation": selected.get("recommendation"),
            "marketIntelligence": selected.get("marketIntelligence"),
            "decisionDegradation": selected.get("decisionDegradation"),
            "qualificationReasons": selected.get("qualificationReasons") or [],
            "betStatus": selected.get("betStatus"),
            "whySummary": selected.get("whySummary"),
            "betTrigger": selected.get("betTrigger"),
            "snapshotTimestamp": selected.get("marketLastUpdated"),
            "marketLastUpdated": selected.get("marketLastUpdated"),
            "marketDataStatus": selected.get("marketDataStatus"),
            "quoteFreshness": selected.get("quoteFreshness"),
            "bestAvailablePrice": selected.get("bestAvailablePrice"),
            "bestAvailableLine": selected.get("bestAvailableLine"),
            "bestAvailableSportsbook": selected.get("bestAvailableSportsbook") or selected.get("book"),
            "recommendedPlayableTo": selected.get("recommendedPlayableTo"),
            "recommendedPlayableToStatus": selected.get("recommendedPlayableToStatus"),
            "recommendedPlayableToReason": selected.get("recommendedPlayableToReason"),
            "rank": selected.get("rank"),
            "marketValidationStatus": selected.get("marketValidationStatus"),
            "productionEligible": selected.get("productionEligible"),
        }
    )
    return merged


def _build_snapshot_context(snapshot_id: str) -> Optional[Dict[str, Any]]:
    decision = get_latest_decision_by_snapshot_id(snapshot_id)
    if decision is None:
        return None
    return {
        "eventId": decision.get("eventId"),
        "selection": decision.get("selection"),
        "market": decision.get("market"),
        "side": decision.get("side"),
        "point": decision.get("point"),
        "price": decision.get("price"),
        "sportsbook": decision.get("sportsbook"),
        "calibratedProbability": decision.get("calibratedProbability"),
        "pushProbability": decision.get("pushProbability"),
        "lossProbability": decision.get("lossProbability"),
        "calibratedEdge": decision.get("calibratedEdge"),
        "currentEV": decision.get("currentEV"),
        "truePlayableTo": decision.get("truePlayableTo"),
        "siScore": decision.get("siScore"),
        "recommendation": decision.get("recommendation"),
        "snapshotTimestamp": decision.get("marketTimestamp") or decision.get("oddsTimestamp") or decision.get("publishedAtUTC"),
    }


def answer_from_context(
    *,
    event_id: str,
    question: str,
    live_context: Dict[str, Any],
    snapshot_id: Optional[str] = None,
    move_the_line: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    snapshot_context = _build_snapshot_context(snapshot_id) if snapshot_id else None
    intent = classify_intent(question)
    market_hint = _market_hint_from_question(question)
    scoped_context = _context_for_market(live_context, market_hint)

    response = _build_structured_explanation(
        question=question,
        context=scoped_context,
        intent=intent,
        top_sia3=live_context.get("topSia3"),
        snapshot_context=snapshot_context,
        move_the_line=move_the_line,
    )

    return {
        "eventId": event_id,
        "question": question,
        "intent": intent,
        "contextMode": "SNAPSHOT_AND_LIVE" if snapshot_context else "LIVE",
        "snapshotId": snapshot_id,
        "answer": response["answer"],
        "why": response["why"],
        "whatChangesDecision": response["whatChangesDecision"],
        "biggestReasonToHesitate": response.get("biggestReasonToHesitate"),
        "snapshotNote": response["snapshotNote"],
        "structured": response["structured"],
        "missingData": response["missingData"],
        "citations": response["citations"],
        "context": {
            "eventId": live_context.get("eventId"),
            "teams": live_context.get("teams"),
            "selection": scoped_context.get("selection"),
            "market": scoped_context.get("market"),
            "bestPrice": scoped_context.get("price"),
            "sportsbook": scoped_context.get("sportsbook"),
            "consensusLine": live_context.get("consensusLine"),
            "rawProbability": scoped_context.get("rawProbability"),
            "calibratedProbability": scoped_context.get("calibratedProbability"),
            "pushProbability": scoped_context.get("pushProbability"),
            "lossProbability": scoped_context.get("lossProbability"),
            "calibratedEdge": scoped_context.get("calibratedEdge"),
            "pushAwareEV": scoped_context.get("currentEV"),
            "fairLine": scoped_context.get("fairLine"),
            "playableTo": scoped_context.get("truePlayableTo"),
            "recommendedPlayableTo": scoped_context.get("recommendedPlayableTo"),
            "recommendedPlayableToStatus": scoped_context.get("recommendedPlayableToStatus"),
            "siScore": scoped_context.get("siScore"),
            "recommendation": scoped_context.get("recommendation"),
            "betStatus": scoped_context.get("betStatus"),
            "whySummary": scoped_context.get("whySummary"),
            "betTrigger": scoped_context.get("betTrigger"),
            "marketIntelligence": scoped_context.get("marketIntelligence"),
            "lineMovement": live_context.get("lineMovement"),
            "restTravel": live_context.get("restTravel"),
            "injuries": live_context.get("injuryContext"),
            "weather": live_context.get("weather"),
            "socialIntelligence": live_context.get("socialIntelligence"),
            "qualificationReasons": scoped_context.get("qualificationReasons"),
            "snapshotTimestamp": scoped_context.get("snapshotTimestamp"),
            "marketDataStatus": scoped_context.get("marketDataStatus"),
            "marketLastUpdated": scoped_context.get("marketLastUpdated"),
            "quoteFreshness": scoped_context.get("quoteFreshness"),
            "bestAvailablePrice": scoped_context.get("bestAvailablePrice"),
            "bestAvailableLine": scoped_context.get("bestAvailableLine"),
            "bestAvailableSportsbook": scoped_context.get("bestAvailableSportsbook"),
            "snapshotId": live_context.get("snapshotId"),
            "marketValidationStatus": scoped_context.get("marketValidationStatus"),
            "productionEligible": scoped_context.get("productionEligible"),
        },
    }


def get_ask_sia_response(
    *,
    event_id: str,
    question: str,
    snapshot_id: Optional[str] = None,
    move_the_line: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    live_context = _build_live_context(event_id)
    return answer_from_context(
        event_id=event_id,
        question=question,
        live_context=live_context,
        snapshot_id=snapshot_id,
        move_the_line=move_the_line,
    )
