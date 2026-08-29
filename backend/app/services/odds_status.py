from __future__ import annotations

import os
import json
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from app.runtime_paths import runtime_paths
from app.runtime_jobs.odds_refresh import build_core_request_signature, core_request_shape_id

DB_PATH = runtime_paths.nfl_model_duckdb

_STALE_HOURS = 24  # flag data as STALE if no refresh within this window
_CORE_BOOTSTRAP_LOCK = threading.Lock()
_CORE_BOOTSTRAP_PROVENANCE = "BOOTSTRAP_CORE_COST"


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name, str(default))).strip())
    except (TypeError, ValueError):
        return float(default)


def _quota_policy() -> Dict[str, float]:
    return {
        "weeklySoftBudget": _env_float("ODDS_WEEKLY_SOFT_BUDGET", 700.0),
        "weeklyHardBudget": _env_float("ODDS_WEEKLY_HARD_BUDGET", 1100.0),
        "minimumReserve": _env_float("ODDS_MINIMUM_RESERVE", 12000.0),
        "warningThresholdRemaining": _env_float("ODDS_WARNING_THRESHOLD_REMAINING", 15000.0),
        "pauseThresholdRemaining": _env_float("ODDS_PAUSE_THRESHOLD_REMAINING", 12000.0),
    }


def _try_duckdb() -> Optional[Any]:
    """Return a DuckDB connection or None if unavailable."""
    if not DB_PATH.exists():
        return None
    try:
        import duckdb  # type: ignore
        return duckdb.connect(str(DB_PATH), read_only=True)
    except Exception:
        return None


def _connect_duckdb(*, read_only: bool) -> Optional[Any]:
    try:
        import duckdb  # type: ignore
        if not read_only:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        if read_only and not DB_PATH.exists():
            return None
        return duckdb.connect(str(DB_PATH), read_only=read_only)
    except Exception:
        return None


def _ensure_bootstrap_schema(con: Any) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS core_odds_cost_bootstrap (
            request_shape_id VARCHAR PRIMARY KEY,
            request_shape_signature VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            requested_at TIMESTAMP,
            completed_at TIMESTAMP,
            actual_credits DOUBLE,
            requests_used INTEGER,
            requests_remaining INTEGER,
            failure_reason VARCHAR,
            request_provenance VARCHAR
        )
        """
    )


def _bootstrap_cost_cap() -> float:
    return _env_float("ODDS_CORE_COST_BOOTSTRAP_MAX_CREDITS", 3.0)


def _bootstrap_row_for_shape(con: Any, shape_id: str) -> Optional[Any]:
    try:
        return con.execute(
            """
            SELECT request_shape_id, request_shape_signature, status, requested_at,
                   completed_at, actual_credits, requests_used, requests_remaining,
                   failure_reason, request_provenance
            FROM core_odds_cost_bootstrap
            WHERE request_shape_id = ?
            LIMIT 1
            """,
            [shape_id],
        ).fetchone()
    except Exception:
        return None


def get_core_cost_bootstrap_status() -> Dict[str, Any]:
    shape_id = core_request_shape_id()
    signature = build_core_request_signature()
    out: Dict[str, Any] = {
        "coreOddsCostBootstrapStatus": "AVAILABLE",
        "coreOddsCostBootstrapAt": None,
        "coreOddsCostBootstrapShapeId": shape_id,
        "coreOddsCostBootstrapActualCredits": None,
    }

    con = _try_duckdb()
    if con is None:
        return out

    try:
        tables = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'core_odds_cost_bootstrap'"
        ).fetchone()[0] > 0
        if not tables:
            return out

        row = _bootstrap_row_for_shape(con, shape_id)
        if row is None:
            return out

        status = str(row[2] or "AVAILABLE").upper()
        requested_at = row[3]
        completed_at = row[4]
        actual_credits = row[5]
        out["coreOddsCostBootstrapStatus"] = status
        out["coreOddsCostBootstrapAt"] = (
            completed_at.isoformat() if completed_at else (requested_at.isoformat() if requested_at else None)
        )
        out["coreOddsCostBootstrapActualCredits"] = float(actual_credits) if actual_credits is not None else None
        return out
    except Exception:
        return out
    finally:
        con.close()


def _usage_table_columns(con: Any) -> set[str]:
    try:
        rows = con.execute(
            "SELECT lower(column_name) FROM information_schema.columns WHERE table_name = 'odds_api_usage'"
        ).fetchall()
    except Exception:
        return set()
    return {str(row[0]) for row in rows}


def get_core_request_cost_verification() -> Dict[str, Any]:
    signature = build_core_request_signature()
    shape_id = core_request_shape_id()
    out: Dict[str, Any] = {
        "coreOddsRequestShapeId": shape_id,
        "coreOddsRequestShape": signature,
        "coreOddsVerifiedRequestCost": None,
        "coreOddsCostVerificationStatus": "UNKNOWN",
    }

    con = _try_duckdb()
    if con is None:
        return out

    try:
        has_usage = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'odds_api_usage'"
        ).fetchone()[0] > 0
        has_bootstrap = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'core_odds_cost_bootstrap'"
        ).fetchone()[0] > 0

        if has_bootstrap:
            row = _bootstrap_row_for_shape(con, shape_id)
            if row is not None:
                stored_sig = str(row[1] or "").strip()
                status = str(row[2] or "").upper()
                try:
                    parsed = json.loads(stored_sig) if stored_sig else None
                except json.JSONDecodeError:
                    parsed = None
                if parsed == signature and status == "COMPLETED" and row[5] is not None:
                    out["coreOddsVerifiedRequestCost"] = float(row[5])
                    out["coreOddsCostVerificationStatus"] = "VERIFIED"
                    return out
                if parsed == signature and status in {"FAILED", "REVIEW_REQUIRED", "IN_PROGRESS"}:
                    out["coreOddsCostVerificationStatus"] = "UNKNOWN"
                    return out

            other_completed = con.execute(
                """
                SELECT request_shape_id
                FROM core_odds_cost_bootstrap
                WHERE status = 'COMPLETED'
                ORDER BY completed_at DESC NULLS LAST, requested_at DESC NULLS LAST
                LIMIT 1
                """
            ).fetchone()
            if other_completed and str(other_completed[0] or "") != shape_id:
                out["coreOddsCostVerificationStatus"] = "SHAPE_CHANGED"
                return out

        if not has_usage:
            return out

        cols = _usage_table_columns(con)
        has_shape_cols = {"request_shape_id", "request_shape_signature", "request_provenance"}.issubset(cols)

        if has_shape_cols:
            other_shape_row = con.execute(
                """
                SELECT request_shape_id
                FROM odds_api_usage
                WHERE endpoint = '/sports/{sport}/odds'
                  AND request_shape_id IS NOT NULL
                  AND requests_last IS NOT NULL
                ORDER BY fetched_at DESC
                LIMIT 1
                """
            ).fetchone()
            if other_shape_row and str(other_shape_row[0] or "") != shape_id:
                out["coreOddsCostVerificationStatus"] = "SHAPE_CHANGED"
                return out

        legacy_row = con.execute(
            """
            SELECT requests_last
            FROM odds_api_usage
            WHERE endpoint = '/sports/{sport}/odds'
              AND requests_last IS NOT NULL
            ORDER BY fetched_at DESC
            LIMIT 1
            """
        ).fetchone()
        if legacy_row:
            out["coreOddsCostVerificationStatus"] = "UNKNOWN"
        return out
    except Exception:
        return out
    finally:
        con.close()


def get_quota_safety_state() -> Dict[str, Any]:
    policy = _quota_policy()
    core_cost = get_core_request_cost_verification()
    bootstrap = get_core_cost_bootstrap_status()
    out: Dict[str, Any] = {
        **policy,
        "weeklyUsageCredits": None,
        "weeklyUsageStatus": "UNKNOWN",
        "coreOddsLastRequestCredits": None,
        "coreOddsRequestsUsed": None,
        "coreOddsRequestsRemaining": None,
        "coreOddsLastRequestAt": None,
        "coreOddsRequestShapeId": core_cost.get("coreOddsRequestShapeId"),
        "coreOddsVerifiedRequestCost": core_cost.get("coreOddsVerifiedRequestCost"),
        "coreOddsCostVerificationStatus": core_cost.get("coreOddsCostVerificationStatus"),
        "coreOddsCostBootstrapStatus": bootstrap.get("coreOddsCostBootstrapStatus"),
        "coreOddsCostBootstrapAt": bootstrap.get("coreOddsCostBootstrapAt"),
        "coreOddsCostBootstrapShapeId": bootstrap.get("coreOddsCostBootstrapShapeId"),
        "coreOddsCostBootstrapActualCredits": bootstrap.get("coreOddsCostBootstrapActualCredits"),
        "weeklySoftBudgetExceeded": None,
        "weeklyHardBudgetExceeded": None,
        "minimumReserveBreached": None,
        "warningThresholdBreached": None,
        "pauseThresholdBreached": None,
    }

    con = _try_duckdb()
    if con is None:
        return out

    try:
        has_usage = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'odds_api_usage'"
        ).fetchone()[0] > 0
        if not has_usage:
            return out

        latest = con.execute(
            """
            SELECT fetched_at, requests_remaining, requests_used, requests_last
            FROM odds_api_usage
            ORDER BY fetched_at DESC
            LIMIT 1
            """
        ).fetchone()
        if latest:
            latest_at = latest[0]
            out["coreOddsLastRequestAt"] = latest_at.isoformat() if hasattr(latest_at, "isoformat") else str(latest_at)
            out["coreOddsRequestsRemaining"] = int(latest[1]) if latest[1] is not None else None
            out["coreOddsRequestsUsed"] = int(latest[2]) if latest[2] is not None else None
            out["coreOddsLastRequestCredits"] = float(latest[3]) if latest[3] is not None else None

        week_start = (datetime.now(timezone.utc) - timedelta(days=7)).replace(tzinfo=None)
        weekly_rows = con.execute(
            """
            SELECT requests_last
            FROM odds_api_usage
            WHERE fetched_at >= ?
            ORDER BY fetched_at ASC
            """,
            [week_start],
        ).fetchall()

        known_values = [float(row[0]) for row in weekly_rows if row[0] is not None]
        if known_values:
            weekly_usage = round(float(sum(known_values)), 4)
            out["weeklyUsageCredits"] = weekly_usage
            out["weeklyUsageStatus"] = "KNOWN"

        remaining = out.get("coreOddsRequestsRemaining")
        weekly_usage = out.get("weeklyUsageCredits")
        if remaining is not None:
            out["minimumReserveBreached"] = float(remaining) <= float(policy["minimumReserve"])
            out["warningThresholdBreached"] = float(remaining) <= float(policy["warningThresholdRemaining"])
            out["pauseThresholdBreached"] = float(remaining) <= float(policy["pauseThresholdRemaining"])
        if weekly_usage is not None:
            out["weeklySoftBudgetExceeded"] = float(weekly_usage) >= float(policy["weeklySoftBudget"])
            out["weeklyHardBudgetExceeded"] = float(weekly_usage) >= float(policy["weeklyHardBudget"])

        return out
    except Exception:
        return out
    finally:
        con.close()


def evaluate_optional_provider_request(
    *,
    estimated_credits: Optional[float],
    allow_unknown_credit_cost: bool = False,
    allow_unknown_weekly_usage: bool = False,
    override_quota_guards: bool = False,
) -> Dict[str, Any]:
    quota = get_quota_safety_state()
    warnings: list[str] = []
    estimated = None if estimated_credits is None else float(estimated_credits)
    verification_status = str(quota.get("coreOddsCostVerificationStatus") or "UNKNOWN").upper()

    if estimated is not None and estimated <= 0:
        return {
            "allowed": True,
            "reason": None,
            "warnings": warnings,
            "quotaSafety": quota,
        }

    if bool(quota.get("warningThresholdBreached")):
        warnings.append("WARNING_THRESHOLD_REMAINING_BREACHED")

    if not override_quota_guards:
        if estimated is None and verification_status in {"UNKNOWN", "SHAPE_CHANGED"} and not allow_unknown_credit_cost:
            return {
                "allowed": False,
                "reason": "UNKNOWN_PROVIDER_CREDIT_COST",
                "warnings": warnings,
                "quotaSafety": quota,
            }

        if estimated is None and not allow_unknown_credit_cost:
            return {
                "allowed": False,
                "reason": "UNKNOWN_PROVIDER_CREDIT_COST",
                "warnings": warnings,
                "quotaSafety": quota,
            }

        if bool(quota.get("pauseThresholdBreached")):
            return {
                "allowed": False,
                "reason": "QUOTA_PAUSE_THRESHOLD_REMAINING",
                "warnings": warnings,
                "quotaSafety": quota,
            }

        if bool(quota.get("minimumReserveBreached")):
            return {
                "allowed": False,
                "reason": "QUOTA_MINIMUM_RESERVE_BREACHED",
                "warnings": warnings,
                "quotaSafety": quota,
            }

        weekly_usage = quota.get("weeklyUsageCredits")
        if weekly_usage is None and not allow_unknown_weekly_usage:
            return {
                "allowed": False,
                "reason": "WEEKLY_USAGE_UNKNOWN",
                "warnings": warnings,
                "quotaSafety": quota,
            }

        if weekly_usage is not None and estimated is not None:
            projected = float(weekly_usage) + estimated
            if projected > float(quota["weeklyHardBudget"]):
                return {
                    "allowed": False,
                    "reason": "WEEKLY_HARD_BUDGET_EXCEEDED",
                    "warnings": warnings,
                    "quotaSafety": quota,
                }
            if projected > float(quota["weeklySoftBudget"]):
                warnings.append("WEEKLY_SOFT_BUDGET_EXCEEDED")

    return {
        "allowed": True,
        "reason": None,
        "warnings": warnings,
        "quotaSafety": quota,
    }


def perform_core_cost_bootstrap(*, requested_shape_id: str) -> Dict[str, Any]:
    active_shape_id = core_request_shape_id()
    signature = build_core_request_signature()
    bootstrap_cap = _bootstrap_cost_cap()
    if str(requested_shape_id or "").strip() != active_shape_id:
        return {
            "triggered": False,
            "reason": "BOOTSTRAP_SHAPE_MISMATCH",
            "coreOddsRequestShapeId": active_shape_id,
            "coreOddsVerifiedRequestCost": None,
            "coreOddsCostVerificationStatus": "SHAPE_CHANGED",
            **get_core_cost_bootstrap_status(),
        }

    with _CORE_BOOTSTRAP_LOCK:
        verification = get_core_request_cost_verification()
        bootstrap = get_core_cost_bootstrap_status()
        if str(verification.get("coreOddsCostVerificationStatus") or "").upper() == "VERIFIED":
            return {
                "triggered": False,
                "reason": "BOOTSTRAP_NOT_REQUIRED",
                **verification,
                **bootstrap,
            }

        status = str(bootstrap.get("coreOddsCostBootstrapStatus") or "AVAILABLE").upper()
        if status == "COMPLETED":
            return {
                "triggered": False,
                "reason": "BOOTSTRAP_ALREADY_COMPLETED",
                **verification,
                **bootstrap,
            }
        if status == "REVIEW_REQUIRED":
            return {
                "triggered": False,
                "reason": "BOOTSTRAP_REVIEW_REQUIRED",
                **verification,
                **bootstrap,
            }
        if status == "IN_PROGRESS":
            return {
                "triggered": False,
                "reason": "BOOTSTRAP_ALREADY_IN_PROGRESS",
                **verification,
                **bootstrap,
            }

        guard = evaluate_optional_provider_request(
            estimated_credits=bootstrap_cap,
            allow_unknown_credit_cost=True,
            allow_unknown_weekly_usage=False,
            override_quota_guards=False,
        )
        if not bool(guard.get("allowed")):
            return {
                "triggered": False,
                "reason": guard.get("reason"),
                "warnings": guard.get("warnings") or [],
                "quotaSafety": guard.get("quotaSafety"),
                **verification,
                **bootstrap,
            }

        con = _connect_duckdb(read_only=False)
        if con is None:
            return {
                "triggered": False,
                "reason": "BOOTSTRAP_STATE_UNAVAILABLE",
                "warnings": guard.get("warnings") or [],
                "quotaSafety": guard.get("quotaSafety"),
                **verification,
                **bootstrap,
            }

        attempt_at = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            _ensure_bootstrap_schema(con)
            existing = _bootstrap_row_for_shape(con, active_shape_id)
            if existing is None:
                con.execute(
                    """
                    INSERT INTO core_odds_cost_bootstrap (
                        request_shape_id, request_shape_signature, status, requested_at,
                        completed_at, actual_credits, requests_used, requests_remaining,
                        failure_reason, request_provenance
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [active_shape_id, json.dumps(signature, sort_keys=True, separators=(",", ":")), "IN_PROGRESS", attempt_at, None, None, None, None, None, _CORE_BOOTSTRAP_PROVENANCE],
                )
            else:
                con.execute(
                    """
                    UPDATE core_odds_cost_bootstrap
                    SET request_shape_signature = ?, status = 'IN_PROGRESS', requested_at = ?,
                        completed_at = NULL, actual_credits = NULL, requests_used = NULL,
                        requests_remaining = NULL, failure_reason = NULL, request_provenance = ?
                    WHERE request_shape_id = ?
                    """,
                    [json.dumps(signature, sort_keys=True, separators=(",", ":")), attempt_at, _CORE_BOOTSTRAP_PROVENANCE, active_shape_id],
                )
            con.close()
        except Exception:
            con.close()
            return {
                "triggered": False,
                "reason": "BOOTSTRAP_STATE_PERSIST_FAILED",
                "warnings": guard.get("warnings") or [],
                "quotaSafety": guard.get("quotaSafety"),
                **verification,
                **bootstrap,
            }

        from app.services.refresh_orchestrator import trigger_now

        refresh_out = trigger_now(request_provenance=_CORE_BOOTSTRAP_PROVENANCE)
        con = _connect_duckdb(read_only=False)
        if con is None:
            return {
                "triggered": bool(refresh_out.get("triggered")),
                "success": bool(refresh_out.get("success")),
                "reason": "BOOTSTRAP_STATE_UNAVAILABLE",
                **refresh_out,
            }

        try:
            _ensure_bootstrap_schema(con)
            usage_row = None
            try:
                usage_row = con.execute(
                    """
                    SELECT fetched_at, requests_last, requests_used, requests_remaining
                    FROM odds_api_usage
                    WHERE endpoint = '/sports/{sport}/odds'
                      AND request_shape_id = ?
                      AND request_provenance = ?
                      AND fetched_at >= ?
                    ORDER BY fetched_at DESC
                    LIMIT 1
                    """,
                    [active_shape_id, _CORE_BOOTSTRAP_PROVENANCE, attempt_at],
                ).fetchone()
            except Exception:
                usage_row = None

            if not bool(refresh_out.get("triggered")) or not bool(refresh_out.get("success")):
                con.execute(
                    """
                    UPDATE core_odds_cost_bootstrap
                    SET status = 'FAILED', completed_at = ?, failure_reason = ?
                    WHERE request_shape_id = ?
                    """,
                    [datetime.now(timezone.utc).replace(tzinfo=None), str(refresh_out.get("reason") or refresh_out.get("lastError") or "BOOTSTRAP_REFRESH_FAILED")[:500], active_shape_id],
                )
            elif usage_row is None:
                con.execute(
                    """
                    UPDATE core_odds_cost_bootstrap
                    SET status = 'FAILED', completed_at = ?, failure_reason = ?
                    WHERE request_shape_id = ?
                    """,
                    [datetime.now(timezone.utc).replace(tzinfo=None), 'BOOTSTRAP_USAGE_TELEMETRY_MISSING', active_shape_id],
                )
            elif usage_row[1] is None:
                con.execute(
                    """
                    UPDATE core_odds_cost_bootstrap
                    SET status = 'FAILED', completed_at = ?, requests_used = ?, requests_remaining = ?, failure_reason = ?
                    WHERE request_shape_id = ?
                    """,
                    [datetime.now(timezone.utc).replace(tzinfo=None), usage_row[2], usage_row[3], 'BOOTSTRAP_REQUEST_COST_MISSING', active_shape_id],
                )
            else:
                actual_credits = float(usage_row[1])
                status_out = 'COMPLETED' if actual_credits <= bootstrap_cap else 'REVIEW_REQUIRED'
                failure_reason = None if status_out == 'COMPLETED' else 'BOOTSTRAP_COST_ABOVE_CAP'
                con.execute(
                    """
                    UPDATE core_odds_cost_bootstrap
                    SET status = ?, completed_at = ?, actual_credits = ?, requests_used = ?, requests_remaining = ?, failure_reason = ?
                    WHERE request_shape_id = ?
                    """,
                    [status_out, usage_row[0], actual_credits, usage_row[2], usage_row[3], failure_reason, active_shape_id],
                )
        finally:
            con.close()

        return {
            **refresh_out,
            **get_core_request_cost_verification(),
            **get_core_cost_bootstrap_status(),
            "quotaSafety": guard.get("quotaSafety"),
            "warnings": guard.get("warnings") or [],
            "bootstrapMaxCredits": bootstrap_cap,
        }


def get_odds_status() -> Dict[str, Any]:
    """Read live odds metrics from DuckDB without exposing credentials."""
    con = _try_duckdb()
    if con is None:
        quota = get_quota_safety_state()
        return {
            "oddsProvider": "The Odds API",
            "oddsDataStatus": "UNAVAILABLE",
            "lastLiveOddsRefresh": None,
            "gamesUpdated": 0,
            "snapshotCount": 0,
            "apiUsageRemaining": None,
            "coreOddsLastRequestCredits": quota.get("coreOddsLastRequestCredits"),
            "coreOddsRequestsUsed": quota.get("coreOddsRequestsUsed"),
            "coreOddsRequestsRemaining": quota.get("coreOddsRequestsRemaining"),
            "coreOddsLastRequestAt": quota.get("coreOddsLastRequestAt"),
            "coreOddsRequestShapeId": quota.get("coreOddsRequestShapeId"),
            "coreOddsVerifiedRequestCost": quota.get("coreOddsVerifiedRequestCost"),
            "coreOddsCostVerificationStatus": quota.get("coreOddsCostVerificationStatus"),
            "coreOddsCostBootstrapStatus": quota.get("coreOddsCostBootstrapStatus"),
            "coreOddsCostBootstrapAt": quota.get("coreOddsCostBootstrapAt"),
            "coreOddsCostBootstrapShapeId": quota.get("coreOddsCostBootstrapShapeId"),
            "coreOddsCostBootstrapActualCredits": quota.get("coreOddsCostBootstrapActualCredits"),
            "quotaSafety": quota,
        }

    try:
        has_snapshots = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'odds_snapshots'"
        ).fetchone()[0] > 0

        if not has_snapshots:
            quota = get_quota_safety_state()
            return {
                "oddsProvider": "The Odds API",
                "oddsDataStatus": "UNAVAILABLE",
                "lastLiveOddsRefresh": None,
                "gamesUpdated": 0,
                "snapshotCount": 0,
                "apiUsageRemaining": None,
                "coreOddsLastRequestCredits": quota.get("coreOddsLastRequestCredits"),
                "coreOddsRequestsUsed": quota.get("coreOddsRequestsUsed"),
                "coreOddsRequestsRemaining": quota.get("coreOddsRequestsRemaining"),
                "coreOddsLastRequestAt": quota.get("coreOddsLastRequestAt"),
                "coreOddsRequestShapeId": quota.get("coreOddsRequestShapeId"),
                "coreOddsVerifiedRequestCost": quota.get("coreOddsVerifiedRequestCost"),
                "coreOddsCostVerificationStatus": quota.get("coreOddsCostVerificationStatus"),
                "coreOddsCostBootstrapStatus": quota.get("coreOddsCostBootstrapStatus"),
                "coreOddsCostBootstrapAt": quota.get("coreOddsCostBootstrapAt"),
                "coreOddsCostBootstrapShapeId": quota.get("coreOddsCostBootstrapShapeId"),
                "coreOddsCostBootstrapActualCredits": quota.get("coreOddsCostBootstrapActualCredits"),
                "quotaSafety": quota,
            }

        snapshot_count = con.execute("SELECT COUNT(*) FROM odds_snapshots").fetchone()[0]
        latest_row = con.execute("SELECT MAX(fetched_at) FROM odds_snapshots").fetchone()
        latest_ts = latest_row[0] if latest_row else None

        games_updated = 0
        if latest_ts is not None:
            games_updated = con.execute(
                "SELECT COUNT(DISTINCT api_event_id) FROM odds_snapshots WHERE fetched_at = ?",
                [latest_ts],
            ).fetchone()[0]

        api_remaining = None
        latest_requests_used = None
        latest_requests_last = None
        latest_requests_at = None
        has_usage = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'odds_api_usage'"
        ).fetchone()[0] > 0
        if has_usage:
            usage_row = con.execute(
                "SELECT fetched_at, requests_remaining, requests_used, requests_last FROM odds_api_usage ORDER BY fetched_at DESC LIMIT 1"
            ).fetchone()
            if usage_row:
                latest_requests_at = usage_row[0]
                api_remaining = usage_row[1]
                latest_requests_used = usage_row[2]
                latest_requests_last = usage_row[3]

        # Determine staleness
        if latest_ts is None:
            data_status = "UNAVAILABLE"
        else:
            ts_utc = latest_ts.replace(tzinfo=timezone.utc) if latest_ts.tzinfo is None else latest_ts
            age = datetime.now(timezone.utc) - ts_utc
            data_status = "LIVE" if age < timedelta(hours=_STALE_HOURS) else "STALE"

        quota = get_quota_safety_state()
        return {
            "oddsProvider": "The Odds API",
            "oddsDataStatus": data_status,
            "lastLiveOddsRefresh": latest_ts.isoformat() if latest_ts else None,
            "gamesUpdated": int(games_updated),
            "snapshotCount": int(snapshot_count),
            "apiUsageRemaining": int(api_remaining) if api_remaining is not None else None,
            "coreOddsLastRequestCredits": float(latest_requests_last) if latest_requests_last is not None else None,
            "coreOddsRequestsUsed": int(latest_requests_used) if latest_requests_used is not None else None,
            "coreOddsRequestsRemaining": int(api_remaining) if api_remaining is not None else None,
            "coreOddsLastRequestAt": latest_requests_at.isoformat() if latest_requests_at else None,
            "coreOddsRequestShapeId": quota.get("coreOddsRequestShapeId"),
            "coreOddsVerifiedRequestCost": quota.get("coreOddsVerifiedRequestCost"),
            "coreOddsCostVerificationStatus": quota.get("coreOddsCostVerificationStatus"),
            "coreOddsCostBootstrapStatus": quota.get("coreOddsCostBootstrapStatus"),
            "coreOddsCostBootstrapAt": quota.get("coreOddsCostBootstrapAt"),
            "coreOddsCostBootstrapShapeId": quota.get("coreOddsCostBootstrapShapeId"),
            "coreOddsCostBootstrapActualCredits": quota.get("coreOddsCostBootstrapActualCredits"),
            "quotaSafety": quota,
        }
    except Exception:
        quota = get_quota_safety_state()
        return {
            "oddsProvider": "The Odds API",
            "oddsDataStatus": "ERROR",
            "lastLiveOddsRefresh": None,
            "gamesUpdated": 0,
            "snapshotCount": 0,
            "apiUsageRemaining": None,
            "coreOddsLastRequestCredits": quota.get("coreOddsLastRequestCredits"),
            "coreOddsRequestsUsed": quota.get("coreOddsRequestsUsed"),
            "coreOddsRequestsRemaining": quota.get("coreOddsRequestsRemaining"),
            "coreOddsLastRequestAt": quota.get("coreOddsLastRequestAt"),
            "coreOddsRequestShapeId": quota.get("coreOddsRequestShapeId"),
            "coreOddsVerifiedRequestCost": quota.get("coreOddsVerifiedRequestCost"),
            "coreOddsCostVerificationStatus": quota.get("coreOddsCostVerificationStatus"),
            "coreOddsCostBootstrapStatus": quota.get("coreOddsCostBootstrapStatus"),
            "coreOddsCostBootstrapAt": quota.get("coreOddsCostBootstrapAt"),
            "coreOddsCostBootstrapShapeId": quota.get("coreOddsCostBootstrapShapeId"),
            "coreOddsCostBootstrapActualCredits": quota.get("coreOddsCostBootstrapActualCredits"),
            "quotaSafety": quota,
        }
    finally:
        con.close()
