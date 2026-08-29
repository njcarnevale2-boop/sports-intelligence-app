from __future__ import annotations

import os
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from app.runtime_paths import runtime_paths


_OUTPUT_COLUMNS = [
    "api_event_id",
    "commence_time",
    "home_team",
    "away_team",
    "sportsbook",
    "market",
    "side",
    "first_seen",
    "last_seen",
    "opening_point_observed",
    "latest_point",
    "point_move",
    "opening_price_observed",
    "latest_price",
    "price_move",
    "steam_flag",
    "snapshots",
]

_GROUP_KEYS = ["api_event_id", "bookmaker_key", "market_key", "outcome_code"]


def _table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    return (
        con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [table],
        ).fetchone()[0]
        > 0
    )


def _apply_duckdb_runtime_guardrails(con: duckdb.DuckDBPyConnection) -> None:
    threads_raw = str(os.getenv("LINE_MOVEMENT_DUCKDB_THREADS", "1") or "1").strip()
    try:
        threads = int(threads_raw)
    except (TypeError, ValueError):
        threads = 1
    if threads > 0:
        con.execute(f"SET threads = {threads}")

    memory_limit_raw = str(os.getenv("LINE_MOVEMENT_DUCKDB_MEMORY_LIMIT_MB", "") or "").strip()
    if not memory_limit_raw:
        return

    try:
        memory_limit_mb = int(float(memory_limit_raw))
    except (TypeError, ValueError):
        return
    if memory_limit_mb > 0:
        con.execute(f"SET memory_limit = '{memory_limit_mb}MB'")


def _legacy_query_full_history(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(
        """
        SELECT fetched_at, api_event_id, commence_time, home_code, away_code,
               bookmaker_key, bookmaker_title, market_key, outcome_code, point, price
        FROM odds_snapshots
        ORDER BY api_event_id, bookmaker_key, market_key, outcome_code, fetched_at
        """
    ).df()


def _build_board_via_pandas_full_history(
    df: pd.DataFrame,
    *,
    spread_threshold: float,
    price_threshold: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for _, group in df.groupby(_GROUP_KEYS, dropna=False):
        if len(group) < 2:
            continue
        ordered = group.sort_values("fetched_at")
        first = ordered.iloc[0]
        last = ordered.iloc[-1]

        p0 = float(first.point) if pd.notna(first.point) else None
        p1 = float(last.point) if pd.notna(last.point) else None
        o0 = float(first.price) if pd.notna(first.price) else None
        o1 = float(last.price) if pd.notna(last.price) else None

        point_move = (p1 - p0) if p0 is not None and p1 is not None else None
        price_move = (o1 - o0) if o0 is not None and o1 is not None else None
        steam = (
            point_move is not None and abs(point_move) >= spread_threshold
        ) or (
            price_move is not None and abs(price_move) >= price_threshold
        )

        rows.append(
            {
                "api_event_id": first.api_event_id,
                "commence_time": first.commence_time,
                "home_team": first.home_code,
                "away_team": first.away_code,
                "sportsbook": first.bookmaker_title,
                "market": first.market_key,
                "side": first.outcome_code,
                "first_seen": first.fetched_at,
                "last_seen": last.fetched_at,
                "opening_point_observed": p0,
                "latest_point": p1,
                "point_move": point_move,
                "opening_price_observed": o0,
                "latest_price": o1,
                "price_move": price_move,
                "steam_flag": bool(steam),
                "snapshots": len(group),
            }
        )

    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values(["steam_flag", "snapshots"], ascending=[False, False])
    return out


def _query_reduced_board_rows(
    con: duckdb.DuckDBPyConnection,
    *,
    spread_threshold: float,
    price_threshold: float,
) -> list[tuple[Any, ...]]:
    rows = con.execute(
        """
        WITH ranked AS (
            SELECT
                fetched_at,
                api_event_id,
                commence_time,
                home_code,
                away_code,
                bookmaker_key,
                bookmaker_title,
                market_key,
                outcome_code,
                point,
                price,
                ROW_NUMBER() OVER (
                    PARTITION BY api_event_id, bookmaker_key, market_key, outcome_code
                    ORDER BY fetched_at ASC
                ) AS rn_first,
                ROW_NUMBER() OVER (
                    PARTITION BY api_event_id, bookmaker_key, market_key, outcome_code
                    ORDER BY fetched_at DESC
                ) AS rn_last,
                COUNT(*) OVER (
                    PARTITION BY api_event_id, bookmaker_key, market_key, outcome_code
                ) AS snapshots
            FROM odds_snapshots
        ),
        first_rows AS (
            SELECT
                api_event_id,
                bookmaker_key,
                market_key,
                outcome_code,
                commence_time,
                home_code,
                away_code,
                bookmaker_title,
                fetched_at AS first_seen,
                point AS opening_point_observed,
                price AS opening_price_observed,
                snapshots
            FROM ranked
            WHERE rn_first = 1
              AND snapshots >= 2
        ),
        last_rows AS (
            SELECT
                api_event_id,
                bookmaker_key,
                market_key,
                outcome_code,
                fetched_at AS last_seen,
                point AS latest_point,
                price AS latest_price
            FROM ranked
            WHERE rn_last = 1
              AND snapshots >= 2
        )
        SELECT
            f.api_event_id,
            f.commence_time,
            f.home_code AS home_team,
            f.away_code AS away_team,
            f.bookmaker_title AS sportsbook,
            f.market_key AS market,
            f.outcome_code AS side,
            f.first_seen,
            l.last_seen,
            f.opening_point_observed,
            l.latest_point,
            CASE
                WHEN f.opening_point_observed IS NOT NULL AND l.latest_point IS NOT NULL
                THEN l.latest_point - f.opening_point_observed
                ELSE NULL
            END AS point_move,
            f.opening_price_observed,
            l.latest_price,
            CASE
                WHEN f.opening_price_observed IS NOT NULL AND l.latest_price IS NOT NULL
                THEN l.latest_price - f.opening_price_observed
                ELSE NULL
            END AS price_move,
            CASE
                WHEN (
                    f.opening_point_observed IS NOT NULL
                    AND l.latest_point IS NOT NULL
                    AND ABS(l.latest_point - f.opening_point_observed) >= ?
                )
                OR (
                    f.opening_price_observed IS NOT NULL
                    AND l.latest_price IS NOT NULL
                    AND ABS(l.latest_price - f.opening_price_observed) >= ?
                )
                THEN TRUE
                ELSE FALSE
            END AS steam_flag,
            f.snapshots
        FROM first_rows f
        INNER JOIN last_rows l
            ON f.api_event_id IS NOT DISTINCT FROM l.api_event_id
           AND f.bookmaker_key IS NOT DISTINCT FROM l.bookmaker_key
           AND f.market_key IS NOT DISTINCT FROM l.market_key
           AND f.outcome_code IS NOT DISTINCT FROM l.outcome_code
        ORDER BY steam_flag DESC, snapshots DESC
        """,
        [spread_threshold, price_threshold],
    ).fetchall()
    return list(rows)


def _rows_to_frame(rows: list[tuple[Any, ...]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS)


def run_rebuild_legacy() -> dict[str, Any]:
    spread_threshold = float(os.getenv("STEAM_SPREAD_MOVE_THRESHOLD", "1.0"))
    price_threshold = float(os.getenv("STEAM_PRICE_MOVE_THRESHOLD", "15"))

    db_path = runtime_paths.nfl_model_duckdb.resolve()
    output_csv = runtime_paths.line_movement_board_csv.resolve()
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path))
    try:
        if not _table_exists(con, "odds_snapshots"):
            raise RuntimeError("odds_snapshots missing")

        _apply_duckdb_runtime_guardrails(con)
        df = _legacy_query_full_history(con)
    finally:
        con.close()

    out = _build_board_via_pandas_full_history(
        df,
        spread_threshold=spread_threshold,
        price_threshold=price_threshold,
    )
    out.to_csv(output_csv, index=False)
    return {"rows": int(len(out))}


def run_rebuild() -> dict[str, Any]:
    spread_threshold = float(os.getenv("STEAM_SPREAD_MOVE_THRESHOLD", "1.0"))
    price_threshold = float(os.getenv("STEAM_PRICE_MOVE_THRESHOLD", "15"))

    db_path = runtime_paths.nfl_model_duckdb.resolve()
    output_csv = runtime_paths.line_movement_board_csv.resolve()
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path))
    try:
        if not _table_exists(con, "odds_snapshots"):
            raise RuntimeError("odds_snapshots missing")

        _apply_duckdb_runtime_guardrails(con)
        reduced_rows = _query_reduced_board_rows(
            con,
            spread_threshold=spread_threshold,
            price_threshold=price_threshold,
        )
    finally:
        con.close()

    out = _rows_to_frame(reduced_rows)
    out.to_csv(output_csv, index=False)
    return {"rows": int(len(out))}


def main() -> None:
    out = run_rebuild()
    print(f"line_movement_rows={out['rows']}")


if __name__ == "__main__":
    main()