from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


log = logging.getLogger("social_history")

_DB_PATH = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9" / "database" / "nfl_model.duckdb"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS social_signal_history (
    stored_at                  TIMESTAMP NOT NULL,
    signal_id                  VARCHAR   NOT NULL,
    signal_timestamp           VARCHAR,
    event_id                   VARCHAR,
    team                       VARCHAR,
    player                     VARCHAR,
    position                   VARCHAR,
    category                   VARCHAR,
    severity                   VARCHAR,
    status                     VARCHAR,
    source_name                VARCHAR,
    source_handle              VARCHAR,
    source_type                VARCHAR,
    source_credibility         DOUBLE,
    corroboration_count        INTEGER,
    confidence                 DOUBLE,
    estimated_point_impact     DOUBLE,
    market_relevance           VARCHAR,
    game_impact                DOUBLE,
    text_summary               TEXT,
    provider                   VARCHAR,
    is_live                    BOOLEAN,
    subsequent_line_movement   DOUBLE,
    closing_line               DOUBLE,
    game_result                VARCHAR
);

CREATE TABLE IF NOT EXISTS social_ingestion_runs (
    stored_at               TIMESTAMP NOT NULL,
    provider                VARCHAR,
    is_live                 BOOLEAN,
    data_status             VARCHAR,
    sources_active          INTEGER,
    signals_detected        INTEGER,
    corroborated_signals    INTEGER,
    official_signals        INTEGER,
    last_ingestion          VARCHAR,
    errors                  TEXT
);
"""


def _open_db(read_only: bool = False):
    import duckdb  # type: ignore

    return duckdb.connect(str(_DB_PATH), read_only=read_only)


def _ensure_schema() -> None:
    if not _DB_PATH.exists():
        return

    try:
        con = _open_db()
        for statement in _SCHEMA.strip().split(";"):
            statement = statement.strip()
            if statement:
                con.execute(statement)
        con.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not ensure social schema: %s", exc)


def store_signals(signals: List[Dict[str, Any]], provider: str, is_live: bool) -> int:
    _ensure_schema()
    if not _DB_PATH.exists() or not signals:
        return 0

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    for signal in signals:
        rows.append(
            [
                now_naive,
                signal.get("signalId"),
                signal.get("timestamp"),
                signal.get("eventId"),
                signal.get("team"),
                signal.get("player"),
                signal.get("position"),
                signal.get("category"),
                signal.get("severity"),
                signal.get("status"),
                signal.get("sourceName"),
                signal.get("sourceHandle"),
                signal.get("sourceType"),
                float(signal.get("sourceCredibility", 0.0) or 0.0),
                int(signal.get("corroborationCount", 0) or 0),
                float(signal.get("confidence", 0.0) or 0.0),
                float(signal.get("estimatedPointImpact", 0.0) or 0.0),
                signal.get("marketRelevance"),
                float(signal.get("gameImpact", 0.0) or 0.0),
                signal.get("textSummary"),
                provider,
                bool(is_live),
                signal.get("subsequentLineMovement"),
                signal.get("closingLine"),
                signal.get("gameResult"),
            ]
        )

    try:
        con = _open_db()
        con.executemany(
            "INSERT INTO social_signal_history VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        con.close()
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not store social signals: %s", exc)
        return 0


def store_ingestion_run(summary: Dict[str, Any]) -> None:
    _ensure_schema()
    if not _DB_PATH.exists():
        return

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    row = [
        now_naive,
        summary.get("provider"),
        bool(summary.get("isLive", False)),
        summary.get("dataStatus"),
        int(summary.get("sourcesActive", 0) or 0),
        int(summary.get("signalsDetected", 0) or 0),
        int(summary.get("corroboratedSignals", 0) or 0),
        int(summary.get("officialSignals", 0) or 0),
        summary.get("lastIngestion"),
        json.dumps(summary.get("errors") or []),
    ]

    try:
        con = _open_db()
        con.execute(
            "INSERT INTO social_ingestion_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
            row,
        )
        con.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not store social ingestion run: %s", exc)


def get_social_summary() -> Dict[str, Any]:
    default = {
        "provider": "MOCK",
        "isLive": False,
        "dataStatus": "MOCK",
        "sourcesActive": 0,
        "signalsDetected": 0,
        "corroboratedSignals": 0,
        "officialSignals": 0,
        "lastIngestion": None,
        "lastError": None,
    }

    _ensure_schema()
    if not _DB_PATH.exists():
        return default

    try:
        con = _open_db(read_only=True)
        latest = con.execute(
            """
            SELECT provider, is_live, data_status, sources_active, signals_detected,
                   corroborated_signals, official_signals, last_ingestion, errors
            FROM social_ingestion_runs
            ORDER BY stored_at DESC
            LIMIT 1
            """
        ).fetchone()
        con.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not load social summary: %s", exc)
        return default

    if latest is None:
        return default

    errors = None
    if latest[8]:
        try:
            parsed = json.loads(latest[8])
            errors = parsed[0] if isinstance(parsed, list) and parsed else str(parsed)
        except json.JSONDecodeError:
            errors = str(latest[8])

    return {
        "provider": latest[0] or "MOCK",
        "isLive": bool(latest[1]),
        "dataStatus": latest[2] or "MOCK",
        "sourcesActive": int(latest[3] or 0),
        "signalsDetected": int(latest[4] or 0),
        "corroboratedSignals": int(latest[5] or 0),
        "officialSignals": int(latest[6] or 0),
        "lastIngestion": latest[7],
        "lastError": errors,
    }