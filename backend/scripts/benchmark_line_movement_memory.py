from __future__ import annotations

import argparse
import json
import resource
import time
from pathlib import Path

import duckdb

from app.runtime_jobs import line_movement


def _create_schema(con: duckdb.DuckDBPyConnection) -> None:
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


def _seed_rows(db_path: Path, rows: int) -> None:
    con = duckdb.connect(str(db_path))
    try:
        _create_schema(con)
        con.execute("DELETE FROM odds_snapshots")
        con.execute(
            f"""
            INSERT INTO odds_snapshots
            SELECT
                TIMESTAMP '2026-09-01 00:00:00' + (i % 40) * INTERVAL 1 MINUTE AS fetched_at,
                'evt_' || CAST(i % 500 AS VARCHAR) AS api_event_id,
                TIMESTAMP '2026-09-10 20:20:00' + (i % 500) * INTERVAL 1 DAY AS commence_time,
                'HOME' AS home_team,
                'AWAY' AS away_team,
                'HOME' AS home_code,
                'AWAY' AS away_code,
                'book_' || CAST(i % 10 AS VARCHAR) AS bookmaker_key,
                'Book ' || CAST(i % 10 AS VARCHAR) AS bookmaker_title,
                CASE (i % 3)
                    WHEN 0 THEN 'spreads'
                    WHEN 1 THEN 'totals'
                    ELSE 'h2h'
                END AS market_key,
                CASE (i % 3)
                    WHEN 0 THEN CASE WHEN ((i / 3) % 2) = 0 THEN 'Home' ELSE 'Away' END
                    WHEN 1 THEN CASE WHEN ((i / 3) % 2) = 0 THEN 'Over' ELSE 'Under' END
                    ELSE CASE WHEN ((i / 3) % 2) = 0 THEN 'Home' ELSE 'Away' END
                END AS outcome_name,
                CASE (i % 3)
                    WHEN 0 THEN CASE WHEN ((i / 3) % 2) = 0 THEN 'home' ELSE 'away' END
                    WHEN 1 THEN CASE WHEN ((i / 3) % 2) = 0 THEN 'over' ELSE 'under' END
                    ELSE CASE WHEN ((i / 3) % 2) = 0 THEN 'home' ELSE 'away' END
                END AS outcome_code,
                CAST(((i % 21) - 10) AS DOUBLE) / 2.0 AS point,
                CAST(-130 + (i % 41) AS DOUBLE) AS price,
                NULL AS implied_prob,
                'current' AS snapshot_type,
                'synthetic' AS source
            FROM range({rows}) AS t(i)
            """
        )
        con.commit()
    finally:
        con.close()


def _rss_mb() -> float:
    # macOS reports ru_maxrss in bytes.
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / (1024.0 * 1024.0)


def _bench_old(db_path: Path) -> dict[str, object]:
    started = time.perf_counter()
    con = duckdb.connect(str(db_path))
    try:
        row_count = int(con.execute("SELECT COUNT(*) FROM odds_snapshots").fetchone()[0])
        line_movement._apply_duckdb_runtime_guardrails(con)
        full_df = line_movement._legacy_query_full_history(con)
    finally:
        con.close()

    out_df = line_movement._build_board_via_pandas_full_history(
        full_df,
        spread_threshold=1.0,
        price_threshold=15.0,
    )

    full_mem = int(full_df.memory_usage(deep=True).sum())
    out_mem = int(out_df.memory_usage(deep=True).sum()) if len(out_df) else 0
    largest_df_shape = full_df.shape if full_mem >= out_mem else out_df.shape
    largest_df_mem = max(full_mem, out_mem)

    return {
        "mode": "old",
        "rows_in_odds_snapshots": row_count,
        "rows_materialized_to_pandas": int(len(full_df)),
        "largest_dataframe_shape": [int(largest_df_shape[0]), int(largest_df_shape[1])],
        "approx_pandas_memory_mb": round((full_mem + out_mem) / (1024.0 * 1024.0), 2),
        "largest_dataframe_memory_mb": round(largest_df_mem / (1024.0 * 1024.0), 2),
        "peak_rss_mb": round(_rss_mb(), 2),
        "runtime_seconds": round(time.perf_counter() - started, 3),
        "output_rows": int(len(out_df)),
    }


def _bench_new(db_path: Path) -> dict[str, object]:
    started = time.perf_counter()
    con = duckdb.connect(str(db_path))
    try:
        row_count = int(con.execute("SELECT COUNT(*) FROM odds_snapshots").fetchone()[0])
        line_movement._apply_duckdb_runtime_guardrails(con)
        reduced_rows = line_movement._query_reduced_board_rows(
            con,
            spread_threshold=1.0,
            price_threshold=15.0,
        )
    finally:
        con.close()

    out_df = line_movement._rows_to_frame(reduced_rows)
    out_mem = int(out_df.memory_usage(deep=True).sum()) if len(out_df) else 0

    return {
        "mode": "new",
        "rows_in_odds_snapshots": row_count,
        "rows_materialized_to_pandas": int(len(out_df)),
        "largest_dataframe_shape": [int(out_df.shape[0]), int(out_df.shape[1])],
        "approx_pandas_memory_mb": round(out_mem / (1024.0 * 1024.0), 2),
        "largest_dataframe_memory_mb": round(out_mem / (1024.0 * 1024.0), 2),
        "peak_rss_mb": round(_rss_mb(), 2),
        "runtime_seconds": round(time.perf_counter() - started, 3),
        "output_rows": int(len(out_df)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--prepare-data", action="store_true")
    parser.add_argument("--mode", choices=["old", "new"], required=True)
    args = parser.parse_args()

    db_path = Path(args.db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if args.prepare_data:
        _seed_rows(db_path, rows=int(args.rows))

    if args.mode == "old":
        out = _bench_old(db_path)
    else:
        out = _bench_new(db_path)

    print(json.dumps(out, sort_keys=True))


if __name__ == "__main__":
    main()
