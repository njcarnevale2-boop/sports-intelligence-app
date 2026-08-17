import numpy as np

from app.services import probability_engine
from app.services.probability_engine import (
    HistoricalResiduals,
    ev_per_dollar_with_push,
    spread_outcome_probabilities,
    total_outcome_probabilities,
    true_playable_to_spread,
    true_playable_to_total,
)


def _residuals() -> HistoricalResiduals:
    return HistoricalResiduals(
        margin_residuals=np.array([-3.0, -1.0, 0.0, 1.0, 3.0]),
        total_residuals=np.array([-4.0, -2.0, 0.0, 2.0, 4.0]),
        sample_size=1000,
    )


def test_spread_probability_changes_by_line_and_is_monotonic(monkeypatch) -> None:
    monkeypatch.setattr(probability_engine, "load_historical_residuals", _residuals)

    model_margin = 3.0

    p_plus_7 = spread_outcome_probabilities(model_margin_home=model_margin, side="away", spread_point=7.0)
    p_plus_6_5 = spread_outcome_probabilities(model_margin_home=model_margin, side="away", spread_point=6.5)
    p_plus_6 = spread_outcome_probabilities(model_margin_home=model_margin, side="away", spread_point=6.0)

    assert p_plus_7.status == "AVAILABLE"
    assert p_plus_7.win >= p_plus_6_5.win >= p_plus_6.win


def test_total_probability_changes_by_line_and_is_monotonic(monkeypatch) -> None:
    monkeypatch.setattr(probability_engine, "load_historical_residuals", _residuals)

    model_total = 47.0

    p_over_46_5 = total_outcome_probabilities(model_total=model_total, side="over", total_point=46.5)
    p_over_47 = total_outcome_probabilities(model_total=model_total, side="over", total_point=47.0)
    p_over_47_5 = total_outcome_probabilities(model_total=model_total, side="over", total_point=47.5)

    assert p_over_46_5.status == "AVAILABLE"
    assert p_over_46_5.win >= p_over_47.win >= p_over_47_5.win


def test_push_probability_present_on_integer_lines(monkeypatch) -> None:
    monkeypatch.setattr(probability_engine, "load_historical_residuals", _residuals)

    spread_probs = spread_outcome_probabilities(model_margin_home=3.0, side="away", spread_point=7.0)
    total_probs = total_outcome_probabilities(model_total=47.0, side="over", total_point=47.0)

    assert spread_probs.push >= 0
    assert total_probs.push > 0


def test_win_push_loss_sum_to_one(monkeypatch) -> None:
    monkeypatch.setattr(probability_engine, "load_historical_residuals", _residuals)

    spread_probs = spread_outcome_probabilities(model_margin_home=-2.5, side="home", spread_point=3.0)
    total_probs = total_outcome_probabilities(model_total=43.0, side="under", total_point=43.0)

    assert abs((spread_probs.win + spread_probs.push + spread_probs.loss) - 1.0) < 1e-9
    assert abs((total_probs.win + total_probs.push + total_probs.loss) - 1.0) < 1e-9


def test_ev_with_push_differs_by_price_same_line(monkeypatch) -> None:
    monkeypatch.setattr(probability_engine, "load_historical_residuals", _residuals)

    probs = spread_outcome_probabilities(model_margin_home=3.0, side="away", spread_point=6.5)

    ev_worse_price = ev_per_dollar_with_push(probs.win, probs.push, -120)
    ev_better_price = ev_per_dollar_with_push(probs.win, probs.push, -105)

    assert ev_better_price > ev_worse_price


def test_true_playable_to_spread_threshold(monkeypatch) -> None:
    monkeypatch.setattr(probability_engine, "load_historical_residuals", _residuals)

    threshold = true_playable_to_spread(
        model_margin_home=3.0,
        side="away",
        start_point=7.0,
        price=-110,
        minimum_playable_ev=0.02,
    )

    assert threshold.status == "AVAILABLE"
    assert threshold.playable_to is not None
    assert threshold.playable_to <= 7.0


def test_true_playable_to_total_threshold(monkeypatch) -> None:
    monkeypatch.setattr(probability_engine, "load_historical_residuals", _residuals)

    threshold = true_playable_to_total(
        model_total=47.0,
        side="over",
        start_point=46.5,
        price=-110,
        minimum_playable_ev=0.02,
    )

    assert threshold.status == "AVAILABLE"
    assert threshold.playable_to is not None
    assert threshold.playable_to >= 46.5


def test_unavailable_when_residuals_missing(monkeypatch) -> None:
    monkeypatch.setattr(probability_engine, "load_historical_residuals", lambda: None)

    spread_probs = spread_outcome_probabilities(model_margin_home=1.0, side="home", spread_point=-1.5)
    total_probs = total_outcome_probabilities(model_total=45.0, side="over", total_point=45.5)

    assert spread_probs.status == "UNAVAILABLE"
    assert total_probs.status == "UNAVAILABLE"
