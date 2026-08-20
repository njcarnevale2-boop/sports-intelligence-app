from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from app.services import shadow_markets


@pytest.fixture
def shadow_db(monkeypatch, tmp_path):
    db = tmp_path / "shadow_prospective.sqlite"
    monkeypatch.setattr(shadow_markets, "_DB_PATH", db)
    shadow_markets._ensure_schema()
    return db


def _read_rows(db: Path, where: str = "1=1"):
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    rows = con.execute(f"SELECT * FROM prospective_market_snapshots WHERE {where} ORDER BY id ASC").fetchall()
    con.close()
    return rows


def test_opening_current_closing_state_separation_and_parity(monkeypatch, shadow_db):
    board = pd.DataFrame(
        [
            {
                "api_event_id": "2026_01_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "spread",
                "side": "away",
                "latest_point": 3.0,
                "latest_price": -110,
                "sportsbook": "BookA",
                "last_seen": "2026-09-10T16:58:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            },
            {
                "api_event_id": "2026_01_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "moneyline",
                "side": "home",
                "latest_point": None,
                "latest_price": -150,
                "sportsbook": "BookA",
                "last_seen": "2026-09-10T16:58:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            },
            {
                "api_event_id": "2026_01_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "total",
                "side": "over",
                "latest_point": 45.5,
                "latest_price": -110,
                "sportsbook": "BookA",
                "last_seen": "2026-09-10T16:58:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            },
            {
                "api_event_id": "2026_01_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "team_totals",
                "side": "over",
                "team_code": "AWAY",
                "latest_point": 21.5,
                "latest_price": -110,
                "sportsbook": "BookA",
                "last_seen": "2026-09-10T16:58:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            },
            {
                "api_event_id": "2026_01_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "spreads_h1",
                "side": "away",
                "latest_point": 1.5,
                "latest_price": -110,
                "sportsbook": "BookA",
                "last_seen": "2026-09-10T16:58:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            },
            {
                "api_event_id": "2026_01_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "h2h_h1",
                "side": "away",
                "latest_point": None,
                "latest_price": 120,
                "sportsbook": "BookA",
                "last_seen": "2026-09-10T16:58:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            },
            {
                "api_event_id": "2026_01_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "totals_h1",
                "side": "over",
                "latest_point": 23.5,
                "latest_price": -110,
                "sportsbook": "BookA",
                "last_seen": "2026-09-10T16:58:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            },
        ]
    )
    proj = {
        "2026_01_AWAY_HOME": pd.Series(
            {
                "api_event_id": "2026_01_AWAY_HOME",
                "model_total_baseline": 46.0,
                "model_margin_home": -2.0,
            }
        )
    }

    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: board)
    monkeypatch.setattr(shadow_markets, "_load_projection_lookup", lambda: proj)

    out = shadow_markets.capture_prospective_from_line_board(week=1, season=2026)
    assert out["currentInserted"] == 7
    assert out["openingInserted"] == 7
    assert out["closingInserted"] == 7

    rows = _read_rows(shadow_db)
    assert len(rows) == 21
    by_state = {"OPENING": 0, "CURRENT": 0, "CLOSING": 0}
    for r in rows:
        by_state[str(r["state_label"])] += 1
    assert by_state == {"OPENING": 7, "CURRENT": 7, "CLOSING": 7}


def test_no_post_kickoff_closing_snapshot(monkeypatch, shadow_db):
    board = pd.DataFrame(
        [
            {
                "api_event_id": "2026_02_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "spread",
                "side": "away",
                "latest_point": 3.0,
                "latest_price": -110,
                "sportsbook": "BookA",
                "last_seen": "2026-09-10T17:05:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            }
        ]
    )

    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: board)
    monkeypatch.setattr(shadow_markets, "_load_projection_lookup", lambda: {})

    out = shadow_markets.capture_prospective_from_line_board(week=2, season=2026)
    assert out["closingInserted"] == 0
    assert out["postKickoffRejectedCount"] == 1


def test_stale_closing_rejection(monkeypatch, shadow_db):
    board = pd.DataFrame(
        [
            {
                "api_event_id": "2026_03_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "total",
                "side": "over",
                "latest_point": 45.5,
                "latest_price": -110,
                "sportsbook": "BookA",
                "last_seen": "2026-09-10T15:00:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            }
        ]
    )

    monkeypatch.setenv("PROSPECTIVE_CLOSING_MAX_AGE_SECONDS", "300")
    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: board)
    monkeypatch.setattr(shadow_markets, "_load_projection_lookup", lambda: {})

    out = shadow_markets.capture_prospective_from_line_board(week=3, season=2026)
    assert out["closingInserted"] == 0
    assert out["staleSnapshotCount"] == 1


def test_all_books_best_price_consensus_and_median(monkeypatch, shadow_db):
    board = pd.DataFrame(
        [
            {
                "api_event_id": "2026_04_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "spread",
                "side": "away",
                "latest_point": 3.0,
                "latest_price": -110,
                "sportsbook": "BookA",
                "last_seen": "2026-09-10T16:50:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            },
            {
                "api_event_id": "2026_04_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "spread",
                "side": "away",
                "latest_point": 3.0,
                "latest_price": -105,
                "sportsbook": "BookB",
                "last_seen": "2026-09-10T16:51:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            },
            {
                "api_event_id": "2026_04_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "spread",
                "side": "away",
                "latest_point": 3.5,
                "latest_price": -108,
                "sportsbook": "BookC",
                "last_seen": "2026-09-10T16:52:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            },
        ]
    )

    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: board)
    monkeypatch.setattr(shadow_markets, "_load_projection_lookup", lambda: {})

    shadow_markets.capture_prospective_from_line_board(week=4, season=2026)
    rows = _read_rows(shadow_db, "state_label = 'CURRENT'")
    assert len(rows) == 3

    all_books = json.loads(rows[0]["all_books"])
    assert len(all_books) == 3
    assert float(rows[0]["best_price"]) == -105.0
    assert str(rows[0]["best_price_book"]) == "BookB"
    assert float(rows[0]["consensus_line"]) == 3.0
    assert float(rows[0]["median_line"]) == 3.0


def test_quota_degradation_path(shadow_db):
    discovery = {
        "targets": {
            "TEAM_TOTAL": {"supported": True},
            "1H_SPREAD": {"supported": True},
            "1H_MONEYLINE": {"supported": True},
            "1H_TOTAL": {"supported": True},
        },
        "quota": {"remaining": "100", "used": "19900", "last": "4"},
        "eventSamples": [{"eventId": "evt-1", "awayTeam": "A", "homeTeam": "B", "commenceTime": "2026-09-10T17:00:00+00:00"}],
        "eventPayloadById": {},
    }

    out = shadow_markets.ingest_expanded_market_snapshots(discovery=discovery)
    assert out["degraded"] is True
    assert out["degradationReason"] == "QUOTA_SAFETY_THRESHOLD"
    assert out["quotaAccounting"]["expandedMarketRequestsThisRun"] == 0


def test_prospective_immutability_and_deduplication(monkeypatch, shadow_db):
    board = pd.DataFrame(
        [
            {
                "api_event_id": "2026_05_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "moneyline",
                "side": "away",
                "latest_point": None,
                "latest_price": 120,
                "sportsbook": "BookA",
                "last_seen": "2026-09-10T16:59:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            }
        ]
    )
    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: board)
    monkeypatch.setattr(shadow_markets, "_load_projection_lookup", lambda: {})

    first = shadow_markets.capture_prospective_from_line_board(week=5, season=2026)
    second = shadow_markets.capture_prospective_from_line_board(week=5, season=2026)

    assert first["currentInserted"] == 1
    assert second["currentInserted"] == 0
    assert second["duplicateRejectionCount"] >= 1


def test_new_line_movement_creates_new_immutable_row(monkeypatch, shadow_db):
    board_a = pd.DataFrame(
        [
            {
                "api_event_id": "2026_06_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "total",
                "side": "over",
                "latest_point": 45.5,
                "latest_price": -110,
                "sportsbook": "BookA",
                "last_seen": "2026-09-10T16:40:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            }
        ]
    )
    board_b = board_a.copy()
    board_b.loc[0, "latest_point"] = 46.0
    board_b.loc[0, "last_seen"] = "2026-09-10T16:45:00+00:00"

    monkeypatch.setattr(shadow_markets, "_load_projection_lookup", lambda: {})
    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: board_a)
    shadow_markets.capture_prospective_from_line_board(week=6, season=2026)

    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: board_b)
    out = shadow_markets.capture_prospective_from_line_board(week=6, season=2026)
    assert out["currentInserted"] == 1


def test_team_total_research_fields_and_firewall(monkeypatch, shadow_db):
    board = pd.DataFrame(
        [
            {
                "api_event_id": "2026_07_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "team_totals",
                "side": "over",
                "team_code": "AWAY",
                "latest_point": 21.5,
                "latest_price": -110,
                "sportsbook": "BookA",
                "last_seen": "2026-09-10T16:57:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            }
        ]
    )
    proj = {
        "2026_07_AWAY_HOME": pd.Series(
            {
                "api_event_id": "2026_07_AWAY_HOME",
                "model_total_baseline": 44.0,
                "model_margin_home": -4.0,
            }
        )
    }

    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: board)
    monkeypatch.setattr(shadow_markets, "_load_projection_lookup", lambda: proj)

    shadow_markets.capture_prospective_from_line_board(week=7, season=2026)
    rows = _read_rows(shadow_db, "market_family = 'TEAM_TOTAL' AND state_label = 'CURRENT'")
    assert rows
    r = rows[0]
    assert r["selected_team_projected_points"] is not None
    assert str(r["model_state"]) == "RESEARCH_ONLY"
    assert str(r["shadow_recommendations"]) == "DISABLED"
    assert int(r["production_eligible"]) == 0
    assert int(r["cross_market_comparable"]) == 0


def test_first_half_model_fields_unavailable(monkeypatch, shadow_db):
    board = pd.DataFrame(
        [
            {
                "api_event_id": "2026_08_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "totals_h1",
                "side": "over",
                "latest_point": 23.5,
                "latest_price": -110,
                "sportsbook": "BookA",
                "last_seen": "2026-09-10T16:57:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            }
        ]
    )
    proj = {
        "2026_08_AWAY_HOME": pd.Series(
            {
                "api_event_id": "2026_08_AWAY_HOME",
                "model_total_baseline": 50.0,
                "model_margin_home": 3.0,
            }
        )
    }

    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: board)
    monkeypatch.setattr(shadow_markets, "_load_projection_lookup", lambda: proj)

    shadow_markets.capture_prospective_from_line_board(week=8, season=2026)
    rows = _read_rows(shadow_db, "market_family = 'FIRST_HALF_TOTAL' AND state_label = 'CURRENT'")
    assert rows
    r = rows[0]
    assert r["projected_game_total"] is None
    assert r["projected_home_margin"] is None
    assert str(r["model_state"]) == "DATA_COLLECTION_ONLY"
    assert str(r["shadow_recommendations"]) == "DISABLED"


def test_reporting_integrity_and_live_compatibility(monkeypatch, shadow_db):
    board = pd.DataFrame(
        [
            {
                "api_event_id": "2026_09_AWAY_HOME",
                "commence_time": "2026-09-10T17:00:00+00:00",
                "market": "spread",
                "side": "away",
                "latest_point": 3.0,
                "latest_price": -110,
                "sportsbook": "BookA",
                "last_seen": "2026-09-10T16:59:00+00:00",
                "home_team": "HOME",
                "away_team": "AWAY",
            }
        ]
    )
    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: board)
    monkeypatch.setattr(shadow_markets, "_load_projection_lookup", lambda: {})

    shadow_markets.capture_prospective_from_line_board(week=9, season=2026)

    report = shadow_markets.prospective_market_capture_report(season=2026, week=9)
    assert report["families"]["SPREAD"]["openingCapture"] == "READY"
    assert report["families"]["SPREAD"]["currentCapture"] == "READY"
    assert report["families"]["SPREAD"]["closingCapture"] == "READY"

    integrity = shadow_markets.prospective_data_integrity_audit(season=2026, week=9)
    assert "openingCoverage" in integrity
    assert "twoSidedNoVigCoverage" in integrity

    live = shadow_markets.live_sia_future_schema_compatibility()
    assert live["phaseLiveSupported"] is True
    assert live["identityUnchanged"] is True


def test_production_firewalls_unchanged_flags():
    assert shadow_markets.MARKET_KEY_TO_FAMILY["spread"] == "SPREAD"
    assert shadow_markets._shadow_recommendation_eligible_for_market("team_total") is False
    assert shadow_markets._shadow_recommendation_eligible_for_market("first_half_total") is False
    assert shadow_markets._shadow_recommendation_eligible_for_market("first_half_spread") is False
    assert shadow_markets._shadow_recommendation_eligible_for_market("first_half_moneyline") is False
