from __future__ import annotations

import logging
import os
import json
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import requests

from app.runtime_paths import runtime_paths


log = logging.getLogger("runtime_jobs.odds_refresh")

BASE = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _shape_id(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _normalize_csv_values(values: list[str], *, lower: bool = True) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = str(raw or "").strip()
        if not item:
            continue
        item = item.lower() if lower else item
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return sorted(out)


def build_core_request_signature() -> dict[str, Any]:
    region = str(os.getenv("ODDS_REGION", "us") or "us").strip().lower() or "us"
    markets = _normalize_csv_values(_csv_env("ODDS_MARKETS", "h2h,spreads,totals"))
    bookmakers = _normalize_csv_values(_csv_env("ODDS_BOOKMAKERS", ""))
    odds_format = str(os.getenv("ODDS_FORMAT", "american") or "american").strip().lower() or "american"

    return {
        "endpointType": "SPORT_ODDS",
        "endpoint": "/sports/{sport}/odds",
        "sport": SPORT,
        "regions": [region],
        "markets": markets,
        "bookmakers": bookmakers,
        "oddsFormat": odds_format,
        "dateFormat": "iso",
    }


def core_request_shape_id() -> str:
    return _shape_id(build_core_request_signature())


def _parse_iso_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _team_code(name: Any) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    return TEAM_MAP.get(raw, raw.upper())


def _load_regular_season_event_keys() -> set[tuple[str, str, str]]:
    schedule_path: Path = runtime_paths.schedule_context_latest_csv.resolve()
    if not schedule_path.exists():
        return set()

    try:
        df = pd.read_csv(schedule_path)
    except Exception:
        return set()

    required_cols = {"season", "week", "gameday", "away_team", "home_team"}
    if df.empty or not required_cols.issubset(set(df.columns)):
        return set()

    out: set[tuple[str, str, str]] = set()
    for _, row in df.iterrows():
        try:
            week = int(row.get("week"))
        except (TypeError, ValueError):
            continue
        if week < 1 or week > 18:
            continue

        game_day = str(row.get("gameday") or "").strip()
        away = str(row.get("away_team") or "").strip().upper()
        home = str(row.get("home_team") or "").strip().upper()
        if not game_day or not away or not home:
            continue
        out.add((game_day, away, home))
    return out


def _event_in_scope(
    event: dict[str, Any],
    *,
    now_utc: datetime,
    regular_keys: set[tuple[str, str, str]],
    max_days_ahead: int,
    max_hours_past: int,
) -> bool:
    kickoff = _parse_iso_utc(event.get("commence_time"))
    if kickoff is None:
        return False

    if kickoff < now_utc - timedelta(hours=max_hours_past):
        return False
    if kickoff > now_utc + timedelta(days=max_days_ahead):
        return False

    if not regular_keys:
        return True

    game_day = kickoff.date().isoformat()
    away = _team_code(event.get("away_team"))
    home = _team_code(event.get("home_team"))
    return (game_day, away, home) in regular_keys

TEAM_MAP = {
    "Arizona Cardinals": "ARI",
    "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR",
    "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN",
    "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN",
    "Detroit Lions": "DET",
    "Green Bay Packers": "GB",
    "Houston Texans": "HOU",
    "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV",
    "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR",
    "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN",
    "New England Patriots": "NE",
    "New Orleans Saints": "NO",
    "New York Giants": "NYG",
    "New York Jets": "NYJ",
    "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA",
    "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN",
    "Washington Commanders": "WAS",
}


def _csv_env(name: str, default: str) -> list[str]:
    raw = str(os.getenv(name, default) or "").strip()
    return [item.strip() for item in raw.split(",") if item.strip()]


def _american_to_implied(odds: Any) -> float | None:
    if odds is None:
        return None
    value = float(odds)
    if value < 0:
        return (-value) / ((-value) + 100.0)
    return 100.0 / (value + 100.0)


def _ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
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
    existing = {
        str(row[0]).lower()
        for row in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'odds_api_usage'"
        ).fetchall()
    }
    if "request_shape_id" not in existing:
        con.execute("ALTER TABLE odds_api_usage ADD COLUMN request_shape_id VARCHAR")
    if "request_shape_signature" not in existing:
        con.execute("ALTER TABLE odds_api_usage ADD COLUMN request_shape_signature VARCHAR")
    if "request_provenance" not in existing:
        con.execute("ALTER TABLE odds_api_usage ADD COLUMN request_provenance VARCHAR")


def _store_usage(
    con: duckdb.DuckDBPyConnection,
    resp: requests.Response,
    endpoint: str,
    *,
    signature: dict[str, Any] | None = None,
    provenance: str | None = None,
    fetched_at: datetime | None = None,
) -> None:
    signature = signature or build_core_request_signature()
    provenance = str(provenance or os.getenv("ODDS_REQUEST_PROVENANCE", "STANDARD_CORE_REFRESH") or "STANDARD_CORE_REFRESH").strip().upper()
    fetched_at = fetched_at or datetime.now(timezone.utc).replace(tzinfo=None)
    def as_int(header_name: str) -> int | None:
        raw = resp.headers.get(header_name)
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    con.execute(
        "INSERT INTO odds_api_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            fetched_at,
            endpoint,
            as_int("x-requests-remaining"),
            as_int("x-requests-used"),
            as_int("x-requests-last"),
            _shape_id(signature),
            _canonical_json(signature),
            provenance,
        ],
    )


def _core_request_params(signature: dict[str, Any], *, api_key: str) -> dict[str, str]:
    region = str((signature.get("regions") or ["us"])[0] or "us")
    markets = [str(item) for item in (signature.get("markets") or [])]
    bookmakers = [str(item) for item in (signature.get("bookmakers") or [])]

    params: dict[str, str] = {
        "apiKey": api_key,
        "regions": region,
        "markets": ",".join(markets),
        "oddsFormat": str(signature.get("oddsFormat") or "american"),
        "dateFormat": str(signature.get("dateFormat") or "iso"),
    }
    if bookmakers:
        params["bookmakers"] = ",".join(bookmakers)
    return params


def _execute_core_request(signature: dict[str, Any], *, api_key: str) -> requests.Response:
    params = _core_request_params(signature, api_key=api_key)
    url = f"{BASE}/sports/{SPORT}/odds"
    resp = requests.get(url, params=params, timeout=45)
    if resp.status_code != 200:
        detail: Any
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text[:500]
        raise RuntimeError(f"ODDS_API_HTTP_{resp.status_code}: {detail}")
    return resp


def run_core_request_usage_only(*, request_provenance: str = "BOOTSTRAP_CORE_COST") -> dict[str, Any]:
    api_key = str(os.getenv("ODDS_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("ODDS_API_KEY_MISSING")

    signature = build_core_request_signature()
    resp = _execute_core_request(signature, api_key=api_key)

    db_path = runtime_paths.nfl_model_duckdb.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        _ensure_schema(con)
        _store_usage(
            con,
            resp,
            "/sports/{sport}/odds",
            signature=signature,
            provenance=request_provenance,
            fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        con.commit()
    finally:
        con.close()

    return {
        "requestsRemaining": resp.headers.get("x-requests-remaining"),
        "requestsUsed": resp.headers.get("x-requests-used"),
        "requestsLast": resp.headers.get("x-requests-last"),
        "requestShapeId": _shape_id(signature),
        "requestProvenance": str(request_provenance or "BOOTSTRAP_CORE_COST").strip().upper(),
    }


def run_refresh() -> dict[str, Any]:
    api_key = str(os.getenv("ODDS_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("ODDS_API_KEY_MISSING")

    signature = build_core_request_signature()
    resp = _execute_core_request(signature, api_key=api_key)

    payload = resp.json()
    now_utc = datetime.now(timezone.utc)
    regular_keys = _load_regular_season_event_keys()
    max_days_ahead = int(str(os.getenv("ODDS_REFRESH_MAX_DAYS_AHEAD", "14") or "14"))
    max_hours_past = int(str(os.getenv("ODDS_REFRESH_MAX_HOURS_PAST", "12") or "12"))

    scoped_payload = [
        event
        for event in payload
        if isinstance(event, dict)
        and _event_in_scope(
            event,
            now_utc=now_utc,
            regular_keys=regular_keys,
            max_days_ahead=max_days_ahead,
            max_hours_past=max_hours_past,
        )
    ]

    db_path = runtime_paths.nfl_model_duckdb.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path))
    try:
        _ensure_schema(con)
        _store_usage(
            con,
            resp,
            "/sports/{sport}/odds",
            signature=signature,
            fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )

        fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
        rows: list[list[Any]] = []
        games_seen: set[str] = set()

        for event in scoped_payload:
            event_id = event.get("id")
            home = event.get("home_team")
            away = event.get("away_team")
            if event_id:
                games_seen.add(str(event_id))

            for book in event.get("bookmakers", []) or []:
                for market in book.get("markets", []) or []:
                    market_key = market.get("key")
                    for outcome in market.get("outcomes", []) or []:
                        name = outcome.get("name")
                        if market_key == "h2h":
                            outcome_code = "home" if name == home else ("away" if name == away else name)
                        elif market_key in {"spreads", "totals"}:
                            outcome_code = (
                                "over"
                                if name == "Over"
                                else (
                                    "under"
                                    if name == "Under"
                                    else ("home" if name == home else ("away" if name == away else name))
                                )
                            )
                        else:
                            outcome_code = name

                        price = outcome.get("price")
                        rows.append(
                            [
                                fetched_at,
                                event_id,
                                event.get("commence_time"),
                                home,
                                away,
                                TEAM_MAP.get(str(home)),
                                TEAM_MAP.get(str(away)),
                                book.get("key"),
                                book.get("title"),
                                market_key,
                                name,
                                outcome_code,
                                outcome.get("point"),
                                price,
                                _american_to_implied(price),
                                "current",
                                "the_odds_api",
                            ]
                        )

        if rows:
            con.executemany(
                "INSERT INTO odds_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
        con.commit()

    finally:
        con.close()

    remaining = resp.headers.get("x-requests-remaining")
    used = resp.headers.get("x-requests-used")
    log.info(
        "Runtime odds refresh wrote outcomes=%d games=%d remaining=%s used=%s scoped_events=%d total_events=%d",
        len(rows),
        len(games_seen),
        remaining,
        used,
        len(scoped_payload),
        len(payload) if isinstance(payload, list) else 0,
    )
    return {
        "rows": len(rows),
        "games": len(games_seen),
        "requestsRemaining": remaining,
        "requestsUsed": used,
        "scopedEvents": len(scoped_payload),
        "totalEvents": len(payload) if isinstance(payload, list) else 0,
    }


def main() -> None:
    out = run_refresh()
    print(
        f"refresh_rows={out['rows']} games={out['games']} "
        f"requests_remaining={out['requestsRemaining']} requests_used={out['requestsUsed']}"
    )


if __name__ == "__main__":
    main()