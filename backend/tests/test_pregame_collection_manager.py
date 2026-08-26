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
    assert out["plan"]["estimatedCredits"] is None
    assert out["plan"]["estimatedCreditsStatus"] == "UNKNOWN"
    assert called["provider"] == 0


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
        estimated_credits_per_request=1.0,
        deterministic_credit_rule_verified=True,
        now_utc=now,
    )
    assert "RUN_CREDIT_BUDGET_EXCEEDED" in plan["skipReasons"]
    assert plan["creditBudget"]["pass"] is False


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
    out = mgr.run_pregame_collection_manager(dry_run=False)

    assert out["status"] == "SKIPPED"
    assert out["execution"]["providerRequests"] == 0
    assert out["execution"]["skipReason"] == "UNKNOWN_PROVIDER_CREDIT_COST"
    assert called["provider"] == 0


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
        allow_unknown_credit_cost=True,
        prop_allowlist=["player_pass_yds"],
    )
    assert out["status"] == "COMPLETED"
    assert out["execution"]["providerRequests"] == 1
    assert out["execution"]["actualCreditsConsumed"] == 1.0

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
        allow_unknown_credit_cost=True,
        prop_allowlist=["player_pass_yds"],
    )
    assert out["status"] == "COMPLETED"
    assert out["execution"]["actualCreditsConsumed"] is None


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

    plan = mgr.build_pregame_collection_plan(dry_run=True, now_utc=now)
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
