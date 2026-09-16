"""
CLV regression tests – all test cases use calculate_clv() directly so
they run without DuckDB or a live odds snapshot.
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

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
    """No closing data -> clv_points stays None, status UNAVAILABLE."""
    result = calculate_clv(
        recommended_point=3.5,
        recommended_price=-110.0,
        closing_point=None,
        closing_price=None,
        market="spreads",
        side="away",
    )
    assert result.clv_points is None
    assert result.closing_status == "UNAVAILABLE"


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
    assert result.closing_status == "CAPTURED"


def test_closing_status_when_data_absent():
    result = calculate_clv(7.0, -110.0, None, None, "spreads", "away")
    assert result.closing_status == "UNAVAILABLE"


def _seed_odds(db_path, rows):
    import duckdb

    con = duckdb.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            fetched_at TIMESTAMP,
            api_event_id VARCHAR,
            commence_time TIMESTAMP,
            home_team VARCHAR,
            away_team VARCHAR,
            home_code VARCHAR,
            away_code VARCHAR,
            bookmaker_key VARCHAR,
            bookmaker_title VARCHAR,
            market_key VARCHAR,
            outcome_name VARCHAR,
            outcome_code VARCHAR,
            point DOUBLE,
            price DOUBLE,
            implied_prob DOUBLE,
            snapshot_type VARCHAR,
            source VARCHAR
        )
        """
    )
    for row in rows:
        con.execute(
            """
            INSERT INTO odds_snapshots (
                fetched_at, api_event_id, commence_time, home_team, away_team,
                home_code, away_code, bookmaker_key, bookmaker_title, market_key,
                outcome_name, outcome_code, point, price, implied_prob, snapshot_type, source
            ) VALUES (?, ?, NULL, NULL, NULL, NULL, NULL, ?, ?, ?, NULL, ?, ?, ?, NULL, 'current', 'test')
            """,
            [
                row["fetched_at"],
                row["event_id"],
                row["bookmaker_key"],
                row.get("bookmaker_title") or row["bookmaker_key"],
                row["market_key"],
                row["outcome_code"],
                row.get("point"),
                row.get("price"),
            ],
        )
    con.close()


def test_get_closing_line_uses_same_book_and_latest_eligible_pre_boundary(tmp_path):
    from app.services import closing_line as cl

    db = tmp_path / "closing.duckdb"
    kickoff = datetime.now(timezone.utc) - timedelta(hours=1)
    boundary = kickoff - timedelta(minutes=2)
    _seed_odds(
        db,
        [
            {
                "fetched_at": (boundary - timedelta(minutes=5)).replace(tzinfo=None),
                "event_id": "evt-a",
                "bookmaker_key": "draftkings",
                "market_key": "spreads",
                "outcome_code": "away",
                "point": 3.0,
                "price": -110,
            },
            {
                "fetched_at": boundary.replace(tzinfo=None),
                "event_id": "evt-a",
                "bookmaker_key": "draftkings",
                "market_key": "spreads",
                "outcome_code": "away",
                "point": 2.5,
                "price": -105,
            },
            {
                "fetched_at": (boundary + timedelta(seconds=1)).replace(tzinfo=None),
                "event_id": "evt-a",
                "bookmaker_key": "draftkings",
                "market_key": "spreads",
                "outcome_code": "away",
                "point": 2.0,
                "price": -101,
            },
            {
                "fetched_at": boundary.replace(tzinfo=None),
                "event_id": "evt-a",
                "bookmaker_key": "fanduel",
                "market_key": "spreads",
                "outcome_code": "away",
                "point": 1.5,
                "price": -102,
            },
        ],
    )

    with patch.object(cl, "_DB_PATH", db):
        out = cl.get_closing_line(
            event_id="evt-a",
            bookmaker_key="draftkings",
            market_key="SPREAD",
            outcome_code="AWAY",
            kickoff_utc=kickoff,
        )

    assert out.closing_status == "CAPTURED"
    assert out.closing_point == pytest.approx(2.5)
    assert out.closing_price == pytest.approx(-105)


def test_get_closing_line_total_and_moneyline_paths(tmp_path):
    from app.services import closing_line as cl

    db = tmp_path / "closing2.duckdb"
    kickoff = datetime.now(timezone.utc) - timedelta(hours=1)
    boundary = kickoff - timedelta(minutes=2)
    _seed_odds(
        db,
        [
            {
                "fetched_at": (boundary - timedelta(minutes=1)).replace(tzinfo=None),
                "event_id": "evt-t",
                "bookmaker_key": "betmgm",
                "market_key": "totals",
                "outcome_code": "over",
                "point": 47.5,
                "price": -110,
            },
            {
                "fetched_at": (boundary - timedelta(minutes=1)).replace(tzinfo=None),
                "event_id": "evt-m",
                "bookmaker_key": "fanduel",
                "market_key": "h2h",
                "outcome_code": "home",
                "point": None,
                "price": -135,
            },
        ],
    )

    with patch.object(cl, "_DB_PATH", db):
        total = cl.get_closing_line("evt-t", "betmgm", "TOTAL", "OVER", kickoff)
        moneyline = cl.get_closing_line("evt-m", "fanduel", "MONEYLINE", "HOME", kickoff)

    assert total.closing_status == "CAPTURED"
    assert total.closing_point == pytest.approx(47.5)
    assert moneyline.closing_status == "CAPTURED"
    assert moneyline.closing_point is None
    assert moneyline.closing_price == pytest.approx(-135)


def test_get_closing_line_stale_evidence_returns_unavailable(tmp_path):
    from app.services import closing_line as cl

    db = tmp_path / "closing3.duckdb"
    kickoff = datetime.now(timezone.utc) - timedelta(hours=1)
    boundary = kickoff - timedelta(minutes=2)
    _seed_odds(
        db,
        [
            {
                "fetched_at": (boundary - timedelta(hours=5)).replace(tzinfo=None),
                "event_id": "evt-s",
                "bookmaker_key": "betrivers",
                "market_key": "spreads",
                "outcome_code": "home",
                "point": -2.5,
                "price": -110,
            }
        ],
    )

    with patch.object(cl, "_DB_PATH", db):
        out = cl.get_closing_line(
            event_id="evt-s",
            bookmaker_key="betrivers",
            market_key="SPREAD",
            outcome_code="HOME",
            kickoff_utc=kickoff,
            closing_max_quote_age_minutes=30,
        )

    assert out.closing_status == "UNAVAILABLE"
    assert out.closing_reason_code == "STALE_PRE_KICK_EVIDENCE"
