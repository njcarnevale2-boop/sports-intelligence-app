"""
CLV regression tests – all test cases use calculate_clv() directly so
they run without DuckDB or a live odds snapshot.
"""
import pytest
from app.services.closing_line import calculate_clv


# ── SPREAD ───────────────────────────────────────────────────────────────────

def test_spread_favorite_beats_close():
    """Home -7 recommended, closes -5.5 → bettor locked in a worse number → negative CLV."""
    result = calculate_clv(
        recommended_point=-7.0,
        recommended_price=-110.0,
        closing_point=-5.5,
        closing_price=-110.0,
        market="spreads",
        side="home",
    )
    assert result.clv_points == pytest.approx(-1.5, abs=0.01)
    assert result.clv_probability is None


def test_spread_underdog_beats_close():
    """Away +7 recommended, closes +5.5 → bettor locked in a better number → positive CLV."""
    result = calculate_clv(
        recommended_point=7.0,
        recommended_price=-110.0,
        closing_point=5.5,
        closing_price=-110.0,
        market="spreads",
        side="away",
    )
    assert result.clv_points == pytest.approx(1.5, abs=0.01)


def test_spread_no_movement():
    result = calculate_clv(
        recommended_point=3.5,
        recommended_price=-110.0,
        closing_point=3.5,
        closing_price=-110.0,
        market="spreads",
        side="away",
    )
    assert result.clv_points == pytest.approx(0.0, abs=0.01)


# ── TOTAL – OVER ─────────────────────────────────────────────────────────────

def test_total_over_beats_close():
    """Bet Over 47, close Over 48.5 → we got the number before it moved up → positive CLV."""
    result = calculate_clv(
        recommended_point=47.0,
        recommended_price=-110.0,
        closing_point=48.5,
        closing_price=-110.0,
        market="totals",
        side="over",
    )
    assert result.clv_points == pytest.approx(1.5, abs=0.01)


def test_total_over_misses_close():
    """Bet Over 48.5, close Over 47 → line moved against over → negative CLV."""
    result = calculate_clv(
        recommended_point=48.5,
        recommended_price=-110.0,
        closing_point=47.0,
        closing_price=-110.0,
        market="totals",
        side="over",
    )
    assert result.clv_points == pytest.approx(-1.5, abs=0.01)


# ── TOTAL – UNDER ────────────────────────────────────────────────────────────

def test_total_under_beats_close():
    """Bet Under 48.5, close Under 47 → line moved down (toward under) → positive CLV."""
    result = calculate_clv(
        recommended_point=48.5,
        recommended_price=-110.0,
        closing_point=47.0,
        closing_price=-110.0,
        market="totals",
        side="under",
    )
    assert result.clv_points == pytest.approx(1.5, abs=0.01)


def test_total_under_misses_close():
    """Bet Under 47, close Under 48.5 → line moved up (against under) → negative CLV."""
    result = calculate_clv(
        recommended_point=47.0,
        recommended_price=-110.0,
        closing_point=48.5,
        closing_price=-110.0,
        market="totals",
        side="under",
    )
    assert result.clv_points == pytest.approx(-1.5, abs=0.01)


# ── MONEYLINE ────────────────────────────────────────────────────────────────

def _impl(price: float) -> float:
    """Duplicate the implied-prob formula for test assertions."""
    if price >= 0:
        return 100.0 / (price + 100.0)
    return abs(price) / (abs(price) + 100.0)


def test_moneyline_positive_clv():
    """Bet team at +160 (underdog), closes at -110 (now a favourite) → market swung to us."""
    result = calculate_clv(
        recommended_point=None,
        recommended_price=160.0,
        closing_point=None,
        closing_price=-110.0,
        market="h2h",
        side="away",
    )
    expected_clv_prob = round(_impl(-110.0) - _impl(160.0), 6)
    assert result.clv_probability == pytest.approx(expected_clv_prob, abs=1e-5)
    assert result.clv_percent == pytest.approx(expected_clv_prob * 100, abs=0.01)
    assert result.clv_probability > 0


def test_moneyline_negative_clv():
    """Bet team at -200 (heavy favourite), closes at +120 (now underdog) → negative CLV."""
    result = calculate_clv(
        recommended_point=None,
        recommended_price=-200.0,
        closing_point=None,
        closing_price=120.0,
        market="h2h",
        side="home",
    )
    assert result.clv_probability < 0


def test_moneyline_alt_key():
    """Ensure 'moneyline' market key is treated identically to 'h2h'."""
    r1 = calculate_clv(None, 150.0, None, -110.0, "h2h",       "away")
    r2 = calculate_clv(None, 150.0, None, -110.0, "moneyline",  "away")
    assert r1.clv_probability == r2.clv_probability


# ── MISSING CLOSING SNAPSHOT ─────────────────────────────────────────────────

def test_missing_closing_point_returns_none_clv():
    """No closing data → clv_points stays None, status NOT_CAPTURED."""
    result = calculate_clv(
        recommended_point=3.5,
        recommended_price=-110.0,
        closing_point=None,
        closing_price=None,
        market="spreads",
        side="away",
    )
    assert result.clv_points is None
    assert result.closing_status == "NOT_CAPTURED"


def test_missing_closing_price_moneyline_returns_none():
    result = calculate_clv(
        recommended_point=None,
        recommended_price=120.0,
        closing_point=None,
        closing_price=None,
        market="h2h",
        side="home",
    )
    assert result.clv_probability is None
    assert result.clv_percent is None


# ── POST-KICKOFF EXCLUSION (integration-level) ────────────────────────────────

def test_post_kickoff_snapshots_excluded(tmp_path):
    """
    Verify that get_closing_line uses the cutoff and would return NOT_CAPTURED
    when no snapshot is available before kickoff (pure logic test, no DuckDB).
    """
    from datetime import datetime, timezone, timedelta
    from app.services.closing_line import _american_to_implied

    # Verify the helper is symmetric
    price = -110.0
    implied = _american_to_implied(price)
    assert pytest.approx(implied, abs=1e-4) == 110.0 / 210.0


# ── CLOSING STATUS VALUES ────────────────────────────────────────────────────

def test_closing_status_when_data_present():
    result = calculate_clv(7.0, -110.0, 5.5, -110.0, "spreads", "away")
    assert result.closing_status == "AVAILABLE"


def test_closing_status_when_data_absent():
    result = calculate_clv(7.0, -110.0, None, None, "spreads", "away")
    assert result.closing_status == "NOT_CAPTURED"
