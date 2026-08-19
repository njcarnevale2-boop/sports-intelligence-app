from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

from app.config import settings
from app.services.calibration import apply_guarded_isotonic
from app.services.closing_line import calculate_clv, get_closing_line
from app.services.cross_market_normalization import attach_shadow_global_scores
from app.services.probability_engine import (
    ev_per_dollar_with_push,
    load_historical_residuals,
    total_outcome_probabilities,
)


MODEL_ROOT = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9"
OUTPUTS_ROOT = MODEL_ROOT / "outputs"
LINE_MOVEMENT_BOARD = OUTPUTS_ROOT / "line_movement_board.csv"
GAME_PROJECTIONS = OUTPUTS_ROOT / "current_game_projections.csv"


def _resolve_db_path() -> Path:
    raw = settings.DATABASE_URL
    if raw.startswith("sqlite:///"):
        rel = raw.removeprefix("sqlite:///")
        return (Path.cwd() / rel).resolve()
    return (Path.cwd() / "sports_intelligence.db").resolve()


_DB_PATH = _resolve_db_path()


SHADOW_SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_candidate_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    created_at_utc TEXT NOT NULL,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    source_snapshot_id TEXT,
    source_market_timestamp TEXT,
    candidate_count INTEGER NOT NULL,
    payload_hash TEXT NOT NULL,
    canonical_payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shadow_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL UNIQUE,
    created_at_utc TEXT NOT NULL,

    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    event_id TEXT NOT NULL,
    commence_time TEXT,

    market_family TEXT NOT NULL,
    market_key TEXT NOT NULL,
    period TEXT NOT NULL,

    selection TEXT NOT NULL,
    side TEXT NOT NULL,
    team_code TEXT,

    line REAL,
    sportsbook TEXT,
    american_price REAL,

    raw_model_probability REAL,
    calibrated_probability REAL,
    market_implied_probability REAL,
    market_no_vig_probability REAL,

    raw_edge REAL,
    calibrated_edge REAL,
    push_probability REAL,
    loss_probability REAL,
    current_ev REAL,

    model_version TEXT,
    probability_engine_version TEXT,
    calibration_version TEXT,
    ranking_version TEXT,
    qualification_version TEXT,
    git_commit_hash TEXT,

    market_snapshot_timestamp TEXT,
    source_odds_snapshot_id TEXT,

    market_rank INTEGER,
    week_rank INTEGER,
    qualification_status TEXT,
    global_research_score REAL,
    global_research_rank INTEGER,
    normalization_method TEXT,
    normalization_version TEXT,
    production_eligible INTEGER,
    cross_market_comparable INTEGER,

    FOREIGN KEY(run_id) REFERENCES shadow_candidate_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_shadow_candidates_run ON shadow_candidates(run_id);
CREATE INDEX IF NOT EXISTS idx_shadow_candidates_week ON shadow_candidates(season, week, market_family);

CREATE TABLE IF NOT EXISTS shadow_publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_snapshot_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    publication_type TEXT NOT NULL,
    official_cadence TEXT,
    is_official INTEGER NOT NULL DEFAULT 0,
    item_count INTEGER NOT NULL,
    payload_hash TEXT NOT NULL,
    canonical_payload TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    FOREIGN KEY(run_id) REFERENCES shadow_candidate_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_shadow_publications_week ON shadow_publications(season, week, is_official);

CREATE TABLE IF NOT EXISTS shadow_publication_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_snapshot_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,

    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    event_id TEXT NOT NULL,
    commence_time TEXT,

    market_family TEXT NOT NULL,
    market_key TEXT NOT NULL,
    period TEXT NOT NULL,

    selection TEXT NOT NULL,
    side TEXT NOT NULL,
    team_code TEXT,

    line REAL,
    sportsbook TEXT,
    american_price REAL,

    raw_model_probability REAL,
    calibrated_probability REAL,
    market_implied_probability REAL,
    market_no_vig_probability REAL,

    raw_edge REAL,
    calibrated_edge REAL,
    push_probability REAL,
    loss_probability REAL,
    current_ev REAL,

    model_version TEXT,
    probability_engine_version TEXT,
    calibration_version TEXT,
    ranking_version TEXT,
    qualification_version TEXT,
    git_commit_hash TEXT,

    market_snapshot_timestamp TEXT,
    source_odds_snapshot_id TEXT,

    market_rank INTEGER,
    week_rank INTEGER,
    qualification_status TEXT,
    global_research_score REAL,
    global_research_rank INTEGER,
    normalization_method TEXT,
    normalization_version TEXT,
    production_eligible INTEGER,
    cross_market_comparable INTEGER,

    FOREIGN KEY(shadow_snapshot_id) REFERENCES shadow_publications(shadow_snapshot_id),
    UNIQUE(shadow_snapshot_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS shadow_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_id TEXT NOT NULL UNIQUE,
    shadow_snapshot_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    captured_at_utc TEXT NOT NULL,

    final_away_score INTEGER,
    final_home_score INTEGER,
    result TEXT NOT NULL,
    profit_per_dollar REAL,

    closing_line REAL,
    closing_price REAL,
    closing_market_novig_probability REAL,
    closing_timestamp TEXT,
    clv REAL,
    clv_type TEXT,

    source_odds_snapshot_id TEXT,
    payload_hash TEXT NOT NULL,
    canonical_payload TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    FOREIGN KEY(candidate_id) REFERENCES shadow_candidates(candidate_id)
);

CREATE INDEX IF NOT EXISTS idx_shadow_outcomes_candidate ON shadow_outcomes(candidate_id);

CREATE TABLE IF NOT EXISTS shadow_market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL UNIQUE,
    captured_at_utc TEXT NOT NULL,

    event_id TEXT NOT NULL,
    provider_event_id TEXT,
    market_family TEXT NOT NULL,
    market_key TEXT NOT NULL,
    period TEXT NOT NULL,
    team_code TEXT,
    selection TEXT NOT NULL,

    line REAL,
    price REAL,
    bookmaker TEXT,
    fetched_at TEXT,

    payload_hash TEXT NOT NULL,
    canonical_payload TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_shadow_market_snapshots_market ON shadow_market_snapshots(market_family, market_key, period);
"""


EDGE_BANDS = [
    (0.00, 0.02, "0-2pp"),
    (0.02, 0.05, "2-5pp"),
    (0.05, 0.08, "5-8pp"),
    (0.08, 0.10, "8-10pp"),
    (0.10, 0.15, "10-15pp"),
    (0.15, 0.20, "15-20pp"),
    (0.20, 9.0, "20pp+"),
]

EV_BANDS = [
    (0.00, 0.02, "0-2%"),
    (0.02, 0.05, "2-5%"),
    (0.05, 0.10, "5-10%"),
    (0.10, 0.15, "10-15%"),
    (0.15, 0.20, "15-20%"),
    (0.20, 0.30, "20-30%"),
    (0.30, 9.0, "30%+"),
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical_json(payload: dict[str, Any]) -> str:
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
    con.executescript(SHADOW_SCHEMA)
    # Backward-compatible migrations for databases created before research score fields existed.
    for table, column_def in [
        ("shadow_candidates", "global_research_score REAL"),
        ("shadow_candidates", "global_research_rank INTEGER"),
        ("shadow_candidates", "normalization_method TEXT"),
        ("shadow_candidates", "normalization_version TEXT"),
        ("shadow_candidates", "production_eligible INTEGER"),
        ("shadow_candidates", "cross_market_comparable INTEGER"),
        ("shadow_publication_items", "global_research_score REAL"),
        ("shadow_publication_items", "global_research_rank INTEGER"),
        ("shadow_publication_items", "normalization_method TEXT"),
        ("shadow_publication_items", "normalization_version TEXT"),
        ("shadow_publication_items", "production_eligible INTEGER"),
        ("shadow_publication_items", "cross_market_comparable INTEGER"),
        ("shadow_outcomes", "closing_market_novig_probability REAL"),
    ]:
        try:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
        except sqlite3.OperationalError:
            pass
    con.commit()
    con.close()


def _safe_float(value: Any) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _implied_probability(american_odds: float) -> float:
    odds = float(american_odds)
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def _devig_two_way(odds_a: float, odds_b: float) -> tuple[float, float]:
    pa = _implied_probability(odds_a)
    pb = _implied_probability(odds_b)
    s = pa + pb
    if s <= 0:
        return 0.5, 0.5
    return pa / s, pb / s


def _moneyline_probability_from_margin(model_margin_home: float, side: str) -> tuple[float, float, float]:
    historical = load_historical_residuals()
    if historical is None:
        # Conservative fallback when residual distribution is unavailable.
        p_home = 0.5
    else:
        sims = pd.Series((model_margin_home + historical.margin_residuals).round())
        home_win = float((sims > 0).mean())
        tie = float((sims == 0).mean())
        p_home = home_win + 0.5 * tie

    p_home = max(1e-6, min(1 - 1e-6, p_home))
    p_side = p_home if side == "home" else 1.0 - p_home
    return p_side, 0.0, max(0.0, 1.0 - p_side)


def _normalize_market(value: str) -> str:
    key = str(value or "").strip().lower()
    if key == "h2h":
        return "moneyline"
    if key == "totals":
        return "total"
    return key


def _line_desirability(market_key: str, side: str, line: Optional[float], price: Optional[float]) -> tuple[float, float]:
    # Higher tuple is better.
    if market_key == "moneyline":
        return (float(price or -9999.0), 0.0)

    p = float(line or 0.0)
    if market_key == "total" and side == "over":
        return (-p, float(price or -9999.0))
    if market_key == "total" and side == "under":
        return (p, float(price or -9999.0))
    return (float(price or -9999.0), 0.0)


def _candidate_id(run_id: str, event_id: str, market_key: str, side: str, book: str, line: Optional[float], price: Optional[float]) -> str:
    seed = {
        "runId": run_id,
        "eventId": event_id,
        "marketKey": market_key,
        "side": side,
        "sportsbook": book,
        "line": line,
        "price": price,
    }
    return str(uuid.uuid5(uuid.NAMESPACE_URL, _sha256(_canonical_json(seed))))


def _load_line_board() -> pd.DataFrame:
    if not LINE_MOVEMENT_BOARD.exists():
        return pd.DataFrame()
    df = pd.read_csv(LINE_MOVEMENT_BOARD)
    if df.empty:
        return df
    df = df.copy()
    df["market"] = df["market"].astype(str).str.strip().str.lower().map(_normalize_market)
    df["side"] = df["side"].astype(str).str.strip().str.lower()
    df["api_event_id"] = df["api_event_id"].astype(str)
    return df


def _load_projection_lookup() -> dict[str, pd.Series]:
    if not GAME_PROJECTIONS.exists():
        return {}
    df = pd.read_csv(GAME_PROJECTIONS)
    if "api_event_id" not in df.columns:
        return {}
    df = df.copy()
    df["api_event_id"] = df["api_event_id"].astype(str)
    return {str(r["api_event_id"]): r for _, r in df.iterrows()}


def _extract_season_week_from_game_id(game_id: str, fallback_dt: Optional[datetime] = None) -> tuple[int, int]:
    text = str(game_id or "")
    parts = text.split("_")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return int(parts[0]), int(parts[1])

    if fallback_dt is not None:
        return int(fallback_dt.year), int(fallback_dt.isocalendar().week)

    now = datetime.now(timezone.utc)
    return now.year, int(now.isocalendar().week)


def _parse_commence(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        ts = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.to_pydatetime()
    except Exception:
        return None


def _score_to_band(value: float, bands: list[tuple[float, float, str]]) -> str:
    val = float(value)
    for lo, hi, label in bands:
        if lo <= val < hi:
            return label
    return bands[-1][2]


def _save_shadow_run(run_payload: dict[str, Any], candidates: list[dict[str, Any]]) -> None:
    _ensure_schema()
    con = _connect()

    run_id = run_payload["runId"]
    canonical_payload = _canonical_json(run_payload)
    payload_hash = _sha256(canonical_payload)

    con.execute(
        """
        INSERT INTO shadow_candidate_runs (
            run_id, created_at_utc, season, week,
            source_snapshot_id, source_market_timestamp,
            candidate_count, payload_hash, canonical_payload
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        [
            run_id,
            run_payload["createdAtUTC"],
            int(run_payload["season"]),
            int(run_payload["week"]),
            run_payload.get("sourceSnapshotId"),
            run_payload.get("sourceMarketTimestamp"),
            len(candidates),
            payload_hash,
            canonical_payload,
        ],
    )

    for row in candidates:
        values = [
            row["runId"],
            row["candidateId"],
            row["createdAtUTC"],
            row["season"],
            row["week"],
            row["eventId"],
            row.get("commenceTime"),
            row["marketFamily"],
            row["marketKey"],
            row["period"],
            row["selection"],
            row["side"],
            row.get("teamCode"),
            row.get("line"),
            row.get("sportsbook"),
            row.get("americanPrice"),
            row.get("rawModelProbability"),
            row.get("calibratedProbability"),
            row.get("marketImpliedProbability"),
            row.get("marketNoVigProbability"),
            row.get("rawEdge"),
            row.get("calibratedEdge"),
            row.get("pushProbability"),
            row.get("lossProbability"),
            row.get("ev"),
            row.get("modelVersion"),
            row.get("probabilityEngineVersion"),
            row.get("calibrationVersion"),
            row.get("rankingVersion"),
            row.get("qualificationVersion"),
            row.get("gitCommitHash"),
            row.get("marketSnapshotTimestamp"),
            row.get("sourceOddsSnapshotId"),
            row.get("marketRank"),
            row.get("weekRank"),
            row.get("qualificationStatus"),
            row.get("globalResearchScore"),
            row.get("globalResearchRank"),
            row.get("normalizationMethod"),
            row.get("normalizationVersion"),
            1 if bool(row.get("productionEligible")) else 0,
            1 if bool(row.get("crossMarketComparable")) else 0,
        ]

        con.execute(
            f"""
            INSERT INTO shadow_candidates (
                run_id, candidate_id, created_at_utc,
                season, week, event_id, commence_time,
                market_family, market_key, period,
                selection, side, team_code,
                line, sportsbook, american_price,
                raw_model_probability, calibrated_probability,
                market_implied_probability, market_no_vig_probability,
                raw_edge, calibrated_edge, push_probability, loss_probability, current_ev,
                model_version, probability_engine_version, calibration_version,
                ranking_version, qualification_version, git_commit_hash,
                market_snapshot_timestamp, source_odds_snapshot_id,
                market_rank, week_rank, qualification_status,
                global_research_score, global_research_rank,
                normalization_method, normalization_version,
                production_eligible, cross_market_comparable
            ) VALUES ({','.join(['?'] * len(values))})
            """,
            values,
        )

    con.commit()
    con.close()


def build_shadow_boards(week: Optional[int] = None, season: Optional[int] = None) -> dict[str, Any]:
    """Build moneyline/total shadow candidates for one week and persist as immutable run rows."""
    board = _load_line_board()
    proj = _load_projection_lookup()

    if board.empty or not proj:
        raise ValueError("Required data unavailable: line_movement_board or current_game_projections")

    working = board[board["market"].isin(["moneyline", "total"])].copy()
    if working.empty:
        raise ValueError("No moneyline/total rows available in line_movement_board")

    # Determine season/week from available events.
    if season is None or week is None:
        first_event = str(working.iloc[0]["api_event_id"])
        fallback_commence = _parse_commence(working.iloc[0].get("commence_time"))
        auto_season, auto_week = _extract_season_week_from_game_id(first_event, fallback_commence)
        season = season if season is not None else auto_season
        week = week if week is not None else auto_week

    # Filter rows to requested week/season when event ids carry season_week format.
    filtered_rows = []
    for _, row in working.iterrows():
        event_id = str(row.get("api_event_id") or "")
        commence = _parse_commence(row.get("commence_time"))
        row_season, row_week = _extract_season_week_from_game_id(event_id, commence)
        if row_season == int(season) and row_week == int(week):
            filtered_rows.append(row)
    if filtered_rows:
        working = pd.DataFrame(filtered_rows)

    created_at = _utc_now_iso()
    run_seed = {
        "createdAtUTC": created_at,
        "season": int(season),
        "week": int(week),
        "rowCount": int(len(working)),
    }
    run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, _sha256(_canonical_json(run_seed))))

    candidates: list[dict[str, Any]] = []

    # First choose one best book quote per event+market+side.
    grouped = working.groupby(["api_event_id", "market", "side"], dropna=False, sort=False)
    selected: dict[tuple[str, str, str], pd.Series] = {}

    for (event_id, market_key, side), group in grouped:
        best_row = None
        best_score = None
        for _, row in group.iterrows():
            line = _safe_float(row.get("latest_point"))
            price = _safe_float(row.get("latest_price"))
            score = _line_desirability(str(market_key), str(side), line, price)
            if best_score is None or score > best_score:
                best_score = score
                best_row = row
        if best_row is not None:
            selected[(str(event_id), str(market_key), str(side))] = best_row

    # Build no-vig map by event+market from selected sides.
    no_vig_map: dict[tuple[str, str], dict[str, float]] = {}
    for event_id in sorted({k[0] for k in selected.keys()}):
        # moneyline pair
        home = selected.get((event_id, "moneyline", "home"))
        away = selected.get((event_id, "moneyline", "away"))
        if home is not None and away is not None:
            hp = _safe_float(home.get("latest_price"))
            ap = _safe_float(away.get("latest_price"))
            if hp is not None and ap is not None:
                h_novig, a_novig = _devig_two_way(hp, ap)
                no_vig_map[(event_id, "moneyline")] = {"home": h_novig, "away": a_novig}

        # total pair
        over = selected.get((event_id, "total", "over"))
        under = selected.get((event_id, "total", "under"))
        if over is not None and under is not None:
            op = _safe_float(over.get("latest_price"))
            up = _safe_float(under.get("latest_price"))
            if op is not None and up is not None:
                o_novig, u_novig = _devig_two_way(op, up)
                no_vig_map[(event_id, "total")] = {"over": o_novig, "under": u_novig}

    # Candidate creation.
    for (event_id, market_key, side), row in selected.items():
        projection = proj.get(str(event_id))
        if projection is None:
            continue

        model_margin = _safe_float(projection.get("model_margin_home"))
        model_total = _safe_float(projection.get("model_total_baseline"))
        price = _safe_float(row.get("latest_price"))
        line = _safe_float(row.get("latest_point"))
        if price is None:
            continue

        raw_prob = None
        push_prob = 0.0
        loss_prob = None

        if market_key == "moneyline":
            if model_margin is None:
                continue
            raw_prob, push_prob, loss_prob = _moneyline_probability_from_margin(model_margin, side)
        elif market_key == "total":
            if model_total is None or line is None:
                continue
            total_probs = total_outcome_probabilities(model_total=model_total, side=side, total_point=line)
            if total_probs.status != "AVAILABLE":
                continue
            raw_prob = total_probs.win
            push_prob = total_probs.push
            loss_prob = total_probs.loss
        else:
            continue

        calibrated_prob = apply_guarded_isotonic(raw_prob)
        if calibrated_prob is None:
            calibrated_prob = raw_prob

        implied = _implied_probability(price)
        novig = no_vig_map.get((event_id, market_key), {}).get(side)
        if novig is None:
            novig = implied

        raw_edge = float(raw_prob - novig)
        cal_edge = float(calibrated_prob - novig)
        ev = float(ev_per_dollar_with_push(win_probability=calibrated_prob, push_probability=push_prob, american_odds=price))

        if market_key == "moneyline":
            family = "MONEYLINE"
            team = str(row.get("home_team") if side == "home" else row.get("away_team"))
            selection = team
            period = "FULL_GAME"
        else:
            family = "TOTAL"
            team = None
            selection = f"{side.upper()} {line:g}" if line is not None else side.upper()
            period = "FULL_GAME"

        snapshot_payload = {
            "eventId": event_id,
            "market": market_key,
            "side": side,
            "line": line,
            "price": price,
            "sportsbook": str(row.get("sportsbook") or ""),
            "lastSeen": str(row.get("last_seen") or ""),
        }
        source_odds_snapshot_id = _sha256(_canonical_json(snapshot_payload))

        candidate = {
            "runId": run_id,
            "candidateId": _candidate_id(run_id, event_id, market_key, side, str(row.get("sportsbook") or ""), line, price),
            "createdAtUTC": created_at,
            "season": int(season),
            "week": int(week),
            "eventId": event_id,
            "commenceTime": str(row.get("commence_time") or ""),
            "marketFamily": family,
            "marketKey": market_key,
            "period": period,
            "selection": selection,
            "side": side,
            "teamCode": team,
            "line": line,
            "sportsbook": str(row.get("sportsbook") or ""),
            "americanPrice": price,
            "rawModelProbability": float(raw_prob),
            "calibratedProbability": float(calibrated_prob),
            "marketImpliedProbability": float(implied),
            "marketNoVigProbability": float(novig),
            "rawEdge": raw_edge,
            "calibratedEdge": cal_edge,
            "pushProbability": float(push_prob),
            "lossProbability": float(loss_prob) if loss_prob is not None else float(max(0.0, 1.0 - calibrated_prob - push_prob)),
            "ev": ev,
            "modelVersion": settings.DEFAULT_MODEL_VERSION,
            "probabilityEngineVersion": settings.DEFAULT_PROBABILITY_ENGINE_VERSION,
            "calibrationVersion": settings.DEFAULT_CALIBRATION_VERSION,
            "rankingVersion": "shadow_rank_v1",
            "qualificationVersion": "shadow_qualification_v1",
            "gitCommitHash": settings.DEFAULT_GIT_COMMIT_HASH,
            "marketSnapshotTimestamp": str(row.get("last_seen") or ""),
            "sourceOddsSnapshotId": source_odds_snapshot_id,
            "marketRank": None,
            "weekRank": None,
            "qualificationStatus": "QUALIFIED" if ev >= float(settings.MIN_PLAYABLE_EV) else "WATCH",
            "productionEligible": False,
            "crossMarketComparable": False,
        }
        candidates.append(candidate)

    # Independent ranking by market family.
    qualified = [c for c in candidates if c["qualificationStatus"] == "QUALIFIED"]
    for family in ["MONEYLINE", "TOTAL"]:
        fam = [c for c in qualified if c["marketFamily"] == family]
        fam.sort(key=lambda x: (-x["calibratedEdge"], -x["ev"], -x["rawModelProbability"], x["eventId"], x["side"]))
        for idx, c in enumerate(fam, start=1):
            c["marketRank"] = idx

    # week rank per family includes non-qualified after qualified.
    for family in ["MONEYLINE", "TOTAL"]:
        fam = [c for c in candidates if c["marketFamily"] == family]
        fam.sort(
            key=lambda x: (
                0 if x["qualificationStatus"] == "QUALIFIED" else 1,
                -x["calibratedEdge"],
                -x["ev"],
                x["eventId"],
                x["side"],
            )
        )
        for idx, c in enumerate(fam, start=1):
            c["weekRank"] = idx

    attach_shadow_global_scores(candidates)

    source_market_timestamp = ""
    if len(working):
        source_market_timestamp = str(working["last_seen"].dropna().max()) if "last_seen" in working.columns else ""

    run_payload = {
        "runId": run_id,
        "createdAtUTC": created_at,
        "season": int(season),
        "week": int(week),
        "sourceSnapshotId": _sha256(_canonical_json({"runId": run_id, "season": season, "week": week})),
        "sourceMarketTimestamp": source_market_timestamp,
    }

    _save_shadow_run(run_payload, candidates)

    return {
        "runId": run_id,
        "createdAtUTC": created_at,
        "season": int(season),
        "week": int(week),
        "sourceSnapshotId": run_payload["sourceSnapshotId"],
        "sourceMarketTimestamp": source_market_timestamp,
        "candidateCount": len(candidates),
        "moneylineCount": len([c for c in candidates if c["marketFamily"] == "MONEYLINE"]),
        "totalCount": len([c for c in candidates if c["marketFamily"] == "TOTAL"]),
    }


def _latest_run(season: Optional[int] = None, week: Optional[int] = None) -> Optional[sqlite3.Row]:
    _ensure_schema()
    con = _connect()
    where = []
    params: list[Any] = []
    if season is not None:
        where.append("season = ?")
        params.append(int(season))
    if week is not None:
        where.append("week = ?")
        params.append(int(week))
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    row = con.execute(
        f"SELECT * FROM shadow_candidate_runs {where_sql} ORDER BY created_at_utc DESC, id DESC LIMIT 1",
        params,
    ).fetchone()
    con.close()
    return row


def publish_shadow_snapshot(
    *,
    season: Optional[int] = None,
    week: Optional[int] = None,
    run_id: Optional[str] = None,
    publication_type: str = "SHADOW_MULTI_MARKET",
    is_official: bool = True,
    official_cadence: Optional[str] = None,
) -> dict[str, Any]:
    _ensure_schema()
    con = _connect()

    if run_id:
        run = con.execute("SELECT * FROM shadow_candidate_runs WHERE run_id = ?", [run_id]).fetchone()
    else:
        where = []
        params: list[Any] = []
        if season is not None:
            where.append("season = ?")
            params.append(int(season))
        if week is not None:
            where.append("week = ?")
            params.append(int(week))
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        run = con.execute(
            f"SELECT * FROM shadow_candidate_runs {where_sql} ORDER BY created_at_utc DESC, id DESC LIMIT 1",
            params,
        ).fetchone()

    if run is None:
        con.close()
        raise ValueError("No shadow candidate run available for publication")

    season_val = int(run["season"])
    week_val = int(run["week"])

    if is_official:
        existing_official = con.execute(
            "SELECT shadow_snapshot_id FROM shadow_publications WHERE season = ? AND week = ? AND is_official = 1 ORDER BY created_at_utc DESC, id DESC LIMIT 1",
            [season_val, week_val],
        ).fetchone()
        if existing_official is not None:
            con.close()
            raise ValueError("Official shadow snapshot already exists for this season/week")

    candidates = con.execute(
        "SELECT * FROM shadow_candidates WHERE run_id = ? ORDER BY market_family, week_rank ASC, id ASC",
        [run["run_id"]],
    ).fetchall()

    payload = {
        "runId": run["run_id"],
        "season": season_val,
        "week": week_val,
        "publicationType": publication_type,
        "isOfficial": bool(is_official),
        "candidateIds": [str(r["candidate_id"]) for r in candidates],
    }
    canonical_payload = _canonical_json(payload)
    payload_hash = _sha256(canonical_payload)
    idempotency_key = _sha256(f"shadow-publication:{payload_hash}")
    shadow_snapshot_id = str(uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key))

    existing = con.execute("SELECT * FROM shadow_publications WHERE idempotency_key = ?", [idempotency_key]).fetchone()
    if existing is not None:
        con.close()
        return {
            "shadowSnapshotId": existing["shadow_snapshot_id"],
            "created": False,
            "season": int(existing["season"]),
            "week": int(existing["week"]),
            "itemCount": int(existing["item_count"]),
        }

    created_at = _utc_now_iso()
    con.execute(
        """
        INSERT INTO shadow_publications (
            shadow_snapshot_id, run_id, created_at_utc,
            season, week, publication_type, official_cadence,
            is_official, item_count, payload_hash, canonical_payload, idempotency_key
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            shadow_snapshot_id,
            run["run_id"],
            created_at,
            season_val,
            week_val,
            publication_type,
            official_cadence or settings.OFFICIAL_SIA3_CADENCE,
            1 if is_official else 0,
            len(candidates),
            payload_hash,
            canonical_payload,
            idempotency_key,
        ],
    )

    for r in candidates:
        con.execute(
            """
            INSERT INTO shadow_publication_items (
                shadow_snapshot_id, candidate_id,
                season, week, event_id, commence_time,
                market_family, market_key, period,
                selection, side, team_code,
                line, sportsbook, american_price,
                raw_model_probability, calibrated_probability,
                market_implied_probability, market_no_vig_probability,
                raw_edge, calibrated_edge, push_probability, loss_probability, current_ev,
                model_version, probability_engine_version, calibration_version,
                ranking_version, qualification_version, git_commit_hash,
                market_snapshot_timestamp, source_odds_snapshot_id,
                market_rank, week_rank, qualification_status,
                global_research_score, global_research_rank,
                normalization_method, normalization_version,
                production_eligible, cross_market_comparable
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                shadow_snapshot_id,
                r["candidate_id"],
                r["season"],
                r["week"],
                r["event_id"],
                r["commence_time"],
                r["market_family"],
                r["market_key"],
                r["period"],
                r["selection"],
                r["side"],
                r["team_code"],
                r["line"],
                r["sportsbook"],
                r["american_price"],
                r["raw_model_probability"],
                r["calibrated_probability"],
                r["market_implied_probability"],
                r["market_no_vig_probability"],
                r["raw_edge"],
                r["calibrated_edge"],
                r["push_probability"],
                r["loss_probability"],
                r["current_ev"],
                r["model_version"],
                r["probability_engine_version"],
                r["calibration_version"],
                r["ranking_version"],
                r["qualification_version"],
                r["git_commit_hash"],
                r["market_snapshot_timestamp"],
                r["source_odds_snapshot_id"],
                r["market_rank"],
                r["week_rank"],
                r["qualification_status"],
                r["global_research_score"],
                r["global_research_rank"],
                r["normalization_method"],
                r["normalization_version"],
                r["production_eligible"],
                r["cross_market_comparable"],
            ],
        )

    con.commit()
    con.close()

    return {
        "shadowSnapshotId": shadow_snapshot_id,
        "created": True,
        "season": season_val,
        "week": week_val,
        "itemCount": len(candidates),
        "publicationType": publication_type,
        "officialCadence": official_cadence or settings.OFFICIAL_SIA3_CADENCE,
    }


def _profit_per_dollar(price: float, result: str) -> float:
    if result == "PUSH":
        return 0.0
    if result == "LOSS":
        return -1.0
    if price < 0:
        return float(100.0 / abs(price))
    return float(price / 100.0)


def append_shadow_outcomes(
    *,
    fetch_scores_fn: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
) -> dict[str, int]:
    _ensure_schema()

    if fetch_scores_fn is None:
        def _none_fetch(_: str) -> Optional[dict[str, Any]]:
            return None
        fetch_scores_fn = _none_fetch

    con = _connect()
    pending = con.execute(
        """
        SELECT i.*
        FROM shadow_publication_items i
        WHERE NOT EXISTS (
            SELECT 1 FROM shadow_outcomes o
            WHERE o.candidate_id = i.candidate_id
        )
        """
    ).fetchall()

    appended = 0
    still_pending = 0

    for r in pending:
        score = fetch_scores_fn(str(r["event_id"]))
        if not score:
            still_pending += 1
            continue

        away = score.get("finalAwayScore")
        home = score.get("finalHomeScore")
        if away is None or home is None:
            still_pending += 1
            continue

        market_family = str(r["market_family"]).upper()
        side = str(r["side"] or "").lower()
        line = _safe_float(r["line"])
        price = _safe_float(r["american_price"])
        if price is None:
            still_pending += 1
            continue

        result = None
        if market_family == "MONEYLINE":
            if side == "home":
                result = "WIN" if int(home) > int(away) else "LOSS"
            elif side == "away":
                result = "WIN" if int(away) > int(home) else "LOSS"
        elif market_family == "TOTAL":
            if line is None:
                still_pending += 1
                continue
            total = float(home) + float(away)
            if side == "over":
                result = "WIN" if total > line else "LOSS" if total < line else "PUSH"
            elif side == "under":
                result = "WIN" if total < line else "LOSS" if total > line else "PUSH"

        if result is None:
            still_pending += 1
            continue

        # Closing and CLV from immutable recommendation price/line, never substituted by current odds.
        closing_line = None
        closing_price = None
        closing_market_novig_probability = None
        closing_timestamp = None
        clv = None
        clv_type = None

        commence = str(r["commence_time"] or "")
        kickoff = _parse_commence(commence)
        if kickoff is not None:
            market_key = "h2h" if market_family == "MONEYLINE" else "totals"
            try:
                close = get_closing_line(
                    event_id=str(r["event_id"]),
                    bookmaker_key=str(r["sportsbook"] or ""),
                    market_key=market_key,
                    outcome_code=side,
                    kickoff_utc=kickoff,
                )
                if close.closing_status == "AVAILABLE":
                    closing_line = close.closing_point
                    closing_price = close.closing_price
                    if closing_price is not None:
                        # True no-vig requires both sides; persist implied probability for this side when only one quote is available.
                        closing_market_novig_probability = _implied_probability(float(closing_price))
                    closing_timestamp = close.closing_timestamp.isoformat() if close.closing_timestamp else None

                    clv_obj = calculate_clv(
                        recommended_point=_safe_float(r["line"]),
                        recommended_price=price,
                        closing_point=closing_line,
                        closing_price=closing_price,
                        market=market_key,
                        side=side,
                    )
                    if clv_obj.clv_points is not None:
                        clv = float(clv_obj.clv_points)
                        clv_type = "POINTS"
                    elif clv_obj.clv_percent is not None:
                        clv = float(clv_obj.clv_percent)
                        clv_type = "PERCENT"
            except Exception:
                pass

        payload = {
            "candidateId": r["candidate_id"],
            "result": result,
            "finalAwayScore": int(away),
            "finalHomeScore": int(home),
            "profitPerDollar": _profit_per_dollar(price, result),
            "closingLine": closing_line,
            "closingPrice": closing_price,
            "closingMarketNoVigProbability": closing_market_novig_probability,
            "closingTimestamp": closing_timestamp,
            "clv": clv,
            "clvType": clv_type,
        }
        canonical = _canonical_json(payload)
        p_hash = _sha256(canonical)
        idem = _sha256(f"shadow-outcome:{p_hash}")
        outcome_id = str(uuid.uuid5(uuid.NAMESPACE_URL, idem))

        con.execute(
            """
            INSERT OR IGNORE INTO shadow_outcomes (
                outcome_id, shadow_snapshot_id, candidate_id, captured_at_utc,
                final_away_score, final_home_score, result, profit_per_dollar,
                closing_line, closing_price, closing_market_novig_probability, closing_timestamp,
                clv, clv_type,
                source_odds_snapshot_id, payload_hash, canonical_payload, idempotency_key
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                outcome_id,
                r["shadow_snapshot_id"],
                r["candidate_id"],
                _utc_now_iso(),
                int(away),
                int(home),
                result,
                payload["profitPerDollar"],
                closing_line,
                closing_price,
                closing_market_novig_probability,
                closing_timestamp,
                clv,
                clv_type,
                r["source_odds_snapshot_id"],
                p_hash,
                canonical,
                idem,
            ],
        )
        appended += 1

    con.commit()
    con.close()
    return {"checked": len(pending), "appended": appended, "pending": still_pending}


def _extract_numeric_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT i.*, o.result, o.profit_per_dollar, o.clv
        FROM shadow_publication_items i
        LEFT JOIN shadow_outcomes o ON o.candidate_id = i.candidate_id
        """
    ).fetchall()


def _brier(y: list[float], p: list[float]) -> Optional[float]:
    if not y or not p:
        return None
    return float(sum((pi - yi) ** 2 for yi, pi in zip(y, p)) / len(y))


def _logloss(y: list[float], p: list[float]) -> Optional[float]:
    if not y or not p:
        return None
    vals = []
    for yi, pi in zip(y, p):
        q = min(1 - 1e-6, max(1e-6, pi))
        vals.append(-(yi * math.log(q) + (1 - yi) * math.log(1 - q)))
    return float(sum(vals) / len(vals))


def _roi_ci(profits: list[float], n_boot: int = 1000) -> Optional[tuple[float, float]]:
    if not profits:
        return None
    import random

    rng = random.Random(2026)
    samples = []
    n = len(profits)
    for _ in range(n_boot):
        draw = [profits[rng.randrange(0, n)] for _ in range(n)]
        samples.append(sum(draw) / n)
    samples.sort()
    lo = samples[int(0.025 * len(samples))]
    hi = samples[int(0.975 * len(samples))]
    return float(lo), float(hi)


def shadow_performance_report() -> dict[str, Any]:
    _ensure_schema()
    con = _connect()
    rows = _extract_numeric_rows(con)
    con.close()

    by_market: dict[str, dict[str, Any]] = {}
    for fam in ["MONEYLINE", "TOTAL"]:
        fam_rows = [r for r in rows if str(r["market_family"]).upper() == fam]
        graded = [r for r in fam_rows if r["result"] in {"WIN", "LOSS", "PUSH"}]

        wins = sum(1 for r in graded if r["result"] == "WIN")
        losses = sum(1 for r in graded if r["result"] == "LOSS")
        pushes = sum(1 for r in graded if r["result"] == "PUSH")
        win_rate = (wins / (wins + losses)) if (wins + losses) > 0 else None

        profits = [float(r["profit_per_dollar"]) for r in graded if r["profit_per_dollar"] is not None]
        roi = (sum(profits) / len(profits)) if profits else None
        roi_ci = _roi_ci(profits)

        y = [1.0 if r["result"] == "WIN" else 0.0 for r in graded if r["result"] != "PUSH"]
        p_model = [float(r["calibrated_probability"]) for r in graded if r["result"] != "PUSH" and r["calibrated_probability"] is not None]
        p_market = [float(r["market_no_vig_probability"]) for r in graded if r["result"] != "PUSH" and r["market_no_vig_probability"] is not None]

        b_model = _brier(y, p_model) if len(y) == len(p_model) else None
        l_model = _logloss(y, p_model) if len(y) == len(p_model) else None
        b_mkt = _brier(y, p_market) if len(y) == len(p_market) else None
        l_mkt = _logloss(y, p_market) if len(y) == len(p_market) else None

        avg_edge = None
        avg_ev = None
        if fam_rows:
            edges = [float(r["calibrated_edge"]) for r in fam_rows if r["calibrated_edge"] is not None]
            evs = [float(r["current_ev"]) for r in fam_rows if r["current_ev"] is not None]
            avg_edge = (sum(edges) / len(edges)) if edges else None
            avg_ev = (sum(evs) / len(evs)) if evs else None

        clv_vals = [float(r["clv"]) for r in graded if r["clv"] is not None]
        avg_clv = (sum(clv_vals) / len(clv_vals)) if clv_vals else None

        # Breakdown
        by_rank: dict[str, int] = {}
        by_global_research_rank: dict[str, int] = {}
        by_edge_band: dict[str, int] = {}
        by_ev_band: dict[str, int] = {}
        by_book: dict[str, int] = {}
        by_week: dict[str, int] = {}
        for r in fam_rows:
            rank = int(r["market_rank"] or 0)
            if rank:
                by_rank[f"{rank}"] = by_rank.get(f"{rank}", 0) + 1

            global_rank = int(r["global_research_rank"] or 0)
            if global_rank:
                by_global_research_rank[f"{global_rank}"] = by_global_research_rank.get(f"{global_rank}", 0) + 1

            edge = float(r["calibrated_edge"] or 0.0)
            ev = float(r["current_ev"] or 0.0)
            by_edge_band[_score_to_band(abs(edge), EDGE_BANDS)] = by_edge_band.get(_score_to_band(abs(edge), EDGE_BANDS), 0) + 1
            by_ev_band[_score_to_band(max(0.0, ev), EV_BANDS)] = by_ev_band.get(_score_to_band(max(0.0, ev), EV_BANDS), 0) + 1

            book = str(r["sportsbook"] or "UNKNOWN")
            by_book[book] = by_book.get(book, 0) + 1

            wk = f"{int(r['season'])}-W{int(r['week'])}"
            by_week[wk] = by_week.get(wk, 0) + 1

        by_market[fam] = {
            "bets": len(graded),
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "winRate": win_rate,
            "roi": roi,
            "roiCI95": list(roi_ci) if roi_ci else None,
            "brier": b_model,
            "logLoss": l_model,
            "marketBrier": b_mkt,
            "marketLogLoss": l_mkt,
            "modelMinusMarketBrier": None if b_model is None or b_mkt is None else (b_model - b_mkt),
            "modelMinusMarketLogLoss": None if l_model is None or l_mkt is None else (l_model - l_mkt),
            "averageEdge": avg_edge,
            "averageEV": avg_ev,
            "averageCLV": avg_clv,
            "bySeasonWeek": by_week,
            "byRank": by_rank,
            "byGlobalResearchRank": by_global_research_rank,
            "byEdgeBand": by_edge_band,
            "byEVBand": by_ev_band,
            "bySportsbook": by_book,
            "topRanksTracked": {
                "top1": by_rank.get("1", 0),
                "top2": by_rank.get("2", 0),
                "top3": by_rank.get("3", 0),
                "top5": sum(v for k, v in by_rank.items() if k.isdigit() and int(k) <= 5),
                "top10": sum(v for k, v in by_rank.items() if k.isdigit() and int(k) <= 10),
            },
            "globalResearchTopRanksTracked": {
                "top1": by_global_research_rank.get("1", 0),
                "top2": by_global_research_rank.get("2", 0),
                "top3": by_global_research_rank.get("3", 0),
                "top5": sum(v for k, v in by_global_research_rank.items() if k.isdigit() and int(k) <= 5),
                "top10": sum(v for k, v in by_global_research_rank.items() if k.isdigit() and int(k) <= 10),
            },
        }

    return {
        "datasetLabel": "PROSPECTIVE SHADOW TRACK RECORD",
        "markets": by_market,
    }


def shadow_promotion_gates() -> dict[str, Any]:
    report = shadow_performance_report()

    gates = {}
    for fam, data in report.get("markets", {}).items():
        sample_ok = int(data.get("bets") or 0) >= 100
        brier_ok = (data.get("modelMinusMarketBrier") is not None) and (float(data["modelMinusMarketBrier"]) <= 0.0)
        ll_ok = (data.get("modelMinusMarketLogLoss") is not None) and (float(data["modelMinusMarketLogLoss"]) <= 0.0)

        roi_ci = data.get("roiCI95")
        roi_ok = bool(roi_ci and roi_ci[0] is not None and float(roi_ci[0]) >= 0.0)

        eligible = bool(sample_ok and brier_ok and ll_ok and roi_ok)

        gates[fam] = {
            "productionEligibility": "YES" if eligible else "NO",
            "criteria": {
                "sufficientProspectiveSample": sample_ok,
                "brierVsNoVigMarket": brier_ok,
                "logLossVsNoVigMarket": ll_ok,
                "roiCI": roi_ok,
                "calibrationQualityAvailable": data.get("brier") is not None and data.get("logLoss") is not None,
                "clvAvailable": data.get("averageCLV") is not None,
                "seasonStabilityAvailable": bool(data.get("bySeasonWeek")),
            },
            "historicalLabel": "MARKET-REFERENCE BACKTEST",
            "prospectiveLabel": "PROSPECTIVE SHADOW TRACK RECORD",
        }

    return {"markets": gates}


def _odds_api_key() -> str:
    return str(os.getenv("ODDS_API_KEY") or "").strip()


def _call_odds_api(markets: list[str], event_ids: bool = False) -> tuple[int, dict[str, str], Any]:
    api_key = _odds_api_key()
    if not api_key:
        return 0, {}, {"error": "ODDS_API_KEY missing"}

    base = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
    query = {
        "apiKey": api_key,
        "regions": "us",
        "markets": ",".join(markets),
        "oddsFormat": "american",
    }
    url = f"{base}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(url, headers={"User-Agent": "SIA-Shadow/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        status = int(resp.status)
        headers = {k.lower(): v for k, v in resp.headers.items()}
        body = resp.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"raw": body}
        return status, headers, parsed


def _summarize_provider_market_response(market_key: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list):
        return {
            "marketKey": market_key,
            "providerAvailability": False,
            "bookCoverage": 0,
            "eventCoverage": 0,
            "lineAvailability": False,
            "priceAvailability": False,
            "timestampAvailability": False,
        }

    books = set()
    events = set()
    has_line = False
    has_price = False
    has_ts = False

    for event in payload:
        event_id = str(event.get("id") or "")
        if event_id:
            events.add(event_id)
        if event.get("commence_time"):
            has_ts = True

        for book in event.get("bookmakers", []) or []:
            bk = str(book.get("key") or "")
            if bk:
                books.add(bk)
            if book.get("last_update"):
                has_ts = True
            for market in book.get("markets", []) or []:
                if str(market.get("key") or "") != market_key:
                    continue
                for outcome in market.get("outcomes", []) or []:
                    if outcome.get("price") is not None:
                        has_price = True
                    if outcome.get("point") is not None:
                        has_line = True

    return {
        "marketKey": market_key,
        "providerAvailability": len(events) > 0,
        "bookCoverage": len(books),
        "eventCoverage": len(events),
        "lineAvailability": has_line,
        "priceAvailability": has_price,
        "timestampAvailability": has_ts,
    }


def discover_expanded_markets() -> dict[str, Any]:
    targets = {
        "TEAM_TOTAL": ["team_totals"],
        "1H_SPREAD": ["spreads_h1"],
        "1H_MONEYLINE": ["h2h_h1"],
        "1H_TOTAL": ["totals_h1"],
        "1H_TEAM_TOTAL": ["team_totals_h1"],
    }

    request_count = 0
    per_target = {}
    quota = {}

    for label, keys in targets.items():
        supported = None
        selected_summary = None
        selected_key = None
        selected_payload = None
        errors = []

        for key in keys:
            request_count += 1
            try:
                status, headers, payload = _call_odds_api([key])
                quota = {
                    "remaining": headers.get("x-requests-remaining"),
                    "used": headers.get("x-requests-used"),
                    "last": headers.get("x-requests-last"),
                }
                summary = _summarize_provider_market_response(key, payload)
                if status == 200 and summary["providerAvailability"]:
                    supported = True
                    selected_summary = summary
                    selected_key = key
                    selected_payload = payload
                    break
                errors.append({"marketKey": key, "status": status, "detail": payload if isinstance(payload, dict) else None})
            except Exception as exc:
                errors.append({"marketKey": key, "status": "EXCEPTION", "detail": str(exc)})

        if supported is None:
            supported = False
            selected_summary = {
                "marketKey": keys[0],
                "providerAvailability": False,
                "bookCoverage": 0,
                "eventCoverage": 0,
                "lineAvailability": False,
                "priceAvailability": False,
                "timestampAvailability": False,
            }

        per_target[label] = {
            "supported": supported,
            "selectedMarketKey": selected_key,
            "summary": selected_summary,
            "errors": errors,
            "samplePayload": selected_payload if supported else None,
        }

    return {
        "targets": per_target,
        "estimatedRequestCost": request_count,
        "quota": quota,
    }


def ingest_expanded_market_snapshots(discovery: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    _ensure_schema()
    if discovery is None:
        discovery = discover_expanded_markets()

    saved = 0
    con = _connect()

    for _, info in (discovery.get("targets") or {}).items():
        if not info.get("supported"):
            continue
        market_key = str(info.get("selectedMarketKey") or "")
        payload = info.get("samplePayload")
        if not isinstance(payload, list):
            continue

        for event in payload:
            event_id = str(event.get("id") or "")
            for book in event.get("bookmakers", []) or []:
                bookmaker = str(book.get("key") or "")
                fetched_at = str(book.get("last_update") or event.get("commence_time") or "")
                for market in book.get("markets", []) or []:
                    if str(market.get("key") or "") != market_key:
                        continue
                    for outcome in market.get("outcomes", []) or []:
                        selection = str(outcome.get("name") or "")
                        line = _safe_float(outcome.get("point"))
                        price = _safe_float(outcome.get("price"))

                        period = "FIRST_HALF" if "_h1" in market_key else "FULL_GAME"
                        family = "TEAM_TOTAL" if "team_totals" in market_key else "FIRST_HALF" if "_h1" in market_key else "OTHER"

                        payload_row = {
                            "eventId": event_id,
                            "providerEventId": event_id,
                            "marketFamily": family,
                            "marketKey": market_key,
                            "period": period,
                            "teamCode": None,
                            "selection": selection,
                            "line": line,
                            "price": price,
                            "bookmaker": bookmaker,
                            "fetchedAt": fetched_at,
                        }
                        canonical = _canonical_json(payload_row)
                        p_hash = _sha256(canonical)
                        idem = _sha256(f"shadow-market:{p_hash}")
                        snapshot_id = str(uuid.uuid5(uuid.NAMESPACE_URL, idem))

                        con.execute(
                            """
                            INSERT OR IGNORE INTO shadow_market_snapshots (
                                snapshot_id, captured_at_utc,
                                event_id, provider_event_id,
                                market_family, market_key, period, team_code, selection,
                                line, price, bookmaker, fetched_at,
                                payload_hash, canonical_payload, idempotency_key
                            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                            """,
                            [
                                snapshot_id,
                                _utc_now_iso(),
                                event_id,
                                event_id,
                                family,
                                market_key,
                                period,
                                None,
                                selection,
                                line,
                                price,
                                bookmaker,
                                fetched_at,
                                p_hash,
                                canonical,
                                idem,
                            ],
                        )
                        saved += 1

    con.commit()
    con.close()
    return {"rowsSaved": saved}


def discover_player_props() -> dict[str, Any]:
    keys = [
        "player_pass_yds",
        "player_pass_tds",
        "player_pass_attempts",
        "player_pass_completions",
        "player_pass_interceptions",
        "player_rush_yds",
        "player_rush_attempts",
        "player_reception_yds",
        "player_receptions",
        "player_anytime_td",
    ]

    results = []
    quota = {}
    request_count = 0
    sampled_players: list[dict[str, Any]] = []

    for key in keys:
        request_count += 1
        try:
            status, headers, payload = _call_odds_api([key])
            quota = {
                "remaining": headers.get("x-requests-remaining"),
                "used": headers.get("x-requests-used"),
                "last": headers.get("x-requests-last"),
            }
            summary = _summarize_provider_market_response(key, payload)

            has_ou_price = False
            player_formats = set()
            books = set()
            has_player_team_meta = False
            event_map = set()
            if isinstance(payload, list):
                for event in payload:
                    if event.get("id"):
                        event_map.add(str(event.get("id")))
                    for book in event.get("bookmakers", []) or []:
                        books.add(str(book.get("key") or ""))
                        for market in book.get("markets", []) or []:
                            if str(market.get("key") or "") != key:
                                continue
                            for outcome in market.get("outcomes", []) or []:
                                name = str(outcome.get("name") or "").strip()
                                if name:
                                    player_formats.add(name)
                                if outcome.get("description"):
                                    has_player_team_meta = True
                                if outcome.get("price") is not None:
                                    has_ou_price = True
                                if len(sampled_players) < 100:
                                    sampled_players.append(
                                        {
                                            "providerMarketKey": key,
                                            "eventId": str(event.get("id") or ""),
                                            "book": str(book.get("key") or ""),
                                            "name": name,
                                            "description": str(outcome.get("description") or ""),
                                            "line": _safe_float(outcome.get("point")),
                                            "price": _safe_float(outcome.get("price")),
                                        }
                                    )

            results.append(
                {
                    "marketKey": key,
                    "providerAvailability": status == 200 and summary["providerAvailability"],
                    "availableBooks": len(books) if books else summary["bookCoverage"],
                    "lineExists": summary["lineAvailability"],
                    "overUnderPriceExists": has_ou_price,
                    "playerNameFormatExamples": sorted(list(player_formats))[:10],
                    "playerTeamMetadataPresent": has_player_team_meta,
                    "eventMappingCount": len(event_map) if event_map else summary["eventCoverage"],
                    "status": status,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "marketKey": key,
                    "providerAvailability": False,
                    "availableBooks": 0,
                    "lineExists": False,
                    "overUnderPriceExists": False,
                    "playerNameFormatExamples": [],
                    "playerTeamMetadataPresent": False,
                    "eventMappingCount": 0,
                    "status": "EXCEPTION",
                    "error": str(exc),
                }
            )

    return {
        "markets": results,
        "sampledPlayers": sampled_players,
        "estimatedRequestCost": request_count,
        "quota": quota,
    }


def player_identity_mapping_plan(sampled_players: list[dict[str, Any]]) -> dict[str, Any]:
    import duckdb  # type: ignore

    db = MODEL_ROOT / "database" / "nfl_model.duckdb"
    if not db.exists():
        return {
            "exactMatchRate": 0.0,
            "normalizedMatchRate": 0.0,
            "ambiguousMatches": [],
            "unmatchedPlayers": [p.get("name") for p in sampled_players if p.get("name")],
            "feasible": False,
            "reason": "nfl_model.duckdb not found",
        }

    con = duckdb.connect(str(db), read_only=True)
    table_rows = con.execute(
        """
        select distinct cast(player_id as varchar) as player_id,
               cast(player_name as varchar) as player_name,
               cast(team as varchar) as team
        from player_pregame_features
        where player_id is not null and player_name is not null
        """
    ).fetchall()
    con.close()

    exact_map: dict[str, list[tuple[str, str]]] = {}
    norm_map: dict[str, list[tuple[str, str]]] = {}

    def _norm(name: str) -> str:
        return "".join(ch for ch in name.lower() if ch.isalnum())

    for pid, pname, team in table_rows:
        pname_s = str(pname).strip()
        exact_map.setdefault(pname_s, []).append((str(pid), str(team or "")))
        norm_map.setdefault(_norm(pname_s), []).append((str(pid), str(team or "")))

    names = [str(p.get("name") or "").strip() for p in sampled_players if str(p.get("name") or "").strip()]
    unique_names = sorted(set(names))

    exact = 0
    normalized = 0
    ambiguous: list[dict[str, Any]] = []
    unmatched: list[str] = []

    for name in unique_names:
        exact_hits = exact_map.get(name, [])
        if len(exact_hits) == 1:
            exact += 1
            continue
        if len(exact_hits) > 1:
            ambiguous.append({"providerName": name, "method": "exact", "matches": exact_hits})
            continue

        norm_hits = norm_map.get(_norm(name), [])
        if len(norm_hits) == 1:
            normalized += 1
        elif len(norm_hits) > 1:
            ambiguous.append({"providerName": name, "method": "normalized", "matches": norm_hits})
        else:
            unmatched.append(name)

    total = max(1, len(unique_names))
    return {
        "totalDistinctProviderPlayers": len(unique_names),
        "exactMatchRate": exact / total,
        "normalizedMatchRate": normalized / total,
        "ambiguousMatches": ambiguous,
        "unmatchedPlayers": unmatched,
        "feasible": len(ambiguous) == 0,
    }


def universal_candidate_contract_design() -> dict[str, Any]:
    return {
        "version": "universal_candidate_contract_v1_design",
        "identity": {
            "primaryKey": "candidate_uid",
            "deterministicKeyFields": [
                "snapshot_id",
                "event_id",
                "market_family",
                "market_key",
                "period",
                "selection_key",
                "sportsbook",
                "line",
                "price",
            ],
            "collisionPrevention": "sha256 over canonical deterministic key payload",
        },
        "commonFields": [
            "candidate_uid", "snapshot_id", "created_at", "season", "week", "event_id", "commence_time",
            "market_family", "market_key", "period", "selection", "side", "line", "price", "sportsbook",
            "raw_model_probability", "calibrated_probability", "market_implied_probability", "market_no_vig_probability",
            "raw_edge", "calibrated_edge", "push_probability", "ev", "qualification_status",
            "model_version", "probability_engine_version", "calibration_version", "ranking_version", "qualification_version",
        ],
        "marketSpecific": {
            "SPREAD": ["team_code", "spread_point"],
            "MONEYLINE": ["team_code"],
            "TOTAL": ["total_point"],
            "TEAM_TOTAL": ["team_code", "total_point"],
            "FIRST_HALF_SPREAD": ["team_code", "spread_point"],
            "FIRST_HALF_MONEYLINE": ["team_code"],
            "FIRST_HALF_TOTAL": ["total_point"],
            "FIRST_HALF_TEAM_TOTAL": ["team_code", "total_point"],
            "PLAYER_PROP": ["player_id", "player_name", "prop_family", "threshold_point", "direction"],
        },
        "notes": "Nulls are permitted for non-applicable market-specific fields; fake placeholder values are forbidden.",
    }


def correlation_metadata_design() -> dict[str, Any]:
    return {
        "version": "correlation_metadata_v1_design",
        "fields": [
            "event_exposure_key",
            "team_exposure_keys",
            "player_exposure_keys",
            "game_script_direction",
            "dependency_hints",
        ],
        "dependencyExamples": [
            "favorite_spread + favorite_moneyline",
            "favorite_spread + opponent_team_total_under",
            "game_total_over + qb_passing_over",
            "game_total_under + qb_passing_under",
            "wr_receiving_over + qb_passing_over",
        ],
        "policy": "Design-only metadata. No production penalty weights are applied in this phase.",
    }
