from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import duckdb
import pandas as pd

from app.runtime_jobs import line_movement


def _runtime_paths(tmp_path: Path) -> tuple[Path, Path]:
    runtime_root = tmp_path / "runtime"
    database_dir = runtime_root / "database"
    outputs_dir = runtime_root / "outputs"
    database_dir.mkdir(parents=True)
    outputs_dir.mkdir(parents=True)
    return database_dir / "nfl_model.duckdb", outputs_dir / "line_movement_board.csv"


def _create_snapshots_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE odds_snapshots (
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


def _seed_small_contract_fixture(db_path: Path) -> None:
    con = duckdb.connect(str(db_path))
    try:
        _create_snapshots_schema(con)

        start = datetime(2026, 9, 10, 12, 0, 0)
        rows = [
            # Group A: spreads/home with 3 snapshots and steam point move.
            [start, "evt_a", start + timedelta(days=1), "BUF", "KC", "BUF", "KC", "book_a", "Book A", "spreads", "Buffalo Bills", "home", -2.5, -110.0, None, "current", "test"],
            [start + timedelta(minutes=5), "evt_a", start + timedelta(days=1), "BUF", "KC", "BUF", "KC", "book_a", "Book A", "spreads", "Buffalo Bills", "home", -3.0, -115.0, None, "current", "test"],
            [start + timedelta(minutes=10), "evt_a", start + timedelta(days=1), "BUF", "KC", "BUF", "KC", "book_a", "Book A", "spreads", "Buffalo Bills", "home", -4.0, -120.0, None, "current", "test"],
            # Group B: totals/over with null opening point and price-only move.
            [start, "evt_b", start + timedelta(days=2), "DAL", "PHI", "DAL", "PHI", "book_b", "Book B", "totals", "Over", "over", None, -105.0, None, "current", "test"],
            [start + timedelta(minutes=7), "evt_b", start + timedelta(days=2), "DAL", "PHI", "DAL", "PHI", "book_b", "Book B", "totals", "Over", "over", 47.5, -130.0, None, "current", "test"],
            # Group C: single snapshot should be excluded.
            [start, "evt_c", start + timedelta(days=3), "NYJ", "MIA", "NYJ", "MIA", "book_c", "Book C", "h2h", "Miami Dolphins", "away", None, -110.0, None, "current", "test"],
            # Group D: null side should still be grouped and retained (dropna=False parity).
            [start, "evt_d", start + timedelta(days=4), "SF", "SEA", "SF", "SEA", "book_d", "Book D", "spreads", "Unknown", None, 1.0, -110.0, None, "current", "test"],
            [start + timedelta(minutes=2), "evt_d", start + timedelta(days=4), "SF", "SEA", "SF", "SEA", "book_d", "Book D", "spreads", "Unknown", None, 1.0, -112.0, None, "current", "test"],
        ]

        con.executemany(
            "INSERT INTO odds_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        con.commit()
    finally:
        con.close()


def test_run_rebuild_matches_legacy_golden_contract_and_is_deterministic(tmp_path, monkeypatch):
    db_path, output_csv = _runtime_paths(tmp_path)
    _seed_small_contract_fixture(db_path)

    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("STEAM_SPREAD_MOVE_THRESHOLD", "1.0")
    monkeypatch.setenv("STEAM_PRICE_MOVE_THRESHOLD", "15")

    legacy_out = line_movement.run_rebuild_legacy()
    legacy_df = pd.read_csv(output_csv)

    new_out = line_movement.run_rebuild()
    new_df_first = pd.read_csv(output_csv)

    rerun_out = line_movement.run_rebuild()
    new_df_second = pd.read_csv(output_csv)

    assert legacy_out["rows"] == new_out["rows"] == rerun_out["rows"]
    assert list(new_df_first.columns) == [
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

    pd.testing.assert_frame_equal(legacy_df, new_df_first, check_dtype=False)
    pd.testing.assert_frame_equal(new_df_first, new_df_second, check_dtype=False)


class _RecordingConnection:
    def __init__(self, inner: duckdb.DuckDBPyConnection) -> None:
        self._inner = inner
        self.last_query = ""
        self.executed_queries: list[str] = []

    def execute(self, query, parameters=None):
        self.last_query = str(query)
        self.executed_queries.append(self.last_query)
        if parameters is None:
            self._inner.execute(query)
        else:
            self._inner.execute(query, parameters)
        return self

    def fetchone(self):
        return self._inner.fetchone()

    def fetchall(self):
        return self._inner.fetchall()

    def df(self):
        if "from odds_snapshots" in self.last_query.lower():
            raise AssertionError("Full-history DataFrame materialization is forbidden for optimized path")
        return self._inner.df()

    def close(self):
        return self._inner.close()


def test_run_rebuild_never_calls_df_on_odds_snapshots_query(tmp_path, monkeypatch):
    db_path, _ = _runtime_paths(tmp_path)
    _seed_small_contract_fixture(db_path)

    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(tmp_path / "runtime"))

    recording_connections: list[_RecordingConnection] = []
    real_connect = line_movement.duckdb.connect

    def _wrapped_connect(path: str):
        wrapped = _RecordingConnection(real_connect(path))
        recording_connections.append(wrapped)
        return wrapped

    with patch.object(line_movement.duckdb, "connect", side_effect=_wrapped_connect):
        out = line_movement.run_rebuild()

    assert out["rows"] > 0
    assert recording_connections, "Expected at least one DuckDB connection"
    all_queries = "\n".join(
        q.lower() for con in recording_connections for q in con.executed_queries
    )
    assert "from odds_snapshots" in all_queries


def _seed_million_rows(db_path: Path) -> None:
    con = duckdb.connect(str(db_path))
    try:
        _create_snapshots_schema(con)
        con.execute(
            """
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
            FROM range(1000000) AS t(i)
            """
        )
        con.commit()
    finally:
        con.close()


def test_run_rebuild_handles_one_million_rows_without_full_history_df(tmp_path, monkeypatch):
    db_path, output_csv = _runtime_paths(tmp_path)
    _seed_million_rows(db_path)

    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("LINE_MOVEMENT_DUCKDB_THREADS", "1")

    real_connect = line_movement.duckdb.connect

    class _NoDfOnHistory(_RecordingConnection):
        pass

    wrappers: list[_NoDfOnHistory] = []

    def _wrapped_connect(path: str):
        wrapped = _NoDfOnHistory(real_connect(path))
        wrappers.append(wrapped)
        return wrapped

    with patch.object(line_movement.duckdb, "connect", side_effect=_wrapped_connect):
        out = line_movement.run_rebuild()

    assert out["rows"] > 0
    assert output_csv.exists()
    frame = pd.read_csv(output_csv)
    assert len(frame) == out["rows"]
    assert len(frame) < 1000000


def test_line_movement_processing_makes_no_provider_requests(tmp_path, monkeypatch):
    db_path, _ = _runtime_paths(tmp_path)
    _seed_small_contract_fixture(db_path)
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(tmp_path / "runtime"))

    with patch("app.runtime_jobs.odds_refresh.requests.get") as request_get:
        line_movement.run_rebuild()
        request_get.assert_not_called()
