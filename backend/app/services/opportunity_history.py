from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.runtime_paths import runtime_paths

_DB_PATH: Path | None = None


def _is_render_production() -> bool:
    return str(os.getenv("RENDER", "") or "").strip().lower() == "true"


def resolve_history_db_path() -> Path:
    configured = str(os.getenv("OPPORTUNITY_HISTORY_DB_PATH", "") or "").strip()
    if configured:
        raw_path = Path(configured).expanduser()
        candidate = raw_path.resolve() if raw_path.is_absolute() else (Path.cwd() / raw_path).resolve()
    else:
        candidate = (runtime_paths.root.resolve() / "opportunity_history.sqlite3").resolve()

    if _is_render_production():
        try:
            candidate.relative_to(Path("/data"))
        except ValueError as exc:
            raise RuntimeError("Opportunity history path must resolve under /data when RENDER=true") from exc

    return candidate


def _effective_db_path() -> Path:
    if _DB_PATH is not None:
        return Path(_DB_PATH).resolve()
    return resolve_history_db_path()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_market(value: Any) -> str:
    text = _normalize_text(value).lower()
    mapping = {
        "spreads": "spread",
        "spread": "spread",
        "totals": "total",
        "total": "total",
        "h2h": "moneyline",
        "moneyline": "moneyline",
    }
    return mapping.get(text, text)


def canonical_opportunity_key(event_id: str, market: str, side: str) -> str:
    raw = "|".join([
        _normalize_text(event_id),
        _normalize_market(market),
        _normalize_text(side).lower(),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical_quote_key(
    event_id: str,
    market: str,
    side: str,
    sportsbook: Optional[str],
    point: Optional[float],
    price: Optional[float],
    source_snapshot_id: Optional[str] = None,
) -> str:
    raw = "|".join([
        _normalize_text(event_id),
        _normalize_market(market),
        _normalize_text(side).lower(),
        _normalize_text(sportsbook),
        str(point if point is not None else ""),
        str(price if price is not None else ""),
        _normalize_text(source_snapshot_id),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _connect() -> sqlite3.Connection:
    db_path = _effective_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con


def _ensure_schema() -> None:
    con = _connect()
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS opportunity_history (
            history_id TEXT PRIMARY KEY,
            opportunity_key TEXT NOT NULL,
            quote_key TEXT NOT NULL,
            event_id TEXT NOT NULL,
            market TEXT NOT NULL,
            side TEXT NOT NULL,
            sportsbook TEXT,
            point REAL,
            price REAL,
            qualification_status TEXT,
            recommendation TEXT,
            production_eligible INTEGER NOT NULL DEFAULT 0,
            current_state TEXT NOT NULL,
            transition_reason TEXT NOT NULL,
            previous_history_id TEXT,
            source_snapshot_id TEXT,
            observed_at_utc TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            model_version TEXT,
            probability_engine_version TEXT,
            calibration_version TEXT,
            ranking_version TEXT,
            qualification_policy_version TEXT,
            git_commit_hash TEXT,
            provenance_json TEXT
        )
        """
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_opportunity_history_event_time ON opportunity_history(event_id, observed_at_utc DESC)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_opportunity_history_key_time ON opportunity_history(opportunity_key, observed_at_utc DESC)"
    )
    con.commit()
    con.close()


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _derive_current_state(snapshot: Dict[str, Any], previous_row: Optional[sqlite3.Row] = None) -> tuple[str, str]:
    qualification = str(snapshot.get("qualificationStatus") or "").upper()
    recommendation = str(snapshot.get("recommendation") or "").upper()
    production_eligible = bool(snapshot.get("productionEligible"))

    if previous_row is not None:
        previous_qualification = str(previous_row["qualification_status"] or "").upper()
        previous_production = bool(previous_row["production_eligible"])
        previous_recommendation = str(previous_row["recommendation"] or "").upper()

        if previous_qualification == "QUALIFIED" and qualification != "QUALIFIED":
            return "NO_LONGER_QUALIFIED", "QUALIFIED_TO_NO_LONGER_QUALIFIED"
        if previous_qualification != "QUALIFIED" and qualification == "QUALIFIED":
            return "QUALIFIED", "WATCH_TO_QUALIFIED"
        if previous_qualification == "QUALIFIED" and qualification == "QUALIFIED":
            if previous_production != production_eligible or previous_recommendation != recommendation:
                return "QUALIFIED", "QUALIFIED_RESTATED"
            return "QUALIFIED", "UNCHANGED"
        if qualification == "NOT_QUALIFIED" and previous_qualification == "QUALIFIED":
            return "NO_LONGER_QUALIFIED", "QUALIFIED_TO_NO_LONGER_QUALIFIED"
        if recommendation in {"WATCH", "LEAN"} or not production_eligible:
            return "WATCH", "WATCH_STATE"
        if previous_recommendation in {"WATCH", "LEAN"} and recommendation not in {"WATCH", "LEAN"}:
            return "QUALIFIED", "WATCH_TO_QUALIFIED"
        return "WATCH", "WATCH_STATE"

    if qualification == "QUALIFIED" or "STRONG" in recommendation or "BET" in recommendation:
        return "QUALIFIED", "NO_PRIOR_STATE"
    if recommendation.startswith("PASS") or qualification == "NOT_QUALIFIED":
        return "NO_LONGER_QUALIFIED", "NO_PRIOR_STATE"
    return "WATCH", "NO_PRIOR_STATE"


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    payload = {
        "historyId": row["history_id"],
        "opportunityKey": row["opportunity_key"],
        "quoteKey": row["quote_key"],
        "eventId": row["event_id"],
        "market": row["market"],
        "side": row["side"],
        "sportsbook": row["sportsbook"],
        "point": row["point"],
        "price": row["price"],
        "qualificationStatus": row["qualification_status"],
        "recommendation": row["recommendation"],
        "productionEligible": bool(row["production_eligible"]),
        "currentState": row["current_state"],
        "transitionReason": row["transition_reason"],
        "previousHistoryId": row["previous_history_id"],
        "sourceSnapshotId": row["source_snapshot_id"],
        "observedAtUTC": row["observed_at_utc"],
        "createdAtUTC": row["created_at_utc"],
        "modelVersion": row["model_version"],
        "probabilityEngineVersion": row["probability_engine_version"],
        "calibrationVersion": row["calibration_version"],
        "rankingVersion": row["ranking_version"],
        "qualificationPolicyVersion": row["qualification_policy_version"],
        "gitCommitHash": row["git_commit_hash"],
        "provenance": json.loads(row["provenance_json"]) if row["provenance_json"] else {},
        "previousSnapshotAvailable": row["previous_history_id"] is not None,
        "idempotent": False,
    }
    return payload


def build_history_snapshot_from_opportunity(opportunity: Dict[str, Any], *, source_snapshot_id: str, observed_at_utc: str | None = None) -> Dict[str, Any]:
    if not opportunity:
        raise ValueError("opportunity is required to build history")
    if not source_snapshot_id:
        raise ValueError("source_snapshot_id is required to build history")

    event_id = _normalize_text(opportunity.get("eventId"))
    market = _normalize_market(opportunity.get("market"))
    side = _normalize_text(opportunity.get("side")).lower()
    if not event_id or not market or not side:
        raise ValueError("eventId, market, and side are required to build history from an opportunity")

    return {
        "eventId": event_id,
        "market": market,
        "side": side,
        "sportsbook": _normalize_text(opportunity.get("sportsbook") or opportunity.get("book") or opportunity.get("marketProvider")) or None,
        "point": _coerce_float(opportunity.get("point")),
        "price": _coerce_float(opportunity.get("price")),
        "qualificationStatus": _normalize_text(opportunity.get("qualificationStatus")) or None,
        "recommendation": _normalize_text(opportunity.get("recommendation")) or None,
        "productionEligible": bool(opportunity.get("productionEligible")),
        "sourceSnapshotId": _normalize_text(source_snapshot_id),
        "observedAtUTC": _normalize_text(observed_at_utc or opportunity.get("snapshotTimestamp") or opportunity.get("marketLastUpdated") or _utc_now_iso()),
        "modelVersion": opportunity.get("modelVersion"),
        "probabilityEngineVersion": opportunity.get("probabilityEngineVersion"),
        "calibrationVersion": opportunity.get("calibrationVersion"),
        "rankingVersion": opportunity.get("rankingVersion") or settings.DEFAULT_RANKING_VERSION,
        "qualificationPolicyVersion": opportunity.get("qualificationPolicyVersion") or settings.DEFAULT_QUALIFICATION_POLICY_VERSION,
        "gitCommitHash": opportunity.get("gitCommitHash"),
    }


def record_history_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_schema()
    event_id = _normalize_text(snapshot.get("eventId"))
    market = _normalize_market(snapshot.get("market"))
    side = _normalize_text(snapshot.get("side")).lower()
    if not event_id or not market or not side:
        raise ValueError("eventId, market, and side are required to record opportunity history")

    source_snapshot_id = _normalize_text(snapshot.get("sourceSnapshotId") or snapshot.get("snapshotId"))
    sportsbook = _normalize_text(snapshot.get("sportsbook"))
    point = _coerce_float(snapshot.get("point"))
    price = _coerce_float(snapshot.get("price"))
    qualification_status = _normalize_text(snapshot.get("qualificationStatus")) or None
    recommendation = _normalize_text(snapshot.get("recommendation")) or None
    production_eligible = bool(snapshot.get("productionEligible"))

    opportunity_key = canonical_opportunity_key(event_id, market, side)
    quote_key = canonical_quote_key(event_id, market, side, sportsbook, point, price, source_snapshot_id)

    con = _connect()
    baseline = None
    if source_snapshot_id:
        baseline = con.execute(
            "SELECT * FROM opportunity_history WHERE opportunity_key = ? AND source_snapshot_id = ? ORDER BY observed_at_utc DESC, created_at_utc DESC, history_id DESC LIMIT 1",
            [opportunity_key, source_snapshot_id],
        ).fetchone()
    else:
        baseline = con.execute(
            "SELECT * FROM opportunity_history WHERE opportunity_key = ? AND quote_key = ? ORDER BY observed_at_utc DESC, created_at_utc DESC, history_id DESC LIMIT 1",
            [opportunity_key, quote_key],
        ).fetchone()

    if baseline is not None:
        current_signature = json.dumps({
            "quoteKey": quote_key,
            "point": point,
            "price": price,
            "sportsbook": sportsbook,
            "qualificationStatus": qualification_status,
            "recommendation": recommendation,
            "productionEligible": int(production_eligible),
            "modelVersion": snapshot.get("modelVersion"),
            "probabilityEngineVersion": snapshot.get("probabilityEngineVersion"),
            "calibrationVersion": snapshot.get("calibrationVersion"),
            "rankingVersion": snapshot.get("rankingVersion"),
            "qualificationPolicyVersion": snapshot.get("qualificationPolicyVersion"),
            "gitCommitHash": snapshot.get("gitCommitHash"),
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        prior_signature = json.dumps({
            "quoteKey": baseline["quote_key"],
            "point": baseline["point"],
            "price": baseline["price"],
            "sportsbook": baseline["sportsbook"],
            "qualificationStatus": baseline["qualification_status"],
            "recommendation": baseline["recommendation"],
            "productionEligible": baseline["production_eligible"],
            "modelVersion": baseline["model_version"],
            "probabilityEngineVersion": baseline["probability_engine_version"],
            "calibrationVersion": baseline["calibration_version"],
            "rankingVersion": baseline["ranking_version"],
            "qualificationPolicyVersion": baseline["qualification_policy_version"],
            "gitCommitHash": baseline["git_commit_hash"],
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        if current_signature == prior_signature:
            payload = _row_to_dict(baseline)
            payload["idempotent"] = True
            con.close()
            return payload

    previous_row = con.execute(
        "SELECT * FROM opportunity_history WHERE opportunity_key = ? ORDER BY observed_at_utc DESC, created_at_utc DESC, history_id DESC LIMIT 1",
        [opportunity_key],
    ).fetchone()

    current_state, transition_reason = _derive_current_state(snapshot, previous_row)
    previous_history_id = previous_row["history_id"] if previous_row is not None else None
    observed_at_utc = _normalize_text(snapshot.get("observedAtUTC") or snapshot.get("observed_at_utc") or _utc_now_iso())
    history_id = str(uuid.uuid4())

    provenance = {
        "modelVersion": snapshot.get("modelVersion"),
        "probabilityEngineVersion": snapshot.get("probabilityEngineVersion"),
        "calibrationVersion": snapshot.get("calibrationVersion"),
        "rankingVersion": snapshot.get("rankingVersion"),
        "qualificationPolicyVersion": snapshot.get("qualificationPolicyVersion"),
        "gitCommitHash": snapshot.get("gitCommitHash"),
    }
    provenance_json = json.dumps(provenance, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    con.execute(
        """
        INSERT INTO opportunity_history (
            history_id,
            opportunity_key,
            quote_key,
            event_id,
            market,
            side,
            sportsbook,
            point,
            price,
            qualification_status,
            recommendation,
            production_eligible,
            current_state,
            transition_reason,
            previous_history_id,
            source_snapshot_id,
            observed_at_utc,
            created_at_utc,
            model_version,
            probability_engine_version,
            calibration_version,
            ranking_version,
            qualification_policy_version,
            git_commit_hash,
            provenance_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            history_id,
            opportunity_key,
            quote_key,
            event_id,
            market,
            side,
            sportsbook or None,
            point,
            price,
            qualification_status,
            recommendation,
            int(production_eligible),
            current_state,
            transition_reason,
            previous_history_id,
            source_snapshot_id or None,
            observed_at_utc,
            _utc_now_iso(),
            snapshot.get("modelVersion"),
            snapshot.get("probabilityEngineVersion"),
            snapshot.get("calibrationVersion"),
            snapshot.get("rankingVersion"),
            snapshot.get("qualificationPolicyVersion"),
            snapshot.get("gitCommitHash"),
            provenance_json,
        ],
    )
    con.commit()
    inserted = con.execute("SELECT * FROM opportunity_history WHERE history_id = ?", [history_id]).fetchone()
    con.close()
    payload = _row_to_dict(inserted)
    payload["previousSnapshotAvailable"] = previous_row is not None
    payload["previousHistoryId"] = previous_history_id
    return payload


def read_history_for_event(event_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    _ensure_schema()
    con = _connect()
    rows = con.execute(
        "SELECT * FROM opportunity_history WHERE event_id = ? ORDER BY observed_at_utc DESC, created_at_utc DESC, history_id DESC LIMIT ?",
        [event_id, max(1, int(limit))],
    ).fetchall()
    con.close()
    return [_row_to_dict(row) for row in rows]


def latest_history_for_opportunity(event_id: str, market: str, side: str) -> Optional[Dict[str, Any]]:
    _ensure_schema()
    key = canonical_opportunity_key(event_id, market, side)
    con = _connect()
    row = con.execute(
        "SELECT * FROM opportunity_history WHERE opportunity_key = ? ORDER BY observed_at_utc DESC, created_at_utc DESC, history_id DESC LIMIT 1",
        [key],
    ).fetchone()
    con.close()
    if row is None:
        return None
    return _row_to_dict(row)


def latest_history_before_snapshot(event_id: str, market: str, side: str, source_snapshot_id: str) -> Optional[Dict[str, Any]]:
    _ensure_schema()
    key = canonical_opportunity_key(event_id, market, side)
    con = _connect()
    row = con.execute(
        "SELECT * FROM opportunity_history WHERE opportunity_key = ? AND source_snapshot_id != ? ORDER BY observed_at_utc DESC, created_at_utc DESC, history_id DESC LIMIT 1",
        [key, _normalize_text(source_snapshot_id)],
    ).fetchone()
    con.close()
    if row is None:
        return None
    return _row_to_dict(row)
