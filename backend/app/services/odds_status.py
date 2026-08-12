from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

DB_PATH = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9" / "database" / "nfl_model.duckdb"

_STALE_HOURS = 24  # flag data as STALE if no refresh within this window


def _try_duckdb() -> Optional[Any]:
    """Return a DuckDB connection or None if unavailable."""
    if not DB_PATH.exists():
        return None
    try:
        import duckdb  # type: ignore
        return duckdb.connect(str(DB_PATH), read_only=True)
    except Exception:
        return None


def get_odds_status() -> Dict[str, Any]:
    """Read live odds metrics from DuckDB without exposing credentials."""
    con = _try_duckdb()
    if con is None:
        return {
            "oddsProvider": "The Odds API",
            "oddsDataStatus": "UNAVAILABLE",
            "lastLiveOddsRefresh": None,
            "gamesUpdated": 0,
            "snapshotCount": 0,
            "apiUsageRemaining": None,
        }

    try:
        has_snapshots = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'odds_snapshots'"
        ).fetchone()[0] > 0

        if not has_snapshots:
            return {
                "oddsProvider": "The Odds API",
                "oddsDataStatus": "UNAVAILABLE",
                "lastLiveOddsRefresh": None,
                "gamesUpdated": 0,
                "snapshotCount": 0,
                "apiUsageRemaining": None,
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
        has_usage = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'odds_api_usage'"
        ).fetchone()[0] > 0
        if has_usage:
            usage_row = con.execute(
                "SELECT requests_remaining FROM odds_api_usage ORDER BY fetched_at DESC LIMIT 1"
            ).fetchone()
            if usage_row:
                api_remaining = usage_row[0]

        # Determine staleness
        if latest_ts is None:
            data_status = "UNAVAILABLE"
        else:
            ts_utc = latest_ts.replace(tzinfo=timezone.utc) if latest_ts.tzinfo is None else latest_ts
            age = datetime.now(timezone.utc) - ts_utc
            data_status = "LIVE" if age < timedelta(hours=_STALE_HOURS) else "STALE"

        return {
            "oddsProvider": "The Odds API",
            "oddsDataStatus": data_status,
            "lastLiveOddsRefresh": latest_ts.isoformat() if latest_ts else None,
            "gamesUpdated": int(games_updated),
            "snapshotCount": int(snapshot_count),
            "apiUsageRemaining": int(api_remaining) if api_remaining is not None else None,
        }
    except Exception:
        return {
            "oddsProvider": "The Odds API",
            "oddsDataStatus": "ERROR",
            "lastLiveOddsRefresh": None,
            "gamesUpdated": 0,
            "snapshotCount": 0,
            "apiUsageRemaining": None,
        }
    finally:
        con.close()
