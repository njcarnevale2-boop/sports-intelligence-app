import math
from pathlib import Path

import numpy as np
import pandas as pd

from app.services import probability_engine
from app.services.probability_engine import (
    HistoricalResiduals,
    american_odds_from_probability,
    ev_per_dollar_with_push,
    total_outcome_probabilities,
)


def implied_prob_american(odds: float) -> float:
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def devig_two_way(odds_a: float, odds_b: float) -> tuple[float, float]:
    pa = implied_prob_american(float(odds_a))
    pb = implied_prob_american(float(odds_b))
    s = pa + pb
    return pa / s, pb / s


def _residuals() -> HistoricalResiduals:
    # Includes zeros so integer totals always have a measurable push component.
    return HistoricalResiduals(
        margin_residuals=np.array([-3.0, -1.0, 0.0, 1.0, 3.0]),
        total_residuals=np.array([-6.0, -3.0, -1.0, 0.0, 1.0, 3.0, 6.0]),
        sample_size=1000,
    )


def test_moneyline_probability_symmetry() -> None:
    home_prob = 0.61
    away_prob = 1.0 - home_prob

    assert abs((home_prob + away_prob) - 1.0) < 1e-12


def test_moneyline_american_odds_round_trip() -> None:
    probs = [0.35, 0.47, 0.53, 0.62]
    for p in probs:
        odds = american_odds_from_probability(p)
        assert odds is not None
        p_back = implied_prob_american(float(odds))
        # Integer American odds round-trip is approximate.
        assert abs(p_back - p) < 0.01


def test_moneyline_no_vig_normalization() -> None:
    home_novig, away_novig = devig_two_way(-120, +110)
    assert abs((home_novig + away_novig) - 1.0) < 1e-12
    assert 0.0 < home_novig < 1.0
    assert 0.0 < away_novig < 1.0


def test_total_over_under_symmetry(monkeypatch) -> None:
    monkeypatch.setattr(probability_engine, "load_historical_residuals", _residuals)

    over = total_outcome_probabilities(model_total=47.0, side="over", total_point=47.0)
    under = total_outcome_probabilities(model_total=47.0, side="under", total_point=47.0)

    assert over.status == "AVAILABLE"
    assert under.status == "AVAILABLE"
    assert abs(over.win - under.loss) < 1e-12
    assert abs(under.win - over.loss) < 1e-12
    assert abs(over.push - under.push) < 1e-12


def test_total_push_handling_and_integer_lines(monkeypatch) -> None:
    monkeypatch.setattr(probability_engine, "load_historical_residuals", _residuals)

    for total_line in [41.0, 42.0, 43.0, 44.0, 45.0, 46.0, 47.0, 48.0, 49.0, 50.0, 51.0]:
        over = total_outcome_probabilities(model_total=47.0, side="over", total_point=total_line)
        under = total_outcome_probabilities(model_total=47.0, side="under", total_point=total_line)

        assert over.push >= 0.0
        assert under.push >= 0.0
        assert abs((over.win + over.push + over.loss) - 1.0) < 1e-12
        assert abs((under.win + under.push + under.loss) - 1.0) < 1e-12


def test_total_ev_math_push_refund() -> None:
    # If win prob equals loss prob and push takes the rest, EV should be near zero at +100.
    ev = ev_per_dollar_with_push(win_probability=0.45, push_probability=0.10, american_odds=100)
    assert abs(ev) < 1e-12


def test_historical_as_of_time_feature_safety() -> None:
    path = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9" / "outputs" / "walkforward_multiseason_predictions.csv"
    assert path.exists(), "walkforward_multiseason_predictions.csv is required for as-of-time safety check"

    df = pd.read_csv(path, usecols=["season", "calibration_season"]).dropna()
    assert not df.empty

    # Prior-only requirement: calibration season strictly precedes evaluated season.
    violations = df[df["calibration_season"] >= df["season"]]
    assert violations.empty, f"Found {len(violations)} prior-only violations"
