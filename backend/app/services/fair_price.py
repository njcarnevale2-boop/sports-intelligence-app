from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

from app.services.probability_engine import (
    american_odds_from_probability,
    ev_per_dollar_with_push,
    fair_price_from_win_push,
    moneyline_outcome_probabilities,
    spread_outcome_probabilities,
    total_outcome_probabilities,
    true_playable_to_moneyline,
    true_playable_to_spread,
    true_playable_to_total,
)


@dataclass
class FairPriceResult:
    fair_price: Optional[int]
    fair_line: Optional[float]
    true_playable_to: Optional[float]
    true_playable_to_status: str
    true_playable_to_reason: Optional[str]
    worst_observed_playable_price: Optional[float]
    worst_observed_playable_price_status: str
    worst_observed_playable_price_reason: Optional[str]
    playable_to: Optional[float]
    playable_to_status: str
    playable_to_reason: Optional[str]
    current_win_probability: Optional[float]
    current_push_probability: Optional[float]
    current_loss_probability: Optional[float]
    current_ev: Optional[float]
    minimum_playable_ev: float
    best_available_price: Optional[float]
    best_available_line: Optional[float]


def safe_float(value: Any) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _line_desirability(market: str, side: str, point: Optional[float], price: Optional[float]) -> Optional[float]:
    market_key = str(market or "").strip().lower()
    side_key = str(side or "").strip().lower()

    if market_key == "moneyline" or market_key == "h2h":
        return price

    if point is None:
        return None

    if market_key == "spread":
        # Bigger point value is always better for the bettor on either side.
        return point

    if market_key == "total":
        if side_key == "over":
            # Lower number is better for over bettors.
            return -point
        if side_key == "under":
            # Higher number is better for under bettors.
            return point

    return None


def _build_observed_threshold_from_rows(
    market: str,
    side: str,
    group_rows: pd.DataFrame | None,
    minimum_playable_ev: float,
) -> tuple[Optional[float], str, Optional[str]]:
    if group_rows is None or group_rows.empty:
        return None, "UNAVAILABLE", "No sportsbook line set available for observed threshold calculation."

    candidates: list[tuple[float, float]] = []
    for _, row in group_rows.iterrows():
        point = safe_float(row.get("point"))
        price = safe_float(row.get("price"))
        ev = safe_float(row.get("ev_per_dollar"))

        if ev is None:
            continue
        if ev < minimum_playable_ev:
            continue

        desirability = _line_desirability(market=market, side=side, point=point, price=price)
        if desirability is None:
            continue

        threshold_value = price if str(market).lower() in {"moneyline", "h2h"} else point
        if threshold_value is None:
            continue

        candidates.append((desirability, float(threshold_value)))

    if not candidates:
        return None, "UNAVAILABLE", "No available sportsbook offer currently meets the minimum EV requirement."

    # Worst observed still-playable offer among currently available books.
    _, threshold = min(candidates, key=lambda item: item[0])
    return threshold, "AVAILABLE", None


def build_fair_price_result(
    row: pd.Series,
    group_rows: pd.DataFrame | None,
    game_projection_row: pd.Series | None,
    minimum_playable_ev: float,
) -> FairPriceResult:
    market = str(row.get("market", "")).strip().lower()
    side = str(row.get("side", "")).strip().lower()

    model_probability = safe_float(row.get("model_prob"))
    row_price = safe_float(row.get("price"))
    row_point = safe_float(row.get("point"))
    current_ev = safe_float(row.get("ev_per_dollar"))

    fair_price: Optional[int] = None
    fair_line: Optional[float] = None
    current_win_probability: Optional[float] = None
    current_push_probability: Optional[float] = None
    current_loss_probability: Optional[float] = None

    model_margin_home: Optional[float] = None
    if game_projection_row is not None:
        model_margin_home = safe_float(game_projection_row.get("model_margin_home"))

    if market in {"moneyline", "h2h"}:
        probs = moneyline_outcome_probabilities(model_margin_home=model_margin_home, side=side)
        if probs.status == "AVAILABLE":
            current_win_probability = probs.win
            current_push_probability = probs.push
        else:
            current_win_probability = model_probability
            current_push_probability = 0.0 if model_probability is not None else None

        if current_win_probability is not None:
            fair_price = fair_price_from_win_push(
                win_probability=current_win_probability,
                push_probability=float(current_push_probability or 0.0),
            )
        else:
            fair_price = american_odds_from_probability(model_probability)

        if row_price is not None and current_win_probability is not None:
            current_ev = ev_per_dollar_with_push(
                win_probability=current_win_probability,
                push_probability=float(current_push_probability or 0.0),
                american_odds=row_price,
            )

    if market == "spread" and game_projection_row is not None:
        if model_margin_home is not None:
            fair_line = -model_margin_home if side == "home" else model_margin_home

        spread_probs = spread_outcome_probabilities(
            model_margin_home=model_margin_home,
            side=side,
            spread_point=row_point,
        )
        if spread_probs.status == "AVAILABLE":
            current_win_probability = spread_probs.win
            current_push_probability = spread_probs.push
            if row_price is not None:
                current_ev = ev_per_dollar_with_push(
                    win_probability=spread_probs.win,
                    push_probability=spread_probs.push,
                    american_odds=row_price,
                )
            fair_price = fair_price_from_win_push(
                win_probability=spread_probs.win,
                push_probability=spread_probs.push,
            )

    model_total: Optional[float] = None
    if market == "total" and game_projection_row is not None:
        model_total = safe_float(game_projection_row.get("model_total_baseline"))
        if model_total is not None:
            fair_line = model_total

        total_probs = total_outcome_probabilities(
            model_total=model_total,
            side=side,
            total_point=row_point,
        )
        if total_probs.status == "AVAILABLE":
            current_win_probability = total_probs.win
            current_push_probability = total_probs.push
            if row_price is not None:
                current_ev = ev_per_dollar_with_push(
                    win_probability=total_probs.win,
                    push_probability=total_probs.push,
                    american_odds=row_price,
                )
            fair_price = fair_price_from_win_push(
                win_probability=total_probs.win,
                push_probability=total_probs.push,
            )

    worst_observed_playable_price, worst_observed_playable_price_status, worst_observed_playable_price_reason = _build_observed_threshold_from_rows(
        market=market,
        side=side,
        group_rows=group_rows,
        minimum_playable_ev=minimum_playable_ev,
    )

    true_playable_to: Optional[float] = None
    true_playable_to_status = "UNAVAILABLE"
    true_playable_to_reason: Optional[str] = "True threshold is not modeled for this market."

    if market == "spread":
        threshold = true_playable_to_spread(
            model_margin_home=model_margin_home,
            side=side,
            start_point=row_point,
            price=row_price,
            minimum_playable_ev=minimum_playable_ev,
        )
        true_playable_to = threshold.playable_to
        true_playable_to_status = threshold.status
        true_playable_to_reason = threshold.reason

    if market == "total":
        threshold = true_playable_to_total(
            model_total=model_total,
            side=side,
            start_point=row_point,
            price=row_price,
            minimum_playable_ev=minimum_playable_ev,
        )
        true_playable_to = threshold.playable_to
        true_playable_to_status = threshold.status
        true_playable_to_reason = threshold.reason

    if market in {"moneyline", "h2h"}:
        threshold = true_playable_to_moneyline(
            win_probability=current_win_probability,
            start_price=row_price,
            minimum_playable_ev=minimum_playable_ev,
        )
        true_playable_to = threshold.playable_to
        true_playable_to_status = threshold.status
        true_playable_to_reason = threshold.reason

    # Backward compatibility for existing clients reading playableTo fields.
    playable_to = worst_observed_playable_price
    playable_to_status = worst_observed_playable_price_status
    playable_to_reason = worst_observed_playable_price_reason

    if playable_to_status == "UNAVAILABLE" and current_ev is None:
        playable_to_reason = "Current EV is unavailable, so observed threshold cannot be validated."

    if current_win_probability is not None and current_push_probability is not None:
        current_loss_probability = max(0.0, 1.0 - current_win_probability - current_push_probability)

    return FairPriceResult(
        fair_price=fair_price,
        fair_line=round(fair_line, 2) if fair_line is not None else None,
        true_playable_to=round(true_playable_to, 2) if true_playable_to is not None else None,
        true_playable_to_status=true_playable_to_status,
        true_playable_to_reason=true_playable_to_reason,
        worst_observed_playable_price=worst_observed_playable_price,
        worst_observed_playable_price_status=worst_observed_playable_price_status,
        worst_observed_playable_price_reason=worst_observed_playable_price_reason,
        playable_to=playable_to,
        playable_to_status=playable_to_status,
        playable_to_reason=playable_to_reason,
        current_win_probability=round(current_win_probability, 6) if current_win_probability is not None else None,
        current_push_probability=round(current_push_probability, 6) if current_push_probability is not None else None,
        current_loss_probability=round(current_loss_probability, 6) if current_loss_probability is not None else None,
        current_ev=round(current_ev, 3) if current_ev is not None else None,
        minimum_playable_ev=float(minimum_playable_ev),
        best_available_price=row_price,
        best_available_line=row_point if market in {"spread", "total"} else None,
    )
