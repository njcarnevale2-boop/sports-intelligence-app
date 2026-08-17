from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


MODEL_ROOT = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9"
OUTPUTS_ROOT = MODEL_ROOT / "outputs"
WALKFORWARD_MULTI = OUTPUTS_ROOT / "walkforward_multiseason_predictions.csv"


@dataclass
class OutcomeProbabilities:
    win: float
    push: float
    loss: float
    status: str
    reason: Optional[str]


@dataclass
class HistoricalResiduals:
    margin_residuals: np.ndarray
    total_residuals: np.ndarray
    sample_size: int


@dataclass
class ThresholdResult:
    playable_to: Optional[float]
    status: str
    reason: Optional[str]


@lru_cache(maxsize=1)
def load_historical_residuals() -> Optional[HistoricalResiduals]:
    if not WALKFORWARD_MULTI.exists():
        return None

    try:
        df = pd.read_csv(WALKFORWARD_MULTI)
    except (OSError, pd.errors.EmptyDataError):
        return None

    required = {
        "home_score",
        "away_score",
        "model_margin",
        "model_total",
    }
    if not required.issubset(set(df.columns)):
        return None

    margin_actual = pd.to_numeric(df["home_score"], errors="coerce") - pd.to_numeric(df["away_score"], errors="coerce")
    total_actual = pd.to_numeric(df["home_score"], errors="coerce") + pd.to_numeric(df["away_score"], errors="coerce")

    margin_pred = pd.to_numeric(df["model_margin"], errors="coerce")
    total_pred = pd.to_numeric(df["model_total"], errors="coerce")

    margin_residuals = (margin_actual - margin_pred).dropna().to_numpy(dtype=float)
    total_residuals = (total_actual - total_pred).dropna().to_numpy(dtype=float)

    sample_size = int(min(len(margin_residuals), len(total_residuals)))
    if sample_size < 200:
        return None

    return HistoricalResiduals(
        margin_residuals=margin_residuals,
        total_residuals=total_residuals,
        sample_size=sample_size,
    )


def american_to_decimal(odds: float) -> float:
    return 1 + (100 / abs(odds) if odds < 0 else odds / 100)


def american_odds_from_probability(probability: Optional[float]) -> Optional[int]:
    if probability is None:
        return None

    if probability <= 0 or probability >= 1:
        return None

    if probability >= 0.5:
        value = -100.0 * probability / (1.0 - probability)
    else:
        value = 100.0 * (1.0 - probability) / probability

    if not np.isfinite(value):
        return None

    return int(round(value))


def ev_per_dollar_with_push(win_probability: float, push_probability: float, american_odds: float) -> float:
    dec = american_to_decimal(american_odds)
    profit_if_win = dec - 1
    loss_probability = max(0.0, 1.0 - win_probability - push_probability)
    return float(win_probability * profit_if_win - loss_probability)


def _simulated_margins(model_margin_home: float, residuals: np.ndarray) -> np.ndarray:
    # Football scoring is discrete; use integer margins for push-aware ATS outcomes.
    return np.rint(model_margin_home + residuals)


def _simulated_totals(model_total: float, residuals: np.ndarray) -> np.ndarray:
    return np.rint(model_total + residuals)


def spread_outcome_probabilities(
    model_margin_home: Optional[float],
    side: str,
    spread_point: Optional[float],
) -> OutcomeProbabilities:
    historical = load_historical_residuals()
    if historical is None:
        return OutcomeProbabilities(
            win=0.0,
            push=0.0,
            loss=0.0,
            status="UNAVAILABLE",
            reason="Historical residual distribution is unavailable or too small.",
        )

    if model_margin_home is None or spread_point is None:
        return OutcomeProbabilities(
            win=0.0,
            push=0.0,
            loss=0.0,
            status="UNAVAILABLE",
            reason="Model margin or spread point is missing.",
        )

    margins = _simulated_margins(model_margin_home, historical.margin_residuals)
    side_key = str(side or "").strip().lower()

    if side_key == "home":
        ats_value = margins + float(spread_point)
    elif side_key == "away":
        ats_value = -margins + float(spread_point)
    else:
        return OutcomeProbabilities(
            win=0.0,
            push=0.0,
            loss=0.0,
            status="UNAVAILABLE",
            reason="Unsupported spread side.",
        )

    win = float(np.mean(ats_value > 0))
    push = float(np.mean(ats_value == 0))
    loss = max(0.0, 1.0 - win - push)

    return OutcomeProbabilities(win=win, push=push, loss=loss, status="AVAILABLE", reason=None)


def total_outcome_probabilities(
    model_total: Optional[float],
    side: str,
    total_point: Optional[float],
) -> OutcomeProbabilities:
    historical = load_historical_residuals()
    if historical is None:
        return OutcomeProbabilities(
            win=0.0,
            push=0.0,
            loss=0.0,
            status="UNAVAILABLE",
            reason="Historical residual distribution is unavailable or too small.",
        )

    if model_total is None or total_point is None:
        return OutcomeProbabilities(
            win=0.0,
            push=0.0,
            loss=0.0,
            status="UNAVAILABLE",
            reason="Model total or market total point is missing.",
        )

    totals = _simulated_totals(model_total, historical.total_residuals)
    side_key = str(side or "").strip().lower()

    if side_key == "over":
        win = float(np.mean(totals > float(total_point)))
        push = float(np.mean(totals == float(total_point)))
    elif side_key == "under":
        win = float(np.mean(totals < float(total_point)))
        push = float(np.mean(totals == float(total_point)))
    else:
        return OutcomeProbabilities(
            win=0.0,
            push=0.0,
            loss=0.0,
            status="UNAVAILABLE",
            reason="Unsupported total side.",
        )

    loss = max(0.0, 1.0 - win - push)
    return OutcomeProbabilities(win=win, push=push, loss=loss, status="AVAILABLE", reason=None)


def fair_price_from_win_push(win_probability: float, push_probability: float) -> Optional[int]:
    non_push = 1.0 - push_probability
    if non_push <= 0:
        return None

    effective_win = win_probability / non_push
    return american_odds_from_probability(effective_win)


def _round_to_half(value: float) -> float:
    return round(value * 2) / 2.0


def true_playable_to_spread(
    model_margin_home: Optional[float],
    side: str,
    start_point: Optional[float],
    price: Optional[float],
    minimum_playable_ev: float,
) -> ThresholdResult:
    if model_margin_home is None or start_point is None or price is None:
        return ThresholdResult(playable_to=None, status="UNAVAILABLE", reason="Insufficient inputs for spread threshold.")

    if load_historical_residuals() is None:
        return ThresholdResult(playable_to=None, status="UNAVAILABLE", reason="Historical residual distribution unavailable.")

    current = _round_to_half(float(start_point))
    threshold: Optional[float] = None

    for _ in range(120):
        probs = spread_outcome_probabilities(model_margin_home=model_margin_home, side=side, spread_point=current)
        if probs.status != "AVAILABLE":
            return ThresholdResult(playable_to=None, status="UNAVAILABLE", reason=probs.reason)

        ev = ev_per_dollar_with_push(probs.win, probs.push, float(price))
        if ev >= minimum_playable_ev:
            threshold = current
            current -= 0.5
            continue
        break

    if threshold is None:
        return ThresholdResult(playable_to=None, status="UNAVAILABLE", reason="Current spread line does not meet minimum EV.")

    return ThresholdResult(playable_to=threshold, status="AVAILABLE", reason=None)


def true_playable_to_total(
    model_total: Optional[float],
    side: str,
    start_point: Optional[float],
    price: Optional[float],
    minimum_playable_ev: float,
) -> ThresholdResult:
    if model_total is None or start_point is None or price is None:
        return ThresholdResult(playable_to=None, status="UNAVAILABLE", reason="Insufficient inputs for total threshold.")

    if load_historical_residuals() is None:
        return ThresholdResult(playable_to=None, status="UNAVAILABLE", reason="Historical residual distribution unavailable.")

    side_key = str(side or "").strip().lower()
    if side_key not in {"over", "under"}:
        return ThresholdResult(playable_to=None, status="UNAVAILABLE", reason="Unsupported total side.")

    current = _round_to_half(float(start_point))
    threshold: Optional[float] = None

    for _ in range(120):
        probs = total_outcome_probabilities(model_total=model_total, side=side_key, total_point=current)
        if probs.status != "AVAILABLE":
            return ThresholdResult(playable_to=None, status="UNAVAILABLE", reason=probs.reason)

        ev = ev_per_dollar_with_push(probs.win, probs.push, float(price))
        if ev >= minimum_playable_ev:
            threshold = current
            current = current + 0.5 if side_key == "over" else current - 0.5
            continue
        break

    if threshold is None:
        return ThresholdResult(playable_to=None, status="UNAVAILABLE", reason="Current total line does not meet minimum EV.")

    return ThresholdResult(playable_to=threshold, status="AVAILABLE", reason=None)
