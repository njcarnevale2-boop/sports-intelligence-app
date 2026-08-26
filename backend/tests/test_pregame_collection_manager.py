from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import pregame_collection_manager as mgr
from app.services import shadow_markets


@pytest.fixture
def shadow_db(monkeypatch, tmp_path):
    db = tmp_path / "pregame_manager_test.sqlite"
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
    assert out["plan"]["plannedRequests"] == 3
    assert out["plan"]["estimatedCreditsStatus"] == "VERIFIED"
    assert out["plan"]["estimatedCreditsPerRequest"] == 6.0
    assert out["plan"]["estimatedCredits"] == 18.0
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
    games = _sixteen_games(now)
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

    plan = mgr.build_pregame_collection_plan(dry_run=True, max_requests_per_run=1, now_utc=now)
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
        max_estimated_credits_per_run=1.0,
        now_utc=now,
    )
    assert "RUN_CREDIT_BUDGET_EXCEEDED" in plan["skipReasons"]
    assert plan["creditBudget"]["pass"] is False


def test_verified_credit_budget_blocks_execution_before_provider_calls(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    games = _sixteen_games(now)
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
    out = mgr.run_pregame_collection_manager(dry_run=False, max_estimated_credits_per_run=95.0)
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
    out = mgr.run_pregame_collection_manager(dry_run=False, prop_allowlist=["player_pass_yds"])

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
        return 200, {"x-requests-last": "1"}, {"bookmakers": []}

    monkeypatch.setattr(shadow_markets, "_call_odds_api_event_odds", _provider)
    out = mgr.run_pregame_collection_manager(
        dry_run=False,
        allow_unknown_credit_cost=True,
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
    assert plan["duplicatesPrevented"] >= 2


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

    out = mgr.run_pregame_collection_manager(dry_run=False, max_requests_per_run=0)
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
        max_requests_per_run=2,
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
    assert plan["plannedRequests"] == 3
    assert plan["estimatedCredits"] is None


def test_request_shape_telemetry_fields_present(shadow_db, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mgr, "_utc_now", lambda: now)
    monkeypatch.setattr(mgr, "_load_week_events", lambda week=None: (1, _games(now)))
    monkeypatch.setattr(mgr, "_load_line_board_market_presence", lambda: {"evt-open": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-day": {"SPREAD", "MONEYLINE", "TOTAL"}, "evt-close": {"SPREAD", "MONEYLINE", "TOTAL"}})
    monkeypatch.setattr(mgr, "_state_exists_for_market", lambda event_id, family, state: False)
    monkeypatch.setattr(mgr, "_state_exists_for_player_prop_event", lambda event_id, state: False)

    out = mgr.run_pregame_collection_manager(dry_run=False, max_requests_per_run=0)
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


def test_production_firewall_invariants_unchanged(shadow_db):
    contract = shadow_markets.player_prop_market_contract()
    model = contract["modelFields"]

    assert model["productionEligible"] is False
    assert model["modelValidated"] is False
    assert model["crossMarketComparable"] is False
    assert model["shadowRecommendationEligible"] is False
