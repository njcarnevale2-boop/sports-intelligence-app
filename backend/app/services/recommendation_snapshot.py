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
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.runtime_paths import runtime_paths
from app.services.closing_line import calculate_clv, get_closing_line
from app.services.sportsbook_policy import resolve_closing_provider_key


log = logging.getLogger("recommendation_snapshot")

_DB_PATH = runtime_paths.nfl_model_duckdb
_SCHEDULE_CSV = runtime_paths.current_game_projections_csv
_CLOSING_CUTOFF_MINUTES = int(os.getenv("CLOSING_LINE_CUTOFF_MINUTES", "2"))
_CLOSING_MAX_QUOTE_AGE_MINUTES = int(os.getenv("CLOSING_MAX_QUOTE_AGE_MINUTES", "120"))
_CLOSING_RESOLUTION_VERSION = "sia_closing_v3a4"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendation_snapshots (
    snapshot_id        VARCHAR PRIMARY KEY,
    season             INTEGER,
    week               INTEGER,
    event_id           VARCHAR NOT NULL,
    recommended_at     TIMESTAMP NOT NULL,
    selection          VARCHAR,
    market             VARCHAR NOT NULL,
    side               VARCHAR NOT NULL,
    point              DOUBLE,
    price              DOUBLE,
    sportsbook         VARCHAR,
    sportsbook_provider_key VARCHAR,
    quote_timestamp    TIMESTAMP,
    market_timestamp   TIMESTAMP,
    si_score           DOUBLE,
    model_probability  DOUBLE,
    raw_model_probability DOUBLE,
    calibrated_probability DOUBLE,
    push_probability   DOUBLE,
    loss_probability   DOUBLE,
    implied_probability DOUBLE,
    market_no_vig_probability DOUBLE,
    edge_pp            DOUBLE,
    raw_edge           DOUBLE,
    calibrated_edge    DOUBLE,
    ev_per_dollar      DOUBLE,
    full_kelly_fraction DOUBLE,
    fractional_kelly_fraction DOUBLE,
    bankroll_percent   DOUBLE,
    recommended_amount DOUBLE,
    recommended_units  DOUBLE,
    unit_size_at_bet   DOUBLE,
    bankroll_basis     DOUBLE,
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
    closing_reason_code VARCHAR,
    closing_boundary_used_at TIMESTAMP,
    closing_resolution_version VARCHAR,
    clv_points         DOUBLE,
    clv_probability    DOUBLE,
    clv_percent        DOUBLE,
    model_version      VARCHAR,
    probability_engine_version VARCHAR,
    calibration_version VARCHAR,
    ranking_version    VARCHAR,
    qualification_policy_version VARCHAR,
    model_timestamp    TIMESTAMP,
    decision_id        VARCHAR
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
    existing_columns = {
        str(row[1])
        for row in con.execute("PRAGMA table_info('recommendation_snapshots')").fetchall()
    }
    required_columns = {
        "season": "INTEGER",
        "week": "INTEGER",
        "selection": "VARCHAR",
        "quote_timestamp": "TIMESTAMP",
        "market_timestamp": "TIMESTAMP",
        "sportsbook_provider_key": "VARCHAR",
        "raw_model_probability": "DOUBLE",
        "calibrated_probability": "DOUBLE",
        "push_probability": "DOUBLE",
        "loss_probability": "DOUBLE",
        "implied_probability": "DOUBLE",
        "market_no_vig_probability": "DOUBLE",
        "raw_edge": "DOUBLE",
        "calibrated_edge": "DOUBLE",
        "full_kelly_fraction": "DOUBLE",
        "fractional_kelly_fraction": "DOUBLE",
        "bankroll_percent": "DOUBLE",
        "recommended_amount": "DOUBLE",
        "recommended_units": "DOUBLE",
        "unit_size_at_bet": "DOUBLE",
        "bankroll_basis": "DOUBLE",
        "model_version": "VARCHAR",
        "probability_engine_version": "VARCHAR",
        "calibration_version": "VARCHAR",
        "ranking_version": "VARCHAR",
        "qualification_policy_version": "VARCHAR",
        "model_timestamp": "TIMESTAMP",
        "decision_id": "VARCHAR",
        "closing_reason_code": "VARCHAR",
        "closing_boundary_used_at": "TIMESTAMP",
        "closing_resolution_version": "VARCHAR",
    }
    for name, sql_type in required_columns.items():
        if name in existing_columns:
            continue
        con.execute(f"ALTER TABLE recommendation_snapshots ADD COLUMN {name} {sql_type}")
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


def _normalize_snapshot_id_seed(payload: Dict[str, Any]) -> Dict[str, Any]:
    def _normalize_probability(value: Any) -> float | None:
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if parsed > 1.0:
            parsed = parsed / 100.0
        return max(0.0, min(1.0, parsed))

    def _normalize_edge(value: Any) -> float | None:
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if parsed > 1.0 or parsed < -1.0:
            parsed = parsed / 100.0
        return parsed

    def _normalize_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return {
        "season": payload.get("season"),
        "week": payload.get("week"),
        "eventId": payload.get("eventId"),
        "commenceTime": payload.get("commenceTime"),
        "market": payload.get("market"),
        "side": payload.get("side"),
        "point": payload.get("point"),
        "price": payload.get("price"),
        "sportsbook": payload.get("sportsbook"),
        "selection": payload.get("selection"),
        "rawModelProbability": _normalize_probability(payload.get("rawModelProbability")),
        "calibratedProbability": _normalize_probability(payload.get("calibratedProbability")),
        "pushProbability": _normalize_probability(payload.get("pushProbability")),
        "lossProbability": _normalize_probability(payload.get("lossProbability")),
        "evPerDollar": _normalize_float(payload.get("evPerDollar")),
        "rawEdge": _normalize_edge(payload.get("rawEdge")),
        "calibratedEdge": _normalize_edge(payload.get("calibratedEdge")),
        "recommendedAmount": _normalize_float(payload.get("recommendedAmount")),
        "recommendedUnits": _normalize_float(payload.get("recommendedUnits")),
        "bankrollPercent": _normalize_float(payload.get("bankrollPercent")),
        "fullKellyFraction": _normalize_float(payload.get("fullKellyFraction")),
        "fractionalKellyFraction": _normalize_float(payload.get("fractionalKellyFraction")),
        "unitSizeAtBet": _normalize_float(payload.get("unitSizeAtBet")),
        "bankrollBasis": _normalize_float(payload.get("bankrollBasis")),
        "modelVersion": payload.get("modelVersion"),
        "probabilityEngineVersion": payload.get("probabilityEngineVersion"),
        "calibrationVersion": payload.get("calibrationVersion"),
        "rankingVersion": payload.get("rankingVersion"),
        "qualificationPolicyVersion": payload.get("qualificationPolicyVersion"),
        "modelTimestamp": payload.get("modelTimestamp"),
        "marketTimestamp": payload.get("marketTimestamp"),
        "quoteTimestamp": payload.get("quoteTimestamp"),
    }


def _normalize_snapshot_market(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"SPREAD", "SPREADS"}:
        return "SPREAD"
    if text in {"TOTAL", "TOTALS"}:
        return "TOTAL"
    if text in {"MONEYLINE", "H2H"}:
        return "MONEYLINE"
    return text


def _normalize_snapshot_side(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"HOME", "AWAY", "OVER", "UNDER"}:
        return text
    return text


def build_snapshot_id(payload: Dict[str, Any]) -> str:
    """Deterministic id for idempotent Add-to-My-Card tracking writes."""
    seed = _normalize_snapshot_id_seed(payload)
    canonical = json.dumps(seed, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, canonical))


def snapshot_exists(snapshot_id: str) -> bool:
    _ensure_schema()
    if not _DB_PATH.exists() or not snapshot_id:
        return False
    try:
        con = _open_db(read_only=True)
        row = con.execute(
            "SELECT COUNT(*) FROM recommendation_snapshots WHERE snapshot_id = ?",
            [snapshot_id],
        ).fetchone()
        con.close()
        return bool(row and int(row[0]) > 0)
    except Exception:
        return False


def link_snapshot_decision(snapshot_id: str, decision_id: str) -> bool:
    """Safely link snapshot to canonical decision without allowing linkage switches."""
    _ensure_schema()
    if not _DB_PATH.exists() or not snapshot_id or not decision_id:
        return False
    con = _open_db()
    try:
        row = con.execute(
            "SELECT decision_id FROM recommendation_snapshots WHERE snapshot_id = ?",
            [snapshot_id],
        ).fetchone()
        if row is None:
            return False

        existing = row[0]
        if existing is not None and str(existing).strip():
            if str(existing) == str(decision_id):
                return True
            raise ValueError("Snapshot decision linkage conflict")

        con.execute(
            "UPDATE recommendation_snapshots SET decision_id = ? WHERE snapshot_id = ?",
            [decision_id, snapshot_id],
        )
        return True
    finally:
        con.close()


def delete_snapshot(snapshot_id: str) -> bool:
    _ensure_schema()
    if not _DB_PATH.exists() or not snapshot_id:
        return False
    try:
        con = _open_db()
        existed = con.execute(
            "SELECT COUNT(*) FROM recommendation_snapshots WHERE snapshot_id = ?",
            [snapshot_id],
        ).fetchone()
        if not existed or int(existed[0]) == 0:
            con.close()
            return False
        con.execute(
            "DELETE FROM recommendation_snapshots WHERE snapshot_id = ?",
            [snapshot_id],
        )
        con.close()
        return True
    except Exception:
        return False


# ── public write ─────────────────────────────────────────────────────────────

def store_snapshot(payload: Dict[str, Any]) -> str:
    """Write an immutable recommendation snapshot.  Returns snapshot_id."""
    _ensure_schema()
    if not _DB_PATH.exists():
        return ""

    snapshot_id = build_snapshot_id(payload)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    normalized_market = _normalize_snapshot_market(payload.get("market"))
    normalized_side = _normalize_snapshot_side(payload.get("side"))
    sportsbook_provider_key = payload.get("sportsbookProviderKey")
    if not sportsbook_provider_key:
        resolved_closing_mapping = resolve_closing_provider_key(payload.get("sportsbook"))
        sportsbook_provider_key = resolved_closing_mapping.get("providerKey")

    values = [
        snapshot_id,
        payload.get("season"),
        payload.get("week"),
        payload.get("eventId", ""),
        now,
        payload.get("selection"),
        normalized_market,
        normalized_side,
        payload.get("point"),
        payload.get("price"),
        payload.get("sportsbook"),
        sportsbook_provider_key,
        payload.get("quoteTimestamp"),
        payload.get("marketTimestamp"),
        payload.get("siScore"),
        payload.get("modelProbability"),
        payload.get("rawModelProbability"),
        payload.get("calibratedProbability"),
        payload.get("pushProbability"),
        payload.get("lossProbability"),
        payload.get("impliedProbability"),
        payload.get("marketNoVigProbability"),
        payload.get("edge"),
        payload.get("rawEdge"),
        payload.get("calibratedEdge"),
        payload.get("evPerDollar"),
        payload.get("fullKellyFraction"),
        payload.get("fractionalKellyFraction"),
        payload.get("bankrollPercent"),
        payload.get("recommendedAmount"),
        payload.get("recommendedUnits"),
        payload.get("unitSizeAtBet"),
        payload.get("bankrollBasis"),
        json.dumps(payload.get("marketIntelligence") or {}),
        json.dumps(payload.get("injuryContext") or {}),
        json.dumps(payload.get("weatherContext") or {}),
        payload.get("commenceTime"),
        payload.get("homeTeam"),
        payload.get("awayTeam"),
        "PENDING",
        None,
        None,
        None,
        payload.get("modelVersion"),
        payload.get("probabilityEngineVersion"),
        payload.get("calibrationVersion"),
        payload.get("rankingVersion"),
        payload.get("qualificationPolicyVersion"),
        payload.get("modelTimestamp"),
        None,
    ]

    con = _open_db()
    con.execute(
        f"""
        INSERT OR IGNORE INTO recommendation_snapshots
        (snapshot_id, season, week, event_id, recommended_at, selection, market, side, point, price,
         sportsbook, sportsbook_provider_key, quote_timestamp, market_timestamp, si_score, model_probability,
         raw_model_probability, calibrated_probability, push_probability, loss_probability,
         implied_probability, market_no_vig_probability,
         edge_pp, raw_edge, calibrated_edge, ev_per_dollar,
         full_kelly_fraction, fractional_kelly_fraction, bankroll_percent,
         recommended_amount, recommended_units, unit_size_at_bet, bankroll_basis,
         market_intelligence, injury_context, weather_context,
         commence_time, home_team, away_team, closing_status,
         closing_reason_code, closing_boundary_used_at, closing_resolution_version,
         model_version, probability_engine_version, calibration_version,
         ranking_version, qualification_policy_version, model_timestamp, decision_id)
        VALUES ({','.join(['?'] * len(values))})
        """,
        values,
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
            "SELECT snapshot_id, event_id, market, side, point, price, sportsbook, sportsbook_provider_key, commence_time, closing_status "
            "FROM recommendation_snapshots "
            "WHERE closing_status IN ('PENDING', 'AWAITING_FINALIZATION', 'ERROR')"
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
        snap_id, event_id, market, side, rec_point, rec_price, sportsbook, sportsbook_provider_key, commence_raw, closing_status = row

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

        if kickoff is None:
            _update_closing(snap_id, status="ERROR", reason_code="MISSING_KICKOFF", resolution_version=_CLOSING_RESOLUTION_VERSION)
            errors += 1
            continue

        boundary_naive = (kickoff - timedelta(minutes=_CLOSING_CUTOFF_MINUTES))

        if now_naive < boundary_naive:
            if str(closing_status or "") != "PENDING":
                _update_closing(
                    snap_id,
                    status="PENDING",
                    reason_code="PRE_BOUNDARY",
                    boundary_used_at=boundary_naive,
                    resolution_version=_CLOSING_RESOLUTION_VERSION,
                )
            still_pending += 1
            continue

        if str(closing_status or "") == "PENDING":
            _update_closing(
                snap_id,
                status="AWAITING_FINALIZATION",
                reason_code="BOUNDARY_REACHED",
                boundary_used_at=boundary_naive,
                resolution_version=_CLOSING_RESOLUTION_VERSION,
            )

        # Game has kicked off – attempt closing line capture
        eligible += 1

        try:
            kickoff_aware = kickoff.replace(tzinfo=timezone.utc)
            provider_key = str(sportsbook_provider_key or "").strip()
            if not provider_key:
                _update_closing(
                    snap_id,
                    status="MAPPING_BLOCKED",
                    reason_code="UNVERIFIED_PROVIDER_MAPPING",
                    boundary_used_at=boundary_naive,
                    resolution_version=_CLOSING_RESOLUTION_VERSION,
                )
                missing += 1
                continue

            closing = get_closing_line(
                event_id=event_id,
                bookmaker_key=provider_key,
                market_key=market,
                outcome_code=side,
                kickoff_utc=kickoff_aware,
                closing_max_quote_age_minutes=_CLOSING_MAX_QUOTE_AGE_MINUTES,
            )

            if closing.closing_status != "CAPTURED":
                missing += 1
                status = "UNAVAILABLE"
                if closing.closing_status == "ERROR":
                    status = "ERROR"
                    errors += 1
                elif closing.closing_status == "PENDING":
                    status = "PENDING"
                elif closing.closing_status == "AWAITING_FINALIZATION":
                    status = "AWAITING_FINALIZATION"
                    still_pending += 1

                _update_closing(
                    snap_id,
                    status=status,
                    reason_code=closing.closing_reason_code,
                    boundary_used_at=boundary_naive,
                    resolution_version=_CLOSING_RESOLUTION_VERSION,
                )
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
                    closing_status     = 'CAPTURED',
                    closing_point      = ?,
                    closing_price      = ?,
                    closing_sportsbook = ?,
                    closing_at         = ?,
                    closing_reason_code = ?,
                    closing_boundary_used_at = ?,
                    closing_resolution_version = ?,
                    clv_points         = ?,
                    clv_probability    = ?,
                    clv_percent        = ?
                WHERE snapshot_id = ?
                """,
                [
                    closing.closing_point,
                    closing.closing_price,
                    closing.closing_sportsbook or sportsbook,
                    closing_ts,
                    closing.closing_reason_code,
                    boundary_naive,
                    _CLOSING_RESOLUTION_VERSION,
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
            _update_closing(
                snap_id,
                status="ERROR",
                reason_code="CAPTURE_EXCEPTION",
                boundary_used_at=boundary_naive,
                resolution_version=_CLOSING_RESOLUTION_VERSION,
            )
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
    _update_closing(snapshot_id, status=status)


def _update_closing(
    snapshot_id: str,
    *,
    status: str,
    reason_code: Optional[str] = None,
    boundary_used_at: Optional[datetime] = None,
    resolution_version: Optional[str] = None,
) -> None:
    con = _open_db()
    con.execute(
        """
        UPDATE recommendation_snapshots
        SET closing_status = ?,
            closing_reason_code = ?,
            closing_boundary_used_at = COALESCE(?, closing_boundary_used_at),
            closing_resolution_version = COALESCE(?, closing_resolution_version)
        WHERE snapshot_id = ?
        """,
        [status, reason_code, boundary_used_at, resolution_version, snapshot_id],
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
                     closing_reason_code, closing_boundary_used_at, closing_resolution_version,
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
        "closingReasonCode", "closingBoundaryUsedAt", "closingResolutionVersion",
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
            WHERE closing_status IN ('CAPTURED', 'AVAILABLE')
            """
        ).fetchall()
        con.close()
    except Exception:
        return empty

    captured = status_map.get("CAPTURED", 0) + status_map.get("AVAILABLE", 0)
    pending  = status_map.get("PENDING", 0) + status_map.get("AWAITING_FINALIZATION", 0) + status_map.get("ERROR", 0)
    missing  = status_map.get("UNAVAILABLE", 0) + status_map.get("NOT_CAPTURED", 0) + status_map.get("MAPPING_BLOCKED", 0)

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
