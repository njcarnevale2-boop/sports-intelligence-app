from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading
from unittest.mock import patch

import duckdb

from app.services import odds_status
from app.runtime_jobs.odds_refresh import build_core_request_signature, core_request_shape_id


def _setup_usage_db(
    runtime_root,
    *,
    requests_last: int | None = 4,
    requests_used: int = 396,
    requests_remaining: int = 19604,
    request_shape_id: str | None = None,
    request_shape_signature: str | None = None,
    request_provenance: str | None = None,
):
    db_path = runtime_root / "database" / "nfl_model.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path))
    try:
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
        con.execute(
            """
            INSERT INTO odds_snapshots VALUES (
                CURRENT_TIMESTAMP,
                'evt-1',
                CURRENT_TIMESTAMP,
                'Home',
                'Away',
                'H',
                'A',
                'draftkings',
                'DraftKings',
                'spreads',
                'Home',
                'home',
                -2.5,
                -110,
                0.5,
                'current',
                'the_odds_api'
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS odds_api_usage (
                fetched_at TIMESTAMP,
                endpoint VARCHAR,
                requests_remaining INTEGER,
                requests_used INTEGER,
                requests_last INTEGER,
                request_shape_id VARCHAR,
                request_shape_signature VARCHAR,
                request_provenance VARCHAR
            )
            """
        )
        con.execute(
            """
            INSERT INTO odds_api_usage VALUES (
                ?,
                '/sports/{sport}/odds',
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            )
            """,
            [
                datetime.now(timezone.utc).replace(tzinfo=None),
                requests_remaining,
                requests_used,
                requests_last,
                request_shape_id,
                request_shape_signature,
                request_provenance,
            ],
        )
    finally:
        con.close()


def _insert_bootstrap_state(
    runtime_root,
    *,
    status: str,
    actual_credits: float | None,
    requests_used: int | None = 396,
    requests_remaining: int | None = 19604,
):
    db_path = runtime_root / "database" / "nfl_model.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        odds_status._ensure_bootstrap_schema(con)
        con.execute(
            """
            INSERT OR REPLACE INTO core_odds_cost_bootstrap VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                core_request_shape_id(),
                odds_status.json.dumps(build_core_request_signature(), sort_keys=True, separators=(",", ":")),
                status,
                datetime.now(timezone.utc).replace(tzinfo=None),
                datetime.now(timezone.utc).replace(tzinfo=None),
                actual_credits,
                requests_used,
                requests_remaining,
                None,
                "BOOTSTRAP_CORE_COST",
            ],
        )
    finally:
        con.close()


def _insert_usage_row(
    runtime_root,
    *,
    requests_last: int | None,
    requests_used: int,
    requests_remaining: int,
    request_shape_id: str,
    request_shape_signature: str,
    request_provenance: str,
):
    db_path = runtime_root / "database" / "nfl_model.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS odds_api_usage (
                fetched_at TIMESTAMP,
                endpoint VARCHAR,
                requests_remaining INTEGER,
                requests_used INTEGER,
                requests_last INTEGER,
                request_shape_id VARCHAR,
                request_shape_signature VARCHAR,
                request_provenance VARCHAR
            )
            """
        )
        con.execute(
            """
            INSERT INTO odds_api_usage VALUES (?, '/sports/{sport}/odds', ?, ?, ?, ?, ?, ?)
            """,
            [
                datetime.now(timezone.utc).replace(tzinfo=None),
                requests_remaining,
                requests_used,
                requests_last,
                request_shape_id,
                request_shape_signature,
                request_provenance,
            ],
        )
    finally:
        con.close()


def test_get_odds_status_exposes_latest_core_request_cost_and_cumulative_usage(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    signature = build_core_request_signature()
    _setup_usage_db(
        runtime_root,
        requests_last=4,
        requests_used=396,
        requests_remaining=19604,
        request_shape_id=core_request_shape_id(),
        request_shape_signature=odds_status.json.dumps(signature, sort_keys=True, separators=(",", ":")),
    )

    out = odds_status.get_odds_status()

    assert out["coreOddsLastRequestCredits"] == 4.0
    assert out["coreOddsRequestsUsed"] == 396
    assert out["coreOddsRequestsRemaining"] == 19604
    assert out["coreOddsLastRequestAt"] is not None
    assert out["coreOddsRequestShapeId"] == core_request_shape_id()
    assert out["coreOddsVerifiedRequestCost"] is None
    assert out["coreOddsCostVerificationStatus"] == "UNKNOWN"


def test_exact_verified_shape_permits_request_when_quota_healthy(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=3, requests_used=396, requests_remaining=19604)
    _insert_bootstrap_state(runtime_root, status="COMPLETED", actual_credits=3.0)

    verification = odds_status.get_core_request_cost_verification()
    guard = odds_status.evaluate_optional_provider_request(
        estimated_credits=verification.get("coreOddsVerifiedRequestCost"),
        allow_unknown_credit_cost=False,
        allow_unknown_weekly_usage=False,
        override_quota_guards=False,
    )

    assert verification["coreOddsVerifiedRequestCost"] == 3.0
    assert verification["coreOddsCostVerificationStatus"] == "VERIFIED"
    assert guard["allowed"] is True


def test_markets_changed_results_in_shape_changed_and_blocked(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=3)
    _insert_bootstrap_state(runtime_root, status="COMPLETED", actual_credits=3.0)
    monkeypatch.setenv("ODDS_MARKETS", "spreads")

    verification = odds_status.get_core_request_cost_verification()
    guard = odds_status.evaluate_optional_provider_request(
        estimated_credits=verification.get("coreOddsVerifiedRequestCost"),
        allow_unknown_credit_cost=False,
        allow_unknown_weekly_usage=False,
        override_quota_guards=False,
    )

    assert verification["coreOddsCostVerificationStatus"] == "SHAPE_CHANGED"
    assert verification["coreOddsVerifiedRequestCost"] is None
    assert guard["allowed"] is False
    assert guard["reason"] == "UNKNOWN_PROVIDER_CREDIT_COST"


def test_regions_changed_results_in_shape_changed_and_blocked(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=3)
    _insert_bootstrap_state(runtime_root, status="COMPLETED", actual_credits=3.0)
    monkeypatch.setenv("ODDS_REGION", "eu")

    verification = odds_status.get_core_request_cost_verification()
    guard = odds_status.evaluate_optional_provider_request(
        estimated_credits=verification.get("coreOddsVerifiedRequestCost"),
        allow_unknown_credit_cost=False,
        allow_unknown_weekly_usage=False,
        override_quota_guards=False,
    )

    assert verification["coreOddsCostVerificationStatus"] == "SHAPE_CHANGED"
    assert guard["allowed"] is False


def test_bookmaker_config_changed_results_in_shape_changed_and_blocked(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=3)
    _insert_bootstrap_state(runtime_root, status="COMPLETED", actual_credits=3.0)
    monkeypatch.setenv("ODDS_BOOKMAKERS", "draftkings,fanduel")

    verification = odds_status.get_core_request_cost_verification()
    guard = odds_status.evaluate_optional_provider_request(
        estimated_credits=verification.get("coreOddsVerifiedRequestCost"),
        allow_unknown_credit_cost=False,
        allow_unknown_weekly_usage=False,
        override_quota_guards=False,
    )

    assert verification["coreOddsCostVerificationStatus"] == "SHAPE_CHANGED"
    assert guard["allowed"] is False


def test_missing_requests_last_keeps_cost_unknown_and_blocks(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    signature = build_core_request_signature()
    _setup_usage_db(
        runtime_root,
        requests_last=None,
        request_shape_id=core_request_shape_id(),
        request_shape_signature=odds_status.json.dumps(signature, sort_keys=True, separators=(",", ":")),
        request_provenance="BOOTSTRAP_CORE_COST",
    )

    verification = odds_status.get_core_request_cost_verification()
    guard = odds_status.evaluate_optional_provider_request(
        estimated_credits=verification.get("coreOddsVerifiedRequestCost"),
        allow_unknown_credit_cost=False,
        allow_unknown_weekly_usage=False,
        override_quota_guards=False,
    )

    assert verification["coreOddsCostVerificationStatus"] == "UNKNOWN"
    assert verification["coreOddsVerifiedRequestCost"] is None
    assert guard["allowed"] is False
    assert guard["reason"] == "UNKNOWN_PROVIDER_CREDIT_COST"


def test_legacy_three_credit_row_without_shape_provenance_remains_unknown(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(
        runtime_root,
        requests_last=3,
        requests_used=396,
        requests_remaining=19604,
        request_shape_id=None,
        request_shape_signature=None,
    )

    verification = odds_status.get_core_request_cost_verification()
    assert verification["coreOddsVerifiedRequestCost"] is None
    assert verification["coreOddsCostVerificationStatus"] == "UNKNOWN"


def test_bootstrap_happy_path_executes_once_and_verifies_exact_shape(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=1, requests_used=393, requests_remaining=19607)
    signature = build_core_request_signature()
    signature_json = odds_status.json.dumps(signature, sort_keys=True, separators=(",", ":"))
    calls = {"count": 0}

    def _trigger_now(request_provenance: str = "MANUAL_REFRESH"):
        calls["count"] += 1
        _insert_usage_row(
            runtime_root,
            requests_last=3,
            requests_used=396,
            requests_remaining=19604,
            request_shape_id=core_request_shape_id(),
            request_shape_signature=signature_json,
            request_provenance=request_provenance,
        )
        return {"triggered": True, "success": True}

    with patch("app.services.refresh_orchestrator.trigger_now", side_effect=_trigger_now):
        out = odds_status.perform_core_cost_bootstrap(requested_shape_id=core_request_shape_id())

    assert calls["count"] == 1
    assert out["coreOddsCostBootstrapStatus"] == "COMPLETED"
    assert out["coreOddsVerifiedRequestCost"] == 3.0
    assert out["coreOddsCostVerificationStatus"] == "VERIFIED"


def test_second_bootstrap_attempt_does_not_call_provider(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=1, requests_used=393, requests_remaining=19607)
    signature = build_core_request_signature()
    signature_json = odds_status.json.dumps(signature, sort_keys=True, separators=(",", ":"))
    _insert_usage_row(
        runtime_root,
        requests_last=3,
        requests_used=396,
        requests_remaining=19604,
        request_shape_id=core_request_shape_id(),
        request_shape_signature=signature_json,
        request_provenance="BOOTSTRAP_CORE_COST",
    )
    db_path = runtime_root / "database" / "nfl_model.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        odds_status._ensure_bootstrap_schema(con)
        con.execute(
            """
            INSERT INTO core_odds_cost_bootstrap VALUES (?, ?, 'COMPLETED', ?, ?, 3.0, 396, 19604, NULL, 'BOOTSTRAP_CORE_COST')
            """,
            [
                core_request_shape_id(),
                signature_json,
                datetime.now(timezone.utc).replace(tzinfo=None),
                datetime.now(timezone.utc).replace(tzinfo=None),
            ],
        )
    finally:
        con.close()

    with patch("app.services.refresh_orchestrator.trigger_now") as trigger_now:
        out = odds_status.perform_core_cost_bootstrap(requested_shape_id=core_request_shape_id())

    assert out["triggered"] is False
    assert out["reason"] in {"BOOTSTRAP_NOT_REQUIRED", "BOOTSTRAP_ALREADY_COMPLETED"}
    trigger_now.assert_not_called()


def test_concurrent_bootstrap_calls_cannot_call_provider_twice(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=1, requests_used=393, requests_remaining=19607)
    signature = build_core_request_signature()
    signature_json = odds_status.json.dumps(signature, sort_keys=True, separators=(",", ":"))
    started = threading.Event()
    release = threading.Event()
    calls = {"count": 0}
    results: list[dict] = []

    def _trigger_now(request_provenance: str = "MANUAL_REFRESH"):
        calls["count"] += 1
        started.set()
        release.wait(timeout=2)
        _insert_usage_row(
            runtime_root,
            requests_last=3,
            requests_used=396,
            requests_remaining=19604,
            request_shape_id=core_request_shape_id(),
            request_shape_signature=signature_json,
            request_provenance=request_provenance,
        )
        return {"triggered": True, "success": True}

    def _call_bootstrap():
        results.append(odds_status.perform_core_cost_bootstrap(requested_shape_id=core_request_shape_id()))

    with patch("app.services.refresh_orchestrator.trigger_now", side_effect=_trigger_now):
        t1 = threading.Thread(target=_call_bootstrap)
        t2 = threading.Thread(target=_call_bootstrap)
        t1.start()
        started.wait(timeout=2)
        t2.start()
        release.set()
        t1.join()
        t2.join()

    assert calls["count"] == 1
    assert len(results) == 2
    assert any(r.get("coreOddsCostBootstrapStatus") == "COMPLETED" for r in results)


def test_persisted_bootstrap_completion_blocks_after_restart_equivalent(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=1, requests_used=393, requests_remaining=19607)
    signature = build_core_request_signature()
    signature_json = odds_status.json.dumps(signature, sort_keys=True, separators=(",", ":"))

    def _trigger_now(request_provenance: str = "MANUAL_REFRESH"):
        _insert_usage_row(
            runtime_root,
            requests_last=3,
            requests_used=396,
            requests_remaining=19604,
            request_shape_id=core_request_shape_id(),
            request_shape_signature=signature_json,
            request_provenance=request_provenance,
        )
        return {"triggered": True, "success": True}

    with patch("app.services.refresh_orchestrator.trigger_now", side_effect=_trigger_now):
        first = odds_status.perform_core_cost_bootstrap(requested_shape_id=core_request_shape_id())

    with patch("app.services.refresh_orchestrator.trigger_now") as trigger_now:
        second = odds_status.perform_core_cost_bootstrap(requested_shape_id=core_request_shape_id())

    assert first["coreOddsCostBootstrapStatus"] == "COMPLETED"
    assert second["triggered"] is False
    trigger_now.assert_not_called()


def test_verified_shape_makes_bootstrap_unnecessary(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=1, requests_used=393, requests_remaining=19607)
    signature_json = odds_status.json.dumps(build_core_request_signature(), sort_keys=True, separators=(",", ":"))
    db_path = runtime_root / "database" / "nfl_model.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        odds_status._ensure_bootstrap_schema(con)
        con.execute(
            """
            INSERT INTO core_odds_cost_bootstrap VALUES (?, ?, 'COMPLETED', ?, ?, 3.0, 396, 19604, NULL, 'BOOTSTRAP_CORE_COST')
            """,
            [
                core_request_shape_id(),
                signature_json,
                datetime.now(timezone.utc).replace(tzinfo=None),
                datetime.now(timezone.utc).replace(tzinfo=None),
            ],
        )
    finally:
        con.close()

    with patch("app.services.refresh_orchestrator.trigger_now") as trigger_now:
        out = odds_status.perform_core_cost_bootstrap(requested_shape_id=core_request_shape_id())

    assert out["triggered"] is False
    trigger_now.assert_not_called()


def test_bootstrap_shape_mismatch_blocks(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=1, requests_used=393, requests_remaining=19607)
    with patch("app.services.refresh_orchestrator.trigger_now") as trigger_now:
        out = odds_status.perform_core_cost_bootstrap(requested_shape_id="wrong-shape")
    assert out["triggered"] is False
    assert out["reason"] == "BOOTSTRAP_SHAPE_MISMATCH"
    trigger_now.assert_not_called()


def test_bootstrap_blocks_below_minimum_reserve(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=1, requests_used=393, requests_remaining=11999)
    with patch("app.services.odds_status.evaluate_optional_provider_request", return_value={
        "allowed": False,
        "reason": "QUOTA_MINIMUM_RESERVE_BREACHED",
        "warnings": [],
        "quotaSafety": {},
    }), patch("app.services.refresh_orchestrator.trigger_now") as trigger_now:
        out = odds_status.perform_core_cost_bootstrap(requested_shape_id=core_request_shape_id())
    assert out["triggered"] is False
    assert out["reason"] == "QUOTA_MINIMUM_RESERVE_BREACHED"
    trigger_now.assert_not_called()


def test_bootstrap_blocks_weekly_hard_budget(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=1098, requests_used=393, requests_remaining=19607)
    with patch("app.services.odds_status.evaluate_optional_provider_request", return_value={
        "allowed": False,
        "reason": "WEEKLY_HARD_BUDGET_EXCEEDED",
        "warnings": [],
        "quotaSafety": {},
    }), patch("app.services.refresh_orchestrator.trigger_now") as trigger_now:
        out = odds_status.perform_core_cost_bootstrap(requested_shape_id=core_request_shape_id())
    assert out["triggered"] is False
    assert out["reason"] == "WEEKLY_HARD_BUDGET_EXCEEDED"
    trigger_now.assert_not_called()


def test_bootstrap_provider_failure_does_not_mark_verified(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=1, requests_used=393, requests_remaining=19607)
    with patch("app.services.refresh_orchestrator.trigger_now", return_value={"triggered": True, "success": False, "lastError": "provider failure"}):
        out = odds_status.perform_core_cost_bootstrap(requested_shape_id=core_request_shape_id())
    assert out["coreOddsCostBootstrapStatus"] == "FAILED"
    assert out["coreOddsCostVerificationStatus"] == "UNKNOWN"


def test_bootstrap_missing_requests_last_does_not_mark_verified(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=1, requests_used=393, requests_remaining=19607)
    signature_json = odds_status.json.dumps(build_core_request_signature(), sort_keys=True, separators=(",", ":"))

    def _trigger_now(request_provenance: str = "MANUAL_REFRESH"):
        _insert_usage_row(
            runtime_root,
            requests_last=None,
            requests_used=396,
            requests_remaining=19604,
            request_shape_id=core_request_shape_id(),
            request_shape_signature=signature_json,
            request_provenance=request_provenance,
        )
        return {"triggered": True, "success": True}

    with patch("app.services.refresh_orchestrator.trigger_now", side_effect=_trigger_now):
        out = odds_status.perform_core_cost_bootstrap(requested_shape_id=core_request_shape_id())
    assert out["coreOddsCostBootstrapStatus"] == "FAILED"
    assert out["coreOddsVerifiedRequestCost"] is None


def test_bootstrap_above_cap_requires_review_not_verification(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=1, requests_used=393, requests_remaining=19607)
    signature_json = odds_status.json.dumps(build_core_request_signature(), sort_keys=True, separators=(",", ":"))

    def _trigger_now(request_provenance: str = "MANUAL_REFRESH"):
        _insert_usage_row(
            runtime_root,
            requests_last=4,
            requests_used=396,
            requests_remaining=19604,
            request_shape_id=core_request_shape_id(),
            request_shape_signature=signature_json,
            request_provenance=request_provenance,
        )
        return {"triggered": True, "success": True}

    with patch("app.services.refresh_orchestrator.trigger_now", side_effect=_trigger_now):
        out = odds_status.perform_core_cost_bootstrap(requested_shape_id=core_request_shape_id())
    assert out["coreOddsCostBootstrapStatus"] == "REVIEW_REQUIRED"
    assert out["coreOddsCostVerificationStatus"] == "UNKNOWN"


def test_bootstrap_success_uses_exact_actual_provider_cost(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=1, requests_used=393, requests_remaining=19607)
    signature_json = odds_status.json.dumps(build_core_request_signature(), sort_keys=True, separators=(",", ":"))

    def _trigger_now(request_provenance: str = "MANUAL_REFRESH"):
        _insert_usage_row(
            runtime_root,
            requests_last=2,
            requests_used=396,
            requests_remaining=19604,
            request_shape_id=core_request_shape_id(),
            request_shape_signature=signature_json,
            request_provenance=request_provenance,
        )
        return {"triggered": True, "success": True}

    with patch("app.services.refresh_orchestrator.trigger_now", side_effect=_trigger_now):
        out = odds_status.perform_core_cost_bootstrap(requested_shape_id=core_request_shape_id())
    assert out["coreOddsCostBootstrapStatus"] == "COMPLETED"
    assert out["coreOddsVerifiedRequestCost"] == 2.0


def test_evaluate_optional_provider_request_blocks_unknown_cost_by_default():
    with patch("app.services.odds_status.get_quota_safety_state", return_value={
        "weeklySoftBudget": 700.0,
        "weeklyHardBudget": 1100.0,
        "minimumReserve": 12000.0,
        "warningThresholdRemaining": 15000.0,
        "pauseThresholdRemaining": 12000.0,
        "weeklyUsageCredits": 10.0,
        "weeklyUsageStatus": "KNOWN",
        "coreOddsRequestsRemaining": 19000,
        "minimumReserveBreached": False,
        "pauseThresholdBreached": False,
        "warningThresholdBreached": False,
    }):
        out = odds_status.evaluate_optional_provider_request(
            estimated_credits=None,
            allow_unknown_credit_cost=False,
            allow_unknown_weekly_usage=True,
            override_quota_guards=False,
        )

    assert out["allowed"] is False
    assert out["reason"] == "UNKNOWN_PROVIDER_CREDIT_COST"


def test_evaluate_optional_provider_request_blocks_on_minimum_reserve():
    with patch("app.services.odds_status.get_quota_safety_state", return_value={
        "weeklySoftBudget": 700.0,
        "weeklyHardBudget": 1100.0,
        "minimumReserve": 12000.0,
        "warningThresholdRemaining": 15000.0,
        "pauseThresholdRemaining": 12000.0,
        "weeklyUsageCredits": 100.0,
        "weeklyUsageStatus": "KNOWN",
        "coreOddsRequestsRemaining": 11000,
        "minimumReserveBreached": True,
        "pauseThresholdBreached": True,
        "warningThresholdBreached": True,
    }):
        out = odds_status.evaluate_optional_provider_request(
            estimated_credits=6.0,
            allow_unknown_credit_cost=True,
            allow_unknown_weekly_usage=True,
            override_quota_guards=False,
        )

    assert out["allowed"] is False
    assert out["reason"] in {"QUOTA_PAUSE_THRESHOLD_REMAINING", "QUOTA_MINIMUM_RESERVE_BREACHED"}


def test_verified_shape_still_blocks_when_below_minimum_reserve(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=3, requests_used=396, requests_remaining=11999)
    _insert_bootstrap_state(runtime_root, status="COMPLETED", actual_credits=3.0, requests_remaining=11999)

    verification = odds_status.get_core_request_cost_verification()
    guard = odds_status.evaluate_optional_provider_request(
        estimated_credits=verification.get("coreOddsVerifiedRequestCost"),
        allow_unknown_credit_cost=False,
        allow_unknown_weekly_usage=False,
        override_quota_guards=False,
    )

    assert verification["coreOddsCostVerificationStatus"] == "VERIFIED"
    assert guard["allowed"] is False
    assert guard["reason"] == "QUOTA_PAUSE_THRESHOLD_REMAINING"


def test_evaluate_optional_provider_request_blocks_on_weekly_hard_budget():
    with patch("app.services.odds_status.get_quota_safety_state", return_value={
        "weeklySoftBudget": 700.0,
        "weeklyHardBudget": 1100.0,
        "minimumReserve": 12000.0,
        "warningThresholdRemaining": 15000.0,
        "pauseThresholdRemaining": 12000.0,
        "weeklyUsageCredits": 1099.0,
        "weeklyUsageStatus": "KNOWN",
        "coreOddsRequestsRemaining": 18000,
        "minimumReserveBreached": False,
        "pauseThresholdBreached": False,
        "warningThresholdBreached": False,
    }):
        out = odds_status.evaluate_optional_provider_request(
            estimated_credits=6.0,
            allow_unknown_credit_cost=True,
            allow_unknown_weekly_usage=False,
            override_quota_guards=False,
        )

    assert out["allowed"] is False
    assert out["reason"] == "WEEKLY_HARD_BUDGET_EXCEEDED"


def test_verified_shape_still_blocks_when_weekly_hard_budget_exceeded(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    _setup_usage_db(runtime_root, requests_last=1098, requests_used=396, requests_remaining=19604)
    _insert_bootstrap_state(runtime_root, status="COMPLETED", actual_credits=1098.0)

    verification = odds_status.get_core_request_cost_verification()
    guard = odds_status.evaluate_optional_provider_request(
        estimated_credits=verification.get("coreOddsVerifiedRequestCost"),
        allow_unknown_credit_cost=False,
        allow_unknown_weekly_usage=False,
        override_quota_guards=False,
    )

    assert verification["coreOddsCostVerificationStatus"] == "VERIFIED"
    assert guard["allowed"] is False
    assert guard["reason"] == "WEEKLY_HARD_BUDGET_EXCEEDED"


def test_quota_safety_weekly_usage_unknown_is_exposed_without_fake_number(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    db_path = runtime_root / "database" / "nfl_model.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS odds_api_usage (
                fetched_at TIMESTAMP,
                endpoint VARCHAR,
                requests_remaining INTEGER,
                requests_used INTEGER,
                requests_last INTEGER,
                request_shape_id VARCHAR,
                request_shape_signature VARCHAR
            )
            """
        )
        con.execute(
            """
            INSERT INTO odds_api_usage VALUES (?, '/sports/{sport}/odds', 19604, 396, NULL, NULL, NULL)
            """,
            [datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)],
        )
    finally:
        con.close()

    out = odds_status.get_quota_safety_state()
    assert out["weeklyUsageCredits"] is None
    assert out["weeklyUsageStatus"] == "UNKNOWN"
