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


_CODE_TO_PROVIDER_NAME = {
    "ARI": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB": "Green Bay Packers",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs",
    "LAC": "Los Angeles Chargers",
    "LAR": "Los Angeles Rams",
    "LV": "Las Vegas Raiders",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE": "New England Patriots",
    "NO": "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
}


def test_canonical_team_normalization_supports_all_current_teams_and_aliases():
    for code in _CODE_TO_PROVIDER_NAME:
        assert odds_refresh._canonical_team_code(code) == code

    assert odds_refresh._canonical_team_code("LA") == "LAR"
    assert odds_refresh._canonical_team_code("LAR") == "LAR"
    assert odds_refresh._canonical_team_code("OAK") == "LV"
    assert odds_refresh._canonical_team_code("LV") == "LV"


def test_schedule_date_matching_handles_tightly_bounded_utc_rollover():
    kickoff_normal = datetime.fromisoformat("2026-09-13T17:00:00+00:00")
    kickoff_snf_rollover = datetime.fromisoformat("2026-09-14T00:20:00+00:00")
    kickoff_mnf_rollover = datetime.fromisoformat("2026-09-15T00:20:00+00:00")
    kickoff_tnf_rollover = datetime.fromisoformat("2026-09-11T00:20:00+00:00")
    kickoff_too_far = datetime.fromisoformat("2026-09-16T00:20:00+00:00")

    assert odds_refresh._dates_match_schedule_gameday("2026-09-13", kickoff_normal)
    assert odds_refresh._dates_match_schedule_gameday("2026-09-13", kickoff_snf_rollover)
    assert odds_refresh._dates_match_schedule_gameday("2026-09-14", kickoff_mnf_rollover)
    assert odds_refresh._dates_match_schedule_gameday("2026-09-10", kickoff_tnf_rollover)
    assert not odds_refresh._dates_match_schedule_gameday("2026-09-14", kickoff_too_far)


def test_scope_matching_rejects_wrong_teams_and_two_day_date_gap():
    now = datetime(2026, 8, 29, 19, 42, 4, tzinfo=timezone.utc)
    match_index = {("NE", "SEA"): {"2026-09-09"}}

    wrong_teams_event = {
        "commence_time": "2026-09-10T00:20:00+00:00",
        "away_team": "Kansas City Chiefs",
        "home_team": "Seattle Seahawks",
    }
    two_day_gap_event = {
        "commence_time": "2026-09-11T00:20:00+00:00",
        "away_team": "New England Patriots",
        "home_team": "Seattle Seahawks",
    }

    allowed_wrong_team, reason_wrong_team = odds_refresh._evaluate_event_scope(
        wrong_teams_event,
        now_utc=now,
        match_index=match_index,
        max_days_ahead=14,
        max_hours_past=12,
    )
    allowed_two_day, reason_two_day = odds_refresh._evaluate_event_scope(
        two_day_gap_event,
        now_utc=now,
        match_index=match_index,
        max_days_ahead=14,
        max_hours_past=12,
    )

    assert not allowed_wrong_team
    assert reason_wrong_team == "REJECTED_BY_TEAM_MATCH"
    assert not allowed_two_day
    assert reason_two_day == "REJECTED_BY_DATE_MATCH"


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


def test_run_refresh_skips_paid_request_when_no_expected_in_scope_events(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    outputs = runtime_root / "outputs"
    outputs.mkdir(parents=True)

    schedule = pd.DataFrame(
        [
            {
                "season": 2026,
                "week": 1,
                "gameday": "2026-01-01",
                "away_team": "KC",
                "home_team": "BUF",
            }
        ]
    )
    schedule.to_csv(outputs / "schedule_context_latest.csv", index=False)

    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("ODDS_API_KEY", "test-key")

    with patch.object(odds_refresh.requests, "get") as request_get:
        out = odds_refresh.run_refresh()

    assert out["providerRequestSkipped"] is True
    assert out["providerRequestSkipReason"] == "NO_EXPECTED_IN_SCOPE_EVENTS"
    assert out["expectedInScopeEvents"] == 0
    request_get.assert_not_called()

    db_path = runtime_root / "database" / "nfl_model.duckdb"
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        usage_count = con.execute("SELECT COUNT(*) FROM odds_api_usage").fetchone()[0]
        telemetry = con.execute(
            "SELECT refresh_status, skip_reason, provider_request_skipped, snapshot_rows_inserted FROM odds_refresh_run_telemetry ORDER BY run_at DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()

    assert usage_count == 0
    assert telemetry[0] == "SKIPPED"
    assert telemetry[1] == "NO_EXPECTED_IN_SCOPE_EVENTS"
    assert bool(telemetry[2]) is True
    assert telemetry[3] == 0


def test_run_refresh_aug29_week1_targeting_and_rollover_matching(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    outputs = runtime_root / "outputs"
    outputs.mkdir(parents=True)

    week1_rows = [
        {"season": 2026, "week": 1, "gameday": "2026-09-09", "away_team": "NE", "home_team": "SEA"},
        {"season": 2026, "week": 1, "gameday": "2026-09-10", "away_team": "SF", "home_team": "LA"},
        {"season": 2026, "week": 1, "gameday": "2026-09-13", "away_team": "ARI", "home_team": "LAC"},
        {"season": 2026, "week": 1, "gameday": "2026-09-13", "away_team": "ATL", "home_team": "PIT"},
        {"season": 2026, "week": 1, "gameday": "2026-09-13", "away_team": "BAL", "home_team": "IND"},
        {"season": 2026, "week": 1, "gameday": "2026-09-13", "away_team": "BUF", "home_team": "HOU"},
        {"season": 2026, "week": 1, "gameday": "2026-09-13", "away_team": "CHI", "home_team": "CAR"},
        {"season": 2026, "week": 1, "gameday": "2026-09-13", "away_team": "CLE", "home_team": "JAX"},
        {"season": 2026, "week": 1, "gameday": "2026-09-13", "away_team": "DAL", "home_team": "NYG"},
        {"season": 2026, "week": 1, "gameday": "2026-09-13", "away_team": "GB", "home_team": "MIN"},
        {"season": 2026, "week": 1, "gameday": "2026-09-13", "away_team": "MIA", "home_team": "LV"},
        {"season": 2026, "week": 1, "gameday": "2026-09-13", "away_team": "NO", "home_team": "DET"},
        {"season": 2026, "week": 1, "gameday": "2026-09-13", "away_team": "NYJ", "home_team": "TEN"},
        {"season": 2026, "week": 1, "gameday": "2026-09-13", "away_team": "TB", "home_team": "CIN"},
        {"season": 2026, "week": 1, "gameday": "2026-09-13", "away_team": "WAS", "home_team": "PHI"},
        {"season": 2026, "week": 1, "gameday": "2026-09-14", "away_team": "DEN", "home_team": "KC"},
        # Week 2 must not be included accidentally.
        {"season": 2026, "week": 2, "gameday": "2026-09-20", "away_team": "ARI", "home_team": "SF"},
        # Preseason remains excluded.
        {"season": 2026, "week": 0, "gameday": "2026-08-20", "away_team": "LV", "home_team": "LAR"},
    ]
    pd.DataFrame(week1_rows).to_csv(outputs / "schedule_context_latest.csv", index=False)

    payload = []
    for row in week1_rows:
        if int(row["week"]) != 1:
            continue
        away = row["away_team"]
        home = row["home_team"]
        if away == "NE" and home == "SEA":
            commence = "2026-09-10T00:20:00+00:00"  # Thursday/UTC rollover test
        elif away == "SF" and home == "LA":
            commence = "2026-09-11T00:20:00+00:00"  # SF@LA alias + UTC rollover
        else:
            commence = f"{row['gameday']}T17:00:00+00:00"
        payload.append(
            {
                "id": f"2026_1_{away}_{home}",
                "commence_time": commence,
                "home_team": _CODE_TO_PROVIDER_NAME["LAR" if home == "LA" else home],
                "away_team": _CODE_TO_PROVIDER_NAME[away],
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "title": "DraftKings",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": _CODE_TO_PROVIDER_NAME["LAR" if home == "LA" else home], "price": -110},
                                    {"name": _CODE_TO_PROVIDER_NAME[away], "price": -110},
                                ],
                            }
                        ],
                    }
                ],
            }
        )

    # Provider can still return out-of-scope future week games; scope must reject.
    payload.append(
        {
            "id": "2026_2_ARI_SF",
            "commence_time": "2026-09-20T17:00:00+00:00",
            "home_team": "San Francisco 49ers",
            "away_team": "Arizona Cardinals",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "San Francisco 49ers", "price": -110},
                                {"name": "Arizona Cardinals", "price": -110},
                            ],
                        }
                    ],
                }
            ],
        }
    )

    fixed_now = datetime(2026, 8, 29, 19, 42, 4, tzinfo=timezone.utc)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.setenv("ODDS_REFRESH_MAX_DAYS_AHEAD", "14")
    monkeypatch.setenv("ODDS_REFRESH_MAX_HOURS_PAST", "12")

    with (
        patch.object(odds_refresh.requests, "get", return_value=_FakeResp(payload)),
        patch.object(odds_refresh, "datetime", _FixedDatetime),
    ):
        out = odds_refresh.run_refresh()

    assert out["providerRequestSkipped"] is False
    assert out["expectedInScopeEvents"] == 16
    assert out["targetRegularWeek"] == 1
    assert out["totalEvents"] == 17
    assert out["eventsAccepted"] == 16
    assert out["scopedEvents"] == 16
    assert out["eventsRejectedByScheduleMatch"] == 1
    assert out["rows"] > 0

    db_path = runtime_root / "database" / "nfl_model.duckdb"
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        events = con.execute("SELECT COUNT(DISTINCT api_event_id) FROM odds_snapshots").fetchone()[0]
        sf_la_rows = con.execute(
            "SELECT COUNT(*) FROM odds_snapshots WHERE api_event_id = '2026_1_SF_LA'"
        ).fetchone()[0]
    finally:
        con.close()

    assert events == 16
    assert sf_la_rows > 0


def test_run_refresh_marks_paid_zero_snapshot_warning(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    outputs = runtime_root / "outputs"
    outputs.mkdir(parents=True)

    schedule = pd.DataFrame(
        [
            {
                "season": 2026,
                "week": 1,
                "gameday": "2026-09-10",
                "away_team": "KC",
                "home_team": "BUF",
            }
        ]
    )
    schedule.to_csv(outputs / "schedule_context_latest.csv", index=False)

    payload = [
        {
            "id": "evt-no-books",
            "commence_time": "2026-09-10T20:00:00+00:00",
            "home_team": "Buffalo Bills",
            "away_team": "Kansas City Chiefs",
            "bookmakers": [],
        }
    ]

    fixed_now = datetime(2026, 8, 29, 19, 42, 4, tzinfo=timezone.utc)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("ODDS_API_KEY", "test-key")

    with (
        patch.object(odds_refresh.requests, "get", return_value=_FakeResp(payload)),
        patch.object(odds_refresh, "datetime", _FixedDatetime),
    ):
        out = odds_refresh.run_refresh()

    assert out["providerRequestSkipped"] is False
    assert out["providerEventsReturned"] == 1
    assert out["eventsAccepted"] == 1
    assert out["rows"] == 0
    assert out["warningCode"] == "PAID_REQUEST_ZERO_SNAPSHOTS"
