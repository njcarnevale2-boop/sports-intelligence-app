"""
Injury snapshot storage and change detection.

Each fetch is persisted to DuckDB so the system can:
  - detect status changes (upgraded / downgraded / ruled out / returned)
  - serve cached data when the live provider is unavailable
  - feed the Decision Timeline

DuckDB table: injury_snapshots
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.runtime_paths import runtime_paths

log = logging.getLogger("injury_history")

_DB_PATH = runtime_paths.nfl_model_duckdb

_SCHEMA = """
CREATE TABLE IF NOT EXISTS injury_snapshots (
    fetched_at      TIMESTAMP NOT NULL,
    player          VARCHAR   NOT NULL,
    team            VARCHAR   NOT NULL,
    position        VARCHAR,
    position_group  VARCHAR,
    status          VARCHAR,
    practice_status VARCHAR,
    starter         BOOLEAN,
    impact          DOUBLE,
    notes           TEXT,
    provider        VARCHAR,
    last_updated    VARCHAR
);

CREATE TABLE IF NOT EXISTS injury_status_changes (
    detected_at     TIMESTAMP NOT NULL,
    player          VARCHAR   NOT NULL,
    team            VARCHAR   NOT NULL,
    position        VARCHAR,
    previous_status VARCHAR,
    new_status      VARCHAR,
    change_type     VARCHAR,
    provider        VARCHAR
);
"""

# Change type labels
_CHANGE_RULED_OUT  = "ruled_out"
_CHANGE_DOWNGRADE  = "status_downgraded"
_CHANGE_UPGRADE    = "status_upgraded"
_CHANGE_RETURNED   = "returned_active"
_CHANGE_ADDED      = "added_to_report"
_CHANGE_STARTER    = "starter_status_changed"

_STATUS_SEVERITY = {
    "Active": 0,
    "Probable": 1,
    "Full": 1,
    "Limited": 2,
    "Questionable": 3,
    "Doubtful": 4,
    "DNP": 4,
    "Out": 5,
    "IR": 6,
}


def _open_db(read_only: bool = False):
    import duckdb  # type: ignore
    return duckdb.connect(str(_DB_PATH), read_only=read_only)


def _ensure_schema() -> None:
    if not _DB_PATH.exists():
        return
    try:
        con = _open_db()
        for stmt in _SCHEMA.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                con.execute(stmt)
        con.close()
    except Exception as exc:
        log.warning("Could not ensure injury schema: %s", exc)


def store_snapshot(injuries: List[Dict[str, Any]], provider: str) -> int:
    """Persist a batch of injury records. Returns count written."""
    _ensure_schema()
    if not _DB_PATH.exists() or not injuries:
        return 0

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    for inj in injuries:
        rows.append([
            now_naive,
            inj.get("player", "Unknown"),
            inj.get("team", "UNK"),
            inj.get("position"),
            inj.get("positionGroup"),
            inj.get("status"),
            inj.get("practiceStatus"),
            bool(inj.get("starter", False)),
            inj.get("impact"),
            inj.get("notes"),
            provider,
            inj.get("lastUpdated"),
        ])

    try:
        con = _open_db()
        con.executemany(
            "INSERT INTO injury_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )
        con.close()
        return len(rows)
    except Exception as exc:
        log.warning("Could not store injury snapshot: %s", exc)
        return 0


def detect_changes(new_injuries: List[Dict[str, Any]], provider: str) -> List[Dict[str, Any]]:
    """
    Compare new_injuries against the previous snapshot.
    Returns a list of detected change events.
    """
    _ensure_schema()
    if not _DB_PATH.exists():
        return []

    try:
        con = _open_db(read_only=True)
        prev_rows = con.execute("""
            SELECT player, team, status, starter
            FROM injury_snapshots
            WHERE fetched_at = (SELECT MAX(fetched_at) FROM injury_snapshots)
        """).fetchall()
        con.close()
    except Exception:
        return []

    prev: Dict[str, Dict[str, Any]] = {}
    for row in prev_rows:
        key = f"{row[0]}::{row[1]}"
        prev[key] = {"status": row[2], "starter": row[3]}

    new_lookup: Dict[str, Dict[str, Any]] = {}
    for inj in new_injuries:
        key = f"{inj.get('player', '')}::{inj.get('team', '')}"
        new_lookup[key] = inj

    changes: List[Dict[str, Any]] = []
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)

    for key, inj in new_lookup.items():
        player = inj.get("player", "")
        team   = inj.get("team", "")
        pos    = inj.get("position", "")
        new_status = inj.get("status", "")
        new_starter = bool(inj.get("starter", False))

        if key not in prev:
            changes.append({
                "detected_at": now_naive,
                "player": player, "team": team, "position": pos,
                "previous_status": None, "new_status": new_status,
                "change_type": _CHANGE_ADDED, "provider": provider,
            })
            continue

        old_status  = prev[key]["status"] or ""
        old_starter = bool(prev[key]["starter"])

        if old_status != new_status:
            old_sev = _STATUS_SEVERITY.get(old_status, 3)
            new_sev = _STATUS_SEVERITY.get(new_status, 3)
            if new_status in ("Out", "IR"):
                change_type = _CHANGE_RULED_OUT
            elif new_status in ("Active", "Full", "Probable") and old_sev > 1:
                change_type = _CHANGE_RETURNED
            elif new_sev > old_sev:
                change_type = _CHANGE_DOWNGRADE
            else:
                change_type = _CHANGE_UPGRADE
            changes.append({
                "detected_at": now_naive,
                "player": player, "team": team, "position": pos,
                "previous_status": old_status, "new_status": new_status,
                "change_type": change_type, "provider": provider,
            })

        if old_starter != new_starter:
            changes.append({
                "detected_at": now_naive,
                "player": player, "team": team, "position": pos,
                "previous_status": old_status, "new_status": new_status,
                "change_type": _CHANGE_STARTER, "provider": provider,
            })

    return changes


def store_changes(changes: List[Dict[str, Any]]) -> None:
    if not changes or not _DB_PATH.exists():
        return
    try:
        con = _open_db()
        con.executemany(
            "INSERT INTO injury_status_changes VALUES (?,?,?,?,?,?,?,?)",
            [[
                c["detected_at"], c["player"], c["team"], c.get("position"),
                c.get("previous_status"), c["new_status"], c["change_type"], c["provider"],
            ] for c in changes],
        )
        con.close()
    except Exception as exc:
        log.warning("Could not store injury changes: %s", exc)


def get_cached_injuries() -> Optional[Dict[str, Any]]:
    """Return the most recent injury snapshot from DuckDB, or None."""
    _ensure_schema()
    if not _DB_PATH.exists():
        return None
    try:
        con = _open_db(read_only=True)
        rows = con.execute("""
            SELECT player, team, position, position_group, status,
                   practice_status, starter, impact, notes, provider, last_updated
            FROM injury_snapshots
            WHERE fetched_at = (SELECT MAX(fetched_at) FROM injury_snapshots)
        """).fetchall()
        if not rows:
            con.close()
            return None
        last_fetch = con.execute(
            "SELECT MAX(fetched_at), provider FROM injury_snapshots GROUP BY provider ORDER BY 1 DESC LIMIT 1"
        ).fetchone()
        con.close()
    except Exception:
        return None

    injuries = []
    for row in rows:
        injuries.append({
            "player": row[0], "team": row[1], "position": row[2],
            "positionGroup": row[3], "status": row[4],
            "practiceStatus": row[5], "starter": bool(row[6]),
            "impact": row[7], "notes": row[8], "lastUpdated": row[10],
        })

    provider = last_fetch[1] if last_fetch else "cached"
    cached_at = last_fetch[0].isoformat() if last_fetch and last_fetch[0] else None

    return {
        "injuries": injuries,
        "provider": provider,
        "isLive": False,
        "dataStatus": "CACHED",
        "lastUpdated": cached_at,
        "cachedCount": len(injuries),
    }


def get_injury_summary() -> Dict[str, Any]:
    """For the admin dashboard."""
    _ensure_schema()
    empty = {
        "playersTracked": 0,
        "teamsUpdated": 0,
        "lastInjuryRefresh": None,
        "lastInjuryError": None,
        "recentChanges": 0,
    }
    if not _DB_PATH.exists():
        return empty
    try:
        con = _open_db(read_only=True)
        players = con.execute(
            "SELECT COUNT(DISTINCT player) FROM injury_snapshots WHERE fetched_at=(SELECT MAX(fetched_at) FROM injury_snapshots)"
        ).fetchone()[0]
        teams = con.execute(
            "SELECT COUNT(DISTINCT team) FROM injury_snapshots WHERE fetched_at=(SELECT MAX(fetched_at) FROM injury_snapshots)"
        ).fetchone()[0]
        last_ts = con.execute("SELECT MAX(fetched_at) FROM injury_snapshots").fetchone()[0]
        changes = con.execute("SELECT COUNT(*) FROM injury_status_changes").fetchone()[0]
        con.close()
        return {
            "playersTracked": int(players or 0),
            "teamsUpdated": int(teams or 0),
            "lastInjuryRefresh": last_ts.isoformat() if last_ts else None,
            "lastInjuryError": None,
            "recentChanges": int(changes or 0),
        }
    except Exception:
        return empty
