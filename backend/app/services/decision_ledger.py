from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.closing_line import calculate_clv, get_closing_line
from app.services.market_data import market_data_service, normalize_market, normalize_side


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _resolve_db_path() -> Path:
    raw = settings.DATABASE_URL
    if raw.startswith("sqlite:///"):
        rel = raw.removeprefix("sqlite:///")
        return (Path.cwd() / rel).resolve()
    return (Path.cwd() / "sports_intelligence.db").resolve()


_DB_PATH = _resolve_db_path()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS decision_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL UNIQUE,
    decision_group_id TEXT NOT NULL,
    decision_version INTEGER NOT NULL,
    supersedes_decision_id TEXT,
    publication_type TEXT NOT NULL,
    published_at_utc TEXT NOT NULL,

    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    event_id TEXT NOT NULL,
    commence_time TEXT,

    away_team TEXT,
    home_team TEXT,

    selection TEXT,
    market TEXT,
    side TEXT,
    point REAL,
    price REAL,
    sportsbook TEXT,

    raw_probability REAL,
    calibrated_probability REAL,
    push_probability REAL,
    loss_probability REAL,

    raw_edge REAL,
    calibrated_edge REAL,
    current_ev REAL,

    fair_line REAL,
    true_playable_to REAL,
    true_playable_to_status TEXT,

    si_score REAL,
    si_grade TEXT,
    si_rank INTEGER,

    recommendation TEXT,
    qualification_status TEXT,
    qualification_reasons TEXT,

    model_version TEXT,
    probability_engine_version TEXT,
    calibration_version TEXT,
    si_score_version TEXT,
    ranking_version TEXT,
    qualification_policy_version TEXT,
    git_commit_hash TEXT,

    odds_provider TEXT,
    odds_timestamp TEXT,
    model_timestamp TEXT,
    market_timestamp TEXT,

    source_snapshot_id TEXT,

    payload_hash TEXT NOT NULL,
    canonical_payload TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    recorded_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decision_group ON decision_ledger(decision_group_id);
CREATE INDEX IF NOT EXISTS idx_decision_week ON decision_ledger(season, week);
CREATE INDEX IF NOT EXISTS idx_decision_payload_hash ON decision_ledger(payload_hash);

CREATE TABLE IF NOT EXISTS sia3_publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    publication_id TEXT NOT NULL UNIQUE,
    publication_type TEXT NOT NULL,
    published_at_utc TEXT NOT NULL,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    is_official INTEGER NOT NULL DEFAULT 0,
    official_cadence TEXT,
    qualified_pick_count INTEGER NOT NULL,
    payload_hash TEXT NOT NULL,
    canonical_payload TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    recorded_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sia3_publication_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    publication_id TEXT NOT NULL,
    slot_rank INTEGER NOT NULL,
    decision_id TEXT,
    slot_label TEXT,
    qualification_status TEXT,
    FOREIGN KEY(publication_id) REFERENCES sia3_publications(publication_id),
    UNIQUE(publication_id, slot_rank)
);

CREATE INDEX IF NOT EXISTS idx_sia3_publications_week ON sia3_publications(season, week, is_official);

CREATE TABLE IF NOT EXISTS decision_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_id TEXT NOT NULL UNIQUE,
    decision_id TEXT NOT NULL,
    captured_at_utc TEXT NOT NULL,

    closing_line REAL,
    closing_price REAL,
    closing_sportsbook TEXT,
    closing_timestamp TEXT,
    closing_consensus_methodology TEXT,

    clv REAL,
    clv_type TEXT,

    final_away_score INTEGER,
    final_home_score INTEGER,

    bet_result TEXT,
    profit_per_dollar REAL,

    source_snapshot_id TEXT,
    payload_hash TEXT NOT NULL,
    canonical_payload TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    recorded_at_utc TEXT NOT NULL,
    FOREIGN KEY(decision_id) REFERENCES decision_ledger(decision_id)
);

CREATE INDEX IF NOT EXISTS idx_outcome_decision ON decision_outcomes(decision_id);
"""


DECISION_FIELDS = [
    "publishedAtUTC",
    "season",
    "week",
    "eventId",
    "commenceTime",
    "awayTeam",
    "homeTeam",
    "selection",
    "market",
    "side",
    "point",
    "price",
    "sportsbook",
    "rawProbability",
    "calibratedProbability",
    "pushProbability",
    "lossProbability",
    "rawEdge",
    "calibratedEdge",
    "currentEV",
    "fairLine",
    "truePlayableTo",
    "truePlayableToStatus",
    "siScore",
    "siGrade",
    "siRank",
    "recommendation",
    "qualificationStatus",
    "qualificationReasons",
    "modelVersion",
    "probabilityEngineVersion",
    "calibrationVersion",
    "siScoreVersion",
    "rankingVersion",
    "qualificationPolicyVersion",
    "gitCommitHash",
    "oddsProvider",
    "oddsTimestamp",
    "modelTimestamp",
    "marketTimestamp",
    "sourceSnapshotId",
]


def _canonical_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def _ensure_schema() -> None:
    con = _connect()
    con.executescript(_SCHEMA)
    con.commit()
    con.close()


def _default_versions(payload: Dict[str, Any]) -> None:
    payload.setdefault("modelVersion", settings.DEFAULT_MODEL_VERSION)
    payload.setdefault("probabilityEngineVersion", settings.DEFAULT_PROBABILITY_ENGINE_VERSION)
    payload.setdefault("calibrationVersion", settings.DEFAULT_CALIBRATION_VERSION)
    payload.setdefault("siScoreVersion", settings.DEFAULT_SI_SCORE_VERSION)
    payload.setdefault("rankingVersion", settings.DEFAULT_RANKING_VERSION)
    payload.setdefault("qualificationPolicyVersion", settings.DEFAULT_QUALIFICATION_POLICY_VERSION)
    payload.setdefault("gitCommitHash", settings.DEFAULT_GIT_COMMIT_HASH)


def _normalize_decision_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload)
    normalized.setdefault("publishedAtUTC", _utc_now_iso())
    normalized.setdefault("qualificationReasons", [])
    _default_versions(normalized)

    return {field: normalized.get(field) for field in DECISION_FIELDS}


def _decision_group_id(publication_type: str, payload: Dict[str, Any]) -> str:
    key = {
        "publicationType": publication_type,
        "season": payload.get("season"),
        "week": payload.get("week"),
        "eventId": payload.get("eventId"),
        "market": payload.get("market"),
        "side": payload.get("side"),
        "selection": payload.get("selection"),
    }
    return _sha256(_canonical_json(key))


def _row_to_decision(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "decisionId": row["decision_id"],
        "decisionVersion": row["decision_version"],
        "supersedesDecisionId": row["supersedes_decision_id"],
        "publicationType": row["publication_type"],
        "publishedAtUTC": row["published_at_utc"],
        "season": row["season"],
        "week": row["week"],
        "eventId": row["event_id"],
        "commenceTime": row["commence_time"],
        "awayTeam": row["away_team"],
        "homeTeam": row["home_team"],
        "selection": row["selection"],
        "market": row["market"],
        "side": row["side"],
        "point": row["point"],
        "price": row["price"],
        "sportsbook": row["sportsbook"],
        "rawProbability": row["raw_probability"],
        "calibratedProbability": row["calibrated_probability"],
        "pushProbability": row["push_probability"],
        "lossProbability": row["loss_probability"],
        "rawEdge": row["raw_edge"],
        "calibratedEdge": row["calibrated_edge"],
        "currentEV": row["current_ev"],
        "fairLine": row["fair_line"],
        "truePlayableTo": row["true_playable_to"],
        "truePlayableToStatus": row["true_playable_to_status"],
        "siScore": row["si_score"],
        "siGrade": row["si_grade"],
        "siRank": row["si_rank"],
        "recommendation": row["recommendation"],
        "qualificationStatus": row["qualification_status"],
        "qualificationReasons": json.loads(row["qualification_reasons"] or "[]"),
        "modelVersion": row["model_version"],
        "probabilityEngineVersion": row["probability_engine_version"],
        "calibrationVersion": row["calibration_version"],
        "siScoreVersion": row["si_score_version"],
        "rankingVersion": row["ranking_version"],
        "qualificationPolicyVersion": row["qualification_policy_version"],
        "gitCommitHash": row["git_commit_hash"],
        "oddsProvider": row["odds_provider"],
        "oddsTimestamp": row["odds_timestamp"],
        "modelTimestamp": row["model_timestamp"],
        "marketTimestamp": row["market_timestamp"],
        "sourceSnapshotId": row["source_snapshot_id"],
        "payloadHash": row["payload_hash"],
        "recordedAtUTC": row["recorded_at_utc"],
    }


def _payload_from_decision_row(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "publishedAtUTC": row["published_at_utc"],
        "season": row["season"],
        "week": row["week"],
        "eventId": row["event_id"],
        "commenceTime": row["commence_time"],
        "awayTeam": row["away_team"],
        "homeTeam": row["home_team"],
        "selection": row["selection"],
        "market": row["market"],
        "side": row["side"],
        "point": row["point"],
        "price": row["price"],
        "sportsbook": row["sportsbook"],
        "rawProbability": row["raw_probability"],
        "calibratedProbability": row["calibrated_probability"],
        "pushProbability": row["push_probability"],
        "lossProbability": row["loss_probability"],
        "rawEdge": row["raw_edge"],
        "calibratedEdge": row["calibrated_edge"],
        "currentEV": row["current_ev"],
        "fairLine": row["fair_line"],
        "truePlayableTo": row["true_playable_to"],
        "truePlayableToStatus": row["true_playable_to_status"],
        "siScore": row["si_score"],
        "siGrade": row["si_grade"],
        "siRank": row["si_rank"],
        "recommendation": row["recommendation"],
        "qualificationStatus": row["qualification_status"],
        "qualificationReasons": json.loads(row["qualification_reasons"] or "[]"),
        "modelVersion": row["model_version"],
        "probabilityEngineVersion": row["probability_engine_version"],
        "calibrationVersion": row["calibration_version"],
        "siScoreVersion": row["si_score_version"],
        "rankingVersion": row["ranking_version"],
        "qualificationPolicyVersion": row["qualification_policy_version"],
        "gitCommitHash": row["git_commit_hash"],
        "oddsProvider": row["odds_provider"],
        "oddsTimestamp": row["odds_timestamp"],
        "modelTimestamp": row["model_timestamp"],
        "marketTimestamp": row["market_timestamp"],
        "sourceSnapshotId": row["source_snapshot_id"],
    }


def record_decision(payload: Dict[str, Any], publication_type: str = "OTHER") -> Dict[str, Any]:
    _ensure_schema()
    normalized = _normalize_decision_payload(payload)

    if normalized.get("season") is None or normalized.get("week") is None or not normalized.get("eventId"):
        raise ValueError("season, week, and eventId are required")

    decision_group_id = _decision_group_id(publication_type, normalized)
    canonical_payload = _canonical_json(normalized)
    payload_hash = _sha256(canonical_payload)
    idempotency_key = _sha256(f"decision:{publication_type}:{decision_group_id}:{payload_hash}")
    decision_id = str(uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key))

    con = _connect()

    existing = con.execute(
        "SELECT * FROM decision_ledger WHERE idempotency_key = ?",
        [idempotency_key],
    ).fetchone()
    if existing is not None:
        con.close()
        out = _row_to_decision(existing)
        out["isLatestDecision"] = _is_latest_decision(existing["decision_id"])
        out["created"] = False
        return out

    previous = con.execute(
        "SELECT * FROM decision_ledger WHERE decision_group_id = ? ORDER BY decision_version DESC, id DESC LIMIT 1",
        [decision_group_id],
    ).fetchone()

    decision_version = 1 if previous is None else int(previous["decision_version"]) + 1
    supersedes_decision_id = None if previous is None else previous["decision_id"]

    con.execute(
        """
        INSERT INTO decision_ledger (
            decision_id, decision_group_id, decision_version, supersedes_decision_id,
            publication_type, published_at_utc,
            season, week, event_id, commence_time,
            away_team, home_team,
            selection, market, side, point, price, sportsbook,
            raw_probability, calibrated_probability, push_probability, loss_probability,
            raw_edge, calibrated_edge, current_ev,
            fair_line, true_playable_to, true_playable_to_status,
            si_score, si_grade, si_rank,
            recommendation, qualification_status, qualification_reasons,
            model_version, probability_engine_version, calibration_version,
            si_score_version, ranking_version, qualification_policy_version, git_commit_hash,
            odds_provider, odds_timestamp, model_timestamp, market_timestamp,
            source_snapshot_id,
            payload_hash, canonical_payload, idempotency_key, recorded_at_utc
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            decision_id,
            decision_group_id,
            decision_version,
            supersedes_decision_id,
            publication_type,
            normalized["publishedAtUTC"],
            int(normalized["season"]),
            int(normalized["week"]),
            normalized["eventId"],
            normalized["commenceTime"],
            normalized["awayTeam"],
            normalized["homeTeam"],
            normalized["selection"],
            normalized["market"],
            normalized["side"],
            normalized["point"],
            normalized["price"],
            normalized["sportsbook"],
            normalized["rawProbability"],
            normalized["calibratedProbability"],
            normalized["pushProbability"],
            normalized["lossProbability"],
            normalized["rawEdge"],
            normalized["calibratedEdge"],
            normalized["currentEV"],
            normalized["fairLine"],
            normalized["truePlayableTo"],
            normalized["truePlayableToStatus"],
            normalized["siScore"],
            normalized["siGrade"],
            normalized["siRank"],
            normalized["recommendation"],
            normalized["qualificationStatus"],
            json.dumps(normalized["qualificationReasons"], ensure_ascii=True),
            normalized["modelVersion"],
            normalized["probabilityEngineVersion"],
            normalized["calibrationVersion"],
            normalized["siScoreVersion"],
            normalized["rankingVersion"],
            normalized["qualificationPolicyVersion"],
            normalized["gitCommitHash"],
            normalized["oddsProvider"],
            normalized["oddsTimestamp"],
            normalized["modelTimestamp"],
            normalized["marketTimestamp"],
            normalized["sourceSnapshotId"],
            payload_hash,
            canonical_payload,
            idempotency_key,
            _utc_now_iso(),
        ],
    )
    con.commit()

    row = con.execute("SELECT * FROM decision_ledger WHERE decision_id = ?", [decision_id]).fetchone()
    con.close()

    out = _row_to_decision(row)
    out["isLatestDecision"] = True
    out["created"] = True
    return out


def _is_latest_decision(decision_id: str) -> bool:
    _ensure_schema()
    con = _connect()
    row = con.execute("SELECT decision_group_id, decision_version FROM decision_ledger WHERE decision_id = ?", [decision_id]).fetchone()
    if row is None:
        con.close()
        return False

    latest = con.execute(
        "SELECT decision_id FROM decision_ledger WHERE decision_group_id = ? ORDER BY decision_version DESC, id DESC LIMIT 1",
        [row["decision_group_id"]],
    ).fetchone()
    con.close()
    return latest is not None and latest["decision_id"] == decision_id


def get_decision(decision_id: str) -> Optional[Dict[str, Any]]:
    _ensure_schema()
    con = _connect()
    row = con.execute("SELECT * FROM decision_ledger WHERE decision_id = ?", [decision_id]).fetchone()
    con.close()
    if row is None:
        return None
    out = _row_to_decision(row)
    out["isLatestDecision"] = _is_latest_decision(decision_id)
    return out


def get_latest_decision_by_snapshot_id(snapshot_id: str) -> Optional[Dict[str, Any]]:
    _ensure_schema()
    value = str(snapshot_id or "").strip()
    if not value:
        return None

    con = _connect()
    row = con.execute(
        """
        SELECT *
        FROM decision_ledger
        WHERE source_snapshot_id = ?
        ORDER BY published_at_utc DESC, id DESC
        LIMIT 1
        """,
        [value],
    ).fetchone()
    con.close()
    if row is None:
        return None
    out = _row_to_decision(row)
    out["isLatestDecision"] = _is_latest_decision(str(row["decision_id"]))
    return out


def list_decisions(
    season: Optional[int] = None,
    week: Optional[int] = None,
    publication_type: Optional[str] = None,
    latest_only: bool = False,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    _ensure_schema()
    where = []
    params: List[Any] = []

    if season is not None:
        where.append("d.season = ?")
        params.append(season)
    if week is not None:
        where.append("d.week = ?")
        params.append(week)
    if publication_type:
        where.append("d.publication_type = ?")
        params.append(publication_type)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    query = f"""
    SELECT d.*,
           CASE WHEN d.decision_id = (
             SELECT d2.decision_id
             FROM decision_ledger d2
             WHERE d2.decision_group_id = d.decision_group_id
             ORDER BY d2.decision_version DESC, d2.id DESC
             LIMIT 1
           ) THEN 1 ELSE 0 END AS is_latest
    FROM decision_ledger d
    {where_sql}
    ORDER BY d.published_at_utc DESC, d.id DESC
    LIMIT ?
    """

    params.append(limit)
    con = _connect()
    rows = con.execute(query, params).fetchall()
    con.close()

    out: List[Dict[str, Any]] = []
    for row in rows:
        if latest_only and int(row["is_latest"]) != 1:
            continue
        item = _row_to_decision(row)
        item["isLatestDecision"] = int(row["is_latest"]) == 1
        out.append(item)
    return out


def validate_decision_hash(decision_id: str) -> Dict[str, Any]:
    _ensure_schema()
    con = _connect()
    row = con.execute("SELECT * FROM decision_ledger WHERE decision_id = ?", [decision_id]).fetchone()
    con.close()

    if row is None:
        return {"found": False, "decisionId": decision_id, "valid": False}

    payload = _payload_from_decision_row(row)
    recomputed_canonical_payload = _canonical_json(payload)
    recomputed_hash = _sha256(recomputed_canonical_payload)
    stored_hash = row["payload_hash"]
    valid = recomputed_hash == stored_hash

    return {
        "found": True,
        "decisionId": decision_id,
        "valid": valid,
        "storedHash": stored_hash,
        "recomputedHash": recomputed_hash,
    }


def _fetch_decision_row(con: sqlite3.Connection, decision_id: str) -> Optional[sqlite3.Row]:
    return con.execute("SELECT * FROM decision_ledger WHERE decision_id = ?", [decision_id]).fetchone()


def _parse_timestamp_utc(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_production_eligible_market(market: Any) -> bool:
    return normalize_market(str(market or "")) == "spread"


def _opportunity_production_eligible(opportunity: Dict[str, Any]) -> bool:
    explicit = opportunity.get("productionEligible")
    if explicit is not None:
        return bool(explicit)
    return _is_production_eligible_market(opportunity.get("market"))


def _snapshot_linkage(
    *,
    event_id: str,
    market: str,
    side: str,
    sportsbook: Optional[str],
    point: Optional[float],
    price: Optional[float],
) -> Dict[str, Any]:
    records = market_data_service.records_for_event(event_id)
    market_key = normalize_market(market)
    side_key = normalize_side(side)
    book_key = str(sportsbook or "").strip().lower()
    point_val = _to_float(point)
    price_val = _to_float(price)

    exact: Optional[Dict[str, Any]] = None
    fallback: Optional[Dict[str, Any]] = None

    for rec in records:
        if normalize_market(rec.get("market")) != market_key:
            continue
        if normalize_side(rec.get("side")) != side_key:
            continue
        if book_key and str(rec.get("sportsbook") or "").strip().lower() != book_key:
            continue

        fallback = rec
        rec_point = _to_float(rec.get("point"))
        rec_price = _to_float(rec.get("americanOdds"))
        point_match = point_val is None or rec_point == point_val
        price_match = price_val is None or rec_price == price_val
        if point_match and price_match:
            exact = rec
            break

    selected = exact or fallback
    if selected is None:
        return {
            "verified": False,
            "reason": "NO_MATCHING_SNAPSHOT_RECORD",
            "sourceSnapshotId": None,
            "oddsTimestamp": None,
            "snapshotAgeMinutes": None,
            "linePriceMatch": False,
        }

    stamp = selected.get("lastSeen") or selected.get("lastUpdated")
    ts = _parse_timestamp_utc(stamp)
    now = datetime.now(timezone.utc)
    age_minutes = None if ts is None else max(0.0, (now - ts).total_seconds() / 60.0)

    source_snapshot_id = _sha256(
        _canonical_json(
            {
                "eventId": selected.get("eventId"),
                "sportsbook": selected.get("sportsbook"),
                "market": selected.get("market"),
                "side": selected.get("side"),
                "point": selected.get("point"),
                "americanOdds": selected.get("americanOdds"),
                "lastSeen": selected.get("lastSeen"),
                "lastUpdated": selected.get("lastUpdated"),
            }
        )
    )

    return {
        "verified": exact is not None,
        "reason": "VERIFIED" if exact is not None else "BOOK_MARKET_SIDE_MATCH_LINE_OR_PRICE_DIFFERS",
        "sourceSnapshotId": source_snapshot_id,
        "oddsTimestamp": ts.isoformat() if ts else None,
        "snapshotAgeMinutes": age_minutes,
        "linePriceMatch": exact is not None,
    }


def _decision_payload_from_opportunity(opportunity: Dict[str, Any], published_at_utc: str) -> Dict[str, Any]:
    raw_probability = _to_float(opportunity.get("rawModelProbability") if opportunity.get("rawModelProbability") is not None else opportunity.get("modelProbability"))
    if raw_probability is not None and raw_probability > 1.0:
        raw_probability = raw_probability / 100.0

    calibrated_probability = _to_float(
        opportunity.get("calibratedProbability")
        if opportunity.get("calibratedProbability") is not None
        else opportunity.get("currentWinProbability")
    )
    if calibrated_probability is not None and calibrated_probability > 1.0:
        calibrated_probability = calibrated_probability / 100.0

    push_probability = _to_float(opportunity.get("currentPushProbability"))
    loss_probability = _to_float(opportunity.get("currentLossProbability"))

    raw_edge = _to_float(opportunity.get("rawEdge") if opportunity.get("rawEdge") is not None else opportunity.get("edge"))
    if raw_edge is not None and raw_edge > 1.0:
        raw_edge = raw_edge / 100.0

    cal_edge = _to_float(opportunity.get("calibratedEdge"))
    if cal_edge is None:
        cal_edge = raw_edge
        if calibrated_probability is not None:
            implied = _to_float(opportunity.get("impliedProbability"))
            if implied is not None:
                if implied > 1.0:
                    implied = implied / 100.0
                cal_edge = calibrated_probability - implied

    score_obj = opportunity.get("sportsIntelligenceScore") or {}
    reasons = []
    if isinstance(score_obj, dict):
        raw_reasons = score_obj.get("reasons")
        if isinstance(raw_reasons, list):
            reasons = [str(x) for x in raw_reasons]

    linkage = _snapshot_linkage(
        event_id=str(opportunity.get("eventId") or ""),
        market=str(opportunity.get("market") or ""),
        side=str(opportunity.get("side") or ""),
        sportsbook=str(opportunity.get("book") or ""),
        point=_to_float(opportunity.get("point")),
        price=_to_float(opportunity.get("price")),
    )

    qualification_status = str(opportunity.get("qualificationStatus") or "").upper() or "QUALIFIED"
    qualification_reasons = opportunity.get("qualificationReasons")
    if not isinstance(qualification_reasons, list):
        qualification_reasons = reasons

    decision = {
        "publishedAtUTC": published_at_utc,
        "season": opportunity.get("season"),
        "week": opportunity.get("week"),
        "eventId": opportunity.get("eventId"),
        "commenceTime": opportunity.get("commenceTime"),
        "awayTeam": opportunity.get("awayTeam"),
        "homeTeam": opportunity.get("homeTeam"),
        "selection": opportunity.get("pick"),
        "market": opportunity.get("market"),
        "side": opportunity.get("side"),
        "point": _to_float(opportunity.get("point")),
        "price": _to_float(opportunity.get("price")),
        "sportsbook": opportunity.get("book"),
        "rawProbability": raw_probability,
        "calibratedProbability": calibrated_probability,
        "pushProbability": push_probability,
        "lossProbability": loss_probability,
        "rawEdge": raw_edge,
        "calibratedEdge": cal_edge,
        "currentEV": _to_float(opportunity.get("currentEV") if opportunity.get("currentEV") is not None else opportunity.get("evPerDollar")),
        "fairLine": _to_float(opportunity.get("fairLine")),
        "truePlayableTo": _to_float(opportunity.get("truePlayableTo")),
        "truePlayableToStatus": opportunity.get("truePlayableToStatus"),
        "siScore": _to_float(score_obj.get("score") if isinstance(score_obj, dict) else None),
        "siGrade": score_obj.get("grade") if isinstance(score_obj, dict) else None,
        "siRank": opportunity.get("weekRank") if opportunity.get("weekRank") is not None else opportunity.get("rank"),
        "recommendation": opportunity.get("recommendation"),
        "qualificationStatus": qualification_status,
        "qualificationReasons": [str(r) for r in qualification_reasons],
        "oddsProvider": opportunity.get("marketProvider") or "line_movement_board",
        "oddsTimestamp": linkage["oddsTimestamp"] or opportunity.get("marketLastUpdated"),
        "modelTimestamp": _utc_now_iso(),
        "marketTimestamp": opportunity.get("marketLastUpdated"),
        "sourceSnapshotId": linkage["sourceSnapshotId"],
    }

    decision["_snapshotLinkage"] = linkage
    return decision


def record_my_card_decision_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    published_at_utc = _utc_now_iso()
    opportunity = {
        "season": payload.get("season"),
        "week": payload.get("week"),
        "eventId": payload.get("eventId"),
        "commenceTime": payload.get("commenceTime"),
        "awayTeam": payload.get("awayTeam"),
        "homeTeam": payload.get("homeTeam"),
        "pick": payload.get("selection") or payload.get("pick") or f"{payload.get('side', '')} {payload.get('point', '')}".strip(),
        "market": payload.get("market"),
        "side": payload.get("side"),
        "point": payload.get("point"),
        "price": payload.get("price"),
        "book": payload.get("sportsbook"),
        "modelProbability": payload.get("modelProbability") or payload.get("rawProbability"),
        "rawModelProbability": payload.get("rawModelProbability"),
        "impliedProbability": payload.get("impliedProbability"),
        "currentWinProbability": payload.get("calibratedProbability"),
        "calibratedProbability": payload.get("calibratedProbability"),
        "currentPushProbability": payload.get("pushProbability"),
        "currentLossProbability": payload.get("lossProbability"),
        "edge": payload.get("edge") or payload.get("rawEdge"),
        "rawEdge": payload.get("rawEdge"),
        "calibratedEdge": payload.get("calibratedEdge"),
        "currentEV": payload.get("currentEV") or payload.get("evPerDollar"),
        "evPerDollar": payload.get("evPerDollar"),
        "fairLine": payload.get("fairLine"),
        "truePlayableTo": payload.get("truePlayableTo"),
        "truePlayableToStatus": payload.get("truePlayableToStatus"),
        "recommendation": payload.get("recommendation") or "MY_CARD",
        "sportsIntelligenceScore": {
            "score": payload.get("siScore"),
            "grade": payload.get("siGrade"),
            "reasons": payload.get("qualificationReasons") or [],
        },
        "weekRank": payload.get("siRank"),
        "rank": payload.get("siRank"),
        "marketProvider": payload.get("oddsProvider") or "line_movement_board",
        "marketLastUpdated": payload.get("marketTimestamp") or payload.get("oddsTimestamp"),
    }

    decision_payload = _decision_payload_from_opportunity(opportunity, published_at_utc)
    # Preserve provided source snapshot when passed by caller.
    if payload.get("sourceSnapshotId"):
        decision_payload["sourceSnapshotId"] = payload.get("sourceSnapshotId")
    decision_payload.pop("_snapshotLinkage", None)
    return record_decision(decision_payload, publication_type="MY_CARD")


def build_official_sia3_preview(
    opportunities: List[Dict[str, Any]],
    *,
    season: int,
    week: int,
    max_odds_age_minutes: Optional[int] = None,
    source_snapshot_id: Optional[str] = None,
) -> Dict[str, Any]:
    threshold = max_odds_age_minutes if max_odds_age_minutes is not None else settings.OFFICIAL_PUBLICATION_MAX_ODDS_AGE_MINUTES
    published_at_utc = _utc_now_iso()

    eligible = [o for o in opportunities if _opportunity_production_eligible(o)]
    top_three = eligible[:3]
    slots = []
    stale_count = 0
    missing_linkage_count = 0
    for idx in range(3):
        rank = idx + 1
        if idx >= len(top_three):
            slots.append(
                {
                    "rank": rank,
                    "slotLabel": "WATCH",
                    "qualificationStatus": "NOT_QUALIFIED",
                    "decision": None,
                    "snapshotVerified": False,
                    "snapshotVerificationReason": "EMPTY_SLOT",
                    "oddsAgeMinutes": None,
                    "isStale": False,
                }
            )
            continue

        opp = dict(top_three[idx])
        opp["season"] = season
        opp["week"] = week
        decision = _decision_payload_from_opportunity(opp, published_at_utc)
        linkage = decision.pop("_snapshotLinkage")
        odds_age = linkage.get("snapshotAgeMinutes")
        is_stale = odds_age is None or (threshold is not None and odds_age > float(threshold))
        if is_stale:
            stale_count += 1
        if not linkage.get("verified"):
            missing_linkage_count += 1

        slot_label = "BET" if decision.get("qualificationStatus") == "QUALIFIED" else "WATCH"
        slots.append(
            {
                "rank": rank,
                "slotLabel": slot_label,
                "qualificationStatus": decision.get("qualificationStatus"),
                "decision": decision,
                "snapshotVerified": bool(linkage.get("verified")),
                "snapshotVerificationReason": linkage.get("reason"),
                "oddsAgeMinutes": odds_age,
                "isStale": is_stale,
            }
        )

    return {
        "snapshotId": source_snapshot_id,
        "publishedAtUTC": published_at_utc,
        "season": season,
        "week": week,
        "maxOddsAgeMinutes": threshold,
        "staleSlotCount": stale_count,
        "missingSnapshotLinkageCount": missing_linkage_count,
        "slots": slots,
    }


def publish_official_sia3_from_preview(preview: Dict[str, Any], *, override_stale: bool = False, override_missing_linkage: bool = False) -> Dict[str, Any]:
    stale_count = int(preview.get("staleSlotCount") or 0)
    missing_count = int(preview.get("missingSnapshotLinkageCount") or 0)
    if stale_count > 0 and not override_stale:
        raise ValueError("Stale odds detected; override required for official publication")
    if missing_count > 0 and not override_missing_linkage:
        raise ValueError("Missing odds snapshot linkage; override required for official publication")

    slots_payload = []
    for slot in preview.get("slots", []):
        decision = slot.get("decision") or {}
        if decision and not _is_production_eligible_market(decision.get("market")):
            raise ValueError("Official SIA 3 publication rejects non-production market families.")
        slots_payload.append(
            {
                "slotLabel": slot.get("slotLabel"),
                "qualificationStatus": slot.get("qualificationStatus"),
                "decision": decision,
            }
        )

    return publish_sia3(
        {
            "publicationType": "SIA_3",
            "publishedAtUTC": preview.get("publishedAtUTC") or _utc_now_iso(),
            "season": int(preview["season"]),
            "week": int(preview["week"]),
            "isOfficial": True,
            "officialCadence": settings.OFFICIAL_SIA3_CADENCE,
            "sourceSnapshotId": preview.get("snapshotId"),
            "slots": slots_payload,
        }
    )


def publish_sia3(payload: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_schema()
    publication_type = payload.get("publicationType") or "SIA_3"
    published_at_utc = payload.get("publishedAtUTC") or _utc_now_iso()
    season = int(payload["season"])
    week = int(payload["week"])
    is_official = bool(payload.get("isOfficial", False))
    official_cadence = payload.get("officialCadence") or settings.OFFICIAL_SIA3_CADENCE
    source_snapshot_id = payload.get("sourceSnapshotId")

    slots = payload.get("slots") or []
    if len(slots) > 3:
        raise ValueError("Only three SIA slots are supported")

    normalized_slots: List[Dict[str, Any]] = []
    con = _connect()

    try:
        for idx in range(3):
            rank = idx + 1
            source = slots[idx] if idx < len(slots) else {}
            slot_label = source.get("slotLabel") or ("WATCH" if source.get("decision") is None and source.get("decisionId") is None else "BET")
            qualification_status = source.get("qualificationStatus")
            decision_id = source.get("decisionId")

            if decision_id is None and source.get("decision") is not None:
                decision_payload = dict(source["decision"])
                if is_official and not _is_production_eligible_market(decision_payload.get("market")):
                    raise ValueError("Official SIA 3 publication rejects non-production market families.")
                decision_payload.setdefault("publishedAtUTC", published_at_utc)
                decision_payload.setdefault("season", season)
                decision_payload.setdefault("week", week)
                if source_snapshot_id and not decision_payload.get("sourceSnapshotId"):
                    decision_payload["sourceSnapshotId"] = source_snapshot_id
                decision = record_decision(decision_payload, publication_type=publication_type)
                decision_id = decision["decisionId"]
                if qualification_status is None:
                    qualification_status = decision.get("qualificationStatus")

            if decision_id is not None:
                drow = _fetch_decision_row(con, decision_id)
                if drow is None:
                    raise ValueError(f"Unknown decisionId: {decision_id}")
                if is_official and not _is_production_eligible_market(drow["market"]):
                    raise ValueError("Official SIA 3 publication rejects non-production market families.")
                if qualification_status is None:
                    qualification_status = drow["qualification_status"]

            normalized_slots.append(
                {
                    "rank": rank,
                    "decisionId": decision_id,
                    "slotLabel": slot_label,
                    "qualificationStatus": qualification_status,
                }
            )

        qualified_pick_count = sum(1 for s in normalized_slots if str(s.get("qualificationStatus") or "").upper() == "QUALIFIED")

        canonical_publication_payload = {
            "publicationType": publication_type,
            "publishedAtUTC": published_at_utc,
            "season": season,
            "week": week,
            "isOfficial": is_official,
            "officialCadence": official_cadence,
            "slots": normalized_slots,
        }

        canonical_payload = _canonical_json(canonical_publication_payload)
        payload_hash = _sha256(canonical_payload)
        idempotency_key = _sha256(f"publication:{payload_hash}")
        publication_id = str(uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key))

        existing = con.execute("SELECT * FROM sia3_publications WHERE idempotency_key = ?", [idempotency_key]).fetchone()
        if existing is None:
            con.execute(
                """
                INSERT INTO sia3_publications (
                    publication_id, publication_type, published_at_utc,
                    season, week, is_official, official_cadence,
                    qualified_pick_count, payload_hash, canonical_payload,
                    idempotency_key, recorded_at_utc
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    publication_id,
                    publication_type,
                    published_at_utc,
                    season,
                    week,
                    1 if is_official else 0,
                    official_cadence,
                    qualified_pick_count,
                    payload_hash,
                    canonical_payload,
                    idempotency_key,
                    _utc_now_iso(),
                ],
            )
            for slot in normalized_slots:
                con.execute(
                    """
                    INSERT INTO sia3_publication_slots (
                        publication_id, slot_rank, decision_id, slot_label, qualification_status
                    ) VALUES (?,?,?,?,?)
                    """,
                    [
                        publication_id,
                        slot["rank"],
                        slot["decisionId"],
                        slot["slotLabel"],
                        slot["qualificationStatus"],
                    ],
                )
            con.commit()
            created = True
        else:
            publication_id = existing["publication_id"]
            created = False

        out = get_publication(publication_id)
        out["created"] = created
        return out
    finally:
        con.close()


def get_publication(publication_id: str) -> Optional[Dict[str, Any]]:
    _ensure_schema()
    con = _connect()
    pub = con.execute("SELECT * FROM sia3_publications WHERE publication_id = ?", [publication_id]).fetchone()
    if pub is None:
        con.close()
        return None

    slots = con.execute(
        "SELECT slot_rank, decision_id, slot_label, qualification_status FROM sia3_publication_slots WHERE publication_id = ? ORDER BY slot_rank",
        [publication_id],
    ).fetchall()
    con.close()

    slot_map = {int(s["slot_rank"]): s for s in slots}
    rank1 = slot_map.get(1)
    rank2 = slot_map.get(2)
    rank3 = slot_map.get(3)

    return {
        "publicationId": pub["publication_id"],
        "publicationType": pub["publication_type"],
        "publishedAtUTC": pub["published_at_utc"],
        "season": pub["season"],
        "week": pub["week"],
        "isOfficial": bool(pub["is_official"]),
        "officialCadence": pub["official_cadence"],
        "qualifiedPickCount": pub["qualified_pick_count"],
        "rank1DecisionId": None if rank1 is None else rank1["decision_id"],
        "rank2DecisionId": None if rank2 is None else rank2["decision_id"],
        "rank3DecisionId": None if rank3 is None else rank3["decision_id"],
        "slots": [
            {
                "rank": i,
                "decisionId": None if slot_map.get(i) is None else slot_map[i]["decision_id"],
                "slotLabel": None if slot_map.get(i) is None else slot_map[i]["slot_label"],
                "qualificationStatus": None if slot_map.get(i) is None else slot_map[i]["qualification_status"],
            }
            for i in [1, 2, 3]
        ],
        "payloadHash": pub["payload_hash"],
        "recordedAtUTC": pub["recorded_at_utc"],
    }


def list_publications(season: Optional[int] = None, week: Optional[int] = None) -> List[Dict[str, Any]]:
    _ensure_schema()
    where = []
    params: List[Any] = []
    if season is not None:
        where.append("season = ?")
        params.append(season)
    if week is not None:
        where.append("week = ?")
        params.append(week)
    where_sql = "WHERE " + " AND ".join(where) if where else ""

    con = _connect()
    rows = con.execute(
        f"SELECT publication_id FROM sia3_publications {where_sql} ORDER BY published_at_utc DESC, id DESC",
        params,
    ).fetchall()
    con.close()
    return [get_publication(r["publication_id"]) for r in rows]


def _profit_per_dollar(price: Optional[float], bet_result: str) -> Optional[float]:
    if price is None:
        return None
    result = (bet_result or "").upper()
    if result == "PUSH":
        return 0.0
    if result == "LOSS":
        return -1.0
    if result != "WIN":
        return None
    if price < 0:
        return round(100.0 / abs(price), 6)
    return round(price / 100.0, 6)


def append_outcome(payload: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_schema()
    decision_id = payload.get("decisionId")
    if not decision_id:
        raise ValueError("decisionId is required")

    con = _connect()
    decision_row = con.execute("SELECT * FROM decision_ledger WHERE decision_id = ?", [decision_id]).fetchone()
    if decision_row is None:
        con.close()
        raise ValueError("decisionId not found")

    closing_line = payload.get("closingLine")
    closing_price = payload.get("closingPrice")
    closing_sportsbook = payload.get("closingSportsbook")
    closing_timestamp = payload.get("closingTimestamp")
    clv_value = payload.get("clv")
    clv_type = payload.get("clvType")
    source_snapshot_id = payload.get("sourceSnapshotId")

    if (closing_line is None and closing_price is None) and decision_row["commence_time"]:
        kickoff = datetime.fromisoformat(str(decision_row["commence_time"]).replace("Z", "+00:00"))
        closing = get_closing_line(
            event_id=str(decision_row["event_id"]),
            bookmaker_key=str(decision_row["sportsbook"] or ""),
            market_key=str(decision_row["market"] or ""),
            outcome_code=str(decision_row["side"] or ""),
            kickoff_utc=kickoff,
        )
        if closing.closing_status == "AVAILABLE":
            closing_line = closing.closing_point
            closing_price = closing.closing_price
            closing_sportsbook = closing_sportsbook or decision_row["sportsbook"]
            closing_timestamp = closing.closing_timestamp.isoformat() if closing.closing_timestamp else None

    if clv_value is None and (closing_line is not None or closing_price is not None):
        clv = calculate_clv(
            recommended_point=decision_row["point"],
            recommended_price=decision_row["price"],
            closing_point=closing_line,
            closing_price=closing_price,
            market=str(decision_row["market"] or ""),
            side=str(decision_row["side"] or ""),
        )
        if clv.clv_points is not None:
            clv_value = clv.clv_points
            clv_type = clv_type or "POINTS"
        elif clv.clv_percent is not None:
            clv_value = clv.clv_percent
            clv_type = clv_type or "PERCENT"

    outcome_payload = {
        "decisionId": decision_id,
        "capturedAtUTC": payload.get("capturedAtUTC") or _utc_now_iso(),
        "closingLine": closing_line,
        "closingPrice": closing_price,
        "closingSportsbook": closing_sportsbook,
        "closingTimestamp": closing_timestamp,
        "closingConsensusMethodology": payload.get("closingConsensusMethodology"),
        "clv": clv_value,
        "clvType": clv_type,
        "finalAwayScore": payload.get("finalAwayScore"),
        "finalHomeScore": payload.get("finalHomeScore"),
        "betResult": payload.get("betResult"),
        "profitPerDollar": payload.get("profitPerDollar"),
        "sourceSnapshotId": source_snapshot_id,
    }

    if outcome_payload["profitPerDollar"] is None and outcome_payload["betResult"]:
        outcome_payload["profitPerDollar"] = _profit_per_dollar(decision_row["price"], str(outcome_payload["betResult"]))

    canonical_payload = _canonical_json(outcome_payload)
    payload_hash = _sha256(canonical_payload)
    idempotency_key = _sha256(f"outcome:{payload_hash}")
    outcome_id = str(uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key))

    existing = con.execute("SELECT * FROM decision_outcomes WHERE idempotency_key = ?", [idempotency_key]).fetchone()
    if existing is None:
        con.execute(
            """
            INSERT INTO decision_outcomes (
                outcome_id, decision_id, captured_at_utc,
                closing_line, closing_price, closing_sportsbook,
                closing_timestamp, closing_consensus_methodology,
                clv, clv_type, final_away_score, final_home_score,
                bet_result, profit_per_dollar,
                source_snapshot_id, payload_hash, canonical_payload,
                idempotency_key, recorded_at_utc
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                outcome_id,
                decision_id,
                outcome_payload["capturedAtUTC"],
                outcome_payload["closingLine"],
                outcome_payload["closingPrice"],
                outcome_payload["closingSportsbook"],
                outcome_payload["closingTimestamp"],
                outcome_payload["closingConsensusMethodology"],
                outcome_payload["clv"],
                outcome_payload["clvType"],
                outcome_payload["finalAwayScore"],
                outcome_payload["finalHomeScore"],
                outcome_payload["betResult"],
                outcome_payload["profitPerDollar"],
                outcome_payload["sourceSnapshotId"],
                payload_hash,
                canonical_payload,
                idempotency_key,
                _utc_now_iso(),
            ],
        )
        con.commit()
        created = True
    else:
        outcome_id = existing["outcome_id"]
        created = False

    row = con.execute("SELECT * FROM decision_outcomes WHERE outcome_id = ?", [outcome_id]).fetchone()
    con.close()

    return {
        "outcomeId": row["outcome_id"],
        "decisionId": row["decision_id"],
        "capturedAtUTC": row["captured_at_utc"],
        "closingLine": row["closing_line"],
        "closingPrice": row["closing_price"],
        "closingSportsbook": row["closing_sportsbook"],
        "closingTimestamp": row["closing_timestamp"],
        "clv": row["clv"],
        "clvType": row["clv_type"],
        "finalAwayScore": row["final_away_score"],
        "finalHomeScore": row["final_home_score"],
        "betResult": row["bet_result"],
        "profitPerDollar": row["profit_per_dollar"],
        "payloadHash": row["payload_hash"],
        "created": created,
    }


def get_admin_ledger_summary(limit: int = 200) -> Dict[str, Any]:
    _ensure_schema()
    con = _connect()

    decisions_recorded = int(con.execute("SELECT COUNT(*) AS n FROM decision_ledger").fetchone()["n"])
    my_card_decisions = int(con.execute("SELECT COUNT(*) AS n FROM decision_ledger WHERE publication_type = 'MY_CARD'").fetchone()["n"])
    sia3_decisions = int(con.execute("SELECT COUNT(*) AS n FROM decision_ledger WHERE publication_type = 'SIA_3'").fetchone()["n"])
    publications_total = int(con.execute("SELECT COUNT(*) AS n FROM sia3_publications").fetchone()["n"])
    official_publications = int(con.execute("SELECT COUNT(*) AS n FROM sia3_publications WHERE is_official = 1").fetchone()["n"])
    outcomes_captured = int(con.execute("SELECT COUNT(*) AS n FROM decision_outcomes").fetchone()["n"])
    closing_lines_captured = int(con.execute("SELECT COUNT(*) AS n FROM decision_outcomes WHERE closing_line IS NOT NULL OR closing_price IS NOT NULL").fetchone()["n"])

    latest_publication = con.execute(
        "SELECT publication_id, published_at_utc FROM sia3_publications ORDER BY published_at_utc DESC, id DESC LIMIT 1"
    ).fetchone()

    rows = con.execute(
        """
        SELECT d.published_at_utc,
               d.season,
               d.week,
               d.selection,
               d.point,
               d.price,
               d.sportsbook,
               d.si_score,
               d.current_ev,
               d.payload_hash,
               o.bet_result,
               s.slot_rank
        FROM decision_ledger d
        LEFT JOIN (
            SELECT decision_id, bet_result,
                   ROW_NUMBER() OVER (PARTITION BY decision_id ORDER BY captured_at_utc DESC, id DESC) AS rn
            FROM decision_outcomes
        ) o ON o.decision_id = d.decision_id AND o.rn = 1
        LEFT JOIN sia3_publication_slots s ON s.decision_id = d.decision_id
        ORDER BY d.published_at_utc DESC, d.id DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()

    missing_outcomes = int(
        con.execute(
            "SELECT COUNT(*) AS n FROM decision_ledger d WHERE NOT EXISTS (SELECT 1 FROM decision_outcomes o WHERE o.decision_id = d.decision_id)"
        ).fetchone()["n"]
    )
    missing_closing_lines = int(
        con.execute(
            "SELECT COUNT(*) AS n FROM decision_outcomes WHERE closing_line IS NULL AND closing_price IS NULL"
        ).fetchone()["n"]
    )

    invalid_hashes = 0
    decision_hash_rows = con.execute("SELECT decision_id FROM decision_ledger").fetchall()
    for drow in decision_hash_rows:
        if not validate_decision_hash(drow["decision_id"]).get("valid"):
            invalid_hashes += 1

    missing_snapshot_linkages = int(
        con.execute(
            "SELECT COUNT(*) AS n FROM decision_ledger WHERE source_snapshot_id IS NULL OR TRIM(source_snapshot_id) = ''"
        ).fetchone()["n"]
    )

    con.close()

    return {
        "decisionsRecorded": decisions_recorded,
        "sia3DecisionsCaptured": sia3_decisions,
        "myCardDecisionsCaptured": my_card_decisions,
        "officialSia3Publications": official_publications,
        "publicationsRecorded": publications_total,
        "latestPublication": None if latest_publication is None else {
            "publicationId": latest_publication["publication_id"],
            "publishedAtUTC": latest_publication["published_at_utc"],
        },
        "ledgerIntegrity": {
            "valid": invalid_hashes == 0,
            "invalidHashCount": invalid_hashes,
        },
        "outcomesCaptured": outcomes_captured,
        "closingLinesCaptured": closing_lines_captured,
        "missingOutcomes": missing_outcomes,
        "missingClosingLines": missing_closing_lines,
        "missingOddsSnapshotLinkages": missing_snapshot_linkages,
        "auditRows": [
            {
                "timestamp": r["published_at_utc"],
                "week": f"{r['season']}-W{r['week']}",
                "rank": r["slot_rank"],
                "selection": r["selection"],
                "line": r["point"],
                "price": r["price"],
                "sportsbook": r["sportsbook"],
                "siScore": r["si_score"],
                "ev": r["current_ev"],
                "decisionHash": r["payload_hash"],
                "result": r["bet_result"],
            }
            for r in rows
        ],
    }


def get_official_publication_for_week(season: int, week: int) -> Optional[Dict[str, Any]]:
    _ensure_schema()
    con = _connect()
    row = con.execute(
        """
        SELECT publication_id
        FROM sia3_publications
        WHERE is_official = 1
          AND season = ?
          AND week = ?
        ORDER BY published_at_utc DESC, id DESC
        LIMIT 1
        """,
        [season, week],
    ).fetchone()
    con.close()
    if row is None:
        return None
    return get_publication(row["publication_id"])


def get_prospective_performance() -> Dict[str, Any]:
    _ensure_schema()
    con = _connect()
    rows = con.execute(
        """
        SELECT s.slot_rank, d.market, d.si_score, d.raw_edge, d.current_ev, d.sportsbook,
               o.bet_result, o.profit_per_dollar, o.clv
        FROM decision_ledger d
        JOIN sia3_publication_slots s ON s.decision_id = d.decision_id
        LEFT JOIN (
            SELECT decision_id, bet_result, profit_per_dollar, clv,
                   ROW_NUMBER() OVER (PARTITION BY decision_id ORDER BY captured_at_utc DESC, id DESC) AS rn
            FROM decision_outcomes
        ) o ON o.decision_id = d.decision_id AND o.rn = 1
        """
    ).fetchall()
    con.close()

    graded = [r for r in rows if r["bet_result"] in {"WIN", "LOSS", "PUSH"}]
    wins = sum(1 for r in graded if r["bet_result"] == "WIN")
    losses = sum(1 for r in graded if r["bet_result"] == "LOSS")
    pushes = sum(1 for r in graded if r["bet_result"] == "PUSH")
    non_push = max(1, wins + losses)
    win_rate = wins / non_push

    profits = [float(r["profit_per_dollar"]) for r in graded if r["profit_per_dollar"] is not None]
    clv_values = [float(r["clv"]) for r in graded if r["clv"] is not None]
    beat_close = sum(1 for v in clv_values if v > 0)

    by_rank: Dict[int, Dict[str, Any]] = {}
    for rank in [1, 2, 3]:
        rrows = [r for r in graded if r["slot_rank"] == rank]
        rw = sum(1 for r in rrows if r["bet_result"] == "WIN")
        rl = sum(1 for r in rrows if r["bet_result"] == "LOSS")
        rp = sum(1 for r in rrows if r["bet_result"] == "PUSH")
        denom = max(1, rw + rl)
        rprofits = [float(r["profit_per_dollar"]) for r in rrows if r["profit_per_dollar"] is not None]
        by_rank[rank] = {
            "W": rw,
            "L": rl,
            "P": rp,
            "winRate": rw / denom,
            "roi": None if not rprofits else sum(rprofits) / len(rprofits),
        }

    return {
        "datasetLabel": "PROSPECTIVE AUDITED TRACK RECORD",
        "historicalLabel": "MARKET-REFERENCE BACKTEST",
        "totalDecisions": len(rows),
        "gradedDecisions": len(graded),
        "W": wins,
        "L": losses,
        "P": pushes,
        "winRate": win_rate,
        "roi": None if not profits else sum(profits) / len(profits),
        "averageCLV": None if not clv_values else sum(clv_values) / len(clv_values),
        "beatClosingLinePercent": None if not clv_values else beat_close / len(clv_values),
        "byRank": {
            "1": by_rank[1],
            "2": by_rank[2],
            "3": by_rank[3],
        },
    }


def auto_append_outcomes_from_scores(
    *,
    fetch_scores_fn: Optional[Any] = None,
) -> Dict[str, Any]:
    """Append outcome rows for decisions that now have final scores.

    This never updates decision rows; it only appends to decision_outcomes.
    """
    _ensure_schema()

    if fetch_scores_fn is None:
        def _default_fetch_scores(event_id: str) -> Optional[Dict[str, Any]]:
            return None
        fetch_scores_fn = _default_fetch_scores

    con = _connect()
    pending = con.execute(
        """
        SELECT d.*
        FROM decision_ledger d
        WHERE NOT EXISTS (
            SELECT 1
            FROM decision_outcomes o
            WHERE o.decision_id = d.decision_id
              AND o.bet_result IN ('WIN','LOSS','PUSH')
        )
        """
    ).fetchall()
    con.close()

    appended = 0
    still_pending = 0
    for row in pending:
        score = fetch_scores_fn(row["event_id"])
        if not score:
            still_pending += 1
            continue

        away = score.get("finalAwayScore")
        home = score.get("finalHomeScore")
        if away is None or home is None:
            still_pending += 1
            continue

        market = str(row["market"] or "").lower()
        side = str(row["side"] or "").lower()
        point = _to_float(row["point"])
        if point is None:
            still_pending += 1
            continue

        result = None
        if market in {"spread", "spreads"}:
            margin = float(home) - float(away)
            if side == "home":
                ats = margin + point
                result = "WIN" if ats > 0 else "LOSS" if ats < 0 else "PUSH"
            elif side == "away":
                ats = -margin - point
                result = "WIN" if ats > 0 else "LOSS" if ats < 0 else "PUSH"
        elif market in {"total", "totals"}:
            total = float(home) + float(away)
            if side == "over":
                result = "WIN" if total > point else "LOSS" if total < point else "PUSH"
            elif side == "under":
                result = "WIN" if total < point else "LOSS" if total > point else "PUSH"

        if result is None:
            still_pending += 1
            continue

        append_outcome(
            {
                "decisionId": row["decision_id"],
                "capturedAtUTC": _utc_now_iso(),
                "betResult": result,
                "finalAwayScore": int(away),
                "finalHomeScore": int(home),
            }
        )
        appended += 1

    return {
        "checked": len(pending),
        "appended": appended,
        "pending": still_pending,
    }
