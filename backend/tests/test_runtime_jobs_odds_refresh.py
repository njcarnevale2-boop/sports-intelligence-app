from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import duckdb
import pandas as pd
import pytest

from app.runtime_jobs import odds_refresh


class _FakeResp:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.text = ""
        self.headers = {
            "x-requests-remaining": "19600",
            "x-requests-used": "400",
            "x-requests-last": "1",
        }

    def json(self):
        return self._payload


def test_run_refresh_requires_odds_api_key_and_makes_no_request_without_key(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)

    with patch.object(odds_refresh.requests, "get") as request_get:
        with pytest.raises(RuntimeError, match="ODDS_API_KEY_MISSING"):
            odds_refresh.run_refresh()
        request_get.assert_not_called()


def test_run_refresh_filters_to_scoped_regular_season_events(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    outputs = runtime_root / "outputs"
    outputs.mkdir(parents=True)

    now = datetime.now(timezone.utc)
    schedule = pd.DataFrame(
        [
            {"season": 2026, "week": 1, "gameday": (now + timedelta(days=3)).date().isoformat(), "away_team": "KC", "home_team": "BUF"},
            {"season": 2026, "week": 0, "gameday": (now + timedelta(days=1)).date().isoformat(), "away_team": "LV", "home_team": "LAR"},
        ]
    )
    schedule.to_csv(outputs / "schedule_context_latest.csv", index=False)

    payload = [
        {
            "id": "2026_1_KC_BUF",
            "commence_time": (now + timedelta(days=3)).isoformat(),
            "home_team": "Buffalo Bills",
            "away_team": "Kansas City Chiefs",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "markets": [
                        {
                            "key": "spreads",
                            "outcomes": [
                                {"name": "Buffalo Bills", "point": -2.5, "price": -110},
                                {"name": "Kansas City Chiefs", "point": 2.5, "price": -110},
                            ],
                        }
                    ],
                }
            ],
        },
        {
            "id": "2026_2_DAL_PHI",
            "commence_time": (now + timedelta(days=20)).isoformat(),
            "home_team": "Philadelphia Eagles",
            "away_team": "Dallas Cowboys",
            "bookmakers": [],
        },
        {
            "id": "2026_0_LV_LAR",
            "commence_time": (now + timedelta(days=1)).isoformat(),
            "home_team": "Los Angeles Rams",
            "away_team": "Las Vegas Raiders",
            "bookmakers": [],
        },
    ]

    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.setenv("ODDS_REFRESH_MAX_DAYS_AHEAD", "14")
    monkeypatch.setenv("ODDS_REFRESH_MAX_HOURS_PAST", "12")

    with patch.object(odds_refresh.requests, "get", return_value=_FakeResp(payload)):
        out = odds_refresh.run_refresh()

    assert out["totalEvents"] == 3
    assert out["scopedEvents"] == 1
    assert out["games"] == 1

    db_path = runtime_root / "database" / "nfl_model.duckdb"
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        ids = [str(r[0]) for r in con.execute("SELECT DISTINCT api_event_id FROM odds_snapshots ORDER BY api_event_id").fetchall()]
    finally:
        con.close()
    assert ids == ["2026_1_KC_BUF"]


def test_run_refresh_excludes_distant_future_without_schedule_context(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    (runtime_root / "outputs").mkdir(parents=True)

    now = datetime.now(timezone.utc)
    payload = [
        {
            "id": "near-event",
            "commence_time": (now + timedelta(days=2)).isoformat(),
            "home_team": "Buffalo Bills",
            "away_team": "Kansas City Chiefs",
            "bookmakers": [],
        },
        {
            "id": "far-event",
            "commence_time": (now + timedelta(days=40)).isoformat(),
            "home_team": "Philadelphia Eagles",
            "away_team": "Dallas Cowboys",
            "bookmakers": [],
        },
    ]

    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.setenv("ODDS_REFRESH_MAX_DAYS_AHEAD", "14")
    monkeypatch.setenv("ODDS_REFRESH_MAX_HOURS_PAST", "12")

    with patch.object(odds_refresh.requests, "get", return_value=_FakeResp(payload)):
        out = odds_refresh.run_refresh()

    assert out["totalEvents"] == 2
    assert out["scopedEvents"] == 1
