# Line Movement Memory Audit (2026-08-29)

## Scope and Safety Constraints

- No production refresh executed.
- No Odds API requests executed as part of line movement audit/bench.
- No production DuckDB mutation.
- Odds automation and pregame automation remained disabled by default.
- Bootstrap/cost verification system untouched.

## Phase 1: Current Normal Refresh Path Audit

### Control Flow

1. Scheduler/admin path enters refresh orchestrator.
2. Refresh orchestrator runs subprocess: app.runtime_jobs.odds_refresh.
3. odds_refresh appends rows into DuckDB table odds_snapshots.
4. Refresh orchestrator runs subprocess: app.runtime_jobs.line_movement.
5. line_movement rebuilds outputs/line_movement_board.csv.
6. Downstream services read line_movement_board.csv (market/opportunity/shadow flows).

### DuckDB Operations (line movement path)

Legacy line_movement implementation:
- SELECT fetched_at, api_event_id, commence_time, home_code, away_code, bookmaker_key, bookmaker_title, market_key, outcome_code, point, price FROM odds_snapshots ORDER BY api_event_id, bookmaker_key, market_key, outcome_code, fetched_at
- Materialization: .df() on full query result

Optimized line_movement implementation:
- Single SQL pipeline with window functions:
  - ROW_NUMBER() ASC and DESC per (api_event_id, bookmaker_key, market_key, outcome_code)
  - COUNT(*) per same partition
  - first_rows and last_rows CTEs filtered to snapshots >= 2
  - null-safe key join using IS NOT DISTINCT FROM
  - movement and steam flag computed in SQL
  - ORDER BY steam_flag DESC, snapshots DESC
- Materialization: fetchall() only for reduced result rows (board-level rows)

### Legacy Full-History Materialization Hotspots

Legacy code performed:
- Full-history DuckDB -> pandas with .df()
- pandas groupby on full DataFrame
- per-group sort_values on fetched_at
- per-group first/last selection and Python dict accumulation
- final DataFrame construction for output

This directly scaled pandas memory with full odds_snapshots history.

### Required Columns

Only these source columns are required to build board semantics:
- fetched_at
- api_event_id
- commence_time
- home_code
- away_code
- bookmaker_key
- bookmaker_title
- market_key
- outcome_code
- point
- price

### Required Historical Rows

For each key partition (api_event_id, bookmaker_key, market_key, outcome_code):
- earliest row (opening)
- latest row (current)
- partition count

All intermediate historical rows are not required by final board output once first/last/count are derived.

## Phase 2: Output Contract (line_movement_board.csv)

### Column Set and Order

1. api_event_id
2. commence_time
3. home_team
4. away_team
5. sportsbook
6. market
7. side
8. first_seen
9. last_seen
10. opening_point_observed
11. latest_point
12. point_move
13. opening_price_observed
14. latest_price
15. price_move
16. steam_flag
17. snapshots

### Semantics

- One row per (api_event_id, bookmaker_key, market_key, outcome_code) where snapshots >= 2.
- opening_* fields come from earliest fetched_at in partition.
- latest_* fields come from latest fetched_at in partition.
- point_move = latest_point - opening_point_observed when both non-null, else null.
- price_move = latest_price - opening_price_observed when both non-null, else null.
- steam_flag true when abs(point_move) >= STEAM_SPREAD_MOVE_THRESHOLD OR abs(price_move) >= STEAM_PRICE_MOVE_THRESHOLD.
- snapshots equals partition row count.
- Row order: steam_flag DESC, snapshots DESC.
- Null group keys are retained (legacy dropna=False parity).

### Golden Fixture

Deterministic parity fixture is codified in backend/tests/test_runtime_jobs_line_movement.py:
- legacy builder output vs optimized builder output exact frame parity.
- deterministic repeated execution equality.

## Phase 3 and 7: Memory Baseline and Comparison (Synthetic 1,000,000 rows)

Local synthetic benchmark command path:
- backend/scripts/benchmark_line_movement_memory.py

Observed metrics:

OLD (legacy full-history pandas path)
- rows in odds_snapshots: 1,000,000
- rows materialized to pandas: 1,000,000
- largest DataFrame: (1,000,000, 11)
- approx pandas memory: 392.98 MB
- peak RSS: 558.64 MB
- runtime: 4.63 s
- output rows: 1,500

NEW (SQL-reduced path)
- rows in odds_snapshots: 1,000,000
- rows materialized to pandas: 1,500
- largest DataFrame: (1,500, 17)
- approx pandas memory: 0.58 MB
- peak RSS: 288.60 MB
- runtime: 1.485 s
- output rows: 1,500

Approx reductions:
- pandas-materialized rows reduction: 99.85%
- approx pandas memory reduction: 99.85%
- peak RSS reduction: 48.34%

## Phase 4: Memory-Safe Implementation Summary

- Removed full-history .df() path from default rebuild.
- Pushed grouping, first/last derivation, movement math, and steam logic into DuckDB SQL.
- Materialize only reduced board-level rows for CSV writing.
- Preserved existing board contract and semantics with regression parity tests.

## Phase 5: DuckDB Guardrails

Changes applied only within line movement runtime job connection scope:
- SET threads = 1 by default for line movement job (LINE_MOVEMENT_DUCKDB_THREADS, default 1).
- Optional memory cap support via LINE_MOVEMENT_DUCKDB_MEMORY_LIMIT_MB (unset by default).

Rationale:
- Lower thread parallelism reduces memory spikes in constrained 512 MB environments.
- Memory limit is optional to avoid unintended impact on unrelated workloads.
- Primary memory reduction comes from architectural elimination of full-history pandas materialization.

## Phase 6: Regression Coverage Added

backend/tests/test_runtime_jobs_line_movement.py includes:
- legacy vs optimized output parity on deterministic fixture
- deterministic repeated output
- no .df() usage on full-history odds_snapshots query in optimized path
- 1M-row synthetic execution with reduced pandas materialization
- no provider request during line movement processing

## Phase 8 Validation Results

- Focused line movement tests: passed (4/4)
- Full backend pytest: passed (464 passed, 3 warnings)
- npx tsc --noEmit: passed
- npx next build: passed

No provider calls were made in this line movement work path.
