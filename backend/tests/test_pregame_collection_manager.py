from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.services import pregame_collection_manager as mgr
from app.services import shadow_markets


@pytest.fixture
def shadow_db(monkeypatch, tmp_path):
    db = tmp_path / "pregame_manager_test.sqlite"
    monkeypatch.setenv("PLAYER_PROP_COLLECTION_ENABLED", "1")
    monkeypatch.setattr(shadow_markets, "_DB_PATH", db)
    mgr._ensure_manager_schema()
    return db


def _games(now: datetime) -> list[dict]:
    return [
        {
            "eventId": "evt-open",
            "commenceTime": (now + timedelta(hours=30)).isoformat(),
            "awayAbbreviation": "NO",
            "homeAbbreviation": "DET",
        },
        {
            "eventId": "evt-day",
            "commenceTime": (now + timedelta(hours=10)).isoformat(),
            "awayAbbreviation": "KC",
            "homeAbbreviation": "BUF",
        },
        {
            "eventId": "evt-close",
            "commenceTime": (now + timedelta(minutes=80)).isoformat(),
            "awayAbbreviation": "SF",
            "homeAbbreviation": "SEA",
        },
        {
            "eventId": "evt-past",
            "commenceTime": (now - timedelta(minutes=10)).isoformat(),
            "awayAbbreviation": "LAR",
            "homeAbbreviation": "HOU",
        },
    ]


def _sixteen_games(now: datetime) -> list[dict]:
    games: list[dict] = []
    for idx in range(16):
        games.append(
            {
                "eventId": f"evt-{idx:02d}",
                "commenceTime": (now + timedelta(hours=30)).isoformat(),
                "awayAbbreviation": f"A{idx:02d}",
                "homeAbbreviation": f"H{idx:02d}",
            }
        )
    return games


def _n_games(now: datetime, count: int, hours_to_kickoff: float) -> list[dict]:
    games: list[dict] = []
    for idx in range(count):
        games.append(
            {
                "eventId": f"evt-n-{idx:02d}",
                "commenceTime": (now + timedelta(hours=hours_to_kickoff)).isoformat(),
                "awayAbbreviation": f"A{idx:02d}",
                "homeAbbreviation": f"H{idx:02d}",
            }
        )
    return games


def _full_standard_presence(games: list[dict]) -> dict[str, set[str]]:
    return {str(g["eventId"]): {"SPREAD", "MONEYLINE", "TOTAL"} for g in games}


def _build_schedule(monkeypatch, now: datetime, games: list[dict], *, market_exists=None, prop_exists=None, prop_allowlist=None):
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, games))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: _full_standard_presence(games))
    monkeypatch.setattr(mgr, "_state_exists_for_market", market_exists or (lambda event_id, family, state: False))
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", prop_exists or (lambda event_id, state: False))
    return mgr.build_pregame_collection_schedule_v1(week=1, now_utc=now, prop_allowlist=prop_allowlist)


def test_target_state_opening_current_closing_and_post_kickoff(shadow_db):
    cfg = mgr._resolve_config(dry_run=True)
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)

    assert mgr._target_state_for_event((now + timedelta(hours=36)).isoformat(), config=cfg, now=now) == "OPENING"
    assert mgr._target_state_for_event((now + timedelta(hours=8)).isoformat(), config=cfg, now=now) == "CURRENT"
    assert mgr._target_state_for_event((now + timedelta(minutes=45)).isoformat(), config=cfg, now=now) == "CLOSING"
    assert mgr._target_state_for_event((now - timedelta(minutes=1)).isoformat(), config=cfg, now=now) is None


def test_player_prop_allowlist_is_supported_and_configurable(shadow_db):
    keys = mgr._resolve_prop_allowlist([
        "player_pass_yds",
        "player_receptions",
        "unsupported_market_key",
        "player_pass_yds",
    ])
    assert keys == ("player_pass_yds", "player_receptions")


def test_dry_run_makes_zero_provider_calls(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, _games(now)))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {"evt-open": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-day": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-close": {"SPREAD", "MONEYLINE", "TOTAL"}})
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    called = {"provider": 0}

    def _should_not_call(*args, **kwargs):
        called["provider"] += 1
        raise AssertionError("provider should not be called in dry run")

    monkeypatch.setattr(shadow_markets, "_call_odds_api_event_odds", _should_not_call)

    out = mgr.run_pregame_collection_manager(dry_run=True)

    assert out["status"] == "DRY_RUN"
    assert out["execution"]["providerRequests"] == 0
    assert out["plan"]["plannedRequests"] == 1
    assert out["plan"]["estimatedCreditsStatus"] == "VERIFIED"
    assert out["plan"]["estimatedCreditsPerRequest"] == 6.0
    assert out["plan"]["estimatedCredits"] == 6.0
    assert called["provider"] == 0


def test_exact_verified_shape_is_6_credits(shadow_db):
    out = mgr._estimate_credits_for_request_shape(
        endpoint_type="EVENT_ODDS",
        region="us",
        markets=list(mgr.DEFAULT_PROP_ALLOWLIST),
    )
    assert out["status"] == "VERIFIED"
    assert out["creditsPerRequest"] == 6.0


def test_market_order_independent_verified_match(shadow_db):
    out = mgr._estimate_credits_for_request_shape(
        endpoint_type="EVENT_ODDS",
        region="us",
        markets=list(reversed(mgr.DEFAULT_PROP_ALLOWLIST)),
    )
    assert out["status"] == "VERIFIED"
    assert out["creditsPerRequest"] == 6.0


def test_subset_market_shape_is_unknown(shadow_db):
    out = mgr._estimate_credits_for_request_shape(
        endpoint_type="EVENT_ODDS",
        region="us",
        markets=["player_pass_yds", "player_pass_tds", "player_rush_yds", "player_reception_yds", "player_receptions"],
    )
    assert out["status"] == "UNKNOWN"
    assert out["creditsPerRequest"] is None


def test_superset_market_shape_is_unknown(shadow_db):
    out = mgr._estimate_credits_for_request_shape(
        endpoint_type="EVENT_ODDS",
        region="us",
        markets=list(mgr.DEFAULT_PROP_ALLOWLIST) + ["player_first_td"],
    )
    assert out["status"] == "UNKNOWN"
    assert out["creditsPerRequest"] is None


def test_different_region_is_unknown(shadow_db):
    out = mgr._estimate_credits_for_request_shape(
        endpoint_type="EVENT_ODDS",
        region="eu",
        markets=list(mgr.DEFAULT_PROP_ALLOWLIST),
    )
    assert out["status"] == "UNKNOWN"
    assert out["creditsPerRequest"] is None


def test_different_endpoint_is_unknown(shadow_db):
    out = mgr._estimate_credits_for_request_shape(
        endpoint_type="SPORT_ODDS",
        region="us",
        markets=list(mgr.DEFAULT_PROP_ALLOWLIST),
    )
    assert out["status"] == "UNKNOWN"
    assert out["creditsPerRequest"] is None


def test_16_event_verified_plan_estimates_96_credits(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=16, hours_to_kickoff=10)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, games))
    monkeypatch.setattr(
        mgr,
        "_load_line_board_market_presence",
        lambda: {str(g["eventId"]): {"SPREAD", "MONEYLINE", "TOTAL"} for g in games},
    )
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    plan = mgr.build_pregame_collection_plan(dry_run=True, now_utc=now)
    assert plan["eventsEvaluated"] == 16
    assert plan["snapshotsDue"]["playerProp"] == 16
    assert plan["plannedRequests"] == 16
    assert plan["estimatedCreditsStatus"] == "VERIFIED"
    assert plan["estimatedCreditsPerRequest"] == 6.0
    assert plan["estimatedCredits"] == 96.0


def test_request_budget_enforcement(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, _games(now)))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {"evt-open": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-day": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-close": {"SPREAD", "MONEYLINE", "TOTAL"}})
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    plan = mgr.build_pregame_collection_plan(dry_run=True, max_requests_per_run=0, now_utc=now)
    assert "REQUEST_BUDGET_EXCEEDED" in plan["skipReasons"]
    assert plan["requestBudget"]["pass"] is False


def test_estimated_credit_budget_enforcement(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, _games(now)))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {"evt-open": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-day": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-close": {"SPREAD", "MONEYLINE", "TOTAL"}})
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    plan = mgr.build_pregame_collection_plan(
        dry_run=True,
        max_estimated_credits_per_run=5.0,
        now_utc=now,
    )
    assert "RUN_CREDIT_BUDGET_EXCEEDED" in plan["skipReasons"]
    assert plan["creditBudget"]["pass"] is False


def test_verified_credit_budget_blocks_execution_before_provider_calls(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    games = _n_games(now, count=16, hours_to_kickoff=10)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, games))
    monkeypatch.setattr(
        mgr,
        "_load_line_board_market_presence",
        lambda: {str(g["eventId"]): {"SPREAD", "MONEYLINE", "TOTAL"} for g in games},
    )
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    called = {"provider": 0}

    def _provider(*args, **kwargs):
        called["provider"] += 1
        raise AssertionError("provider should not be called when verified credit budget fails")

    monkeypatch.setattr(shadow_markets, "_call_odds_api_event_odds", _provider)
    out = mgr.run_pregame_collection_manager(dry_run=False, max_estimated_credits_per_run=95.0, allow_unknown_weekly_usage=True)
    assert out["status"] == "SKIPPED"
    assert out["execution"]["providerRequests"] == 0
    assert out["execution"]["skipReason"] == "RUN_CREDIT_BUDGET_EXCEEDED"
    assert called["provider"] == 0


def test_verified_credit_budget_passes_when_budget_sufficient(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _sixteen_games(now)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, games))
    monkeypatch.setattr(
        mgr,
        "_load_line_board_market_presence",
        lambda: {str(g["eventId"]): {"SPREAD", "MONEYLINE", "TOTAL"} for g in games},
    )
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    plan = mgr.build_pregame_collection_plan(dry_run=True, max_estimated_credits_per_run=96.0, now_utc=now)
    assert "RUN_CREDIT_BUDGET_EXCEEDED" not in plan["skipReasons"]
    assert plan["creditBudget"]["pass"] is True


def test_unknown_cost_real_execution_blocked_by_default(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, _games(now)))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {"evt-open": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-day": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-close": {"SPREAD", "MONEYLINE", "TOTAL"}})
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    called = {"provider": 0}

    def _provider(*args, **kwargs):
        called["provider"] += 1
        raise AssertionError("provider should not be called when unknown cost is not explicitly allowed")

    monkeypatch.setattr(shadow_markets, "_call_odds_api_event_odds", _provider)
    out = mgr.run_pregame_collection_manager(dry_run=False, prop_allowlist=["player_pass_yds"], allow_unknown_weekly_usage=True)

    assert out["status"] == "SKIPPED"
    assert out["execution"]["providerRequests"] == 0
    assert out["execution"]["skipReason"] == "UNKNOWN_PROVIDER_CREDIT_COST"
    assert called["provider"] == 0


def test_unknown_cost_explicit_opt_in_still_allows_execution(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    games = [
        {
            "eventId": "evt-day",
            "commenceTime": (now + timedelta(hours=3)).isoformat(),
            "awayAbbreviation": "KC",
            "homeAbbreviation": "BUF",
        }
    ]
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, games))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {"evt-day": {"SPREAD", "MONEYLINE", "TOTAL"}})
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)
    monkeypatch.setattr(shadow_markets, "capture_prospective_from_line_board", lambda week=None, season=None: {"rowsReceived": 1})

    def _provider(event_id: str, markets: list[str]):
        return 200, {"x-requests-last": "1"}, {"bookmakers": []}

    monkeypatch.setattr(shadow_markets, "_call_odds_api_event_odds", _provider)
    out = mgr.run_pregame_collection_manager(
        dry_run=False,
        allow_unknown_credit_cost=True,
        allow_unknown_weekly_usage=True,
        prop_allowlist=["player_pass_yds"],
    )

    assert out["status"] == "COMPLETED"
    assert out["execution"]["providerRequests"] == 1


def test_unknown_quota_behavior_is_null_when_unavailable(shadow_db):
    api = mgr._api_usage_today()
    assert api["actualCreditsToday"] is None
    assert api["quotaRemaining"] is None
    assert api["quotaUsed"] is None


def test_duplicate_prevention_and_due_counts(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, _games(now)))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {"evt-open": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-day": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-close": {"SPREAD", "MONEYLINE", "TOTAL"}})

    def _market_exists(event_id: str, family: str, state: str) -> bool:
        return event_id == "evt-day" and family == "SPREAD" and state == "CURRENT"

    def _prop_exists(event_id: str, state: str) -> bool:
        return event_id == "evt-open" and state == "OPENING"

    monkeypatch.setattr(mgr, "_state_exists_for_market", _market_exists)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", _prop_exists)

    plan = mgr.build_pregame_collection_plan(dry_run=True, now_utc=now)
    assert plan["snapshotsDue"]["spread"] >= 2
    assert plan["duplicatesPrevented"] >= 1


def test_player_props_enforced_pregame_only(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = [
        {
            "eventId": "evt-past",
            "commenceTime": (now - timedelta(hours=1)).isoformat(),
            "awayAbbreviation": "NO",
            "homeAbbreviation": "DET",
        }
    ]
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, games))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {"evt-past": {"SPREAD", "MONEYLINE", "TOTAL"}})
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    plan = mgr.build_pregame_collection_plan(dry_run=True, now_utc=now)
    assert plan["eventsEvaluated"] == 0
    assert plan["snapshotsDue"]["playerProp"] == 0


def test_skipped_request_reason_persists_in_telemetry(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, _games(now)))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {"evt-open": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-day": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-close": {"SPREAD", "MONEYLINE", "TOTAL"}})
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    out = mgr.run_pregame_collection_manager(dry_run=False, max_requests_per_run=0, allow_unknown_weekly_usage=True)
    assert out["status"] == "SKIPPED"

    con = shadow_markets._connect()
    row = con.execute("SELECT skip_reason, skipped FROM pregame_collection_request_telemetry ORDER BY id DESC LIMIT 1").fetchone()
    con.close()

    assert row is not None
    assert str(row["skip_reason"]) == "REQUEST_BUDGET_EXCEEDED"
    assert int(row["skipped"]) == 1


def test_unknown_cost_explicit_opt_in_allows_execution_and_tracks_actual_credits(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    games = [
        {
            "eventId": "evt-day",
            "commenceTime": (now + timedelta(hours=3)).isoformat(),
            "awayAbbreviation": "KC",
            "homeAbbreviation": "BUF",
        }
    ]
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, games))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {"evt-day": {"SPREAD", "MONEYLINE", "TOTAL"}})
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)
    monkeypatch.setattr(shadow_markets, "capture_prospective_from_line_board", lambda week=None, season=None: {"rowsReceived": 1})

    def _provider(event_id: str, markets: list[str]):
        payload = {
            "bookmakers": [
                {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "last_update": (now - timedelta(minutes=1)).isoformat(),
                    "markets": [
                        {
                            "key": "player_pass_yds",
                            "last_update": (now - timedelta(minutes=1)).isoformat(),
                            "outcomes": [
                                {"name": "Over", "description": "Patrick Mahomes", "point": 280.5, "price": -110, "team": "KC"},
                                {"name": "Under", "description": "Patrick Mahomes", "point": 280.5, "price": -110, "team": "KC"},
                            ],
                        }
                    ],
                }
            ]
        }
        headers = {"x-requests-last": "1", "x-requests-remaining": "4999", "x-requests-used": "1"}
        return 200, headers, payload

    monkeypatch.setattr(shadow_markets, "_call_odds_api_event_odds", _provider)

    out = mgr.run_pregame_collection_manager(
        dry_run=False,
        allow_unknown_weekly_usage=True,
        prop_allowlist=list(mgr.DEFAULT_PROP_ALLOWLIST),
    )
    assert out["status"] == "COMPLETED"
    assert out["execution"]["providerRequests"] == 1
    assert out["execution"]["actualCreditsConsumed"] == 1.0
    assert out["execution"]["creditCostEstimateMismatch"] is True

    status = mgr.pregame_collection_status_report()
    assert status["api"]["requestsToday"] >= 1
    assert status["api"]["estimatedCreditsToday"] is not None
    assert status["api"]["actualCreditsToday"] is not None


def test_missing_actual_credit_telemetry_remains_unknown(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    games = [
        {
            "eventId": "evt-day",
            "commenceTime": (now + timedelta(hours=2)).isoformat(),
            "awayAbbreviation": "KC",
            "homeAbbreviation": "BUF",
        }
    ]
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, games))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {"evt-day": {"SPREAD", "MONEYLINE", "TOTAL"}})
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)
    monkeypatch.setattr(shadow_markets, "capture_prospective_from_line_board", lambda week=None, season=None: {"rowsReceived": 1})

    def _provider(event_id: str, markets: list[str]):
        payload = {"bookmakers": []}
        headers = {"x-requests-remaining": "4999", "x-requests-used": "1"}
        return 200, headers, payload

    monkeypatch.setattr(shadow_markets, "_call_odds_api_event_odds", _provider)

    out = mgr.run_pregame_collection_manager(
        dry_run=False,
        allow_unknown_weekly_usage=True,
        prop_allowlist=list(mgr.DEFAULT_PROP_ALLOWLIST),
    )
    assert out["status"] == "COMPLETED"
    assert out["execution"]["actualCreditsConsumed"] is None
    assert out["execution"]["creditCostEstimateMismatch"] is False


def test_request_budget_enforced_even_when_credit_cost_unknown(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, _games(now)))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {"evt-open": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-day": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-close": {"SPREAD", "MONEYLINE", "TOTAL"}})
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    plan = mgr.build_pregame_collection_plan(
        dry_run=False,
        max_requests_per_run=0,
        prop_allowlist=["player_pass_yds"],
        now_utc=now,
    )
    assert plan["estimatedCredits"] is None
    assert "REQUEST_BUDGET_EXCEEDED" in plan["skipReasons"]


def test_request_count_not_treated_as_credit_cost(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, _games(now)))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {"evt-open": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-day": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-close": {"SPREAD", "MONEYLINE", "TOTAL"}})
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    plan = mgr.build_pregame_collection_plan(dry_run=True, now_utc=now, prop_allowlist=["player_pass_yds"])
    assert plan["plannedRequests"] == 1
    assert plan["estimatedCredits"] is None


def test_request_shape_telemetry_fields_present(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, _games(now)))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {"evt-open": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-day": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-close": {"SPREAD", "MONEYLINE", "TOTAL"}})
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    out = mgr.run_pregame_collection_manager(dry_run=False, max_requests_per_run=0, allow_unknown_weekly_usage=True)
    assert out["status"] == "SKIPPED"

    con = shadow_markets._connect()
    row = con.execute(
        "SELECT endpoint_type, region, market_count FROM pregame_collection_request_telemetry ORDER BY id DESC LIMIT 1"
    ).fetchone()
    con.close()
    assert row is not None
    assert str(row["endpoint_type"]) == "EVENT_ODDS"
    assert str(row["region"]) == "us"
    assert int(row["market_count"]) >= 1


def test_weekly_hard_budget_blocks_provider_requests_before_execution(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, _games(now)))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {"evt-open": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-day": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-close": {"SPREAD", "MONEYLINE", "TOTAL"}})
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)
    monkeypatch.setattr(
        mgr,
        "evaluate_optional_provider_request",
        lambda **kwargs: {
            "allowed": False,
            "reason": "WEEKLY_HARD_BUDGET_EXCEEDED",
            "warnings": [],
            "quotaSafety": {"weeklyUsageStatus": "KNOWN"},
        },
    )

    called = {"provider": 0}

    def _provider(*args, **kwargs):
        called["provider"] += 1
        raise AssertionError("provider should not be called when weekly hard budget blocks run")

    monkeypatch.setattr(shadow_markets, "_call_odds_api_event_odds", _provider)
    out = mgr.run_pregame_collection_manager(dry_run=False)
    assert out["status"] == "SKIPPED"
    assert out["execution"]["providerRequests"] == 0
    assert out["execution"]["skipReason"] == "WEEKLY_HARD_BUDGET_EXCEEDED"
    assert called["provider"] == 0


def test_minimum_reserve_blocks_provider_requests_before_execution(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, _games(now)))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {"evt-open": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-day": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-close": {"SPREAD", "MONEYLINE", "TOTAL"}})
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)
    monkeypatch.setattr(
        mgr,
        "evaluate_optional_provider_request",
        lambda **kwargs: {
            "allowed": False,
            "reason": "QUOTA_MINIMUM_RESERVE_BREACHED",
            "warnings": [],
            "quotaSafety": {"weeklyUsageStatus": "KNOWN"},
        },
    )

    called = {"provider": 0}

    def _provider(*args, **kwargs):
        called["provider"] += 1
        raise AssertionError("provider should not be called when minimum reserve blocks run")

    monkeypatch.setattr(shadow_markets, "_call_odds_api_event_odds", _provider)
    out = mgr.run_pregame_collection_manager(dry_run=False)
    assert out["status"] == "SKIPPED"
    assert out["execution"]["providerRequests"] == 0
    assert out["execution"]["skipReason"] == "QUOTA_MINIMUM_RESERVE_BREACHED"
    assert called["provider"] == 0


def test_core_capture_passes_both_week_and_season_without_provider_request(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = [
        {
            "eventId": "evt-open",
            "season": 2026,
            "week": 1,
            "commenceTime": (now + timedelta(hours=30)).isoformat(),
            "awayAbbreviation": "KC",
            "homeAbbreviation": "BUF",
        }
    ]
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, games))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {"evt-open": {"SPREAD", "MONEYLINE", "TOTAL"}})
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    capture_args = {}

    def _capture(week=None, season=None):
        capture_args["week"] = week
        capture_args["season"] = season
        return {"rowsReceived": 0}

    monkeypatch.setattr(shadow_markets, "capture_prospective_from_line_board", _capture)

    called = {"provider": 0}

    def _provider(*args, **kwargs):
        called["provider"] += 1
        raise AssertionError("provider should not be called for opening-only run")

    monkeypatch.setattr(shadow_markets, "_call_odds_api_event_odds", _provider)

    out = mgr.run_pregame_collection_manager(dry_run=False, allow_unknown_weekly_usage=True)
    assert out["status"] == "COMPLETED"
    assert out["execution"]["providerRequests"] == 0
    assert capture_args["week"] == 1
    assert capture_args["season"] == 2026
    assert called["provider"] == 0


def test_week1_capture_excludes_other_weeks_and_preseason_rows_without_provider_requests(shadow_db, monkeypatch):
    rows = [
        {
            "api_event_id": "2026_1_KC_BUF",
            "commence_time": "2026-09-10T20:20:00Z",
            "away_team": "KC",
            "home_team": "BUF",
            "sportsbook": "DraftKings",
            "market": "spread",
            "side": "home",
            "latest_point": -3.0,
            "opening_point_observed": -2.5,
            "latest_price": -110,
            "opening_price_observed": -110,
            "snapshots": 2,
            "first_seen": "2026-09-10T18:00:00Z",
            "last_seen": "2026-09-10T19:00:00Z",
            "steam_flag": False,
        },
        {
            "api_event_id": "2026_2_DAL_PHI",
            "commence_time": "2026-09-17T20:20:00Z",
            "away_team": "DAL",
            "home_team": "PHI",
            "sportsbook": "DraftKings",
            "market": "spread",
            "side": "home",
            "latest_point": -1.5,
            "opening_point_observed": -1.0,
            "latest_price": -108,
            "opening_price_observed": -110,
            "snapshots": 2,
            "first_seen": "2026-09-17T18:00:00Z",
            "last_seen": "2026-09-17T19:00:00Z",
            "steam_flag": False,
        },
        {
            "api_event_id": "2026_0_LV_LAR",
            "commence_time": "2026-08-20T20:20:00Z",
            "away_team": "LV",
            "home_team": "LAR",
            "sportsbook": "DraftKings",
            "market": "spread",
            "side": "home",
            "latest_point": -2.0,
            "opening_point_observed": -2.0,
            "latest_price": -110,
            "opening_price_observed": -110,
            "snapshots": 2,
            "first_seen": "2026-08-20T18:00:00Z",
            "last_seen": "2026-08-20T19:00:00Z",
            "steam_flag": False,
        },
    ]

    monkeypatch.setattr(shadow_markets, "_load_line_board", lambda: pd.DataFrame(rows))
    monkeypatch.setattr(shadow_markets, "_load_projection_lookup", lambda: {})

    out = shadow_markets.capture_prospective_from_line_board(week=1, season=2026)
    assert out["rowsReceived"] == 1

    con = shadow_markets._connect()
    captured = con.execute(
        "SELECT DISTINCT event_id FROM prospective_market_snapshots ORDER BY event_id"
    ).fetchall()
    con.close()
    assert [str(r[0]) for r in captured] == ["2026_1_KC_BUF"]


def test_schedule_opening_due_when_absent(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=30)
    out = _build_schedule(monkeypatch, now, games)
    event = out["events"][0]

    assert event["currentLifecycleWindow"] == "OPENING"
    assert event["spread"]["OPENING"] == "DUE"


def test_schedule_opening_not_due_if_already_captured(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=30)

    def _market_exists(event_id: str, family: str, state: str) -> bool:
        return state == "OPENING"

    out = _build_schedule(monkeypatch, now, games, market_exists=_market_exists)
    event = out["events"][0]
    assert event["spread"]["OPENING"] == "CAPTURED"


def test_schedule_game_day_due_when_absent(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=10)
    out = _build_schedule(monkeypatch, now, games)
    event = out["events"][0]

    assert event["currentLifecycleWindow"] == "GAME_DAY"
    assert event["spread"]["GAME_DAY"] == "DUE"


def test_schedule_game_day_not_due_if_already_captured(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=10)

    def _market_exists(event_id: str, family: str, state: str) -> bool:
        return state == "CURRENT"

    out = _build_schedule(monkeypatch, now, games, market_exists=_market_exists)
    event = out["events"][0]
    assert event["spread"]["GAME_DAY"] == "CAPTURED"


def test_schedule_closing_due_when_absent(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=1)
    out = _build_schedule(monkeypatch, now, games)
    event = out["events"][0]

    assert event["currentLifecycleWindow"] == "CLOSING"
    assert event["spread"]["CLOSING"] == "DUE"


def test_schedule_closing_not_due_if_already_captured(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=1)

    def _market_exists(event_id: str, family: str, state: str) -> bool:
        return state == "CLOSING"

    out = _build_schedule(monkeypatch, now, games, market_exists=_market_exists)
    event = out["events"][0]
    assert event["spread"]["CLOSING"] == "CAPTURED"


def test_schedule_post_kickoff_closes_all_pregame_states(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=-1)
    out = _build_schedule(monkeypatch, now, games)
    event = out["events"][0]

    assert event["currentLifecycleWindow"] == "CLOSED"
    assert event["spread"]["OPENING"] == "CLOSED"
    assert event["spread"]["GAME_DAY"] == "CLOSED"
    assert event["spread"]["CLOSING"] == "CLOSED"
    assert out["totals"]["standardSnapshotsDue"] == 0


def test_schedule_missed_opening_marked_missed_not_backfilled(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=10)
    out = _build_schedule(monkeypatch, now, games)
    event = out["events"][0]

    assert event["spread"]["OPENING"] == "MISSED"
    assert event["spread"]["GAME_DAY"] == "DUE"


def test_schedule_missed_game_day_marked_missed_in_closing(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=1)
    out = _build_schedule(monkeypatch, now, games)
    event = out["events"][0]

    assert event["spread"]["GAME_DAY"] == "MISSED"
    assert event["spread"]["CLOSING"] == "DUE"


def test_schedule_player_props_due_only_during_game_day(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=10)
    out = _build_schedule(monkeypatch, now, games)
    event = out["events"][0]

    assert event["playerProps"]["GAME_DAY"] == "DUE"


def test_schedule_player_props_not_due_during_opening(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=30)
    out = _build_schedule(monkeypatch, now, games)
    event = out["events"][0]

    assert event["playerProps"]["GAME_DAY"] == "FUTURE"


def test_schedule_player_props_not_due_during_closing(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=1)
    out = _build_schedule(monkeypatch, now, games)
    event = out["events"][0]

    assert event["playerProps"]["GAME_DAY"] == "MISSED"


def test_schedule_player_props_closed_post_kickoff(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=-1)
    out = _build_schedule(monkeypatch, now, games)
    event = out["events"][0]

    assert event["playerProps"]["GAME_DAY"] == "CLOSED"


@pytest.mark.parametrize("game_count,expected_credits", [(16, 96.0), (17, 102.0), (14, 84.0)])
def test_schedule_verified_player_prop_credits_by_slate_size(shadow_db, monkeypatch, game_count: int, expected_credits: float):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=game_count, hours_to_kickoff=10)
    out = _build_schedule(monkeypatch, now, games)

    assert out["totals"]["playerPropSnapshotsDue"] == game_count
    assert out["totals"]["verifiedPlayerPropCreditsDue"] == expected_credits


def test_schedule_dry_run_provider_calls_remain_zero(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=3, hours_to_kickoff=10)
    out = _build_schedule(monkeypatch, now, games)

    assert out["totals"]["providerRequestsMade"] == 0
    assert out["totals"]["providerCreditsSpent"] == 0


def test_schedule_duplicate_state_protection_marks_captured_once(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=30)

    def _market_exists(event_id: str, family: str, state: str) -> bool:
        return state == "OPENING"

    out = _build_schedule(monkeypatch, now, games, market_exists=_market_exists)
    event = out["events"][0]

    assert event["spread"]["OPENING"] == "CAPTURED"
    assert event["spread"]["GAME_DAY"] == "FUTURE"


def test_schedule_unknown_prop_request_shape_remains_fail_safe(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=2, hours_to_kickoff=10)
    out = _build_schedule(monkeypatch, now, games, prop_allowlist=["player_pass_yds"])

    assert out["totals"]["playerPropVerifiedCreditCostStatus"] == "UNKNOWN"
    assert out["totals"]["verifiedPlayerPropCreditsDue"] is None


def test_schedule_production_firewalls_unchanged(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=10)
    out = _build_schedule(monkeypatch, now, games)

    assert out["firewalls"]["officialProductionMarket"] == "SPREAD"
    assert out["firewalls"]["moneylineProductionEligible"] is False
    assert out["firewalls"]["totalProductionEligible"] is False
    assert out["firewalls"]["playerPropProductionEligible"] is False
    assert out["firewalls"]["livePolling"] == "NO"


def test_production_firewall_invariants_unchanged(shadow_db):
    contract = shadow_markets.player_prop_market_contract()
    model = contract["modelFields"]

    assert model["productionEligible"] is False
    assert model["modelValidated"] is False
    assert model["crossMarketComparable"] is False
    assert model["shadowRecommendationEligible"] is False


def test_schedule_contract_includes_canonical_fields(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=10)
    out = _build_schedule(monkeypatch, now, games)
    event = out["events"][0]

    assert out["generatedAtUTC"]
    assert out["eventsTracked"] == 1
    assert out["policy"]["lifecycleNormalization"]["storage"]["GAME_DAY"] == "CURRENT"
    assert out["policy"]["continuousPolling"] == "NO"
    assert out["policy"]["postKickoffSportsbookCollection"] == "NO"

    assert event["matchup"]
    assert event["nextCollectionState"] == "GAME_DAY"
    assert event["nextCollectionWindow"] == "GAME_DAY"
    assert event["playerPropGameDayStatus"] == "DUE"
    assert event["postKickoffCollectionAllowed"] == "NO"

    telemetry = event["stateTelemetry"]
    assert telemetry["SPREAD"]["GAME_DAY"]["storageState"] == "CURRENT"
    assert telemetry["SPREAD"]["GAME_DAY"]["providerRequestRequired"] == "NO"
    assert telemetry["PLAYER_PROPS"]["GAME_DAY"]["storageState"] == "CURRENT"


def test_p1_inconsistency_fixed_not_tracked_family_is_explicit(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=30)

    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, games))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {str(games[0]["eventId"]): {"MONEYLINE", "TOTAL"}})
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    out = mgr.build_pregame_collection_schedule_v1(week=1, now_utc=now)
    event = out["events"][0]

    assert event["spread"]["OPENING"] == "NOT_TRACKED"
    assert event["moneyline"]["OPENING"] == "DUE"
    assert event["total"]["OPENING"] == "DUE"
    assert out["totals"]["openingDue"] == 2
    assert out["totals"]["standardSnapshotsDue"] == 2
    assert out["totals"]["standardFamilyCoverage"]["coveredFamilies"] == ["MONEYLINE", "TOTAL"]
    assert out["totals"]["standardFamilyCoverage"]["uncoveredFamilies"] == ["SPREAD"]


def test_state_telemetry_marks_captured_without_reschedule(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    games = _n_games(now, count=1, hours_to_kickoff=10)

    def _market_exists(event_id: str, family: str, state: str) -> bool:
        return family == "SPREAD" and state == "CURRENT"

    out = _build_schedule(monkeypatch, now, games, market_exists=_market_exists)
    event = out["events"][0]

    assert event["spread"]["GAME_DAY"] == "CAPTURED"
    assert event["stateTelemetry"]["SPREAD"]["GAME_DAY"]["status"] == "CAPTURED"
    assert out["totals"]["gameDayDue"] == 2


def test_player_prop_collection_disabled_by_default(shadow_db, monkeypatch):
    monkeypatch.delenv("PLAYER_PROP_COLLECTION_ENABLED", raising=False)
    cfg = mgr._resolve_config(dry_run=True)
    assert cfg.player_prop_collection_enabled is False


def test_plan_excludes_prop_requests_when_collection_disabled(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("PLAYER_PROP_COLLECTION_ENABLED", "0")
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, _n_games(now, count=16, hours_to_kickoff=10)))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: _full_standard_presence(_n_games(now, count=16, hours_to_kickoff=10)))
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    plan = mgr.build_pregame_collection_plan(dry_run=True, now_utc=now)
    assert plan["playerPropCollectionEnabled"] is False
    assert plan["playerPropCollectionSkipReason"] == "PLAYER_PROP_COLLECTION_DISABLED"
    assert plan["snapshotsDue"]["playerProp"] == 16
    assert plan["plannedRequests"] == 0
    assert plan["estimatedRequests"] == 0
    assert plan["estimatedCreditsStatus"] == "DISABLED"
    assert plan["estimatedCredits"] == 0.0
    assert plan["playerProp"]["collectionEnabled"] is False
    assert plan["playerProp"]["collectionSkipReason"] == "PLAYER_PROP_COLLECTION_DISABLED"


def test_schedule_excludes_prop_provider_requests_when_collection_disabled(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("PLAYER_PROP_COLLECTION_ENABLED", "0")
    games = _n_games(now, count=2, hours_to_kickoff=10)
    out = _build_schedule(monkeypatch, now, games)

    assert out["playerPropCollectionEnabled"] is False
    assert out["totals"]["playerPropSnapshotsDue"] == 2
    assert out["totals"]["plannedPlayerPropProviderRequests"] == 0
    assert out["totals"]["playerPropProviderRequestsRequired"] == 0
    assert out["totals"]["playerPropVerifiedCreditCostStatus"] == "DISABLED"
    assert out["totals"]["verifiedPlayerPropCreditsDue"] == 0.0
    assert out["weeklyCostModel"]["projectedWeekCredits"] == 0.0
    assert out["firewalls"]["playerPropCollectionEnabled"] is False
    assert out["events"][0]["stateTelemetry"]["PLAYER_PROPS"]["GAME_DAY"]["providerRequestRequired"] == "NO"


def test_run_manager_supports_pregame_true_with_props_disabled(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("PLAYER_PROP_COLLECTION_ENABLED", "0")
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    games = _games(now)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, games))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: _full_standard_presence(games))
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    capture_args = {}
    ingest_called = {"count": 0}

    def _capture(week=None, season=None):
        capture_args["week"] = week
        capture_args["season"] = season
        return {"rowsReceived": 9}

    def _ingest(*args, **kwargs):
        ingest_called["count"] += 1
        raise AssertionError("player prop ingestion should not run when collection is disabled")

    monkeypatch.setattr(shadow_markets, "capture_prospective_from_line_board", _capture)
    monkeypatch.setattr(shadow_markets, "ingest_player_prop_market_snapshots", _ingest)

    out = mgr.run_pregame_collection_manager(dry_run=False, allow_unknown_weekly_usage=True)
    assert out["status"] == "COMPLETED"
    assert out["execution"]["providerRequests"] == 0
    assert out["execution"]["playerPropCollectionEnabled"] is False
    assert out["execution"]["playerPropCollectionSkipReason"] == "PLAYER_PROP_COLLECTION_DISABLED"
    assert out["execution"]["playerPropIngestion"]["status"] == "DISABLED"
    assert out["execution"]["playerPropIngestion"]["skipReason"] == "PLAYER_PROP_COLLECTION_DISABLED"
    assert capture_args["week"] == 1
    assert ingest_called["count"] == 0


def test_prop_planning_restored_when_collection_enabled(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("PLAYER_PROP_COLLECTION_ENABLED", "1")
    games = _n_games(now, count=16, hours_to_kickoff=10)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, games))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: _full_standard_presence(games))
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    plan = mgr.build_pregame_collection_plan(dry_run=True, now_utc=now)
    assert plan["playerPropCollectionEnabled"] is True
    assert plan["plannedRequests"] == 16
    assert plan["estimatedCreditsStatus"] == "VERIFIED"
    assert plan["estimatedCredits"] == 96.0
