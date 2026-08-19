import numpy as np
import pandas as pd

from app.services import probability_engine
from app.services.fair_price import build_fair_price_result
from app.services.probability_engine import HistoricalResiduals, american_odds_from_probability


def _mock_residuals() -> HistoricalResiduals:
    # A small deterministic residual set for line-specific probability tests.
    return HistoricalResiduals(
        margin_residuals=np.array([-3.0, -1.0, 0.0, 1.0, 3.0]),
        total_residuals=np.array([-4.0, -2.0, 0.0, 2.0, 4.0]),
        sample_size=1000,
    )


def test_american_odds_from_probability_handles_favorite_and_dog() -> None:
    assert american_odds_from_probability(0.60) == -150
    assert american_odds_from_probability(0.40) == 150


def test_build_fair_price_result_moneyline_playable_threshold(monkeypatch) -> None:
    monkeypatch.setattr(probability_engine, "load_historical_residuals", _mock_residuals)

    row = pd.Series(
        {
            "market": "moneyline",
            "side": "away",
            "model_prob": 0.55,
            "ev_per_dollar": 0.04,
            "price": -110,
        }
    )

    group = pd.DataFrame(
        [
            {"market": "moneyline", "side": "away", "price": -105, "ev_per_dollar": 0.06},
            {"market": "moneyline", "side": "away", "price": -120, "ev_per_dollar": 0.03},
            {"market": "moneyline", "side": "away", "price": -130, "ev_per_dollar": -0.01},
        ]
    )

    result = build_fair_price_result(
        row=row,
        group_rows=group,
        game_projection_row=pd.Series({"model_margin_home": -1.5}),
        minimum_playable_ev=0.02,
    )

    assert result.fair_price is not None
    assert result.fair_price < 0
    assert result.fair_line is None
    assert result.true_playable_to is not None
    assert result.true_playable_to_status == "AVAILABLE"
    assert result.worst_observed_playable_price == -120
    assert result.playable_to == -120
    assert result.playable_to_status == "AVAILABLE"
    assert result.playable_to_reason is None
    assert result.current_win_probability is not None
    assert 0.0 < result.current_win_probability < 1.0
    assert result.current_push_probability == 0.0
    assert result.current_loss_probability is not None
    assert abs((result.current_win_probability + result.current_loss_probability) - 1.0) < 1e-6
    assert result.current_ev is not None
    assert result.minimum_playable_ev == 0.02


def test_build_fair_price_result_total_uses_projection_line_and_unavailable_reason(monkeypatch) -> None:
    monkeypatch.setattr(probability_engine, "load_historical_residuals", _mock_residuals)

    row = pd.Series(
        {
            "market": "total",
            "side": "over",
            "model_prob": 0.53,
            "ev_per_dollar": None,
            "point": 46.5,
            "price": -110,
        }
    )

    group = pd.DataFrame(
        [
            {"market": "total", "side": "over", "point": 47.5, "price": -110, "ev_per_dollar": None},
            {"market": "total", "side": "over", "point": 46.0, "price": -115, "ev_per_dollar": None},
        ]
    )

    projection = pd.Series(
        {
            "model_total_baseline": 45.8,
        }
    )

    result = build_fair_price_result(
        row=row,
        group_rows=group,
        game_projection_row=projection,
        minimum_playable_ev=0.20,
    )

    assert result.fair_price is not None
    assert result.fair_line == 45.8
    assert result.playable_to is None
    assert result.playable_to_status == "UNAVAILABLE"
    assert result.worst_observed_playable_price is None
    assert result.true_playable_to_status == "UNAVAILABLE"
    assert result.current_win_probability is not None
    assert result.current_push_probability is not None
    assert result.current_loss_probability is not None
    assert abs((result.current_win_probability + result.current_push_probability + result.current_loss_probability) - 1.0) < 1e-6


def test_build_fair_price_result_spread_home_line_orientation(monkeypatch) -> None:
    monkeypatch.setattr(probability_engine, "load_historical_residuals", _mock_residuals)

    row = pd.Series(
        {
            "market": "spread",
            "side": "home",
            "model_prob": 0.51,
            "ev_per_dollar": 0.015,
            "point": -2.5,
            "price": -110,
        }
    )

    group = pd.DataFrame(
        [
            {"market": "spread", "side": "home", "point": -3.0, "price": -110, "ev_per_dollar": 0.03},
            {"market": "spread", "side": "home", "point": -2.5, "price": -115, "ev_per_dollar": 0.02},
            {"market": "spread", "side": "home", "point": -1.5, "price": -120, "ev_per_dollar": -0.01},
        ]
    )

    projection = pd.Series(
        {
            "model_margin_home": 2.7,
        }
    )

    result = build_fair_price_result(
        row=row,
        group_rows=group,
        game_projection_row=projection,
        minimum_playable_ev=0.02,
    )

    assert result.fair_line == -2.7
    assert result.true_playable_to == -2.5
    assert result.true_playable_to_status == "AVAILABLE"
    assert result.worst_observed_playable_price == -3.0
    assert result.playable_to == -3.0
    assert result.playable_to_status == "AVAILABLE"
    assert result.current_loss_probability is not None
    assert result.true_playable_to != result.worst_observed_playable_price


def test_true_playable_to_can_differ_from_best_available_line(monkeypatch) -> None:
    monkeypatch.setattr(probability_engine, "load_historical_residuals", _mock_residuals)

    row = pd.Series(
        {
            "market": "spread",
            "side": "away",
            "model_prob": 0.55,
            "ev_per_dollar": 0.10,
            "point": 7.0,
            "price": -110,
        }
    )

    group = pd.DataFrame(
        [
            {"market": "spread", "side": "away", "point": 7.0, "price": -110, "ev_per_dollar": 0.10},
            {"market": "spread", "side": "away", "point": 6.5, "price": -110, "ev_per_dollar": 0.08},
            {"market": "spread", "side": "away", "point": 6.0, "price": -110, "ev_per_dollar": 0.06},
        ]
    )

    projection = pd.Series(
        {
            "model_margin_home": 3.0,
        }
    )

    result = build_fair_price_result(
        row=row,
        group_rows=group,
        game_projection_row=projection,
        minimum_playable_ev=0.02,
    )

    assert result.best_available_line == 7.0
    assert result.true_playable_to is not None
    assert result.true_playable_to < result.best_available_line
