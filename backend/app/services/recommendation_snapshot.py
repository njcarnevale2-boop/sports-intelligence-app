"""
Immutable recommendation snapshot storage and CLV resolution.

Each snapshot is written once when a bet is added to My Card.
The record is never mutated after creation – closing line and CLV
fields are populated in a separate pass after kickoff.

DuckDB table: recommendation_snapshots (in the NFL Analytics OS database)
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.closing_line import calculate_clv, get_closing_line


log = logging.getLogger("recommendation_snapshot")

_DB_PATH = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9" / "database" / "nfl_model.duckdb"
_SCHEDULE_CSV = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9" / "outputs" / "current_game_projections.csv"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendation_snapshots (
    snapshot_id        VARCHAR PRIMARY KEY,
    event_id           VARCHAR NOT NULL,
    recommended_at     TIMESTAMP NOT NULL,
    market             VARCHAR NOT NULL,
    side               VARCHAR NOT NULL,
    point              DOUBLE,
    price              DOUBLE,
    sportsbook         VARCHAR,
    si_score           DOUBLE,
    model_probability  DOUBLE,
    edge_pp            DOUBLE,
    ev_per_dollar      DOUBLE,
    market_intelligence TEXT,
    injury_context     TEXT,
    weather_context    TEXT,
    commence_time      TIMESTAMP,
    home_team          VARCHAR,
    away_team          VARCHAR,
    closing_status     VARCHAR DEFAULT 'PENDING',
    closing_point      DOUBLE,
    closing_price      DOUBLE,
    closing_sportsbook VARCHAR,
    closing_at         TIMESTAMP,
    clv_points         DOUBLE,
    clv_probability    DOUBLE,
    clv_percent        DOUBLE
)
"""


def _open_db(read_only: bool = False):
    import duckdb  # type: ignore
    return duckdb.connect(str(_DB_PATH), read_only=read_only)


def _ensure_schema() -> None:
    if not _DB_PATH.exists():
        return
    con = _open_db()
    con.execute(_SCHEMA)
    con.close()


def _kickoff_for_event(event_id: str) -> Optional[datetime]:
    """Look up commence_time from the projections CSV."""
    try:
        import pandas as pd  # type: ignore
        if not _SCHEDULE_CSV.exists():
            return None
        df = pd.read_csv(_SCHEDULE_CSV)
        row = df[df["api_event_id"] == event_id]
        if row.empty:
            return None
        raw = row.iloc[0]["commence_time"]
        dt = pd.to_datetime(raw, utc=True, errors="coerce")
        if pd.isna(dt):
            return None
        return dt.to_pydatetime()
    except Exception:
        return None


# ── public write ─────────────────────────────────────────────────────────────

def store_snapshot(payload: Dict[str, Any]) -> str:
    """Write an immutable recommendation snapshot.  Returns snapshot_id."""
    _ensure_schema()
    if not _DB_PATH.exists():
        return ""

    snapshot_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    con = _open_db()
    con.execute(
        """
        INSERT OR IGNORE INTO recommendation_snapshots
        (snapshot_id, event_id, recommended_at, market, side, point, price,
         sportsbook, si_score, model_probability, edge_pp, ev_per_dollar,
         market_intelligence, injury_context, weather_context,
         commence_time, home_team, away_team, closing_status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'PENDING')
        """,
        [
            snapshot_id,
            payload.get("eventId", ""),
            now,
            payload.get("market", ""),
            payload.get("side", ""),
            payload.get("point"),
            payload.get("price"),
            payload.get("sportsbook"),
            payload.get("siScore"),
            payload.get("modelProbability"),
            payload.get("edge"),
            payload.get("evPerDollar"),
            json.dumps(payload.get("marketIntelligence") or {}),
            json.dumps(payload.get("injuryContext") or {}),
            json.dumps(payload.get("weatherContext") or {}),
            payload.get("commenceTime"),
            payload.get("homeTeam"),
            payload.get("awayTeam"),
        ],
    )
    con.close()
    return snapshot_id


# ── closing line capture pass ─────────────────────────────────────────────────

def capture_closing_lines() -> Dict[str, int]:
    """
    Scan PENDING snapshots.  For games that have kicked off, attempt to
    resolve a closing line from DuckDB odds_snapshots and compute CLV.

    Returns counts: {eligible, captured, pending, missing, errors}.
    """
    _ensure_schema()
    if not _DB_PATH.exists():
        return {"eligible": 0, "captured": 0, "pending": 0, "missing": 0, "errors": 0}

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    started = datetime.now(timezone.utc)

    con = _open_db()
    try:
        pending = con.execute(
            "SELECT snapshot_id, event_id, market, side, point, price, sportsbook, commence_time "
            "FROM recommendation_snapshots WHERE closing_status = 'PENDING'"
        ).fetchall()
    except Exception:
        con.close()
        return {"eligible": 0, "captured": 0, "pending": 0, "missing": 0, "errors": 0}
    con.close()

    log.info("Closing capture started: pending_snapshots=%d", len(pending))

    eligible = 0
    captured = 0
    still_pending = 0
    missing = 0
    errors = 0

    for row in pending:
        snap_id, event_id, market, side, rec_point, rec_price, sportsbook, commence_raw = row

        kickoff = None
        if commence_raw:
            try:
                if isinstance(commence_raw, datetime):
                    kickoff = commence_raw.replace(tzinfo=None) if commence_raw.tzinfo else commence_raw
                else:
                    kickoff = datetime.fromisoformat(str(commence_raw).replace("Z", "+00:00"))
                    kickoff = kickoff.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                pass

        if kickoff is None:
            # Try CSV lookup
            kickoff_dt = _kickoff_for_event(event_id)
            if kickoff_dt:
                kickoff = kickoff_dt.astimezone(timezone.utc).replace(tzinfo=None)

        if kickoff is None or now_naive < kickoff:
            still_pending += 1
            continue

        # Game has kicked off – attempt closing line capture
        eligible += 1

        try:
            kickoff_aware = kickoff.replace(tzinfo=timezone.utc)
            closing = get_closing_line(
                event_id=event_id,
                bookmaker_key=sportsbook or "",
                market_key=market,
                outcome_code=side,
                kickoff_utc=kickoff_aware,
            )

            if closing.closing_status != "AVAILABLE":
                missing += 1
                _update_status(snap_id, "NOT_CAPTURED")
                continue

            clv = calculate_clv(
                recommended_point=float(rec_point) if rec_point is not None else None,
                recommended_price=float(rec_price) if rec_price is not None else None,
                closing_point=closing.closing_point,
                closing_price=closing.closing_price,
                market=market,
                side=side,
            )

            closing_ts = closing.closing_timestamp
            if isinstance(closing_ts, datetime) and closing_ts.tzinfo is not None:
                closing_ts = closing_ts.replace(tzinfo=None)

            con = _open_db()
            con.execute(
                """
                UPDATE recommendation_snapshots SET
                    closing_status     = 'AVAILABLE',
                    closing_point      = ?,
                    closing_price      = ?,
                    closing_sportsbook = ?,
                    closing_at         = ?,
                    clv_points         = ?,
                    clv_probability    = ?,
                    clv_percent        = ?
                WHERE snapshot_id = ?
                """,
                [
                    closing.closing_point,
                    closing.closing_price,
                    sportsbook,
                    closing_ts,
                    clv.clv_points,
                    clv.clv_probability,
                    clv.clv_percent,
                    snap_id,
                ],
            )
            con.close()
            captured += 1
        except Exception as exc:
            errors += 1
            still_pending += 1
            log.warning(
                "Closing capture failed for snapshot=%s event=%s market=%s side=%s: %s",
                snap_id,
                event_id,
                market,
                side,
                exc,
            )

    duration = round((datetime.now(timezone.utc) - started).total_seconds(), 3)
    log.info(
        "Closing capture finished: eligible=%d captured=%d pending=%d missing=%d errors=%d duration=%.3fs",
        eligible,
        captured,
        still_pending,
        missing,
        errors,
        duration,
    )

    return {
        "eligible": eligible,
        "captured": captured,
        "pending": still_pending,
        "missing": missing,
        "errors": errors,
    }


def _update_status(snapshot_id: str, status: str) -> None:
    con = _open_db()
    con.execute(
        "UPDATE recommendation_snapshots SET closing_status = ? WHERE snapshot_id = ?",
        [status, snapshot_id],
    )
    con.close()


# ── read helpers ─────────────────────────────────────────────────────────────

def get_clv_for_event(event_id: str) -> List[Dict[str, Any]]:
    """Return all CLV records for a specific event."""
    _ensure_schema()
    if not _DB_PATH.exists():
        return []
    try:
        con = _open_db(read_only=True)
        rows = con.execute(
            """
            SELECT snapshot_id, recommended_at, market, side, point, price,
                   sportsbook, si_score, closing_status,
                   closing_point, closing_price, closing_at,
                   clv_points, clv_probability, clv_percent
            FROM recommendation_snapshots
            WHERE event_id = ?
            ORDER BY recommended_at DESC
            """,
            [event_id],
        ).fetchall()
        con.close()
    except Exception:
        return []

    cols = [
        "snapshotId", "recommendedAt", "market", "side", "point", "price",
        "sportsbook", "siScore", "closingStatus",
        "closingPoint", "closingPrice", "closingAt",
        "clvPoints", "clvProbability", "clvPercent",
    ]
    return [dict(zip(cols, row)) for row in rows]


def get_clv_summary() -> Dict[str, Any]:
    """Aggregate CLV stats for the performance API and admin dashboard."""
    _ensure_schema()
    empty: Dict[str, Any] = {
        "closingLinesCaptured": 0,
        "pendingClosingLines":  0,
        "missingClosingLines":  0,
        "averageCLVPoints":     None,
        "positiveCLVPercent":   None,
        "clvByMarket":          [],
        "clvBySiScoreBand":     [],
        "clvBySportsbook":      [],
    }
    if not _DB_PATH.exists():
        return empty

    try:
        con = _open_db(read_only=True)

        # Counts by status
        counts = con.execute(
            "SELECT closing_status, COUNT(*) FROM recommendation_snapshots GROUP BY closing_status"
        ).fetchall()
        status_map = {r[0]: int(r[1]) for r in counts}

        rows = con.execute(
            """
            SELECT market, side, si_score, sportsbook,
                   clv_points, clv_probability, clv_percent
            FROM recommendation_snapshots
            WHERE closing_status = 'AVAILABLE'
            """
        ).fetchall()
        con.close()
    except Exception:
        return empty

    captured = status_map.get("AVAILABLE", 0)
    pending  = status_map.get("PENDING",   0)
    missing  = status_map.get("NOT_CAPTURED", 0)

    all_clv_pts = [float(r[4]) for r in rows if r[4] is not None]
    avg_clv  = round(sum(all_clv_pts) / len(all_clv_pts), 3) if all_clv_pts else None
    pos_pct  = round(sum(1 for v in all_clv_pts if v > 0) / len(all_clv_pts) * 100, 1) if all_clv_pts else None

    # Group by market
    by_market: Dict[str, list] = {}
    by_si: Dict[str, list] = {}
    by_book: Dict[str, list] = {}
    for market, side, si, book, clv_pts, _, _ in rows:
        if clv_pts is None:
            continue
        by_market.setdefault(market or "unknown", []).append(clv_pts)
        si_band = _si_band(si)
        by_si.setdefault(si_band, []).append(clv_pts)
        by_book.setdefault(book or "unknown", []).append(clv_pts)

    def _summarise(d: Dict[str, list]) -> List[Dict[str, Any]]:
        return [
            {"label": k, "averageCLV": round(sum(v) / len(v), 3), "count": len(v)}
            for k, v in sorted(d.items())
        ]

    return {
        "closingLinesCaptured": captured,
        "pendingClosingLines":  pending,
        "missingClosingLines":  missing,
        "averageCLVPoints":     avg_clv,
        "positiveCLVPercent":   pos_pct,
        "clvByMarket":          _summarise(by_market),
        "clvBySiScoreBand":     _summarise(by_si),
        "clvBySportsbook":      _summarise(by_book),
    }


def _si_band(si: Optional[float]) -> str:
    if si is None:
        return "Unknown"
    si = float(si)
    if si >= 85:
        return "Elite (85+)"
    if si >= 75:
        return "Strong (75–84)"
    if si >= 65:
        return "Moderate (65–74)"
    return "Speculative (<65)"
