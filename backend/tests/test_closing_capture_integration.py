"""
Integration tests for closing-line capture wired into the orchestrator.

Tests use a real DuckDB file in a tmp_path so both recommendation_snapshot
and closing_line operate on the same data.  Production DB is never touched.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


def _utc(offset_hours: float = 0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=offset_hours)


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


@pytest.fixture()
def db_path(tmp_path):
    """Real DuckDB file with required schema."""
    import duckdb
    path = tmp_path / "test_nfl.duckdb"
    con = duckdb.connect(str(path))
    con.execute("""
        CREATE TABLE odds_snapshots (
            fetched_at TIMESTAMP, api_event_id VARCHAR,
            commence_time TIMESTAMP, home_team VARCHAR, away_team VARCHAR,
            home_code VARCHAR, away_code VARCHAR,
            bookmaker_key VARCHAR, bookmaker_title VARCHAR,
            market_key VARCHAR, outcome_name VARCHAR, outcome_code VARCHAR,
            point DOUBLE, price DOUBLE, implied_prob DOUBLE,
            snapshot_type VARCHAR, source VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE recommendation_snapshots (
            snapshot_id VARCHAR PRIMARY KEY, event_id VARCHAR NOT NULL,
            recommended_at TIMESTAMP NOT NULL, market VARCHAR NOT NULL,
            side VARCHAR NOT NULL, point DOUBLE, price DOUBLE,
            sportsbook VARCHAR, si_score DOUBLE, model_probability DOUBLE,
            edge_pp DOUBLE, ev_per_dollar DOUBLE,
            market_intelligence TEXT, injury_context TEXT, weather_context TEXT,
            commence_time TIMESTAMP, home_team VARCHAR, away_team VARCHAR,
            closing_status VARCHAR DEFAULT 'PENDING',
            closing_point DOUBLE, closing_price DOUBLE,
            closing_sportsbook VARCHAR, closing_at TIMESTAMP,
            clv_points DOUBLE, clv_probability DOUBLE, clv_percent DOUBLE
        )
    """)
    con.close()
    return path


def _insert_snap(db_path, event_id, market, side, rec_point, rec_price,
                 sportsbook, kickoff_naive, status="PENDING"):
    import duckdb
    sid = str(uuid.uuid4())
    con = duckdb.connect(str(db_path))
    con.execute(
        "INSERT INTO recommendation_snapshots "
        "(snapshot_id,event_id,recommended_at,market,side,"
        "point,price,sportsbook,closing_status,commence_time) "
        "VALUES (?,?,CURRENT_TIMESTAMP,?,?,?,?,?,?,?)",
        [sid, event_id, market, side, rec_point, rec_price, sportsbook, status, kickoff_naive],
    )
    con.close()
    return sid


def _insert_odds(db_path, event_id, market, side, point, price, bookmaker_key, fetched_naive):
    import duckdb
    con = duckdb.connect(str(db_path))
    con.execute(
        "INSERT INTO odds_snapshots "
        "(fetched_at,api_event_id,market_key,outcome_code,"
        "bookmaker_key,bookmaker_title,point,price,"
        "commence_time,home_team,away_team,home_code,away_code,"
        "implied_prob,snapshot_type,source,outcome_name) "
        "VALUES (?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,NULL,NULL,'current','test',NULL)",
        [fetched_naive, event_id, market, side, bookmaker_key, bookmaker_key, point, price],
    )
    con.close()


def _run_capture(db_path):
    import app.services.recommendation_snapshot as rs
    import app.services.closing_line as cl
    with (
        patch.object(rs, "_DB_PATH", db_path),
        patch.object(cl, "_DB_PATH", db_path),
        patch.object(rs, "_kickoff_for_event", return_value=None),
    ):
        return rs.capture_closing_lines()


def _fetch(db_path, event_id):
    import duckdb
    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute(
        "SELECT closing_status, closing_point, clv_points "
        "FROM recommendation_snapshots WHERE event_id=? ORDER BY recommended_at",
        [event_id],
    ).fetchall()
    con.close()
    return rows


def test_game_not_started_remains_pending(db_path):
    """Kickoff in the future -> snapshot stays PENDING."""
    kickoff = _naive(_utc(+2))
    _insert_snap(db_path, "evt1", "spreads", "away", 7.0, -110.0, "DK", kickoff)
    _insert_odds(db_path, "evt1", "spreads", "away", 7.0, -110.0, "DK", _naive(_utc(-1)))
    counts = _run_capture(db_path)
    assert counts["pending"] == 1 and counts["captured"] == 0
    assert _fetch(db_path, "evt1")[0][0] == "PENDING"


def test_game_started_valid_pre_kick_snapshot_available(db_path):
    """Kickoff passed, pre-kick odds exist -> AVAILABLE + correct spread CLV."""
    kickoff = _naive(_utc(-1))
    _insert_snap(db_path, "evt2", "spreads", "away", 7.0, -110.0, "DK", kickoff)
    _insert_odds(db_path, "evt2", "spreads", "away", 5.5, -110.0, "DK", _naive(_utc(-1.5)))
    counts = _run_capture(db_path)
    assert counts["captured"] == 1
    status, close_pt, clv_pts = _fetch(db_path, "evt2")[0]
    assert status == "AVAILABLE"
    assert close_pt == pytest.approx(5.5)
    assert clv_pts == pytest.approx(1.5, abs=0.01)


def test_repeated_capture_is_idempotent(db_path):
    """Running capture twice must not change an AVAILABLE record."""
    kickoff = _naive(_utc(-1))
    _insert_snap(db_path, "evt3", "spreads", "home", -3.5, -110.0, "FD", kickoff)
    _insert_odds(db_path, "evt3", "spreads", "home", -2.5, -110.0, "FD", _naive(_utc(-1.5)))
    assert _run_capture(db_path)["captured"] == 1
    assert _run_capture(db_path)["captured"] == 0
    rows = _fetch(db_path, "evt3")
    assert len(rows) == 1 and rows[0][0] == "AVAILABLE"


def test_no_eligible_pre_kick_snapshot_marks_not_captured(db_path):
    """All odds snaps fall within the 2-min cutoff -> NOT_CAPTURED."""
    kickoff = _naive(_utc(-1))
    _insert_snap(db_path, "evt4", "spreads", "away", 6.0, -110.0, "BM", kickoff)
    _insert_odds(db_path, "evt4", "spreads", "away", 5.5, -110.0, "BM", kickoff)
    counts = _run_capture(db_path)
    assert counts["missing"] == 1
    assert _fetch(db_path, "evt4")[0][0] == "NOT_CAPTURED"


def test_post_kick_odds_excluded_from_closing_line(db_path):
    """Pre-kick AND post-kick snapshots exist - only pre-kick is used."""
    kickoff = _naive(_utc(-1))
    _insert_snap(db_path, "evt5", "totals", "under", 48.5, -110.0, "DK", kickoff)
    _insert_odds(db_path, "evt5", "totals", "under", 47.0, -110.0, "DK", _naive(_utc(-1.5)))
    _insert_odds(db_path, "evt5", "totals", "under", 44.0, -110.0, "DK", _naive(_utc(-0.3)))
    _run_capture(db_path)
    _, close_pt, _ = _fetch(db_path, "evt5")[0]
    assert close_pt == pytest.approx(47.0)


def test_multiple_recommendations_same_game(db_path):
    """Two recommendations for the same event are captured independently."""
    kickoff = _naive(_utc(-1))
    pre = _naive(_utc(-1.5))
    _insert_snap(db_path, "evt6", "spreads", "away",  7.0, -110.0, "DK", kickoff)
    _insert_snap(db_path, "evt6", "totals",  "over", 48.5, -110.0, "DK", kickoff)
    _insert_odds(db_path, "evt6", "spreads", "away",  5.5, -110.0, "DK", pre)
    _insert_odds(db_path, "evt6", "totals",  "over", 50.0, -110.0, "DK", pre)
    counts = _run_capture(db_path)
    assert counts["captured"] == 2
    import duckdb
    con = duckdb.connect(str(db_path), read_only=True)
    row_dict = {r[0]: r[1] for r in con.execute(
        "SELECT market, closing_point FROM recommendation_snapshots "
        "WHERE event_id='evt6' ORDER BY market"
    ).fetchall()}
    con.close()
    assert row_dict["spreads"] == pytest.approx(5.5)
    assert row_dict["totals"]  == pytest.approx(50.0)


def test_different_sportsbooks_captured_separately(db_path):
    """Two sportsbooks for same event/market produce separate records."""
    kickoff = _naive(_utc(-1))
    pre = _naive(_utc(-1.5))
    _insert_snap(db_path, "evt7", "spreads", "away", 7.0, -110.0, "DraftKings", kickoff)
    _insert_snap(db_path, "evt7", "spreads", "away", 7.0, -110.0, "FanDuel",    kickoff)
    _insert_odds(db_path, "evt7", "spreads", "away", 5.5, -110.0, "DraftKings", pre)
    _insert_odds(db_path, "evt7", "spreads", "away", 6.0, -110.0, "FanDuel",    pre)
    counts = _run_capture(db_path)
    assert counts["captured"] == 2
    import duckdb
    con = duckdb.connect(str(db_path), read_only=True)
    book_dict = {r[0]: r[1] for r in con.execute(
        "SELECT sportsbook, closing_point FROM recommendation_snapshots "
        "WHERE event_id='evt7' ORDER BY sportsbook"
    ).fetchall()}
    con.close()
    assert book_dict["DraftKings"] == pytest.approx(5.5)
    assert book_dict["FanDuel"]    == pytest.approx(6.0)


def test_get_refresh_status_includes_clv_fields(tmp_path):
    """get_refresh_status() always returns the three CLV counter keys."""
    from app.services import refresh_orchestrator as orch
    with patch.object(orch, "_STATE_FILE", tmp_path / "state.json"):
        status = orch.get_refresh_status()
    assert "closingLinesCapturedThisRun" in status
    assert "closingLinesStillPending"    in status
    assert "closingLinesMissing"         in status


def test_trigger_now_response_includes_clv_fields(tmp_path):
    """trigger_now() response exposes CLV stats from the persisted state."""
    from app.services import refresh_orchestrator as orch
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({
        "lastRefreshAt": "2026-08-12T00:00:00+00:00",
        "closingLinesCapturedThisRun": 3,
        "closingLinesStillPending": 1,
        "closingLinesMissing": 0,
        "isRunning": False,
        "consecutiveFailures": 0,
    }))
    with (
        patch.object(orch, "_STATE_FILE", state_file),
        patch.object(orch, "_run_once", return_value=True),
    ):
        result = orch.trigger_now()
    assert "closingLinesCapturedThisRun" in result
