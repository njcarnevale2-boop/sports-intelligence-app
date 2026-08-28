"""
Weather snapshot storage and change detection.

Each game-time fetch is persisted to DuckDB so the system can:
  - serve cached forecasts when the live provider is unavailable
  - detect significant forecast changes (wind increase, rain onset, etc.)
  - feed the Decision Timeline

DuckDB tables: weather_snapshots, weather_forecast_changes
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.runtime_paths import runtime_paths

log = logging.getLogger("weather_history")

_DB_PATH = runtime_paths.nfl_model_duckdb

_SCHEMA = """
CREATE TABLE IF NOT EXISTS weather_snapshots (
    fetched_at                TIMESTAMP NOT NULL,
    home_team                 VARCHAR,
    event_id                  VARCHAR,
    kickoff_time              TIMESTAMP,
    forecast_timestamp        VARCHAR,
    temperature               DOUBLE,
    wind_speed                DOUBLE,
    wind_gust                 DOUBLE,
    wind_direction            VARCHAR,
    precipitation_probability DOUBLE,
    precipitation_amount      DOUBLE,
    humidity                  DOUBLE,
    conditions                VARCHAR,
    stadium_type              VARCHAR,
    surface                   VARCHAR,
    provider                  VARCHAR,
    data_status               VARCHAR
);

CREATE TABLE IF NOT EXISTS weather_forecast_changes (
    detected_at               TIMESTAMP NOT NULL,
    home_team                 VARCHAR,
    event_id                  VARCHAR,
    change_type               VARCHAR,
    previous_value            DOUBLE,
    new_value                 DOUBLE,
    field_name                VARCHAR,
    provider                  VARCHAR
);
"""

# Thresholds for reporting a "significant" forecast change
_WIND_CHANGE_MPH       = 5.0
_TEMP_CHANGE_F         = 8.0
_PRECIP_PROB_CHANGE    = 15.0   # percentage points


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
        log.warning("Could not ensure weather schema: %s", exc)


def store_snapshot(weather: Dict[str, Any], home_team: str, event_id: str = "",
                   kickoff_time: Optional[datetime] = None) -> None:
    """Persist a weather snapshot row."""
    _ensure_schema()
    if not _DB_PATH.exists():
        return
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    kickoff_naive = kickoff_time.astimezone(timezone.utc).replace(tzinfo=None) if kickoff_time else None
    try:
        con = _open_db()
        con.execute(
            """INSERT INTO weather_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                now_naive, home_team, event_id or None, kickoff_naive,
                weather.get("forecastTimestamp"),
                weather.get("temperature"), weather.get("windSpeed"),
                weather.get("windGust"), weather.get("windDirection"),
                weather.get("precipitationProbability"), weather.get("precipitationAmount"),
                weather.get("humidity"), weather.get("conditions"),
                weather.get("stadiumType"), weather.get("surface"),
                weather.get("provider"), weather.get("dataStatus"),
            ],
        )
        con.close()
    except Exception as exc:
        log.warning("Could not store weather snapshot: %s", exc)


def detect_changes(new_weather: Dict[str, Any], home_team: str,
                   event_id: str = "") -> List[Dict[str, Any]]:
    """Compare to previous snapshot; return list of significant changes."""
    _ensure_schema()
    if not _DB_PATH.exists():
        return []
    try:
        con = _open_db(read_only=True)
        row = con.execute(
            """SELECT wind_speed, temperature, precipitation_probability
               FROM weather_snapshots
               WHERE home_team = ?
               ORDER BY fetched_at DESC LIMIT 1""",
            [home_team],
        ).fetchone()
        con.close()
    except Exception:
        return []
    if not row:
        return []

    prev_wind, prev_temp, prev_precip = row
    changes: List[Dict[str, Any]] = []
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)

    def _chk(field: str, prev, curr, threshold: float, change_type: str):
        if prev is None or curr is None:
            return
        delta = float(curr) - float(prev)
        if abs(delta) >= threshold:
            changes.append({
                "detected_at": now_naive, "home_team": home_team,
                "event_id": event_id, "change_type": change_type,
                "previous_value": float(prev), "new_value": float(curr),
                "field_name": field,
            })

    _chk("wind_speed", prev_wind, new_weather.get("windSpeed"), _WIND_CHANGE_MPH, "wind_change")
    _chk("temperature", prev_temp, new_weather.get("temperature"), _TEMP_CHANGE_F, "temperature_shift")
    _chk("precipitation_probability", prev_precip, new_weather.get("precipitationProbability"),
         _PRECIP_PROB_CHANGE, "precipitation_change")
    return changes


def store_changes(changes: List[Dict[str, Any]], provider: str) -> None:
    if not changes or not _DB_PATH.exists():
        return
    try:
        con = _open_db()
        con.executemany(
            "INSERT INTO weather_forecast_changes VALUES (?,?,?,?,?,?,?,?)",
            [[c["detected_at"], c["home_team"], c["event_id"], c["change_type"],
              c["previous_value"], c["new_value"], c["field_name"], provider]
             for c in changes],
        )
        con.close()
    except Exception as exc:
        log.warning("Could not store weather changes: %s", exc)


def get_cached_weather(home_team: str) -> Optional[Dict[str, Any]]:
    """Return the most recent weather snapshot for a team, or None."""
    _ensure_schema()
    if not _DB_PATH.exists():
        return None
    try:
        con = _open_db(read_only=True)
        row = con.execute(
            """SELECT temperature, wind_speed, wind_gust, wind_direction,
                      precipitation_probability, precipitation_amount, humidity,
                      conditions, forecast_timestamp, stadium_type, surface,
                      provider, fetched_at
               FROM weather_snapshots
               WHERE home_team = ?
               ORDER BY fetched_at DESC LIMIT 1""",
            [home_team],
        ).fetchone()
        con.close()
    except Exception:
        return None
    if not row:
        return None

    (temp, wind, gust, wdir, pp, pa, hum, cond, ft, st, surf, prov, cat) = row
    cached_at = cat.isoformat() if cat else None
    return {
        "temperature": temp, "windSpeed": wind, "windGust": gust,
        "windDirection": wdir, "precipitationProbability": pp,
        "precipitationAmount": pa, "humidity": hum, "conditions": cond,
        "forecastTimestamp": ft, "stadiumType": st, "surface": surf,
        "provider": prov, "isLive": False, "dataStatus": "CACHED",
        "lastUpdated": cached_at, "recordCount": 1,
    }


def get_weather_summary() -> Dict[str, Any]:
    """Aggregate stats for the admin dashboard."""
    _ensure_schema()
    empty = {
        "gamesUpdated": 0, "forecastsAvailable": 0,
        "lastWeatherRefresh": None, "lastWeatherError": None,
    }
    if not _DB_PATH.exists():
        return empty
    try:
        con = _open_db(read_only=True)
        games = con.execute(
            "SELECT COUNT(DISTINCT home_team) FROM weather_snapshots WHERE fetched_at=(SELECT MAX(fetched_at) FROM weather_snapshots)"
        ).fetchone()[0]
        total = con.execute(
            "SELECT COUNT(DISTINCT home_team) FROM weather_snapshots"
        ).fetchone()[0]
        last_ts = con.execute("SELECT MAX(fetched_at) FROM weather_snapshots").fetchone()[0]
        con.close()
        return {
            "gamesUpdated": int(games or 0),
            "forecastsAvailable": int(total or 0),
            "lastWeatherRefresh": last_ts.isoformat() if last_ts else None,
            "lastWeatherError": None,
        }
    except Exception:
        return empty
