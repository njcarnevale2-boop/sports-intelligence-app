from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import duckdb
import requests

from app.runtime_paths import runtime_paths


log = logging.getLogger("runtime_jobs.odds_refresh")

BASE = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"

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
            requests_last INTEGER
        )
        """
    )


def _store_usage(con: duckdb.DuckDBPyConnection, resp: requests.Response, endpoint: str) -> None:
    def as_int(header_name: str) -> int | None:
        raw = resp.headers.get(header_name)
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    con.execute(
        "INSERT INTO odds_api_usage VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?)",
        [
            endpoint,
            as_int("x-requests-remaining"),
            as_int("x-requests-used"),
            as_int("x-requests-last"),
        ],
    )


def run_refresh() -> dict[str, Any]:
    api_key = str(os.getenv("ODDS_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("ODDS_API_KEY_MISSING")

    region = str(os.getenv("ODDS_REGION", "us") or "us").strip() or "us"
    markets = _csv_env("ODDS_MARKETS", "h2h,spreads,totals")
    bookmakers = _csv_env("ODDS_BOOKMAKERS", "")

    params: dict[str, str] = {
        "apiKey": api_key,
        "regions": region,
        "markets": ",".join(markets),
        "oddsFormat": str(os.getenv("ODDS_FORMAT", "american") or "american"),
        "dateFormat": "iso",
    }
    if bookmakers:
        params["bookmakers"] = ",".join(bookmakers)

    url = f"{BASE}/sports/{SPORT}/odds"
    resp = requests.get(url, params=params, timeout=45)
    if resp.status_code != 200:
        detail: Any
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text[:500]
        raise RuntimeError(f"ODDS_API_HTTP_{resp.status_code}: {detail}")

    payload = resp.json()
    db_path = runtime_paths.nfl_model_duckdb.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path))
    try:
        _ensure_schema(con)
        _store_usage(con, resp, "/sports/{sport}/odds")

        fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
        rows: list[list[Any]] = []
        games_seen: set[str] = set()

        for event in payload:
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

    finally:
        con.close()

    remaining = resp.headers.get("x-requests-remaining")
    used = resp.headers.get("x-requests-used")
    log.info(
        "Runtime odds refresh wrote outcomes=%d games=%d remaining=%s used=%s",
        len(rows),
        len(games_seen),
        remaining,
        used,
    )
    return {
        "rows": len(rows),
        "games": len(games_seen),
        "requestsRemaining": remaining,
        "requestsUsed": used,
    }


def main() -> None:
    out = run_refresh()
    print(
        f"refresh_rows={out['rows']} games={out['games']} "
        f"requests_remaining={out['requestsRemaining']} requests_used={out['requestsUsed']}"
    )


if __name__ == "__main__":
    main()