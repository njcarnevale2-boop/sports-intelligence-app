from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from app.runtime_paths import runtime_paths

DB_PATH = runtime_paths.nfl_model_duckdb

_STALE_HOURS = 24  # flag data as STALE if no refresh within this window


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


def get_quota_safety_state() -> Dict[str, Any]:
    policy = _quota_policy()
    out: Dict[str, Any] = {
        **policy,
        "weeklyUsageCredits": None,
        "weeklyUsageStatus": "UNKNOWN",
        "coreOddsLastRequestCredits": None,
        "coreOddsRequestsUsed": None,
        "coreOddsRequestsRemaining": None,
        "coreOddsLastRequestAt": None,
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
            "quotaSafety": quota,
        }
    finally:
        con.close()
