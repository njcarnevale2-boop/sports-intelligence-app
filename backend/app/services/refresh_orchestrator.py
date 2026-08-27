"""
Quota-aware recurring odds refresh orchestrator.

Runs update_odds.py → build_line_movement.py using the NFL Analytics venv.
Scheduling cadence is driven entirely by environment variables so no
aggressive defaults are baked in.  Overlap is prevented by a threading.Lock;
state is persisted to a JSON file so the admin dashboard survives restarts.

Environment variables (all optional – defaults shown):
  ODDS_REFRESH_OFFSEASON_MINS   360   far from any game
  ODDS_REFRESH_GAMEWEEK_MINS    120   Mon-Sat during season, no games today
  ODDS_REFRESH_GAMEDAY_MINS      30   a game is scheduled today
  ODDS_REFRESH_NEARKICKOFF_MINS  15   within 3 h of any scheduled kickoff
  ODDS_QUOTA_PAUSE_THRESHOLD     20   stop refreshing below this
  ODDS_QUOTA_REDUCE_THRESHOLD    50   floor cadence at GAMEWEEK interval
  ODDS_QUOTA_SLOW_THRESHOLD     100   floor cadence at OFFSEASON interval
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("refresh_orchestrator")

# ── paths ──────────────────────────────────────────────────────────────────
_MODEL_ROOT = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9"
_SCRIPTS_DIR = _MODEL_ROOT / "scripts"
_NFL_PYTHON = _MODEL_ROOT / ".venv" / "bin" / "python3"
_STATE_FILE = _MODEL_ROOT / "logs" / "refresh_state.json"
_SCHEDULE_CSV = _MODEL_ROOT / "outputs" / "current_game_projections.csv"

# ── cadence env vars (minutes) ─────────────────────────────────────────────
def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


MINS_OFFSEASON    = lambda: _env_int("ODDS_REFRESH_OFFSEASON_MINS",    360)
MINS_GAMEWEEK     = lambda: _env_int("ODDS_REFRESH_GAMEWEEK_MINS",     120)
MINS_GAMEDAY      = lambda: _env_int("ODDS_REFRESH_GAMEDAY_MINS",       30)
MINS_NEARKICKOFF  = lambda: _env_int("ODDS_REFRESH_NEARKICKOFF_MINS",   15)
QUOTA_PAUSE       = lambda: _env_int("ODDS_QUOTA_PAUSE_THRESHOLD",      20)
QUOTA_REDUCE      = lambda: _env_int("ODDS_QUOTA_REDUCE_THRESHOLD",     50)
QUOTA_SLOW        = lambda: _env_int("ODDS_QUOTA_SLOW_THRESHOLD",      100)
NEAR_KICKOFF_HRS  = lambda: _env_int("ODDS_NEARKICKOFF_HOURS",           3)


def _determine_base_cadence_minutes() -> int:
    """Return cadence based on scheduled games in the projections CSV."""
    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()

    try:
        import pandas as pd  # type: ignore
        if not _SCHEDULE_CSV.exists():
            return MINS_OFFSEASON()
        df = pd.read_csv(_SCHEDULE_CSV)
        if df.empty or "commence_time" not in df.columns:
            return MINS_OFFSEASON()

        kickoffs = pd.to_datetime(df["commence_time"], utc=True, errors="coerce").dropna()
        if kickoffs.empty:
            return MINS_OFFSEASON()

        # Near-kickoff: any game starting within NEAR_KICKOFF_HRS hours
        near_hrs = NEAR_KICKOFF_HRS()
        near_window_end = now_utc + timedelta(hours=near_hrs)
        if ((kickoffs >= now_utc) & (kickoffs <= near_window_end)).any():
            return MINS_NEARKICKOFF()

        # Game-day: any game today
        if (kickoffs.dt.date == today).any():
            return MINS_GAMEDAY()

        # Game-week: any game this calendar week
        week_end = today + timedelta(days=(6 - today.weekday()))
        if ((kickoffs.dt.date >= today) & (kickoffs.dt.date <= week_end)).any():
            return MINS_GAMEWEEK()

    except Exception as exc:
        log.warning("Could not read schedule for cadence: %s", exc)

    return MINS_OFFSEASON()


def _quota_cap(base_minutes: int, quota: Optional[int]) -> Optional[int]:
    """Return None if refresh should be paused; else return effective interval."""
    if quota is None:
        return base_minutes
    if quota <= QUOTA_PAUSE():
        return None  # paused
    if quota <= QUOTA_REDUCE():
        return max(base_minutes, MINS_GAMEWEEK())
    if quota <= QUOTA_SLOW():
        return max(base_minutes, MINS_OFFSEASON())
    return base_minutes


# ── state persistence ───────────────────────────────────────────────────────
_EMPTY_STATE: Dict[str, Any] = {
    "lastRefreshAt": None,
    "nextRefreshAt": None,
    "lastError": None,
    "isRunning": False,
    "cadenceMinutes": None,
    "consecutiveFailures": 0,
    "quotaRemaining": None,
    # CLV closing-capture stats (updated each run)
    "closingCaptureLastRun": None,
    "closingCaptureEligible": 0,
    "closingLinesCapturedThisRun": 0,
    "closingLinesStillPending": 0,
    "closingLinesMissing": 0,
    "closingCaptureErrors": 0,
    "lastClosingCaptureError": None,
    # Ledger outcome append stats (updated each run)
    "ledgerOutcomeChecked": 0,
    "ledgerOutcomesAppended": 0,
    "ledgerOutcomesStillPending": 0,
    "lastLedgerOutcomeError": None,
    "shadowOutcomeChecked": 0,
    "shadowOutcomesAppended": 0,
    "shadowOutcomesStillPending": 0,
    "lastShadowOutcomeError": None,
    # Injury refresh stats (updated each run)
    "injuryPlayersUpdated": 0,
    "injuryTeamsUpdated": 0,
    "lastInjuryError": None,
    "injuryDataStatus": "MOCK",
    # Weather refresh stats (updated each run)
    "weatherGamesUpdated": 0,
    "weatherForecastsAvailable": 0,
    "lastWeatherError": None,
    "weatherDataStatus": "MOCK",
}


def _read_state() -> Dict[str, Any]:
    try:
        if _STATE_FILE.exists():
            return {**_EMPTY_STATE, **json.loads(_STATE_FILE.read_text())}
    except Exception:
        pass
    return dict(_EMPTY_STATE)


def _write_state(state: Dict[str, Any]) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, default=str, indent=2))
    except Exception as exc:
        log.warning("Could not write refresh state: %s", exc)


# ── core runner ─────────────────────────────────────────────────────────────
_run_lock = threading.Lock()


def _run_once() -> bool:
    """Execute update_odds → build_line_movement.  Returns True on success."""
    if not _run_lock.acquire(blocking=False):
        log.info("Refresh already running – skipping overlap")
        return False

    state = _read_state()
    state["isRunning"] = True
    _write_state(state)

    started = datetime.now(timezone.utc)
    log.info("Odds refresh started at %s", started.isoformat())

    try:
        python = str(_NFL_PYTHON) if _NFL_PYTHON.exists() else "python3"

        # Step 1: fetch odds (appends to DuckDB – never overwrites)
        r1 = subprocess.run(
            [python, "scripts/update_odds.py"],
            cwd=str(_MODEL_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r1.returncode != 0:
            raise RuntimeError(f"update_odds.py failed: {r1.stderr[-500:]}")
        log.info("update_odds.py: %s", r1.stdout.strip())

        # Step 2: rebuild line movement board from new snapshot
        r2 = subprocess.run(
            [python, "scripts/build_line_movement.py"],
            cwd=str(_MODEL_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r2.returncode != 0:
            raise RuntimeError(f"build_line_movement.py failed: {r2.stderr[-500:]}")
        log.info("build_line_movement.py: done")

        # Step 3: capture closing lines for PENDING recommendations post-kickoff.
        # Already-captured (AVAILABLE) records are never touched (idempotent).
        clv_counts: Dict[str, int] = {"eligible": 0, "captured": 0, "pending": 0, "missing": 0, "errors": 0}
        closing_capture_error: Optional[str] = None
        closing_started = datetime.now(timezone.utc)
        try:
            from app.services.recommendation_snapshot import capture_closing_lines
            log.info("Closing capture starting")
            clv_counts = capture_closing_lines()
            closing_duration = round((datetime.now(timezone.utc) - closing_started).total_seconds(), 3)
            log.info(
                "Closing capture finished: eligible=%d captured=%d pending=%d missing=%d errors=%d duration=%.3fs",
                clv_counts["eligible"],
                clv_counts["captured"],
                clv_counts["pending"],
                clv_counts["missing"],
                clv_counts["errors"],
                closing_duration,
            )
        except Exception as exc:
            closing_capture_error = str(exc)[:300]
            log.warning("Closing line capture step failed (non-fatal): %s", exc)

        # Step 3b: process OFFICIAL ledger postgame lifecycle for finished games.
        ledger_outcomes: Dict[str, int] = {"checked": 0, "appended": 0, "pending": 0}
        ledger_outcome_error: Optional[str] = None
        try:
            from app.services.decision_ledger import run_official_postgame_lifecycle

            lifecycle = run_official_postgame_lifecycle(fetch_scores_fn=_fetch_final_score_from_duckdb)
            ledger_outcomes = {
                "checked": int(lifecycle.get("checked") or 0),
                "appended": int(lifecycle.get("settled") or 0),
                "pending": int(lifecycle.get("pending") or 0),
            }
            log.info(
                "Ledger postgame lifecycle: checked=%d settled=%d pending=%d",
                ledger_outcomes.get("checked", 0),
                ledger_outcomes.get("appended", 0),
                ledger_outcomes.get("pending", 0),
            )
        except Exception as exc:
            ledger_outcome_error = str(exc)[:300]
            log.warning("Ledger outcome append step failed (non-fatal): %s", exc)

        # Step 3c: append shadow outcomes for frozen shadow snapshots (append-only).
        shadow_outcomes: Dict[str, int] = {"checked": 0, "appended": 0, "pending": 0}
        shadow_outcome_error: Optional[str] = None
        try:
            from app.services.shadow_markets import append_shadow_outcomes

            shadow_outcomes = append_shadow_outcomes(fetch_scores_fn=_fetch_final_score_from_duckdb)
            log.info(
                "Shadow outcome append: checked=%d appended=%d pending=%d",
                shadow_outcomes.get("checked", 0),
                shadow_outcomes.get("appended", 0),
                shadow_outcomes.get("pending", 0),
            )
        except Exception as exc:
            shadow_outcome_error = str(exc)[:300]
            log.warning("Shadow outcome append step failed (non-fatal): %s", exc)

        # Step 4: refresh performance metrics after CLV capture (non-fatal).
        try:
            from app.services.performance import get_performance_service
            perf_summary = get_performance_service().get_performance_summary()
            log.info(
                "Performance refresh: closing_captured=%s pending=%s missing=%s average_clv=%s",
                perf_summary.get("closingLinesCaptured"),
                perf_summary.get("pendingClosingLines"),
                perf_summary.get("missingClosingLines"),
                perf_summary.get("averageCLV"),
            )
        except Exception as exc:
            log.warning("Performance refresh step failed (non-fatal): %s", exc)

        duration = round((datetime.now(timezone.utc) - started).total_seconds(), 2)
        log.info("Odds refresh finished in %.2fs", duration)

        state = _read_state()
        state["lastRefreshAt"] = started.isoformat()
        state["lastError"] = None
        state["consecutiveFailures"] = 0
        state["closingCaptureLastRun"] = datetime.now(timezone.utc).isoformat()
        state["closingCaptureEligible"] = clv_counts["eligible"]
        state["closingLinesCapturedThisRun"] = clv_counts["captured"]
        state["closingLinesStillPending"]    = clv_counts["pending"]
        state["closingLinesMissing"]         = clv_counts["missing"]
        state["closingCaptureErrors"]        = max(clv_counts["errors"], 1 if closing_capture_error else 0)
        state["lastClosingCaptureError"]     = closing_capture_error
        state["ledgerOutcomeChecked"] = int(ledger_outcomes.get("checked", 0))
        state["ledgerOutcomesAppended"] = int(ledger_outcomes.get("appended", 0))
        state["ledgerOutcomesStillPending"] = int(ledger_outcomes.get("pending", 0))
        state["lastLedgerOutcomeError"] = ledger_outcome_error
        state["shadowOutcomeChecked"] = int(shadow_outcomes.get("checked", 0))
        state["shadowOutcomesAppended"] = int(shadow_outcomes.get("appended", 0))
        state["shadowOutcomesStillPending"] = int(shadow_outcomes.get("pending", 0))
        state["lastShadowOutcomeError"] = shadow_outcome_error

        # Step 5: refresh injury data (non-fatal – never blocks odds refresh)
        try:
            from app.services.injuries import InjuryAnalyzer
            from app.services.injury_history import get_injury_summary
            analyzer = InjuryAnalyzer()
            analyzer.analyze()   # triggers live fetch + snapshot store
            inj_summary = get_injury_summary()
            state["injuryPlayersUpdated"] = inj_summary.get("playersTracked", 0)
            state["injuryTeamsUpdated"]   = inj_summary.get("teamsUpdated", 0)
            state["lastInjuryError"]      = None
            state["injuryDataStatus"]     = analyzer._data_status
            log.info(
                "Injury refresh: players=%d teams=%d status=%s",
                state["injuryPlayersUpdated"], state["injuryTeamsUpdated"],
                state["injuryDataStatus"],
            )
        except Exception as exc:
            log.warning("Injury refresh step failed (non-fatal): %s", exc)
            state["lastInjuryError"] = str(exc)[:300]

        # Step 6: refresh weather forecasts for upcoming games (non-fatal)
        try:
            from app.services.weather import WeatherAnalyzer
            from app.services.weather_history import get_weather_summary
            import pandas as _pd
            games_updated = 0
            proj_csv = _MODEL_ROOT / "outputs" / "current_game_projections.csv"
            if proj_csv.exists():
                df = _pd.read_csv(proj_csv)
                home_teams = df["home_team"].dropna().unique().tolist() if "home_team" in df.columns else []
                for ht in home_teams[:32]:   # cap to 32 (one per team per run)
                    try:
                        WeatherAnalyzer(home_team=str(ht).upper())
                        games_updated += 1
                    except Exception:
                        pass
            wx_summary = get_weather_summary()
            state["weatherGamesUpdated"]      = games_updated
            state["weatherForecastsAvailable"] = wx_summary.get("forecastsAvailable", 0)
            state["lastWeatherError"]          = None
            state["weatherDataStatus"]         = "LIVE" if games_updated > 0 else "UNAVAILABLE"
            log.info("Weather refresh: games_updated=%d", games_updated)
        except Exception as exc:
            log.warning("Weather refresh step failed (non-fatal): %s", exc)
            state["lastWeatherError"] = str(exc)[:300]

        # Update quota from DuckDB
        try:
            state["quotaRemaining"] = _read_quota_from_db()
        except Exception:
            pass

        state["isRunning"] = False
        _write_state(state)
        return True

    except Exception as exc:
        log.error("Odds refresh error: %s", exc)
        state = _read_state()
        state["lastError"] = str(exc)[:500]
        state["consecutiveFailures"] = int(state.get("consecutiveFailures") or 0) + 1
        state["isRunning"] = False
        _write_state(state)
        return False
    finally:
        _run_lock.release()


def _read_quota_from_db() -> Optional[int]:
    try:
        import duckdb  # type: ignore
        db_path = _MODEL_ROOT / "database" / "nfl_model.duckdb"
        if not db_path.exists():
            return None
        con = duckdb.connect(str(db_path), read_only=True)
        row = con.execute(
            "SELECT requests_remaining FROM odds_api_usage ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
        con.close()
        return int(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def _fetch_final_score_from_duckdb(event_id: str) -> Optional[Dict[str, Any]]:
    """Best-effort final score lookup for an event id from nfl_model DuckDB."""
    try:
        import duckdb  # type: ignore

        db_path = _MODEL_ROOT / "database" / "nfl_model.duckdb"
        if not db_path.exists():
            return None

        con = duckdb.connect(str(db_path), read_only=True)
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if "schedules" not in tables:
            con.close()
            return None

        # 1) direct game_id/event_id match
        row = con.execute(
            """
            SELECT away_score, home_score
            FROM schedules
            WHERE game_id = ?
              AND away_score IS NOT NULL
              AND home_score IS NOT NULL
            LIMIT 1
            """,
            [event_id],
        ).fetchone()

        if row is not None:
            con.close()
            return {"finalAwayScore": int(row[0]), "finalHomeScore": int(row[1])}

        # 2) fallback parse for event pattern: YYYY_W_AWAY_HOME
        parts = str(event_id).split("_")
        if len(parts) >= 4:
            season = int(parts[0])
            week = int(parts[1])
            away = parts[2]
            home = parts[3]
            row = con.execute(
                """
                SELECT away_score, home_score
                FROM schedules
                WHERE season = ?
                  AND week = ?
                  AND away_team = ?
                  AND home_team = ?
                  AND away_score IS NOT NULL
                  AND home_score IS NOT NULL
                LIMIT 1
                """,
                [season, week, away, home],
            ).fetchone()
            if row is not None:
                con.close()
                return {"finalAwayScore": int(row[0]), "finalHomeScore": int(row[1])}

        con.close()
        return None
    except Exception:
        return None


def _log_captured_records() -> None:
    """Log detail (no sensitive data) for every newly resolved CLV record."""
    try:
        import duckdb  # type: ignore
        db_path = _MODEL_ROOT / "database" / "nfl_model.duckdb"
        if not db_path.exists():
            return
        con = duckdb.connect(str(db_path), read_only=True)
        rows = con.execute(
            """
            SELECT event_id, sportsbook, market, side,
                   recommended_at, closing_at, clv_points, clv_percent
            FROM recommendation_snapshots
            WHERE closing_status = 'AVAILABLE'
            ORDER BY closing_at DESC
            LIMIT 50
            """
        ).fetchall()
        con.close()
        for r in rows:
            event_id, book, mkt, side, rec_at, close_at, clv_pts, clv_pct = r
            clv_str = (
                f"CLV={clv_pts:+.2f}pts" if clv_pts is not None
                else f"CLV={clv_pct:+.2f}%" if clv_pct is not None
                else "CLV=n/a"
            )
            log.info(
                "CLV captured: event=%s book=%s market=%s side=%s rec_at=%s close_at=%s %s",
                event_id, book, mkt, side, rec_at, close_at, clv_str,
            )
    except Exception as exc:
        log.debug("Could not log CLV details: %s", exc)


# ── scheduler loop ──────────────────────────────────────────────────────────
_scheduler_started = False
_scheduler_lock = threading.Lock()


def _scheduler_loop() -> None:
    import time

    while True:
        try:
            state = _read_state()
            quota = state.get("quotaRemaining")

            base = _determine_base_cadence_minutes()
            effective = _quota_cap(base, quota)

            state["cadenceMinutes"] = effective

            if effective is None:
                log.warning("Odds quota at or below pause threshold – refresh suspended")
                state["nextRefreshAt"] = None
                _write_state(state)
                time.sleep(300)
                continue

            last_str = state.get("lastRefreshAt")
            last_dt = None
            if last_str:
                try:
                    last_dt = datetime.fromisoformat(last_str)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass

            now = datetime.now(timezone.utc)
            next_dt = (last_dt + timedelta(minutes=effective)) if last_dt else now

            state["nextRefreshAt"] = next_dt.isoformat()
            _write_state(state)

            if now >= next_dt:
                _run_once()
            else:
                sleep_secs = min((next_dt - now).total_seconds(), 60)
                time.sleep(max(sleep_secs, 5))

        except Exception as exc:
            log.error("Scheduler loop error: %s", exc)
            import time
            time.sleep(60)


def start_scheduler() -> None:
    """Start the background scheduler thread (idempotent)."""
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    t = threading.Thread(target=_scheduler_loop, name="odds-refresh-scheduler", daemon=True)
    t.start()
    log.info("Odds refresh scheduler started")


# ── public API ───────────────────────────────────────────────────────────────
def trigger_now() -> Dict[str, Any]:
    """Trigger an immediate refresh (used by admin 'Refresh Now').

    Returns a summary dict.  Non-blocking overlap check: if a refresh is
    already running the call returns immediately with is_running=True.
    """
    if not _run_lock.acquire(blocking=False):
        return {"triggered": False, "reason": "refresh already running"}
    _run_lock.release()  # release so _run_once can re-acquire

    success = _run_once()
    state = _read_state()
    return {
        "triggered": True,
        "success": success,
        "lastRefreshAt": state.get("lastRefreshAt"),
        "lastError": state.get("lastError"),
        "quotaRemaining": state.get("quotaRemaining"),
        "closingCaptureLastRun": state.get("closingCaptureLastRun"),
        "closingCaptureEligible": state.get("closingCaptureEligible", 0),
        "closingLinesCapturedThisRun": state.get("closingLinesCapturedThisRun", 0),
        "closingLinesStillPending":    state.get("closingLinesStillPending",    0),
        "closingLinesMissing":         state.get("closingLinesMissing",         0),
        "closingCaptureErrors":        state.get("closingCaptureErrors",        0),
        "lastClosingCaptureError":     state.get("lastClosingCaptureError"),
        "ledgerOutcomeChecked": state.get("ledgerOutcomeChecked", 0),
        "ledgerOutcomesAppended": state.get("ledgerOutcomesAppended", 0),
        "ledgerOutcomesStillPending": state.get("ledgerOutcomesStillPending", 0),
        "lastLedgerOutcomeError": state.get("lastLedgerOutcomeError"),
    }


def get_refresh_status() -> Dict[str, Any]:
    """Return current scheduler status for the admin dashboard."""
    state = _read_state()
    quota = state.get("quotaRemaining")
    base = _determine_base_cadence_minutes()
    effective = _quota_cap(base, quota)

    return {
        "lastRefreshAt": state.get("lastRefreshAt"),
        "nextRefreshAt": state.get("nextRefreshAt"),
        "cadenceMinutes": effective,
        "isRunning": bool(state.get("isRunning")),
        "lastError": state.get("lastError"),
        "consecutiveFailures": int(state.get("consecutiveFailures") or 0),
        "quotaRemaining": quota,
        "quotaPaused": effective is None,
        "provider": "The Odds API",
        "closingCaptureLastRun": state.get("closingCaptureLastRun"),
        "closingCaptureEligible": int(state.get("closingCaptureEligible") or 0),
        "closingLinesCapturedThisRun": int(state.get("closingLinesCapturedThisRun") or 0),
        "closingLinesStillPending":    int(state.get("closingLinesStillPending")    or 0),
        "closingLinesMissing":         int(state.get("closingLinesMissing")         or 0),
        "closingCaptureErrors":        int(state.get("closingCaptureErrors")        or 0),
        "lastClosingCaptureError":     state.get("lastClosingCaptureError"),
        "ledgerOutcomeChecked": int(state.get("ledgerOutcomeChecked") or 0),
        "ledgerOutcomesAppended": int(state.get("ledgerOutcomesAppended") or 0),
        "ledgerOutcomesStillPending": int(state.get("ledgerOutcomesStillPending") or 0),
        "lastLedgerOutcomeError": state.get("lastLedgerOutcomeError"),
        "injuryPlayersUpdated": int(state.get("injuryPlayersUpdated") or 0),
        "injuryTeamsUpdated":   int(state.get("injuryTeamsUpdated")   or 0),
        "lastInjuryError":      state.get("lastInjuryError"),
        "injuryDataStatus":     state.get("injuryDataStatus", "MOCK"),
        "weatherGamesUpdated":      int(state.get("weatherGamesUpdated")      or 0),
        "weatherForecastsAvailable": int(state.get("weatherForecastsAvailable") or 0),
        "lastWeatherError":          state.get("lastWeatherError"),
        "weatherDataStatus":         state.get("weatherDataStatus", "MOCK"),
    }
