from __future__ import annotations

import os
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from app.runtime_paths import runtime_paths


def _table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    return (
        con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [table],
        ).fetchone()[0]
        > 0
    )


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

        df = con.execute(
            """
            SELECT fetched_at, api_event_id, commence_time, home_code, away_code,
                   bookmaker_key, bookmaker_title, market_key, outcome_code, point, price
            FROM odds_snapshots
            ORDER BY api_event_id, bookmaker_key, market_key, outcome_code, fetched_at
            """
        ).df()
    finally:
        con.close()

    keys = ["api_event_id", "bookmaker_key", "market_key", "outcome_code"]
    rows: list[dict[str, Any]] = []

    for _, group in df.groupby(keys, dropna=False):
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
    out.to_csv(output_csv, index=False)
    return {"rows": int(len(out))}


def main() -> None:
    out = run_rebuild()
    print(f"line_movement_rows={out['rows']}")


if __name__ == "__main__":
    main()