from __future__ import annotations

import hashlib
import json
import math
import os
import ssl
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    raw_closing_implied_probability REAL,
    closing_market_novig_probability REAL,
    closing_no_vig_status TEXT,
    closing_timestamp TEXT,
    line_clv_points REAL,
    price_clv_probability REAL,
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
    phase TEXT NOT NULL DEFAULT 'PREGAME',
    period TEXT NOT NULL,
    game_state_timestamp TEXT,
    team_code TEXT,
    selection TEXT NOT NULL,
    side TEXT,

    line REAL,
    price REAL,
    bookmaker TEXT,
    market_timestamp TEXT,
    fetched_at TEXT,
    source_snapshot_id TEXT,

    book_coverage_count INTEGER,
    available_books TEXT,
    best_price_book TEXT,
    consensus_available INTEGER,
    market_depth_status TEXT,

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


PHASE2B_MARKET_FAMILIES: dict[str, dict[str, Any]] = {
    "TEAM_TOTAL": {
        "marketKey": "team_total",
        "providerKeys": ["team_totals"],
        "period": "FULL_GAME",
        "modelAvailable": True,
        "modelValidated": False,
        "shadowEligible": False,
        "productionEligible": False,
        "requiredModelData": ["model_total_baseline", "model_margin_home"],
    },
    "FIRST_HALF_SPREAD": {
        "marketKey": "first_half_spread",
        "providerKeys": ["spreads_h1"],
        "period": "FIRST_HALF",
        "modelAvailable": False,
        "modelValidated": False,
        "shadowEligible": False,
        "productionEligible": False,
        "requiredModelData": ["first_half_margin_model"],
    },
    "FIRST_HALF_MONEYLINE": {
        "marketKey": "first_half_moneyline",
        "providerKeys": ["h2h_h1"],
        "period": "FIRST_HALF",
        "modelAvailable": False,
        "modelValidated": False,
        "shadowEligible": False,
        "productionEligible": False,
        "requiredModelData": ["first_half_win_probability_model"],
    },
    "FIRST_HALF_TOTAL": {
        "marketKey": "first_half_total",
        "providerKeys": ["totals_h1"],
        "period": "FIRST_HALF",
        "modelAvailable": False,
        "modelValidated": False,
        "shadowEligible": False,
        "productionEligible": False,
        "requiredModelData": ["first_half_total_model"],
    },
}


EXPANDED_MARKET_REGISTRY: dict[str, dict[str, str]] = {
    "TEAM_TOTAL": {
        "providerKey": "team_totals",
        "marketFamily": "TEAM_TOTAL",
        "period": "FULL_GAME",
    },
    "FIRST_HALF_SPREAD": {
        "providerKey": "spreads_h1",
        "marketFamily": "FIRST_HALF_SPREAD",
        "period": "FIRST_HALF",
    },
    "FIRST_HALF_MONEYLINE": {
        "providerKey": "h2h_h1",
        "marketFamily": "FIRST_HALF_MONEYLINE",
        "period": "FIRST_HALF",
    },
    "FIRST_HALF_TOTAL": {
        "providerKey": "totals_h1",
        "marketFamily": "FIRST_HALF_TOTAL",
        "period": "FIRST_HALF",
    },
}


_EVENT_DISCOVERY_CACHE: dict[str, Any] = {
    "fetchedAt": None,
    "events": [],
}


def _market_depth_status(book_count: int) -> str:
    if book_count >= 6:
        return "DEEP"
    if book_count >= 3:
        return "MODERATE"
    if book_count == 2:
        return "THIN"
    if book_count == 1:
        return "SINGLE_BOOK"
    return "NO_BOOKS"


MARKET_KEY_TO_FAMILY: dict[str, str] = {
    "spread": "SPREAD",
    "moneyline": "MONEYLINE",
    "total": "TOTAL",
    "team_total": "TEAM_TOTAL",
    "first_half_spread": "FIRST_HALF_SPREAD",
    "first_half_moneyline": "FIRST_HALF_MONEYLINE",
    "first_half_total": "FIRST_HALF_TOTAL",
}


BOOKMAKER_DISPLAY_NAMES: dict[str, str] = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "betmgm": "BetMGM",
    "caesars": "Caesars",
    "espnbet": "ESPN BET",
    "betrivers": "BetRivers",
    "fanatics": "Fanatics",
    "williamhill_us": "Caesars",
}


LINE_SHOPPING_MARKET_KEYS = {
    "spread",
    "moneyline",
    "total",
    "team_total",
    "first_half_spread",
    "first_half_moneyline",
    "first_half_total",
}


PLAYER_PROP_TARGET_MARKETS: dict[str, str] = {
    "player_pass_yds": "PASSING_YARDS",
    "player_pass_tds": "PASSING_TD",
    "player_pass_attempts": "PASSING_ATTEMPTS",
    "player_pass_completions": "PASSING_COMPLETIONS",
    "player_pass_interceptions": "PASSING_INTERCEPTIONS",
    "player_rush_yds": "RUSHING_YARDS",
    "player_rush_attempts": "RUSHING_ATTEMPTS",
    "player_reception_yds": "RECEIVING_YARDS",
    "player_receptions": "RECEPTIONS",
    "player_anytime_td": "ANYTIME_TD",
    "player_first_td": "FIRST_TD",
}

_PLAYER_PROP_TEAM_NAME_TO_CODE: dict[str, str] = {
    "ARIZONA CARDINALS": "ARI",
    "ATLANTA FALCONS": "ATL",
    "BALTIMORE RAVENS": "BAL",
    "BUFFALO BILLS": "BUF",
    "CAROLINA PANTHERS": "CAR",
    "CHICAGO BEARS": "CHI",
    "CINCINNATI BENGALS": "CIN",
    "CLEVELAND BROWNS": "CLE",
    "DALLAS COWBOYS": "DAL",
    "DENVER BRONCOS": "DEN",
    "DETROIT LIONS": "DET",
    "GREEN BAY PACKERS": "GB",
    "HOUSTON TEXANS": "HOU",
    "INDIANAPOLIS COLTS": "IND",
    "JACKSONVILLE JAGUARS": "JAX",
    "KANSAS CITY CHIEFS": "KC",
    "LAS VEGAS RAIDERS": "LV",
    "LOS ANGELES CHARGERS": "LAC",
    "LOS ANGELES RAMS": "LAR",
    "MIAMI DOLPHINS": "MIA",
    "MINNESOTA VIKINGS": "MIN",
    "NEW ENGLAND PATRIOTS": "NE",
    "NEW ORLEANS SAINTS": "NO",
    "NEW YORK GIANTS": "NYG",
    "NEW YORK JETS": "NYJ",
    "PHILADELPHIA EAGLES": "PHI",
    "PITTSBURGH STEELERS": "PIT",
    "SAN FRANCISCO 49ERS": "SF",
    "SEATTLE SEAHAWKS": "SEA",
    "TAMPA BAY BUCCANEERS": "TB",
    "TENNESSEE TITANS": "TEN",
    "WASHINGTON COMMANDERS": "WAS",
}

_PLAYER_PROP_TEAM_ALIASES: dict[str, str] = {
    "LA": "LAR",
    "JAC": "JAX",
}


PLAYER_PROP_SUFFIX_TOKENS = {"JR", "SR", "II", "III", "IV", "V"}


PLAYER_PROP_GRADING_COLUMN_CANDIDATES: dict[str, list[str]] = {
    "PASSING_YARDS": ["pass_yds", "passing_yards", "pass_yards"],
    "PASSING_TD": ["pass_tds", "passing_tds", "pass_td"],
    "PASSING_ATTEMPTS": ["pass_attempts", "passing_attempts"],
    "PASSING_COMPLETIONS": ["pass_completions", "passing_completions"],
    "PASSING_INTERCEPTIONS": ["interceptions", "pass_int", "pass_interceptions"],
    "RUSHING_YARDS": ["rush_yds", "rushing_yards", "rush_yards"],
    "RUSHING_ATTEMPTS": ["rush_attempts", "rushing_attempts"],
    "RECEIVING_YARDS": ["rec_yds", "receiving_yards", "rec_yards"],
    "RECEPTIONS": ["receptions", "rec"],
    "ANYTIME_TD": ["touchdowns", "total_tds", "rush_tds", "rec_tds", "pass_tds"],
    "FIRST_TD": ["first_td_scorer"],
}


PROSPECTIVE_MARKET_FAMILIES = [
    "SPREAD",
    "MONEYLINE",
    "TOTAL",
    "TEAM_TOTAL",
    "FIRST_HALF_SPREAD",
    "FIRST_HALF_MONEYLINE",
    "FIRST_HALF_TOTAL",
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
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS prospective_market_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT NOT NULL UNIQUE,
            captured_at_utc TEXT NOT NULL,

            season INTEGER,
            week INTEGER,
            event_id TEXT NOT NULL,
            provider_event_id TEXT,
            commence_time TEXT,

            market_family TEXT NOT NULL,
            market_key TEXT NOT NULL,
            phase TEXT NOT NULL,
            period TEXT NOT NULL,
            state_label TEXT NOT NULL,
            closing_status TEXT,
            closing_cutoff_utc TEXT,
            closing_max_age_seconds INTEGER,

            team_code TEXT,
            selection TEXT,
            side TEXT,
            line REAL,
            price REAL,
            sportsbook TEXT,
            bookmaker_key TEXT,

            market_timestamp TEXT,
            fetched_at TEXT,
            source_snapshot_id TEXT,

            book_coverage_count INTEGER,
            available_books TEXT,
            market_depth_status TEXT,
            all_books TEXT,
            best_price REAL,
            best_price_book TEXT,
            consensus_line REAL,
            median_line REAL,

            projected_game_total REAL,
            projected_home_margin REAL,
            derived_projected_home_points REAL,
            derived_projected_away_points REAL,
            selected_team_projected_points REAL,

            raw_probability REAL,
            calibrated_probability REAL,
            push_probability REAL,
            loss_probability REAL,
            market_implied_probability REAL,
            market_no_vig_probability REAL,

            edge REAL,
            ev REAL,
            fair_value REAL,
            playable_to REAL,
            si_score REAL,

            market_rank INTEGER,
            global_research_score REAL,
            global_research_rank INTEGER,

            production_eligible INTEGER,
            cross_market_comparable INTEGER,
            market_validation_status TEXT,
            model_state TEXT,
            shadow_recommendations TEXT,

            model_version TEXT,
            probability_engine_version TEXT,
            calibration_version TEXT,
            ranking_version TEXT,
            qualification_policy_version TEXT,
            git_commit_hash TEXT,

            game_state_timestamp TEXT,
            game_quarter INTEGER,
            game_clock TEXT,
            possession TEXT,

            payload_hash TEXT NOT NULL,
            canonical_payload TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE
        );

        CREATE INDEX IF NOT EXISTS idx_prospective_market_state
            ON prospective_market_snapshots(event_id, market_family, period, state_label);

        CREATE INDEX IF NOT EXISTS idx_prospective_market_week
            ON prospective_market_snapshots(season, week, market_family);

        CREATE TABLE IF NOT EXISTS player_prop_market_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT NOT NULL UNIQUE,
            captured_at_utc TEXT NOT NULL,

            season INTEGER,
            week INTEGER,
            event_id TEXT NOT NULL,
            provider_event_id TEXT,
            commence_time TEXT,

            market_family TEXT NOT NULL,
            prop_type TEXT NOT NULL,
            provider_market_key TEXT NOT NULL,
            period TEXT NOT NULL,
            phase TEXT NOT NULL,
            state_label TEXT NOT NULL,
            closing_status TEXT,
            closing_cutoff_utc TEXT,
            closing_max_age_seconds INTEGER,

            provider_player_name TEXT,
            normalized_player_name TEXT,
            player_match_status TEXT,
            provider_player_id TEXT,
            canonical_player_id TEXT,
            player_name TEXT,
            team TEXT,
            opponent TEXT,
            position TEXT,

            selection TEXT,
            side TEXT,
            point REAL,
            price REAL,

            sportsbook TEXT,
            bookmaker_key TEXT,

            market_timestamp TEXT,
            fetched_at TEXT,
            source_snapshot_id TEXT,

            book_coverage_count INTEGER,
            available_books TEXT,
            market_depth_status TEXT,
            all_books TEXT,
            best_market_book TEXT,
            best_market_point REAL,
            best_market_price REAL,
            market_no_vig_probability REAL,
            no_vig_status TEXT,

            production_eligible INTEGER,
            cross_market_comparable INTEGER,
            market_validation_status TEXT,
            model_available INTEGER,
            model_validated INTEGER,
            shadow_recommendation_eligible INTEGER,

            model_version TEXT,
            probability_engine_version TEXT,
            calibration_version TEXT,
            ranking_version TEXT,
            qualification_policy_version TEXT,
            git_commit_hash TEXT,

            game_state_timestamp TEXT,
            game_quarter INTEGER,
            game_clock TEXT,

            payload_hash TEXT NOT NULL,
            canonical_payload TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE
        );

        CREATE INDEX IF NOT EXISTS idx_player_prop_snapshots_state
            ON player_prop_market_snapshots(event_id, prop_type, state_label, phase);

        CREATE INDEX IF NOT EXISTS idx_player_prop_snapshots_week
            ON player_prop_market_snapshots(season, week, prop_type);
        """
    )
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
        ("shadow_outcomes", "raw_closing_implied_probability REAL"),
        ("shadow_outcomes", "closing_market_novig_probability REAL"),
        ("shadow_outcomes", "closing_no_vig_status TEXT"),
        ("shadow_outcomes", "line_clv_points REAL"),
        ("shadow_outcomes", "price_clv_probability REAL"),
        ("shadow_market_snapshots", "phase TEXT DEFAULT 'PREGAME'"),
        ("shadow_market_snapshots", "game_state_timestamp TEXT"),
        ("shadow_market_snapshots", "side TEXT"),
        ("shadow_market_snapshots", "market_timestamp TEXT"),
        ("shadow_market_snapshots", "source_snapshot_id TEXT"),
        ("shadow_market_snapshots", "book_coverage_count INTEGER"),
        ("shadow_market_snapshots", "available_books TEXT"),
        ("shadow_market_snapshots", "best_price_book TEXT"),
        ("shadow_market_snapshots", "consensus_available INTEGER"),
        ("shadow_market_snapshots", "market_depth_status TEXT"),
        ("prospective_market_snapshots", "closing_status TEXT"),
        ("prospective_market_snapshots", "closing_cutoff_utc TEXT"),
        ("prospective_market_snapshots", "closing_max_age_seconds INTEGER"),
        ("prospective_market_snapshots", "all_books TEXT"),
        ("prospective_market_snapshots", "best_price REAL"),
        ("prospective_market_snapshots", "best_price_book TEXT"),
        ("prospective_market_snapshots", "consensus_line REAL"),
        ("prospective_market_snapshots", "median_line REAL"),
        ("prospective_market_snapshots", "projected_game_total REAL"),
        ("prospective_market_snapshots", "projected_home_margin REAL"),
        ("prospective_market_snapshots", "derived_projected_home_points REAL"),
        ("prospective_market_snapshots", "derived_projected_away_points REAL"),
        ("prospective_market_snapshots", "selected_team_projected_points REAL"),
        ("prospective_market_snapshots", "raw_probability REAL"),
        ("prospective_market_snapshots", "calibrated_probability REAL"),
        ("prospective_market_snapshots", "push_probability REAL"),
        ("prospective_market_snapshots", "loss_probability REAL"),
        ("prospective_market_snapshots", "market_implied_probability REAL"),
        ("prospective_market_snapshots", "market_no_vig_probability REAL"),
        ("prospective_market_snapshots", "edge REAL"),
        ("prospective_market_snapshots", "ev REAL"),
        ("prospective_market_snapshots", "fair_value REAL"),
        ("prospective_market_snapshots", "playable_to REAL"),
        ("prospective_market_snapshots", "si_score REAL"),
        ("prospective_market_snapshots", "market_rank INTEGER"),
        ("prospective_market_snapshots", "global_research_score REAL"),
        ("prospective_market_snapshots", "global_research_rank INTEGER"),
        ("prospective_market_snapshots", "production_eligible INTEGER"),
        ("prospective_market_snapshots", "cross_market_comparable INTEGER"),
        ("prospective_market_snapshots", "market_validation_status TEXT"),
        ("prospective_market_snapshots", "model_state TEXT"),
        ("prospective_market_snapshots", "shadow_recommendations TEXT"),
        ("prospective_market_snapshots", "model_version TEXT"),
        ("prospective_market_snapshots", "probability_engine_version TEXT"),
        ("prospective_market_snapshots", "calibration_version TEXT"),
        ("prospective_market_snapshots", "ranking_version TEXT"),
        ("prospective_market_snapshots", "qualification_policy_version TEXT"),
        ("prospective_market_snapshots", "git_commit_hash TEXT"),
        ("prospective_market_snapshots", "game_state_timestamp TEXT"),
        ("prospective_market_snapshots", "game_quarter INTEGER"),
        ("prospective_market_snapshots", "game_clock TEXT"),
        ("prospective_market_snapshots", "possession TEXT"),
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
    if key == "team_totals":
        return "team_total"
    if key == "spreads_h1":
        return "first_half_spread"
    if key == "h2h_h1":
        return "first_half_moneyline"
    if key == "totals_h1":
        return "first_half_total"
    return key


def _normalize_bookmaker_key(value: Any) -> str:
    key = str(value or "").strip().lower()
    aliases = {
        "dk": "draftkings",
        "fd": "fanduel",
        "mgm": "betmgm",
        "czr": "caesars",
    }
    return aliases.get(key, key)


def _normalize_bookmaker_display(value: Any, bookmaker_key: str) -> str:
    raw = str(value or "").strip()
    if raw:
        compact = " ".join(raw.split())
        if compact:
            return compact
    return BOOKMAKER_DISPLAY_NAMES.get(bookmaker_key, bookmaker_key or "UNKNOWN")


def _normalize_player_name(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    for token in [".", ",", "'", "-", "_"]:
        text = text.replace(token, " ")
    parts = [p for p in text.split() if p]
    if parts and parts[-1] in PLAYER_PROP_SUFFIX_TOKENS:
        parts = parts[:-1]
    return " ".join(parts)


def _normalize_player_prop_team_code(value: Any) -> Optional[str]:
    raw = str(value or "").strip().upper()
    if not raw:
        return None
    if raw in _PLAYER_PROP_TEAM_NAME_TO_CODE:
        return _PLAYER_PROP_TEAM_NAME_TO_CODE[raw]
    return _PLAYER_PROP_TEAM_ALIASES.get(raw, raw)


def _dedupe_identity_candidates(candidates: list[dict[str, Optional[str]]]) -> list[dict[str, Optional[str]]]:
    by_player_id: dict[str, dict[str, Optional[str]]] = {}
    without_id: list[dict[str, Optional[str]]] = []
    for c in candidates:
        pid = str(c.get("playerId") or "")
        if pid:
            by_player_id.setdefault(pid, c)
        else:
            without_id.append(c)
    return list(by_player_id.values()) + without_id


def _load_canonical_player_index() -> list[dict[str, Optional[str]]]:
    try:
        import duckdb  # type: ignore
    except Exception:
        return []

    db = MODEL_ROOT / "database" / "nfl_model.duckdb"
    if not db.exists():
        return []

    con = duckdb.connect(str(db), read_only=True)
    try:
        cols = {
            str(r[1]).lower()
            for r in con.execute("PRAGMA table_info('player_pregame_features')").fetchall()
            if len(r) >= 2
        }
        if "player_name" not in cols or "player_id" not in cols:
            return []

        team_expr = "cast(team as varchar) as team" if "team" in cols else "NULL as team"
        pos_expr = "cast(position as varchar) as position" if "position" in cols else "NULL as position"
        rows = con.execute(
            f"""
            SELECT DISTINCT
                cast(player_id as varchar) as player_id,
                cast(player_name as varchar) as player_name,
                {team_expr},
                {pos_expr}
            FROM player_pregame_features
            WHERE player_id is not null and player_name is not null
            """
        ).fetchall()
    finally:
        con.close()

    out: list[dict[str, Optional[str]]] = []
    for pid, pname, team, pos in rows:
        out.append(
            {
                "playerId": str(pid),
                "playerName": str(pname),
                "normalizedPlayerName": _normalize_player_name(pname),
                "team": str(team or "").upper() or None,
                "position": str(pos or "").upper() or None,
            }
        )
    return out


def _resolve_player_identity(
    provider_player_name: str,
    team: Optional[str],
    provider_player_id: Optional[str] = None,
    event_team_codes: Optional[set[str]] = None,
) -> dict[str, Any]:
    candidates = _load_canonical_player_index()
    provider = str(provider_player_name or "").strip()
    normalized = _normalize_player_name(provider)
    team_key = _normalize_player_prop_team_code(team)
    provider_pid = str(provider_player_id or "").strip() or None
    evt_teams = {
        _normalize_player_prop_team_code(code)
        for code in (event_team_codes or set())
        if _normalize_player_prop_team_code(code)
    }

    if not provider:
        return {
            "providerPlayerName": provider,
            "normalizedPlayerName": normalized,
            "matchStatus": "UNMATCHED",
            "canonicalPlayerId": None,
            "canonicalPlayerName": None,
            "position": None,
            "team": team_key,
            "opponent": None,
            "reason": "EMPTY_PROVIDER_NAME",
        }

    if provider_pid:
        id_hits = _dedupe_identity_candidates([
            c for c in candidates
            if str(c.get("playerId") or "") == provider_pid
        ])
        if len(id_hits) == 1:
            hit = id_hits[0]
            return {
                "providerPlayerName": provider,
                "normalizedPlayerName": normalized,
                "matchStatus": "EXACT",
                "canonicalPlayerId": hit.get("playerId"),
                "canonicalPlayerName": hit.get("playerName"),
                "position": hit.get("position"),
                "team": team_key or hit.get("team"),
                "opponent": None,
                "reason": "PROVIDER_PLAYER_ID",
            }

    exact_hits = _dedupe_identity_candidates([
        c for c in candidates
        if str(c.get("playerName") or "").upper() == provider.upper()
        and (team_key is None or c.get("team") == team_key)
    ])
    if len(exact_hits) == 1:
        hit = exact_hits[0]
        return {
            "providerPlayerName": provider,
            "normalizedPlayerName": normalized,
            "matchStatus": "EXACT",
            "canonicalPlayerId": hit.get("playerId"),
            "canonicalPlayerName": hit.get("playerName"),
            "position": hit.get("position"),
            "team": team_key or hit.get("team"),
            "opponent": None,
            "reason": "EXACT_NAME",
        }
    if len(exact_hits) > 1 and evt_teams:
        event_hits = _dedupe_identity_candidates([
            c for c in exact_hits
            if str(c.get("team") or "") in evt_teams
        ])
        if len(event_hits) == 1:
            hit = event_hits[0]
            return {
                "providerPlayerName": provider,
                "normalizedPlayerName": normalized,
                "matchStatus": "EXACT",
                "canonicalPlayerId": hit.get("playerId"),
                "canonicalPlayerName": hit.get("playerName"),
                "position": hit.get("position"),
                "team": team_key or hit.get("team"),
                "opponent": None,
                "reason": "EXACT_NAME_EVENT_TEAM_CONTEXT",
            }
    if len(exact_hits) > 1:
        return {
            "providerPlayerName": provider,
            "normalizedPlayerName": normalized,
            "matchStatus": "AMBIGUOUS",
            "canonicalPlayerId": None,
            "canonicalPlayerName": None,
            "position": None,
            "team": team_key,
            "opponent": None,
            "reason": "DUPLICATE_EXACT_NAME",
        }

    normalized_hits = _dedupe_identity_candidates([
        c for c in candidates
        if str(c.get("normalizedPlayerName") or "") == normalized
        and (team_key is None or c.get("team") == team_key)
    ])
    if len(normalized_hits) == 1:
        hit = normalized_hits[0]
        return {
            "providerPlayerName": provider,
            "normalizedPlayerName": normalized,
            "matchStatus": "NORMALIZED",
            "canonicalPlayerId": hit.get("playerId"),
            "canonicalPlayerName": hit.get("playerName"),
            "position": hit.get("position"),
            "team": team_key or hit.get("team"),
            "opponent": None,
            "reason": "NORMALIZED_NAME",
        }
    if len(normalized_hits) > 1 and evt_teams:
        event_hits = _dedupe_identity_candidates([
            c for c in normalized_hits
            if str(c.get("team") or "") in evt_teams
        ])
        if len(event_hits) == 1:
            hit = event_hits[0]
            return {
                "providerPlayerName": provider,
                "normalizedPlayerName": normalized,
                "matchStatus": "NORMALIZED",
                "canonicalPlayerId": hit.get("playerId"),
                "canonicalPlayerName": hit.get("playerName"),
                "position": hit.get("position"),
                "team": team_key or hit.get("team"),
                "opponent": None,
                "reason": "NORMALIZED_NAME_EVENT_TEAM_CONTEXT",
            }
    if len(normalized_hits) > 1:
        return {
            "providerPlayerName": provider,
            "normalizedPlayerName": normalized,
            "matchStatus": "AMBIGUOUS",
            "canonicalPlayerId": None,
            "canonicalPlayerName": None,
            "position": None,
            "team": team_key,
            "opponent": None,
            "reason": "DUPLICATE_NORMALIZED_NAME",
        }

    return {
        "providerPlayerName": provider,
        "normalizedPlayerName": normalized,
        "matchStatus": "UNMATCHED",
        "canonicalPlayerId": None,
        "canonicalPlayerName": None,
        "position": None,
        "team": team_key,
        "opponent": None,
        "reason": "NO_CANONICAL_MATCH",
    }


def _player_prop_sort_key(side: Optional[str], point: Optional[float], price: Optional[float]) -> tuple[float, float]:
    sd = str(side or "").upper()
    p = float(point) if point is not None else 0.0
    pr = float(price) if price is not None else -9999.0
    if sd == "OVER":
        return (-p, pr)
    if sd == "UNDER":
        return (p, pr)
    return (pr, 0.0)


def _player_prop_two_sided_no_vig(quotes: list[dict[str, Any]], target: dict[str, Any]) -> tuple[Optional[float], str]:
    side = str(target.get("side") or "").upper()
    if side not in {"OVER", "UNDER"}:
        return None, "NOT_APPLICABLE"

    point = _safe_float(target.get("point"))
    book = str(target.get("bookmakerKey") or "")
    ts = str(target.get("marketTimestamp") or "")
    if point is None or not book or not ts:
        return None, "UNAVAILABLE_TWO_SIDED_MARKET"

    over = next(
        (
            q for q in quotes
            if str(q.get("side") or "").upper() == "OVER"
            and _safe_float(q.get("point")) is not None
            and abs(float(_safe_float(q.get("point"))) - float(point)) < 1e-9
            and str(q.get("bookmakerKey") or "") == book
            and str(q.get("marketTimestamp") or "") == ts
            and q.get("price") is not None
        ),
        None,
    )
    under = next(
        (
            q for q in quotes
            if str(q.get("side") or "").upper() == "UNDER"
            and _safe_float(q.get("point")) is not None
            and abs(float(_safe_float(q.get("point"))) - float(point)) < 1e-9
            and str(q.get("bookmakerKey") or "") == book
            and str(q.get("marketTimestamp") or "") == ts
            and q.get("price") is not None
        ),
        None,
    )
    if not over or not under:
        return None, "UNAVAILABLE_TWO_SIDED_MARKET"

    over_nv, under_nv = _devig_two_way(float(over["price"]), float(under["price"]))
    return (over_nv if side == "OVER" else under_nv), "AVAILABLE_TWO_SIDED_MARKET"


def _american_to_decimal(american_odds: Optional[float]) -> Optional[float]:
    if american_odds is None:
        return None
    odds = float(american_odds)
    if odds > 0:
        return float(round(1.0 + (odds / 100.0), 6))
    return float(round(1.0 + (100.0 / abs(odds)), 6))


def _line_shopping_sort_key(market_key: str, side: str, line: Optional[float], price: Optional[float]) -> tuple[float, float]:
    mk = _normalize_market(market_key)
    sd = str(side or "").lower()
    line_value = float(line) if line is not None else 0.0
    price_value = float(price) if price is not None else -9999.0

    if mk in {"moneyline", "first_half_moneyline"}:
        return (price_value, 0.0)

    if mk in {"spread", "first_half_spread"}:
        if sd == "home":
            return (-line_value, price_value)
        return (line_value, price_value)

    if mk in {"total", "first_half_total", "team_total"}:
        if sd == "under":
            return (line_value, price_value)
        return (-line_value, price_value)

    return (price_value, 0.0)


def _quote_freshness(
    *,
    phase: str,
    market_timestamp: Optional[str],
    fetched_at: Optional[str],
    now_utc: Optional[datetime] = None,
) -> str:
    phase_key = str(phase or "PREGAME").upper()
    ts = _parse_iso_for_compare(market_timestamp) or _parse_iso_for_compare(fetched_at)
    if ts is None:
        return "STALE"

    now = now_utc.astimezone(timezone.utc) if now_utc is not None else datetime.now(timezone.utc)
    age_seconds = max(0.0, (now - ts).total_seconds())

    if phase_key == "PREGAME":
        fresh_seconds = int(os.getenv("PREGAME_QUOTE_FRESH_SECONDS", "300"))
        stale_seconds = int(os.getenv("PREGAME_QUOTE_STALE_SECONDS", "1800"))
    else:
        fresh_seconds = int(os.getenv("LIVE_QUOTE_FRESH_SECONDS", "20"))
        stale_seconds = int(os.getenv("LIVE_QUOTE_STALE_SECONDS", "90"))

    if age_seconds <= fresh_seconds:
        return "FRESH"
    if age_seconds <= stale_seconds:
        return "AGING"
    return "STALE"


def _quote_playable_status(
    *,
    market_key: str,
    side: str,
    line: Optional[float],
    price: Optional[float],
    playable_to_line: Optional[float],
    playable_to_price: Optional[float],
    model_state: Optional[str],
) -> str:
    mk = _normalize_market(market_key)
    sd = str(side or "").lower()

    if mk in {"team_total", "first_half_spread", "first_half_moneyline", "first_half_total"}:
        if str(model_state or "").upper() in {"RESEARCH_ONLY", "DATA_COLLECTION_ONLY"}:
            return "UNKNOWN"

    if mk in {"moneyline", "first_half_moneyline"}:
        if playable_to_price is None or price is None:
            return "UNKNOWN"
        return "PLAYABLE" if float(price) >= float(playable_to_price) else "NOT_PLAYABLE"

    if mk in {"spread", "first_half_spread"}:
        if playable_to_line is None or line is None:
            return "UNKNOWN"
        return "PLAYABLE" if float(line) >= float(playable_to_line) else "NOT_PLAYABLE"

    if mk in {"total", "first_half_total", "team_total"}:
        if playable_to_line is None or line is None:
            return "UNKNOWN"
        if sd == "under":
            return "PLAYABLE" if float(line) >= float(playable_to_line) else "NOT_PLAYABLE"
        return "PLAYABLE" if float(line) <= float(playable_to_line) else "NOT_PLAYABLE"

    return "UNKNOWN"


def _market_period_for_key(market_key: str) -> str:
    fam = MARKET_KEY_TO_FAMILY.get(str(market_key), "")
    if fam in {"FIRST_HALF_SPREAD", "FIRST_HALF_MONEYLINE", "FIRST_HALF_TOTAL"}:
        return "FIRST_HALF"
    return "FULL_GAME"


def _team_code_from_row(row: pd.Series, side: str) -> Optional[str]:
    explicit = str(row.get("team_code") or row.get("team") or "").strip().upper()
    if explicit:
        return explicit
    sd = str(side or "").lower()
    if sd == "home":
        return str(row.get("home_team") or "").strip().upper() or None
    if sd == "away":
        return str(row.get("away_team") or "").strip().upper() or None
    return None


def _model_available_for_market(market_key: str) -> bool:
    fam = MARKET_KEY_TO_FAMILY.get(str(market_key), "")
    if fam in PHASE2B_MARKET_FAMILIES:
        return bool(PHASE2B_MARKET_FAMILIES[fam]["modelAvailable"])
    return True


def _shadow_recommendation_eligible_for_market(market_key: str) -> bool:
    fam = MARKET_KEY_TO_FAMILY.get(str(market_key), "")
    if fam in PHASE2B_MARKET_FAMILIES:
        return bool(PHASE2B_MARKET_FAMILIES[fam]["shadowEligible"])
    return True


def _first_half_scores(score: dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    away = _safe_float(score.get("firstHalfAwayScore"))
    home = _safe_float(score.get("firstHalfHomeScore"))
    return away, home


def _line_desirability(market_key: str, side: str, line: Optional[float], price: Optional[float]) -> tuple[float, float]:
    # Higher tuple is better.
    if market_key == "moneyline":
        return (float(price or -9999.0), 0.0)

    if market_key == "spread":
        p = float(line or 0.0)
        if side == "away":
            # Away spread: higher line is better (+3.5 beats +3, -2.5 beats -3).
            return (p, float(price or -9999.0))
        # Home spread: lower line is better (-2.5 beats -3.0).
        return (-p, float(price or -9999.0))

    p = float(line or 0.0)
    if market_key == "total" and side == "over":
        return (-p, float(price or -9999.0))
    if market_key == "total" and side == "under":
        return (p, float(price or -9999.0))
    if market_key == "first_half_total" and side == "over":
        return (-p, float(price or -9999.0))
    if market_key == "first_half_total" and side == "under":
        return (p, float(price or -9999.0))
    if market_key == "team_total" and side == "over":
        return (-p, float(price or -9999.0))
    if market_key == "team_total" and side == "under":
        return (p, float(price or -9999.0))
    if market_key == "first_half_spread":
        if side == "away":
            return (p, float(price or -9999.0))
        return (-p, float(price or -9999.0))
    return (float(price or -9999.0), 0.0)


def _team_total_probability(
    *,
    team_code: str,
    side: str,
    total_point: float,
    model_total_baseline: float,
    model_margin_home: float,
    home_team: str,
    away_team: str,
) -> tuple[Optional[float], float, Optional[float]]:
    home = str(home_team or "").strip().upper()
    away = str(away_team or "").strip().upper()
    team = str(team_code or "").strip().upper()
    if not team or team not in {home, away}:
        return None, 0.0, None

    home_pts = (float(model_total_baseline) + float(model_margin_home)) / 2.0
    away_pts = float(model_total_baseline) - home_pts
    model_team_total = home_pts if team == home else away_pts

    probs = total_outcome_probabilities(model_total=model_team_total, side=str(side), total_point=float(total_point))
    if probs.status != "AVAILABLE":
        return None, 0.0, None
    return float(probs.win), float(probs.push), float(probs.loss)


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


def _extract_away_home_from_event_id(event_id: str) -> tuple[Optional[str], Optional[str]]:
    parts = str(event_id or "").split("_")
    if len(parts) >= 4:
        away = str(parts[2] or "").strip().upper() or None
        home = str(parts[3] or "").strip().upper() or None
        return away, home
    return None, None


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


def _parse_iso_for_compare(value: Any) -> Optional[datetime]:
    dt = _parse_commence(value)
    if dt is None:
        return None
    return dt.astimezone(timezone.utc)


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _consensus_and_median_line(lines: list[float]) -> tuple[Optional[float], Optional[float]]:
    if not lines:
        return None, None
    clean = sorted(float(v) for v in lines)
    median = float(clean[len(clean) // 2]) if len(clean) % 2 == 1 else float((clean[len(clean) // 2 - 1] + clean[len(clean) // 2]) / 2.0)

    counts: dict[float, int] = {}
    for val in clean:
        counts[val] = counts.get(val, 0) + 1
    winner, cnt = max(counts.items(), key=lambda item: (item[1], -abs(item[0])))
    consensus = float(winner) if cnt >= 2 else None
    return consensus, median


def _closing_cutoff_details(
    *,
    commence_time: Optional[str],
    market_timestamp: Optional[str],
    fetched_at: Optional[str],
) -> tuple[bool, str, Optional[str], int]:
    max_age_seconds = int(os.getenv("PROSPECTIVE_CLOSING_MAX_AGE_SECONDS", "900"))
    commence_dt = _parse_iso_for_compare(commence_time)
    quote_dt = _parse_iso_for_compare(market_timestamp) or _parse_iso_for_compare(fetched_at)
    if commence_dt is None or quote_dt is None:
        return False, "UNAVAILABLE", None, max_age_seconds

    if quote_dt > commence_dt:
        return False, "POST_KICKOFF_REJECTED", commence_dt.isoformat(), max_age_seconds

    age = (commence_dt - quote_dt).total_seconds()
    if age > float(max_age_seconds):
        return False, "STALE_REJECTED", commence_dt.isoformat(), max_age_seconds

    return True, "AVAILABLE", commence_dt.isoformat(), max_age_seconds


def _logical_market_identity(row: dict[str, Any]) -> tuple[str, str, str, str, str, str, str]:
    return (
        str(row.get("eventId") or ""),
        str(row.get("marketFamily") or ""),
        str(row.get("period") or ""),
        str(row.get("sportsbook") or ""),
        str(row.get("selection") or ""),
        str(row.get("side") or ""),
        str(row.get("teamCode") or ""),
    )


def _market_novig_from_pair(
    *,
    market_key: str,
    side: str,
    team_code: Optional[str],
    line: Optional[float],
    quotes: list[dict[str, Any]],
) -> tuple[Optional[float], str]:
    mk = str(market_key or "")
    sd = str(side or "").lower()
    team = str(team_code or "").upper()

    if mk in {"moneyline", "first_half_moneyline"}:
        home = next((q for q in quotes if str(q.get("side") or "").lower() == "home" and q.get("price") is not None), None)
        away = next((q for q in quotes if str(q.get("side") or "").lower() == "away" and q.get("price") is not None), None)
        if home and away and sd in {"home", "away"}:
            home_nv, away_nv = _devig_two_way(float(home["price"]), float(away["price"]))
            return (home_nv if sd == "home" else away_nv), "TWO_SIDED_AVAILABLE"
        return None, "UNAVAILABLE_TWO_SIDED_MARKET"

    if mk in {"spread", "first_half_spread"}:
        if line is None:
            return None, "UNAVAILABLE_TWO_SIDED_MARKET"
        home = next((q for q in quotes if str(q.get("side") or "").lower() == "home" and q.get("price") is not None and q.get("line") is not None and abs(float(q["line"]) + float(line)) < 1e-9), None)
        away = next((q for q in quotes if str(q.get("side") or "").lower() == "away" and q.get("price") is not None and q.get("line") is not None and abs(float(q["line"]) + float(line)) < 1e-9), None)
        if home and away and sd in {"home", "away"}:
            home_nv, away_nv = _devig_two_way(float(home["price"]), float(away["price"]))
            return (home_nv if sd == "home" else away_nv), "TWO_SIDED_AVAILABLE"
        return None, "UNAVAILABLE_TWO_SIDED_MARKET"

    if mk in {"total", "first_half_total", "team_total"}:
        over = next(
            (
                q
                for q in quotes
                if str(q.get("side") or "").lower() == "over"
                and q.get("price") is not None
                and q.get("line") is not None
                and (line is None or abs(float(q["line"]) - float(line)) < 1e-9)
                and (mk != "team_total" or str(q.get("teamCode") or "").upper() == team)
            ),
            None,
        )
        under = next(
            (
                q
                for q in quotes
                if str(q.get("side") or "").lower() == "under"
                and q.get("price") is not None
                and q.get("line") is not None
                and (line is None or abs(float(q["line"]) - float(line)) < 1e-9)
                and (mk != "team_total" or str(q.get("teamCode") or "").upper() == team)
            ),
            None,
        )
        if over and under and sd in {"over", "under"}:
            over_nv, under_nv = _devig_two_way(float(over["price"]), float(under["price"]))
            return (over_nv if sd == "over" else under_nv), "TWO_SIDED_AVAILABLE"
        return None, "UNAVAILABLE_TWO_SIDED_MARKET"

    return None, "UNAVAILABLE_TWO_SIDED_MARKET"


def _persist_prospective_state_row(
    con: sqlite3.Connection,
    *,
    row: dict[str, Any],
    state_label: str,
    closing_status: Optional[str],
    closing_cutoff_utc: Optional[str],
    closing_max_age_seconds: Optional[int],
) -> bool:
    payload = dict(row)
    payload["stateLabel"] = state_label
    payload["closingStatus"] = closing_status
    payload["closingCutoffUTC"] = closing_cutoff_utc
    payload["closingMaxAgeSeconds"] = closing_max_age_seconds
    canonical = _canonical_json(payload)
    payload_hash = _sha256(canonical)
    idem = _sha256(f"prospective-market:{payload_hash}")
    snapshot_id = str(uuid.uuid5(uuid.NAMESPACE_URL, idem))

    values = [
        snapshot_id,
        _utc_now_iso(),
        row.get("season"),
        row.get("week"),
        row.get("eventId"),
        row.get("providerEventId"),
        row.get("commenceTime"),
        row.get("marketFamily"),
        row.get("marketKey"),
        row.get("phase") or "PREGAME",
        row.get("period"),
        state_label,
        closing_status,
        closing_cutoff_utc,
        closing_max_age_seconds,
        row.get("teamCode"),
        row.get("selection"),
        row.get("side"),
        row.get("line"),
        row.get("price"),
        row.get("sportsbook"),
        row.get("bookmakerKey"),
        row.get("marketTimestamp"),
        row.get("fetchedAt"),
        row.get("sourceSnapshotId"),
        row.get("bookCoverageCount"),
        json.dumps(row.get("availableBooks") or [], separators=(",", ":")),
        row.get("marketDepthStatus"),
        json.dumps(row.get("allBooks") or [], separators=(",", ":")),
        row.get("bestPrice"),
        row.get("bestPriceBook"),
        row.get("consensusLine"),
        row.get("medianLine"),
        row.get("projectedGameTotal"),
        row.get("projectedHomeMargin"),
        row.get("derivedProjectedHomePoints"),
        row.get("derivedProjectedAwayPoints"),
        row.get("selectedTeamProjectedPoints"),
        row.get("rawProbability"),
        row.get("calibratedProbability"),
        row.get("pushProbability"),
        row.get("lossProbability"),
        row.get("marketImpliedProbability"),
        row.get("marketNoVigProbability"),
        row.get("edge"),
        row.get("ev"),
        row.get("fairValue"),
        row.get("playableTo"),
        row.get("siScore"),
        row.get("marketRank"),
        row.get("globalResearchScore"),
        row.get("globalResearchRank"),
        1 if bool(row.get("productionEligible")) else 0,
        1 if bool(row.get("crossMarketComparable")) else 0,
        row.get("marketValidationStatus"),
        row.get("modelState"),
        row.get("shadowRecommendations"),
        row.get("modelVersion"),
        row.get("probabilityEngineVersion"),
        row.get("calibrationVersion"),
        row.get("rankingVersion"),
        row.get("qualificationPolicyVersion"),
        row.get("gitCommitHash"),
        row.get("gameStateTimestamp"),
        row.get("gameQuarter"),
        row.get("gameClock"),
        row.get("possession"),
        payload_hash,
        canonical,
        idem,
    ]

    before = con.total_changes
    con.execute(
        f"""
        INSERT OR IGNORE INTO prospective_market_snapshots (
            snapshot_id, captured_at_utc,
            season, week, event_id, provider_event_id, commence_time,
            market_family, market_key, phase, period, state_label,
            closing_status, closing_cutoff_utc, closing_max_age_seconds,
            team_code, selection, side, line, price, sportsbook, bookmaker_key,
            market_timestamp, fetched_at, source_snapshot_id,
            book_coverage_count, available_books, market_depth_status, all_books,
            best_price, best_price_book, consensus_line, median_line,
            projected_game_total, projected_home_margin,
            derived_projected_home_points, derived_projected_away_points, selected_team_projected_points,
            raw_probability, calibrated_probability, push_probability, loss_probability,
            market_implied_probability, market_no_vig_probability,
            edge, ev, fair_value, playable_to, si_score,
            market_rank, global_research_score, global_research_rank,
            production_eligible, cross_market_comparable,
            market_validation_status, model_state, shadow_recommendations,
            model_version, probability_engine_version, calibration_version,
            ranking_version, qualification_policy_version, git_commit_hash,
            game_state_timestamp, game_quarter, game_clock, possession,
            payload_hash, canonical_payload, idempotency_key
        ) VALUES ({','.join(['?'] * len(values))})
        """,
        values,
    )
    return con.total_changes > before


def _opening_state_exists(con: sqlite3.Connection, row: dict[str, Any]) -> bool:
    identity = _logical_market_identity(row)
    found = con.execute(
        """
        SELECT 1
        FROM prospective_market_snapshots
        WHERE event_id = ?
          AND market_family = ?
          AND period = ?
          AND sportsbook = ?
          AND selection = ?
          AND side = ?
          AND ifnull(team_code, '') = ?
          AND phase = 'PREGAME'
          AND state_label = 'OPENING'
        LIMIT 1
        """,
        list(identity),
    ).fetchone()
    return found is not None


def _capture_prospective_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    _ensure_schema()
    con = _connect()

    inserted_current = 0
    inserted_opening = 0
    inserted_closing = 0
    duplicate_rejections = 0
    stale_rejections = 0
    post_kickoff_rejections = 0
    missing_fields = 0

    for row in rows:
        if not row.get("eventId") or not row.get("marketFamily") or not row.get("period"):
            missing_fields += 1
            continue

        if _persist_prospective_state_row(
            con,
            row=row,
            state_label="CURRENT",
            closing_status=None,
            closing_cutoff_utc=None,
            closing_max_age_seconds=None,
        ):
            inserted_current += 1
        else:
            duplicate_rejections += 1

        if not _opening_state_exists(con, row):
            if _persist_prospective_state_row(
                con,
                row=row,
                state_label="OPENING",
                closing_status=None,
                closing_cutoff_utc=None,
                closing_max_age_seconds=None,
            ):
                inserted_opening += 1
            else:
                duplicate_rejections += 1

        closing_ok, close_status, close_cutoff, close_max_age = _closing_cutoff_details(
            commence_time=row.get("commenceTime"),
            market_timestamp=row.get("marketTimestamp"),
            fetched_at=row.get("fetchedAt"),
        )
        if closing_ok:
            if _persist_prospective_state_row(
                con,
                row=row,
                state_label="CLOSING",
                closing_status="AVAILABLE",
                closing_cutoff_utc=close_cutoff,
                closing_max_age_seconds=close_max_age,
            ):
                inserted_closing += 1
            else:
                duplicate_rejections += 1
        elif close_status == "STALE_REJECTED":
            stale_rejections += 1
        elif close_status == "POST_KICKOFF_REJECTED":
            post_kickoff_rejections += 1

    con.commit()
    con.close()

    return {
        "rowsReceived": len(rows),
        "currentInserted": inserted_current,
        "openingInserted": inserted_opening,
        "closingInserted": inserted_closing,
        "duplicateRejectionCount": duplicate_rejections,
        "staleSnapshotCount": stale_rejections,
        "postKickoffRejectedCount": post_kickoff_rejections,
        "missingFieldCount": missing_fields,
    }


def _row_market_metadata(
    *,
    market_key: str,
    market_family: str,
    side: str,
    team_code: Optional[str],
) -> tuple[str, str]:
    if market_family == "TEAM_TOTAL":
        return "RESEARCH_ONLY", "DISABLED"
    if market_family in {"FIRST_HALF_SPREAD", "FIRST_HALF_MONEYLINE", "FIRST_HALF_TOTAL"}:
        return "DATA_COLLECTION_ONLY", "DISABLED"
    return "MODEL_BACKED", "ENABLED" if market_key == "spread" else "DISABLED"


def capture_prospective_from_line_board(week: Optional[int] = None, season: Optional[int] = None) -> dict[str, Any]:
    board = _load_line_board()
    if board.empty:
        return {
            "rowsReceived": 0,
            "currentInserted": 0,
            "openingInserted": 0,
            "closingInserted": 0,
            "duplicateRejectionCount": 0,
            "staleSnapshotCount": 0,
            "postKickoffRejectedCount": 0,
            "missingFieldCount": 0,
        }

    board = board.copy()
    board["market"] = board["market"].astype(str).str.strip().str.lower().map(_normalize_market)
    board["side"] = board["side"].astype(str).str.strip().str.lower()
    board = board[board["market"].isin({"spread", "moneyline", "total", "team_total", "first_half_spread", "first_half_moneyline", "first_half_total"})]
    if board.empty:
        return {
            "rowsReceived": 0,
            "currentInserted": 0,
            "openingInserted": 0,
            "closingInserted": 0,
            "duplicateRejectionCount": 0,
            "staleSnapshotCount": 0,
            "postKickoffRejectedCount": 0,
            "missingFieldCount": 0,
        }

    if season is not None and week is not None:
        keep_rows = []
        for _, rr in board.iterrows():
            row_season, row_week = _extract_season_week_from_game_id(
                str(rr.get("api_event_id") or ""),
                _parse_commence(rr.get("commence_time")),
            )
            if row_season == int(season) and row_week == int(week):
                keep_rows.append(rr)
        if keep_rows:
            board = pd.DataFrame(keep_rows)

    projections = _load_projection_lookup()
    grouped_quotes: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}

    for _, rr in board.iterrows():
        event_id = str(rr.get("api_event_id") or "")
        market_key = str(rr.get("market") or "")
        side = str(rr.get("side") or "").lower()
        team_code = _team_code_from_row(rr, side)
        identity = (event_id, market_key, side, str(team_code or ""))
        grouped_quotes.setdefault(identity, []).append(
            {
                "line": _safe_float(rr.get("latest_point")),
                "price": _safe_float(rr.get("latest_price")),
                "sportsbook": str(rr.get("sportsbook") or ""),
                "side": side,
                "teamCode": team_code,
            }
        )

    prospective_rows: list[dict[str, Any]] = []

    for _, rr in board.iterrows():
        event_id = str(rr.get("api_event_id") or "")
        market_key = str(rr.get("market") or "")
        market_family = MARKET_KEY_TO_FAMILY.get(market_key)
        if market_family not in PROSPECTIVE_MARKET_FAMILIES:
            continue

        side = str(rr.get("side") or "").lower()
        team_code = _team_code_from_row(rr, side)
        line = _safe_float(rr.get("latest_point"))
        price = _safe_float(rr.get("latest_price"))
        if price is None:
            continue

        quotes = grouped_quotes.get((event_id, market_key, side, str(team_code or "")), [])
        all_books = sorted({str(q.get("sportsbook") or "") for q in quotes if str(q.get("sportsbook") or "")})
        best_q = max((q for q in quotes if q.get("price") is not None), key=lambda q: float(q["price"]), default=None)
        lines = [float(q["line"]) for q in quotes if q.get("line") is not None]
        consensus_line, median_line = _consensus_and_median_line(lines)

        implied = _implied_probability(float(price))
        novig, novig_status = _market_novig_from_pair(
            market_key=market_key,
            side=side,
            team_code=team_code,
            line=line,
            quotes=quotes,
        )

        projection = projections.get(event_id)
        projected_game_total = _safe_float(projection.get("model_total_baseline")) if projection is not None else None
        projected_home_margin = _safe_float(projection.get("model_margin_home")) if projection is not None else None
        if market_family in {"FIRST_HALF_SPREAD", "FIRST_HALF_MONEYLINE", "FIRST_HALF_TOTAL"}:
            projected_game_total = None
            projected_home_margin = None
        derived_home = None
        derived_away = None
        selected_team = None
        if projected_game_total is not None and projected_home_margin is not None:
            derived_home = (float(projected_game_total) + float(projected_home_margin)) / 2.0
            derived_away = float(projected_game_total) - float(derived_home)
            away_code, home_code = _extract_away_home_from_event_id(event_id)
            if market_family == "TEAM_TOTAL":
                team = str(team_code or "").upper()
                if home_code and team == home_code:
                    selected_team = derived_home
                elif away_code and team == away_code:
                    selected_team = derived_away

        model_state, recommendations = _row_market_metadata(
            market_key=market_key,
            market_family=market_family,
            side=side,
            team_code=team_code,
        )

        season_row, week_row = _extract_season_week_from_game_id(
            event_id,
            _parse_commence(rr.get("commence_time")),
        )

        prospective_rows.append(
            {
                "season": int(season if season is not None else season_row),
                "week": int(week if week is not None else week_row),
                "eventId": event_id,
                "providerEventId": event_id,
                "commenceTime": str(rr.get("commence_time") or ""),
                "marketFamily": market_family,
                "marketKey": market_key,
                "phase": "PREGAME",
                "period": _market_period_for_key(market_key),
                "teamCode": team_code,
                "selection": str(rr.get("selection") or rr.get("team") or side),
                "side": side,
                "line": line,
                "price": price,
                "sportsbook": str(rr.get("sportsbook") or ""),
                "bookmakerKey": str(rr.get("bookmakerKey") or rr.get("sportsbook") or ""),
                "marketTimestamp": str(rr.get("last_seen") or ""),
                "fetchedAt": _utc_now_iso(),
                "sourceSnapshotId": _sha256(
                    _canonical_json(
                        {
                            "eventId": event_id,
                            "market": market_key,
                            "side": side,
                            "line": line,
                            "price": price,
                            "sportsbook": str(rr.get("sportsbook") or ""),
                            "marketTimestamp": str(rr.get("last_seen") or ""),
                        }
                    )
                ),
                "bookCoverageCount": len(all_books),
                "availableBooks": all_books,
                "marketDepthStatus": _market_depth_status(len(all_books)),
                "allBooks": quotes,
                "bestPrice": best_q.get("price") if best_q else price,
                "bestPriceBook": best_q.get("sportsbook") if best_q else str(rr.get("sportsbook") or ""),
                "consensusLine": consensus_line,
                "medianLine": median_line,
                "projectedGameTotal": projected_game_total,
                "projectedHomeMargin": projected_home_margin,
                "derivedProjectedHomePoints": derived_home,
                "derivedProjectedAwayPoints": derived_away,
                "selectedTeamProjectedPoints": selected_team,
                "rawProbability": None,
                "calibratedProbability": None,
                "pushProbability": None,
                "lossProbability": None,
                "marketImpliedProbability": implied,
                "marketNoVigProbability": novig,
                "edge": None,
                "ev": None,
                "fairValue": None,
                "playableTo": None,
                "siScore": None,
                "marketRank": None,
                "globalResearchScore": None,
                "globalResearchRank": None,
                "productionEligible": True if market_family == "SPREAD" else False,
                "crossMarketComparable": False,
                "marketValidationStatus": novig_status,
                "modelState": model_state,
                "shadowRecommendations": recommendations,
                "modelVersion": settings.DEFAULT_MODEL_VERSION,
                "probabilityEngineVersion": settings.DEFAULT_PROBABILITY_ENGINE_VERSION,
                "calibrationVersion": settings.DEFAULT_CALIBRATION_VERSION,
                "rankingVersion": settings.DEFAULT_RANKING_VERSION,
                "qualificationPolicyVersion": settings.DEFAULT_QUALIFICATION_POLICY_VERSION,
                "gitCommitHash": settings.DEFAULT_GIT_COMMIT_HASH,
                "gameStateTimestamp": None,
                "gameQuarter": None,
                "gameClock": None,
                "possession": None,
            }
        )

    return _capture_prospective_rows(prospective_rows)


def prospective_market_capture_report(*, season: Optional[int] = None, week: Optional[int] = None) -> dict[str, Any]:
    _ensure_schema()
    con = _connect()
    where = ["phase = 'PREGAME'", "market_family IN ('SPREAD','MONEYLINE','TOTAL','TEAM_TOTAL','FIRST_HALF_SPREAD','FIRST_HALF_MONEYLINE','FIRST_HALF_TOTAL')"]
    params: list[Any] = []
    if season is not None:
        where.append("season = ?")
        params.append(int(season))
    if week is not None:
        where.append("week = ?")
        params.append(int(week))
    sql = "SELECT * FROM prospective_market_snapshots WHERE " + " AND ".join(where)
    rows = con.execute(sql, params).fetchall()
    con.close()

    by_market: dict[str, Any] = {}
    for family in PROSPECTIVE_MARKET_FAMILIES:
        fam_rows = [r for r in rows if str(r["market_family"]) == family]
        states = {"OPENING": 0, "CURRENT": 0, "CLOSING": 0}
        for r in fam_rows:
            label = str(r["state_label"] or "")
            if label in states:
                states[label] += 1

        book_depth = sorted({str(r["market_depth_status"] or "") for r in fam_rows if str(r["market_depth_status"] or "")})
        by_market[family] = {
            "rowsCaptured": len(fam_rows),
            "eventsCaptured": len({str(r["event_id"] or "") for r in fam_rows if str(r["event_id"] or "")}),
            "openingCapture": "READY" if states["OPENING"] > 0 else "NOT_READY",
            "currentCapture": "READY" if states["CURRENT"] > 0 else "NOT_READY",
            "closingCapture": "READY" if states["CLOSING"] > 0 else "NOT_READY",
            "stateCounts": states,
            "bookDepthStatuses": book_depth,
            "modelDataAvailability": {
                "projectionAvailable": any(r["projected_game_total"] is not None for r in fam_rows),
                "rawProbabilityAvailable": any(r["raw_probability"] is not None for r in fam_rows),
            },
            "gradingAvailability": {
                "outcomesLinked": False,
            },
        }

    return {
        "phase": "PREGAME",
        "families": by_market,
        "closingCutoffPolicy": {
            "definition": "latest valid sportsbook snapshot captured before commenceTime and not stale",
            "staleMaxAgeSeconds": int(os.getenv("PROSPECTIVE_CLOSING_MAX_AGE_SECONDS", "900")),
            "postKickoffPolicy": "REJECT_POST_KICKOFF",
            "unavailableStatus": "UNAVAILABLE",
        },
    }


def prospective_data_integrity_audit(*, season: Optional[int] = None, week: Optional[int] = None) -> dict[str, Any]:
    _ensure_schema()
    con = _connect()
    where = ["phase = 'PREGAME'", "market_family IN ('SPREAD','MONEYLINE','TOTAL','TEAM_TOTAL','FIRST_HALF_SPREAD','FIRST_HALF_MONEYLINE','FIRST_HALF_TOTAL')"]
    params: list[Any] = []
    if season is not None:
        where.append("season = ?")
        params.append(int(season))
    if week is not None:
        where.append("week = ?")
        params.append(int(week))
    sql = "SELECT * FROM prospective_market_snapshots WHERE " + " AND ".join(where)
    rows = con.execute(sql, params).fetchall()
    con.close()

    events = {str(r["event_id"]) for r in rows if str(r["event_id"] or "")}
    markets_expected = len(events) * len(PROSPECTIVE_MARKET_FAMILIES)
    market_presence = {(str(r["event_id"]), str(r["market_family"])) for r in rows if str(r["event_id"] or "")}
    two_sided_coverage = [r for r in rows if r["market_no_vig_probability"] is not None]

    def _coverage(state: str) -> float:
        if not markets_expected:
            return 0.0
        available = {
            (str(r["event_id"]), str(r["market_family"]))
            for r in rows
            if str(r["state_label"] or "") == state
        }
        return float(len(available) / markets_expected)

    missing_fields = 0
    for r in rows:
        if not r["event_id"] or not r["market_family"] or not r["period"]:
            missing_fields += 1

    return {
        "eventsExpected": len(events),
        "eventsCaptured": len(events),
        "marketsExpected": markets_expected,
        "marketsCaptured": len(market_presence),
        "openingCoverage": _coverage("OPENING"),
        "currentCoverage": _coverage("CURRENT"),
        "closingCoverage": _coverage("CLOSING"),
        "outcomeCoverage": 0.0,
        "twoSidedNoVigCoverage": float(len(two_sided_coverage) / len(rows)) if rows else 0.0,
        "bookCoverageByMarket": {
            fam: len({str(r["sportsbook"] or "") for r in rows if str(r["market_family"]) == fam and str(r["sportsbook"] or "")})
            for fam in PROSPECTIVE_MARKET_FAMILIES
        },
        "staleSnapshotCount": sum(1 for r in rows if str(r["closing_status"] or "") == "STALE_REJECTED"),
        "duplicateRejectionCount": 0,
        "missingFieldCount": missing_fields,
    }


def live_sia_future_schema_compatibility() -> dict[str, Any]:
    return {
        "phaseLiveSupported": True,
        "requiredLiveFields": ["gameStateTimestamp", "quarter", "clock", "score", "possession"],
        "currentSchemaFields": [
            "game_state_timestamp",
            "game_quarter",
            "game_clock",
            "possession",
        ],
        "identityUnchanged": True,
        "notes": "Live fields are schema-ready but live capture remains disabled.",
    }


def canonical_quote_contract() -> dict[str, Any]:
    return {
        "fields": [
            "eventId",
            "marketFamily",
            "period",
            "phase",
            "team",
            "selection",
            "side",
            "point",
            "sportsbook",
            "bookmakerKey",
            "americanPrice",
            "decimalPrice",
            "marketTimestamp",
            "fetchedAt",
            "sourceSnapshotId",
        ],
        "moneylinePointPolicy": "DO_NOT_FABRICATE_POINT",
    }


def _canonical_quote_from_snapshot_row(row: sqlite3.Row, *, now_utc: Optional[datetime] = None) -> dict[str, Any]:
    market_key = _normalize_market(str(row["market_key"] or ""))
    bookmaker_key = _normalize_bookmaker_key(row["bookmaker_key"] or row["sportsbook"])
    point = _safe_float(row["line"])
    if market_key in {"moneyline", "first_half_moneyline"}:
        point = None
    price = _safe_float(row["price"])

    return {
        "eventId": str(row["event_id"] or ""),
        "marketFamily": str(row["market_family"] or ""),
        "period": str(row["period"] or ""),
        "phase": str(row["phase"] or "PREGAME"),
        "team": str(row["team_code"] or "") or None,
        "selection": str(row["selection"] or ""),
        "side": str(row["side"] or "").lower(),
        "point": point,
        "sportsbook": _normalize_bookmaker_display(row["sportsbook"], bookmaker_key),
        "bookmakerKey": bookmaker_key,
        "americanPrice": price,
        "decimalPrice": _american_to_decimal(price),
        "marketTimestamp": str(row["market_timestamp"] or "") or None,
        "fetchedAt": str(row["fetched_at"] or "") or None,
        "sourceSnapshotId": str(row["source_snapshot_id"] or "") or None,
        "modelState": str(row["model_state"] or "") or None,
        "quoteFreshness": _quote_freshness(
            phase=str(row["phase"] or "PREGAME"),
            market_timestamp=str(row["market_timestamp"] or "") or None,
            fetched_at=str(row["fetched_at"] or "") or None,
            now_utc=now_utc,
        ),
    }


def _dedupe_quotes_by_book_latest(quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_book: dict[str, dict[str, Any]] = {}
    for quote in quotes:
        key = str(quote.get("bookmakerKey") or quote.get("sportsbook") or "")
        existing = by_book.get(key)
        if existing is None:
            by_book[key] = quote
            continue
        ex_ts = _parse_iso_for_compare(existing.get("marketTimestamp") or existing.get("fetchedAt"))
        q_ts = _parse_iso_for_compare(quote.get("marketTimestamp") or quote.get("fetchedAt"))
        if ex_ts is None and q_ts is not None:
            by_book[key] = quote
        elif ex_ts is not None and q_ts is not None and q_ts > ex_ts:
            by_book[key] = quote
    return list(by_book.values())


def _median_price(prices: list[float]) -> Optional[float]:
    if not prices:
        return None
    vals = sorted(float(p) for p in prices)
    n = len(vals)
    mid = n // 2
    if n % 2 == 1:
        return float(vals[mid])
    return float((vals[mid - 1] + vals[mid]) / 2.0)


def _quote_depth_metrics(quotes: list[dict[str, Any]], market_key: str, side: str) -> dict[str, Any]:
    lines = [float(q["point"]) for q in quotes if q.get("point") is not None]
    prices = [float(q["americanPrice"]) for q in quotes if q.get("americanPrice") is not None]
    consensus_line, median_line = _consensus_and_median_line(lines)
    market_consensus_prob = None

    if _normalize_market(market_key) in {"moneyline", "first_half_moneyline"}:
        probs = [_implied_probability(float(p)) for p in prices]
        if probs:
            market_consensus_prob = float(round(sum(probs) / len(probs), 6))

    return {
        "bookCount": len({str(q.get("bookmakerKey") or "") for q in quotes if str(q.get("bookmakerKey") or "")}),
        "consensusLine": consensus_line,
        "medianLine": median_line,
        "priceRange": None if not prices else [float(min(prices)), float(max(prices))],
        "medianPrice": _median_price(prices),
        "marketConsensusProbability": market_consensus_prob,
        "marketDepthStatus": _market_depth_status(len({str(q.get("bookmakerKey") or "") for q in quotes if str(q.get("bookmakerKey") or "")})),
    }


def _line_shopping_improvement(
    *,
    market_key: str,
    side: str,
    best_quote: Optional[dict[str, Any]],
    depth_metrics: dict[str, Any],
) -> dict[str, Any]:
    if best_quote is None:
        return {
            "lineImprovement": None,
            "priceImprovement": None,
            "impliedProbabilityImprovement": None,
        }

    median_line = depth_metrics.get("medianLine")
    median_price = depth_metrics.get("medianPrice")
    best_line = _safe_float(best_quote.get("point"))
    best_price = _safe_float(best_quote.get("americanPrice"))
    mk = _normalize_market(market_key)
    sd = str(side or "").lower()

    line_improvement = None
    if best_line is not None and median_line is not None:
        if mk in {"spread", "first_half_spread"}:
            line_improvement = float(best_line - float(median_line)) if sd != "home" else float(float(median_line) - best_line)
        elif mk in {"total", "first_half_total", "team_total"}:
            line_improvement = float(float(median_line) - best_line) if sd != "under" else float(best_line - float(median_line))

    implied_improvement = None
    if best_price is not None and median_price is not None:
        implied_improvement = float(round(_implied_probability(float(median_price)) - _implied_probability(float(best_price)), 6))

    return {
        "lineImprovement": line_improvement,
        "priceImprovement": None if best_price is None or median_price is None else float(best_price - float(median_price)),
        "impliedProbabilityImprovement": implied_improvement,
    }


def line_shopping_market_view(
    *,
    event_id: str,
    market_family: str,
    side: str,
    period: Optional[str] = None,
    phase: str = "PREGAME",
    team_code: Optional[str] = None,
    selection: Optional[str] = None,
    playable_to_line: Optional[float] = None,
    playable_to_price: Optional[float] = None,
) -> dict[str, Any]:
    _ensure_schema()
    con = _connect()
    query = [
        "event_id = ?",
        "market_family = ?",
        "state_label = 'CURRENT'",
        "phase = ?",
        "side = ?",
    ]
    params: list[Any] = [str(event_id), str(market_family), str(phase), str(side).lower()]
    if period is not None:
        query.append("period = ?")
        params.append(str(period))
    if team_code is not None:
        query.append("ifnull(team_code, '') = ?")
        params.append(str(team_code).upper())
    if selection is not None:
        query.append("selection = ?")
        params.append(str(selection))

    rows = con.execute(
        "SELECT * FROM prospective_market_snapshots WHERE " + " AND ".join(query),
        params,
    ).fetchall()
    con.close()

    quotes = _dedupe_quotes_by_book_latest([_canonical_quote_from_snapshot_row(r) for r in rows])
    if not quotes:
        return {
            "status": "NO_QUOTES",
            "bestMarketQuote": None,
            "bestPlayableQuote": None,
            "playableBookCount": 0,
            "totalBookCount": 0,
            "marketDepth": {
                "bookCount": 0,
                "consensusLine": None,
                "medianLine": None,
                "priceRange": None,
                "marketConsensusProbability": None,
                "marketDepthStatus": "NO_BOOKS",
            },
            "lineShoppingValue": {
                "lineImprovement": None,
                "priceImprovement": None,
                "impliedProbabilityImprovement": None,
            },
            "quotes": [],
        }

    mk = _normalize_market(str(rows[0]["market_key"] if rows else ""))
    sorted_quotes = sorted(
        quotes,
        key=lambda q: _line_shopping_sort_key(mk, str(q.get("side") or ""), _safe_float(q.get("point")), _safe_float(q.get("americanPrice"))),
        reverse=True,
    )
    best_market = sorted_quotes[0]

    playable_quotes: list[dict[str, Any]] = []
    for quote in sorted_quotes:
        playable_status = _quote_playable_status(
            market_key=mk,
            side=str(quote.get("side") or ""),
            line=_safe_float(quote.get("point")),
            price=_safe_float(quote.get("americanPrice")),
            playable_to_line=playable_to_line,
            playable_to_price=playable_to_price,
            model_state=quote.get("modelState"),
        )
        quote["playableStatus"] = playable_status
        if playable_status == "PLAYABLE" and str(quote.get("quoteFreshness") or "") != "STALE":
            playable_quotes.append(quote)

    best_playable = playable_quotes[0] if playable_quotes else None
    depth = _quote_depth_metrics(sorted_quotes, mk, side)

    return {
        "status": "OK" if best_playable is not None else "NO_EXECUTABLE_PRICE",
        "bestMarketQuote": best_market,
        "bestPlayableQuote": best_playable,
        "bestPlayableBook": None if best_playable is None else best_playable.get("sportsbook"),
        "bestPlayablePoint": None if best_playable is None else best_playable.get("point"),
        "bestPlayablePrice": None if best_playable is None else best_playable.get("americanPrice"),
        "playableBookCount": len(playable_quotes),
        "totalBookCount": len(sorted_quotes),
        "marketDepth": depth,
        "lineShoppingValue": _line_shopping_improvement(
            market_key=mk,
            side=str(side or ""),
            best_quote=best_market,
            depth_metrics=depth,
        ),
        "quotes": sorted_quotes,
    }


def sportsbook_coverage_audit(*, max_events: int = 6) -> dict[str, Any]:
    _ensure_schema()
    con = _connect()
    rows = con.execute(
        """
        SELECT market_family, event_id, sportsbook
        FROM prospective_market_snapshots
        WHERE state_label = 'CURRENT'
          AND phase = 'PREGAME'
          AND market_family IN ('SPREAD','MONEYLINE','TOTAL','TEAM_TOTAL','FIRST_HALF_SPREAD','FIRST_HALF_MONEYLINE','FIRST_HALF_TOTAL')
        """
    ).fetchall()
    con.close()

    families = [
        "SPREAD",
        "MONEYLINE",
        "TOTAL",
        "TEAM_TOTAL",
        "FIRST_HALF_SPREAD",
        "FIRST_HALF_MONEYLINE",
        "FIRST_HALF_TOTAL",
    ]
    coverage: dict[str, dict[str, Any]] = {
        fam: {
            "events": {},
            "books": set(),
        }
        for fam in families
    }

    for r in rows:
        fam = str(r["market_family"] or "")
        if fam not in coverage:
            continue
        event_id = str(r["event_id"] or "")
        book = _normalize_bookmaker_display(r["sportsbook"], _normalize_bookmaker_key(r["sportsbook"]))
        coverage[fam]["events"].setdefault(event_id, set()).add(book)
        coverage[fam]["books"].add(book)

    unique_books = set()

    # Controlled fallback only when local snapshots are insufficient.
    if (not rows or any(len(coverage[f]["events"]) == 0 for f in families)) and _odds_api_key():
        status, _, payload = _call_odds_api(["spreads", "h2h", "totals"])
        if status == 200 and isinstance(payload, list):
            for event in payload[:max_events]:
                event_id = str(event.get("id") or "")
                for book in event.get("bookmakers", []) or []:
                    bk = _normalize_bookmaker_key(book.get("key"))
                    display = _normalize_bookmaker_display(book.get("title") or book.get("key"), bk)
                    for m in book.get("markets", []) or []:
                        mk = str(m.get("key") or "")
                        fam = "SPREAD" if mk == "spreads" else "MONEYLINE" if mk == "h2h" else "TOTAL" if mk == "totals" else None
                        if fam is None:
                            continue
                        coverage[fam]["events"].setdefault(event_id, set()).add(display)
                        coverage[fam]["books"].add(display)

        event_status, _, events_payload = _call_odds_api_events()
        if event_status == 200 and isinstance(events_payload, list):
            for event in events_payload[:max_events]:
                event_id = str(event.get("id") or "")
                estatus, _, epayload = _call_odds_api_event_odds(event_id, ["team_totals", "spreads_h1", "h2h_h1", "totals_h1"])
                if estatus != 200 or not isinstance(epayload, dict):
                    continue
                for book in epayload.get("bookmakers", []) or []:
                    bk = _normalize_bookmaker_key(book.get("key"))
                    display = _normalize_bookmaker_display(book.get("title") or book.get("key"), bk)
                    for m in book.get("markets", []) or []:
                        mk = str(m.get("key") or "")
                        fam = (
                            "TEAM_TOTAL" if mk == "team_totals"
                            else "FIRST_HALF_SPREAD" if mk == "spreads_h1"
                            else "FIRST_HALF_MONEYLINE" if mk == "h2h_h1"
                            else "FIRST_HALF_TOTAL" if mk == "totals_h1"
                            else None
                        )
                        if fam is None:
                            continue
                        coverage[fam]["events"].setdefault(event_id, set()).add(display)
                        coverage[fam]["books"].add(display)

    metrics: dict[str, Any] = {}
    for fam in families:
        events = coverage[fam]["events"]
        counts = sorted(len(v) for v in events.values())
        books = sorted(str(b) for b in coverage[fam]["books"])
        unique_books.update(books)

        avg = float(sum(counts) / len(counts)) if counts else 0.0
        median = float(counts[len(counts) // 2]) if counts else 0.0
        if counts and len(counts) % 2 == 0:
            median = float((counts[len(counts) // 2 - 1] + counts[len(counts) // 2]) / 2.0)

        metrics[fam] = {
            "eventsSampled": len(events),
            "averageBooksPerEvent": round(avg, 4),
            "medianBooksPerEvent": round(median, 4),
            "minBooks": min(counts) if counts else 0,
            "maxBooks": max(counts) if counts else 0,
            "uniqueSportsbooks": books,
        }

    return {
        "status": "PASS" if any(metrics[f]["eventsSampled"] > 0 for f in families) else "FAIL",
        "markets": metrics,
        "uniqueBooks": sorted(unique_books),
    }


def _two_sided_closing_no_vig(
    *,
    event_id: str,
    sportsbook: str,
    market_family: str,
    side: str,
    kickoff: datetime,
    recommended_line: Optional[float],
    team_code: Optional[str] = None,
) -> tuple[Optional[float], str]:
    """Return no-vig probability for the candidate side from a two-sided closing market.

    Status values:
      AVAILABLE_TWO_SIDED_MARKET
      UNAVAILABLE_TWO_SIDED_MARKET
      MISMATCHED_TOTAL_POINTS
    """
    try:
        import duckdb  # type: ignore
    except Exception:
        return None, "UNAVAILABLE_TWO_SIDED_MARKET"

    db_path = MODEL_ROOT / "database" / "nfl_model.duckdb"
    if not db_path.exists():
        return None, "UNAVAILABLE_TWO_SIDED_MARKET"

    if market_family == "MONEYLINE":
        market_key = "h2h"
        sides = ("home", "away")
    elif market_family == "TOTAL":
        market_key = "totals"
        sides = ("over", "under")
    elif market_family == "SPREAD":
        market_key = "spreads"
        sides = ("home", "away")
    elif market_family == "TEAM_TOTAL":
        market_key = "team_totals"
        sides = ("over", "under")
    elif market_family == "FIRST_HALF_SPREAD":
        market_key = "spreads_h1"
        sides = ("home", "away")
    elif market_family == "FIRST_HALF_MONEYLINE":
        market_key = "h2h_h1"
        sides = ("home", "away")
    elif market_family == "FIRST_HALF_TOTAL":
        market_key = "totals_h1"
        sides = ("over", "under")
    else:
        return None, "UNAVAILABLE_TWO_SIDED_MARKET"

    cutoff = kickoff.astimezone(timezone.utc) - timedelta(minutes=2)
    cutoff_naive = cutoff.replace(tzinfo=None)

    con = duckdb.connect(str(db_path), read_only=True)
    schema_cols = {
        str(r[1]).lower()
        for r in con.execute("PRAGMA table_info('odds_snapshots')").fetchall()
        if len(r) >= 2
    }
    outcome_name_expr = "outcome_name" if "outcome_name" in schema_cols else "NULL AS outcome_name"
    rows = con.execute(
        f"""
        SELECT fetched_at, outcome_code, {outcome_name_expr}, point, price
        FROM odds_snapshots
        WHERE api_event_id = ?
          AND bookmaker_key = ?
          AND market_key = ?
          AND outcome_code IN (?, ?)
          AND fetched_at <= ?
        ORDER BY fetched_at DESC
        """,
        [event_id, sportsbook, market_key, sides[0], sides[1], cutoff_naive],
    ).fetchall()
    con.close()

    if not rows:
        return None, "UNAVAILABLE_TWO_SIDED_MARKET"

    by_ts: dict[Any, dict[str, tuple[Optional[float], Optional[float]]]] = {}
    for fetched_at, outcome_code, outcome_name, point, price in rows:
        ts_map = by_ts.setdefault(fetched_at, {})
        ts_map[str(outcome_code)] = (str(outcome_name or ""), _safe_float(point), _safe_float(price))

    for ts in sorted(by_ts.keys(), reverse=True):
        snap = by_ts[ts]
        if any(s not in snap or snap[s][2] is None for s in sides):
            continue

        if market_family in {"TOTAL", "FIRST_HALF_TOTAL", "TEAM_TOTAL"}:
            over_point = snap["over"][1]
            under_point = snap["under"][1]
            if over_point is None or under_point is None or abs(over_point - under_point) > 1e-9:
                continue
            if recommended_line is not None and abs(float(recommended_line) - float(over_point)) > 1e-9:
                return None, "MISMATCHED_TOTAL_POINTS"

        if market_family == "TEAM_TOTAL":
            # Team totals require explicit team-scoped market; if team identity is absent, fail closed.
            over_name = str(snap["over"][0] or "").upper()
            under_name = str(snap["under"][0] or "").upper()
            if not over_name or not under_name or over_name != under_name:
                return None, "UNAVAILABLE_TWO_SIDED_MARKET"
            wanted = str(team_code or "").strip().upper()
            if wanted and wanted not in over_name:
                return None, "UNAVAILABLE_TWO_SIDED_MARKET"

        if market_family == "SPREAD" and recommended_line is not None:
            side_point = snap.get(side, (None, None, None))[1]
            if side_point is not None and abs(float(side_point) - float(recommended_line)) > 1e-9:
                continue

        if market_family == "FIRST_HALF_SPREAD" and recommended_line is not None:
            side_point = snap.get(side, (None, None, None))[1]
            if side_point is not None and abs(float(side_point) - float(recommended_line)) > 1e-9:
                continue

        p_a = float(snap[sides[0]][2])
        p_b = float(snap[sides[1]][2])
        novig_a, novig_b = _devig_two_way(p_a, p_b)
        if side == sides[0]:
            return novig_a, "AVAILABLE_TWO_SIDED_MARKET"
        if side == sides[1]:
            return novig_b, "AVAILABLE_TWO_SIDED_MARKET"
        break

    return None, "UNAVAILABLE_TWO_SIDED_MARKET"


def _line_clv_points(market_family: str, side: str, recommended_line: Optional[float], closing_line: Optional[float]) -> Optional[float]:
    if recommended_line is None or closing_line is None:
        return None
    market = market_family.upper()
    sd = str(side).lower()

    if market in {"SPREAD", "FIRST_HALF_SPREAD"}:
        return float(round(float(recommended_line) - float(closing_line), 3))
    if market in {"TOTAL", "FIRST_HALF_TOTAL", "TEAM_TOTAL"}:
        if sd == "over":
            return float(round(float(closing_line) - float(recommended_line), 3))
        if sd == "under":
            return float(round(float(recommended_line) - float(closing_line), 3))
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
    """Build shadow candidates for supported market families and persist immutable run rows."""
    board = _load_line_board()
    proj = _load_projection_lookup()

    if board.empty or not proj:
        raise ValueError("Required data unavailable: line_movement_board or current_game_projections")

    board = board.copy()
    board["market"] = board["market"].map(_normalize_market)
    board["side"] = board["side"].astype(str).str.strip().str.lower()
    board["_group_side"] = board["side"]
    for idx, row in board.iterrows():
        if str(row.get("market") or "") != "team_total":
            continue
        team_code = _team_code_from_row(row, str(row.get("side") or ""))
        if team_code:
            board.at[idx, "_group_side"] = f"{str(row.get('side') or '').lower()}:{team_code}"

    working = board[
        board["market"].isin(
            [
                "spread",
                "moneyline",
                "total",
                "team_total",
                "first_half_spread",
                "first_half_moneyline",
                "first_half_total",
            ]
        )
    ].copy()
    if working.empty:
        raise ValueError("No supported rows available in line_movement_board")

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
    grouped = working.groupby(["api_event_id", "market", "_group_side"], dropna=False, sort=False)
    selected: dict[tuple[str, str, str], pd.Series] = {}

    for (event_id, market_key, side_key), group in grouped:
        best_row = None
        best_score = None
        for _, row in group.iterrows():
            line = _safe_float(row.get("latest_point"))
            price = _safe_float(row.get("latest_price"))
            score = _line_desirability(str(market_key), str(row.get("side") or ""), line, price)
            if best_score is None or score > best_score:
                best_score = score
                best_row = row
        if best_row is not None:
            selected[(str(event_id), str(market_key), str(side_key))] = best_row

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

        # spread pair
        sh = selected.get((event_id, "spread", "home"))
        sa = selected.get((event_id, "spread", "away"))
        if sh is not None and sa is not None:
            shp = _safe_float(sh.get("latest_price"))
            sap = _safe_float(sa.get("latest_price"))
            if shp is not None and sap is not None:
                h_novig, a_novig = _devig_two_way(shp, sap)
                no_vig_map[(event_id, "spread")] = {"home": h_novig, "away": a_novig}

        # first-half moneyline pair
        h1h = selected.get((event_id, "first_half_moneyline", "home"))
        h1a = selected.get((event_id, "first_half_moneyline", "away"))
        if h1h is not None and h1a is not None:
            hp = _safe_float(h1h.get("latest_price"))
            ap = _safe_float(h1a.get("latest_price"))
            if hp is not None and ap is not None:
                h_novig, a_novig = _devig_two_way(hp, ap)
                no_vig_map[(event_id, "first_half_moneyline")] = {"home": h_novig, "away": a_novig}

        # first-half spread pair
        h1sh = selected.get((event_id, "first_half_spread", "home"))
        h1sa = selected.get((event_id, "first_half_spread", "away"))
        if h1sh is not None and h1sa is not None:
            hp = _safe_float(h1sh.get("latest_price"))
            ap = _safe_float(h1sa.get("latest_price"))
            if hp is not None and ap is not None:
                h_novig, a_novig = _devig_two_way(hp, ap)
                no_vig_map[(event_id, "first_half_spread")] = {"home": h_novig, "away": a_novig}

        # first-half total pair
        h1o = selected.get((event_id, "first_half_total", "over"))
        h1u = selected.get((event_id, "first_half_total", "under"))
        if h1o is not None and h1u is not None:
            op = _safe_float(h1o.get("latest_price"))
            up = _safe_float(h1u.get("latest_price"))
            if op is not None and up is not None:
                o_novig, u_novig = _devig_two_way(op, up)
                no_vig_map[(event_id, "first_half_total")] = {"over": o_novig, "under": u_novig}

        # team total pairs by team
        for team in {str(row.get("home_team") or "").strip().upper(), str(row.get("away_team") or "").strip().upper()}:
            if not team:
                continue
            over = selected.get((event_id, "team_total", f"over:{team}"))
            if over is None:
                over = selected.get((event_id, "team_total", "over"))
            under = selected.get((event_id, "team_total", f"under:{team}"))
            if under is None:
                under = selected.get((event_id, "team_total", "under"))
            if over is not None and under is not None:
                op = _safe_float(over.get("latest_price"))
                up = _safe_float(under.get("latest_price"))
                if op is not None and up is not None:
                    o_novig, u_novig = _devig_two_way(op, up)
                    no_vig_map[(event_id, f"team_total:{team}")] = {"over": o_novig, "under": u_novig}

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
    for (event_id, market_key, side_key), row in selected.items():
        side = str(row.get("side") or str(side_key).split(":", 1)[0]).lower()
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

        if not _model_available_for_market(market_key):
            # Modeling firewall: no defensible model, no synthetic probabilities.
            continue
        if not _shadow_recommendation_eligible_for_market(market_key):
            # Research-only firewall: collect raw market data, but do not publish recommendations.
            continue

        if market_key == "spread":
            raw_prob = _safe_float(row.get("model_prob"))
            if raw_prob is None:
                continue
            raw_prob = max(1e-6, min(1.0 - 1e-6, float(raw_prob)))
            push_prob = _safe_float(row.get("push_probability")) or 0.0
            loss_prob = max(0.0, 1.0 - raw_prob - push_prob)
        elif market_key == "moneyline":
            if model_margin is None:
                continue
            raw_prob, push_prob, loss_prob = _moneyline_probability_from_margin(model_margin, side)
        elif market_key == "team_total":
            if model_total is None or model_margin is None or line is None:
                continue
            team_code = _team_code_from_row(row, str(side))
            if team_code is None:
                continue
            raw_prob, push_prob, loss_prob = _team_total_probability(
                team_code=team_code,
                side=str(side),
                total_point=float(line),
                model_total_baseline=float(model_total),
                model_margin_home=float(model_margin),
                home_team=str(row.get("home_team") or ""),
                away_team=str(row.get("away_team") or ""),
            )
            if raw_prob is None:
                continue
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
        if market_key == "team_total":
            team_code = _team_code_from_row(row, str(side)) or ""
            novig = no_vig_map.get((event_id, f"team_total:{team_code}"), {}).get(side)
        if novig is None:
            novig = implied

        raw_edge = float(raw_prob - novig)
        cal_edge = float(calibrated_prob - novig)
        ev = float(ev_per_dollar_with_push(win_probability=calibrated_prob, push_probability=push_prob, american_odds=price))

        if market_key == "spread":
            family = "SPREAD"
            team = str(row.get("home_team") if side == "home" else row.get("away_team"))
            if line is not None:
                selection = f"{team} {line:+g}"
            else:
                selection = team
            period = _market_period_for_key(market_key)
        elif market_key == "team_total":
            family = "TEAM_TOTAL"
            team = _team_code_from_row(row, str(side))
            selection = f"{str(team or '').upper()} {str(side).upper()} {line:g}" if line is not None else f"{str(team or '').upper()} {str(side).upper()}"
            period = _market_period_for_key(market_key)
        elif market_key == "moneyline":
            family = "MONEYLINE"
            team = str(row.get("home_team") if side == "home" else row.get("away_team"))
            selection = team
            period = _market_period_for_key(market_key)
        elif market_key == "first_half_moneyline":
            family = "FIRST_HALF_MONEYLINE"
            team = str(row.get("home_team") if side == "home" else row.get("away_team"))
            selection = team
            period = _market_period_for_key(market_key)
        elif market_key == "first_half_spread":
            family = "FIRST_HALF_SPREAD"
            team = str(row.get("home_team") if side == "home" else row.get("away_team"))
            selection = f"{team} {line:+g}" if line is not None else team
            period = _market_period_for_key(market_key)
        elif market_key == "first_half_total":
            family = "FIRST_HALF_TOTAL"
            team = None
            selection = f"{side.upper()} {line:g}" if line is not None else side.upper()
            period = _market_period_for_key(market_key)
        else:
            family = "TOTAL"
            team = None
            selection = f"{side.upper()} {line:g}" if line is not None else side.upper()
            period = _market_period_for_key(market_key)

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
        if family == "SPREAD":
            candidate["productionEligible"] = True
        candidates.append(candidate)

    # Independent ranking by market family.
    qualified = [c for c in candidates if c["qualificationStatus"] == "QUALIFIED"]
    for family in ["SPREAD", "MONEYLINE", "TOTAL", "TEAM_TOTAL", "FIRST_HALF_SPREAD", "FIRST_HALF_MONEYLINE", "FIRST_HALF_TOTAL"]:
        fam = [c for c in qualified if c["marketFamily"] == family]
        fam.sort(key=lambda x: (-x["calibratedEdge"], -x["ev"], -x["rawModelProbability"], x["eventId"], x["side"]))
        for idx, c in enumerate(fam, start=1):
            c["marketRank"] = idx

    # week rank per family includes non-qualified after qualified.
    for family in ["SPREAD", "MONEYLINE", "TOTAL", "TEAM_TOTAL", "FIRST_HALF_SPREAD", "FIRST_HALF_MONEYLINE", "FIRST_HALF_TOTAL"]:
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

    prospective_capture = capture_prospective_from_line_board(week=int(week), season=int(season))

    return {
        "runId": run_id,
        "createdAtUTC": created_at,
        "season": int(season),
        "week": int(week),
        "sourceSnapshotId": run_payload["sourceSnapshotId"],
        "sourceMarketTimestamp": source_market_timestamp,
        "candidateCount": len(candidates),
        "spreadCount": len([c for c in candidates if c["marketFamily"] == "SPREAD"]),
        "moneylineCount": len([c for c in candidates if c["marketFamily"] == "MONEYLINE"]),
        "totalCount": len([c for c in candidates if c["marketFamily"] == "TOTAL"]),
        "teamTotalCount": len([c for c in candidates if c["marketFamily"] == "TEAM_TOTAL"]),
        "firstHalfSpreadCount": len([c for c in candidates if c["marketFamily"] == "FIRST_HALF_SPREAD"]),
        "firstHalfMoneylineCount": len([c for c in candidates if c["marketFamily"] == "FIRST_HALF_MONEYLINE"]),
        "firstHalfTotalCount": len([c for c in candidates if c["marketFamily"] == "FIRST_HALF_TOTAL"]),
        "prospectiveCapture": prospective_capture,
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
        elif market_family == "FIRST_HALF_MONEYLINE":
            away_h1, home_h1 = _first_half_scores(score)
            if away_h1 is None or home_h1 is None:
                still_pending += 1
                continue
            if side == "home":
                result = "WIN" if home_h1 > away_h1 else "LOSS" if home_h1 < away_h1 else "PUSH"
            elif side == "away":
                result = "WIN" if away_h1 > home_h1 else "LOSS" if away_h1 < home_h1 else "PUSH"
        elif market_family == "TOTAL":
            if line is None:
                still_pending += 1
                continue
            total = float(home) + float(away)
            if side == "over":
                result = "WIN" if total > line else "LOSS" if total < line else "PUSH"
            elif side == "under":
                result = "WIN" if total < line else "LOSS" if total > line else "PUSH"
        elif market_family == "FIRST_HALF_TOTAL":
            if line is None:
                still_pending += 1
                continue
            away_h1, home_h1 = _first_half_scores(score)
            if away_h1 is None or home_h1 is None:
                still_pending += 1
                continue
            total_h1 = float(away_h1) + float(home_h1)
            if side == "over":
                result = "WIN" if total_h1 > line else "LOSS" if total_h1 < line else "PUSH"
            elif side == "under":
                result = "WIN" if total_h1 < line else "LOSS" if total_h1 > line else "PUSH"
        elif market_family == "SPREAD":
            if line is None:
                still_pending += 1
                continue
            away_score = float(away)
            home_score = float(home)
            if side == "away":
                ats_margin = (away_score + float(line)) - home_score
            elif side == "home":
                ats_margin = (home_score + float(line)) - away_score
            else:
                ats_margin = None
            if ats_margin is None:
                still_pending += 1
                continue
            if ats_margin > 0:
                result = "WIN"
            elif ats_margin < 0:
                result = "LOSS"
            else:
                result = "PUSH"
        elif market_family == "FIRST_HALF_SPREAD":
            if line is None:
                still_pending += 1
                continue
            away_h1, home_h1 = _first_half_scores(score)
            if away_h1 is None or home_h1 is None:
                still_pending += 1
                continue
            if side == "away":
                ats_margin = (float(away_h1) + float(line)) - float(home_h1)
            elif side == "home":
                ats_margin = (float(home_h1) + float(line)) - float(away_h1)
            else:
                ats_margin = None
            if ats_margin is None:
                still_pending += 1
                continue
            if ats_margin > 0:
                result = "WIN"
            elif ats_margin < 0:
                result = "LOSS"
            else:
                result = "PUSH"
        elif market_family == "TEAM_TOTAL":
            if line is None:
                still_pending += 1
                continue
            team_code = str(r["team_code"] or "").upper()
            away_code, home_code = _extract_away_home_from_event_id(str(r["event_id"] or ""))
            team_score = None
            if team_code and home_code and team_code == home_code:
                team_score = float(home)
            elif team_code and away_code and team_code == away_code:
                team_score = float(away)
            if team_score is None:
                still_pending += 1
                continue
            if side == "over":
                result = "WIN" if team_score > line else "LOSS" if team_score < line else "PUSH"
            elif side == "under":
                result = "WIN" if team_score < line else "LOSS" if team_score > line else "PUSH"

        if result is None:
            still_pending += 1
            continue

        # Closing and CLV from immutable recommendation price/line, never substituted by current odds.
        closing_line = None
        closing_price = None
        raw_closing_implied_probability = None
        closing_market_novig_probability = None
        closing_no_vig_status = "UNAVAILABLE_TWO_SIDED_MARKET"
        closing_timestamp = None
        line_clv_points = None
        price_clv_probability = None
        clv = None
        clv_type = None

        commence = str(r["commence_time"] or "")
        kickoff = _parse_commence(commence)
        if kickoff is not None:
            market_key = (
                "h2h" if market_family == "MONEYLINE"
                else "totals" if market_family == "TOTAL"
                else "spreads" if market_family == "SPREAD"
                else "team_totals" if market_family == "TEAM_TOTAL"
                else "spreads_h1" if market_family == "FIRST_HALF_SPREAD"
                else "h2h_h1" if market_family == "FIRST_HALF_MONEYLINE"
                else "totals_h1" if market_family == "FIRST_HALF_TOTAL"
                else ""
            )
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
                        raw_closing_implied_probability = _implied_probability(float(closing_price))

                    closing_market_novig_probability, closing_no_vig_status = _two_sided_closing_no_vig(
                        event_id=str(r["event_id"]),
                        sportsbook=str(r["sportsbook"] or ""),
                        market_family=market_family,
                        side=side,
                        kickoff=kickoff,
                        recommended_line=_safe_float(r["line"]),
                        team_code=str(r["team_code"] or "").upper() if market_family == "TEAM_TOTAL" else None,
                    )

                    closing_timestamp = close.closing_timestamp.isoformat() if close.closing_timestamp else None

                    line_clv_points = _line_clv_points(
                        market_family=market_family,
                        side=side,
                        recommended_line=_safe_float(r["line"]),
                        closing_line=closing_line,
                    )

                    if closing_market_novig_probability is not None and r["market_no_vig_probability"] is not None:
                        price_clv_probability = float(round(closing_market_novig_probability - float(r["market_no_vig_probability"]), 6))

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
            "rawClosingImpliedProbability": raw_closing_implied_probability,
            "closingMarketNoVigProbability": closing_market_novig_probability,
            "closingNoVigStatus": closing_no_vig_status,
            "closingTimestamp": closing_timestamp,
            "lineCLVPoints": line_clv_points,
            "priceCLVProbability": price_clv_probability,
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
                closing_line, closing_price, raw_closing_implied_probability,
                closing_market_novig_probability, closing_no_vig_status, closing_timestamp,
                line_clv_points, price_clv_probability,
                clv, clv_type,
                source_odds_snapshot_id, payload_hash, canonical_payload, idempotency_key
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                raw_closing_implied_probability,
                closing_market_novig_probability,
                closing_no_vig_status,
                closing_timestamp,
                line_clv_points,
                price_clv_probability,
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
        SELECT i.*, o.result, o.profit_per_dollar, o.clv,
               o.line_clv_points, o.price_clv_probability,
               o.closing_market_novig_probability, o.closing_no_vig_status
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


def _ece(y: list[float], p: list[float], bins: int = 10) -> Optional[float]:
    if not y or not p or len(y) != len(p):
        return None
    import numpy as np

    y_arr = np.asarray(y, dtype=float)
    p_arr = np.clip(np.asarray(p, dtype=float), 0.0, 1.0)
    edges = np.linspace(0.0, 1.0, bins + 1)
    bucket = np.clip(np.digitize(p_arr, edges, right=True) - 1, 0, bins - 1)

    score = 0.0
    for b in range(bins):
        mask = bucket == b
        if not mask.any():
            continue
        w = float(mask.mean())
        conf = float(p_arr[mask].mean())
        acc = float(y_arr[mask].mean())
        score += w * abs(acc - conf)
    return float(score)


def _rolling_roi(points: list[float], window: int = 20) -> list[float]:
    if not points:
        return []
    out: list[float] = []
    for idx in range(len(points)):
        lo = max(0, idx - window + 1)
        segment = points[lo : idx + 1]
        out.append(float(sum(segment) / len(segment)))
    return out


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


PROSPECTIVE_SETTLED_TARGETS = {
    "MONEYLINE": 200,
    "TOTAL": 300,
}


def _settled_target_for_family(family: str) -> int:
    return int(PROSPECTIVE_SETTLED_TARGETS.get(str(family).upper(), 100))


def _prospective_snapshot_metrics(con: sqlite3.Connection, family: str) -> dict[str, Any]:
    rows = con.execute(
        """
        SELECT event_id, state_label, book_coverage_count, market_no_vig_probability, sportsbook
        FROM prospective_market_snapshots
        WHERE phase = 'PREGAME' AND market_family = ?
        """,
        [family],
    ).fetchall()

    if not rows:
        return {
            "openingCoverage": 0.0,
            "currentCoverage": 0.0,
            "closingCoverage": 0.0,
            "twoSidedNoVigCoverage": 0.0,
            "averageSportsbookDepth": None,
            "medianSportsbookDepth": None,
            "snapshotEventCount": 0,
            "snapshotRowCount": 0,
        }

    events = {str(r["event_id"] or "") for r in rows if str(r["event_id"] or "")}
    per_state_events: dict[str, set[str]] = {"OPENING": set(), "CURRENT": set(), "CLOSING": set()}
    depth_values: list[float] = []
    two_sided = 0

    for r in rows:
        event_id = str(r["event_id"] or "")
        state = str(r["state_label"] or "")
        if event_id and state in per_state_events:
            per_state_events[state].add(event_id)
        if r["book_coverage_count"] is not None:
            depth_values.append(float(r["book_coverage_count"]))
        if r["market_no_vig_probability"] is not None:
            two_sided += 1

    def _coverage(state: str) -> float:
        return float(len(per_state_events[state]) / len(events)) if events else 0.0

    avg_depth = (sum(depth_values) / len(depth_values)) if depth_values else None
    median_depth = None
    if depth_values:
        ordered = sorted(depth_values)
        mid = len(ordered) // 2
        median_depth = float(ordered[mid]) if len(ordered) % 2 else float((ordered[mid - 1] + ordered[mid]) / 2.0)

    return {
        "openingCoverage": _coverage("OPENING"),
        "currentCoverage": _coverage("CURRENT"),
        "closingCoverage": _coverage("CLOSING"),
        "twoSidedNoVigCoverage": float(two_sided / len(rows)),
        "averageSportsbookDepth": avg_depth,
        "medianSportsbookDepth": median_depth,
        "snapshotEventCount": len(events),
        "snapshotRowCount": len(rows),
    }


def shadow_performance_report() -> dict[str, Any]:
    _ensure_schema()
    con = _connect()
    rows = _extract_numeric_rows(con)
    family_snapshot_metrics = {
        fam: _prospective_snapshot_metrics(con, fam)
        for fam in [
            "SPREAD",
            "MONEYLINE",
            "TOTAL",
            "TEAM_TOTAL",
            "FIRST_HALF_SPREAD",
            "FIRST_HALF_MONEYLINE",
            "FIRST_HALF_TOTAL",
        ]
    }
    con.close()

    by_market: dict[str, dict[str, Any]] = {}
    for fam in [
        "SPREAD",
        "MONEYLINE",
        "TOTAL",
        "TEAM_TOTAL",
        "FIRST_HALF_SPREAD",
        "FIRST_HALF_MONEYLINE",
        "FIRST_HALF_TOTAL",
    ]:
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
        positive_clv_rate = (sum(1 for r in graded if r["clv"] is not None and float(r["clv"]) > 0) / len(clv_vals)) if clv_vals else None
        line_clv_vals = [float(r["line_clv_points"]) for r in graded if r["line_clv_points"] is not None]
        price_clv_vals = [float(r["price_clv_probability"]) for r in graded if r["price_clv_probability"] is not None]
        clv_cov = (sum(1 for r in graded if r["clv"] is not None) / len(graded)) if graded else 0.0

        target = _settled_target_for_family(fam)
        snapshot_metrics = family_snapshot_metrics.get(fam, {})
        published = len(fam_rows)
        graded_count = len(graded)

        avg_model_probability = None
        model_probs = [float(r["calibrated_probability"]) for r in fam_rows if r["calibrated_probability"] is not None]
        if model_probs:
            avg_model_probability = sum(model_probs) / len(model_probs)

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
            "published": published,
            "graded": graded_count,
            "bets": graded_count,
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "winRate": win_rate,
            "actualWinRate": win_rate,
            "roi": roi,
            "roiCI95": list(roi_ci) if roi_ci else None,
            "brier": b_model,
            "logLoss": l_model,
            "marketBrier": b_mkt,
            "marketLogLoss": l_mkt,
            "modelMinusMarketBrier": None if b_model is None or b_mkt is None else (b_model - b_mkt),
            "modelMinusMarketLogLoss": None if l_model is None or l_mkt is None else (l_model - l_mkt),
            "ece": _ece(y, p_model),
            "averageModelProbability": avg_model_probability,
            "averageEdge": avg_edge,
            "averageEV": avg_ev,
            "averageCLV": avg_clv,
            "positiveCLVRate": positive_clv_rate,
            "averageLineCLVPoints": (sum(line_clv_vals) / len(line_clv_vals)) if line_clv_vals else None,
            "averagePriceCLVProbability": (sum(price_clv_vals) / len(price_clv_vals)) if price_clv_vals else None,
            "clvCoverage": clv_cov,
            "settledSampleTarget": target,
            "settledSampleProgress": float(graded_count / target) if target else None,
            "openingCoverage": snapshot_metrics.get("openingCoverage"),
            "currentCoverage": snapshot_metrics.get("currentCoverage"),
            "closingCoverage": snapshot_metrics.get("closingCoverage"),
            "twoSidedNoVigCoverage": snapshot_metrics.get("twoSidedNoVigCoverage"),
            "averageSportsbookDepth": snapshot_metrics.get("averageSportsbookDepth"),
            "medianSportsbookDepth": snapshot_metrics.get("medianSportsbookDepth"),
            "snapshotEventCount": snapshot_metrics.get("snapshotEventCount"),
            "snapshotRowCount": snapshot_metrics.get("snapshotRowCount"),
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
            "rolling": {
                "roi20": _rolling_roi(profits, window=20),
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
        target_sample = int(data.get("settledSampleTarget") or _settled_target_for_family(fam))
        graded_sample = int(data.get("graded") or 0)
        sample_ok = graded_sample >= target_sample
        brier_ok = (data.get("modelMinusMarketBrier") is not None) and (float(data["modelMinusMarketBrier"]) <= 0.0)
        ll_ok = (data.get("modelMinusMarketLogLoss") is not None) and (float(data["modelMinusMarketLogLoss"]) <= 0.0)
        ece_ok = (data.get("ece") is not None) and (float(data["ece"]) <= 0.03)

        opening_ok = (data.get("openingCoverage") is not None) and (float(data["openingCoverage"]) >= 0.95)
        current_ok = (data.get("currentCoverage") is not None) and (float(data["currentCoverage"]) >= 0.95)
        closing_ok = (data.get("closingCoverage") is not None) and (float(data["closingCoverage"]) >= 0.95)
        no_vig_ok = (data.get("twoSidedNoVigCoverage") is not None) and (float(data["twoSidedNoVigCoverage"]) >= 0.95)

        avg_depth = data.get("averageSportsbookDepth")
        med_depth = data.get("medianSportsbookDepth")
        depth_ok = bool(avg_depth is not None and med_depth is not None and float(avg_depth) >= 4.0 and float(med_depth) >= 3.0)

        roi_ci = data.get("roiCI95")
        roi_ok = bool(roi_ci and roi_ci[0] is not None and float(roi_ci[0]) >= 0.0)

        eligible = bool(sample_ok and brier_ok and ll_ok and ece_ok and opening_ok and current_ok and closing_ok and no_vig_ok and depth_ok and roi_ok)

        gates[fam] = {
            "productionEligibility": "YES" if eligible else "NO",
            "criteria": {
                "settledSampleTarget": target_sample,
                "settledSampleCount": graded_sample,
                "settledSampleProgress": data.get("settledSampleProgress"),
                "sufficientProspectiveSample": sample_ok,
                "openingCoverageAtLeast95Percent": opening_ok,
                "currentCoverageAtLeast95Percent": current_ok,
                "closingCoverageAtLeast95Percent": closing_ok,
                "twoSidedNoVigCoverageAtLeast95Percent": no_vig_ok,
                "brierVsNoVigMarket": brier_ok,
                "logLossVsNoVigMarket": ll_ok,
                "eceAtMost003": ece_ok,
                "minimumAverageSportsbookDepth": avg_depth is not None and float(avg_depth) >= 4.0,
                "minimumMedianSportsbookDepth": med_depth is not None and float(med_depth) >= 3.0,
                "averageSportsbookDepth": avg_depth,
                "medianSportsbookDepth": med_depth,
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


def _odds_ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _odds_request_json(url: str) -> tuple[int, dict[str, str], Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "SIA-Shadow/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=_odds_ssl_context()) as resp:
            status = int(resp.status)
            headers = {k.lower(): v for k, v in resp.headers.items()}
            body = resp.read().decode("utf-8")
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = {"raw": body}
            return status, headers, parsed
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            parsed = json.loads(body) if body else {"raw": ""}
        except json.JSONDecodeError:
            parsed = {"raw": body}
        headers = {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])}
        return int(exc.code), headers, parsed


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
    return _odds_request_json(url)


def _call_odds_api_events() -> tuple[int, dict[str, str], Any]:
    api_key = _odds_api_key()
    if not api_key:
        return 0, {}, {"error": "ODDS_API_KEY missing"}

    ttl = int(os.getenv("EXPANDED_MARKET_EVENT_CACHE_SECONDS", "300"))
    cached_at = _EVENT_DISCOVERY_CACHE.get("fetchedAt")
    cached_events = _EVENT_DISCOVERY_CACHE.get("events")
    if cached_at and isinstance(cached_events, list):
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        if age <= ttl:
            return 200, {}, cached_events

    base = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events"
    query = {"apiKey": api_key, "dateFormat": "iso"}
    status, headers, payload = _odds_request_json(f"{base}?{urllib.parse.urlencode(query)}")
    if status == 200 and isinstance(payload, list):
        _EVENT_DISCOVERY_CACHE["fetchedAt"] = datetime.now(timezone.utc)
        _EVENT_DISCOVERY_CACHE["events"] = payload
    return status, headers, payload


def _call_odds_api_event_odds(event_id: str, markets: list[str]) -> tuple[int, dict[str, str], Any]:
    api_key = _odds_api_key()
    if not api_key:
        return 0, {}, {"error": "ODDS_API_KEY missing"}

    base = f"https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events/{event_id}/odds"
    query = {
        "apiKey": api_key,
        "regions": "us",
        "markets": ",".join(markets),
        "oddsFormat": "american",
    }
    return _odds_request_json(f"{base}?{urllib.parse.urlencode(query)}")


def _summarize_event_market_payload(event_payload: dict[str, Any], market_key: str) -> dict[str, Any]:
    books = set()
    has_line = False
    has_price = False
    has_ts = False
    usable_outcomes = 0

    for book in event_payload.get("bookmakers", []) or []:
        book_key = str(book.get("key") or "")
        if book.get("last_update"):
            has_ts = True
        for market in book.get("markets", []) or []:
            if str(market.get("key") or "") != market_key:
                continue
            if book_key:
                books.add(book_key)
            if market.get("last_update"):
                has_ts = True
            for outcome in market.get("outcomes", []) or []:
                point = _safe_float(outcome.get("point"))
                price = _safe_float(outcome.get("price"))
                if point is not None:
                    has_line = True
                if price is not None:
                    has_price = True
                if market_key == "h2h_h1":
                    if price is not None:
                        usable_outcomes += 1
                else:
                    if point is not None and price is not None:
                        usable_outcomes += 1

    return {
        "marketKey": market_key,
        "bookCoverage": len(books),
        "availableBooks": sorted(books),
        "lineAvailability": has_line,
        "priceAvailability": has_price,
        "timestampAvailability": has_ts,
        "usableOutcomes": usable_outcomes,
    }


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
    target_labels = {
        "TEAM_TOTAL": "TEAM_TOTAL",
        "FIRST_HALF_SPREAD": "1H_SPREAD",
        "FIRST_HALF_MONEYLINE": "1H_MONEYLINE",
        "FIRST_HALF_TOTAL": "1H_TOTAL",
    }
    request_count = 0
    quota = {}

    per_target: dict[str, dict[str, Any]] = {}
    accum: dict[str, dict[str, Any]] = {}
    for family, label in target_labels.items():
        key = EXPANDED_MARKET_REGISTRY[family]["providerKey"]
        per_target[label] = {
            "supported": False,
            "selectedMarketKey": key,
            "summary": {
                "marketKey": key,
                "providerAvailability": False,
                "bookCoverage": 0,
                "eventCoverage": 0,
                "lineAvailability": False,
                "priceAvailability": False,
                "timestampAvailability": False,
                "usableOutcomes": 0,
                "availableBooks": [],
                "marketDepthStatus": "NO_BOOKS",
            },
            "status": "UNKNOWN",
            "errors": [],
        }
        accum[label] = {
            "books": set(),
            "events": set(),
            "line": False,
            "price": False,
            "ts": False,
            "usable": 0,
            "saw200": False,
            "invalid": False,
            "request_failed": False,
        }

    event_status, event_headers, events_payload = _call_odds_api_events()
    if event_headers:
        quota = {
            "remaining": event_headers.get("x-requests-remaining"),
            "used": event_headers.get("x-requests-used"),
            "last": event_headers.get("x-requests-last"),
        }

    if event_status != 200 or not isinstance(events_payload, list) or not events_payload:
        for label in per_target:
            per_target[label]["status"] = "REQUEST_FAILED"
            per_target[label]["errors"].append(
                {
                    "status": event_status,
                    "detail": events_payload if isinstance(events_payload, dict) else {"message": "Event discovery failed"},
                }
            )
        return {
            "targets": per_target,
            "estimatedRequestCost": request_count,
            "quota": quota,
            "eventSamples": [],
            "eventPayloadById": {},
            "quotaAccounting": {
                "creditsUsed": quota.get("used"),
                "creditsRemaining": quota.get("remaining"),
                "lastRequestCost": quota.get("last"),
                "expandedMarketRequestCount": request_count,
            },
        }

    sample_n = max(1, int(os.getenv("EXPANDED_MARKET_EVENT_SAMPLE_SIZE", "4")))
    sampled_events = events_payload[:sample_n]
    sample_keys = [EXPANDED_MARKET_REGISTRY[f]["providerKey"] for f in target_labels]
    event_payload_map: dict[str, Any] = {}

    for event in sampled_events:
        event_id = str(event.get("id") or "")
        if not event_id:
            continue
        request_count += 1
        status, headers, payload = _call_odds_api_event_odds(event_id, sample_keys)
        quota = {
            "remaining": headers.get("x-requests-remaining"),
            "used": headers.get("x-requests-used"),
            "last": headers.get("x-requests-last"),
        }

        if status == 200 and isinstance(payload, dict):
            event_payload_map[event_id] = payload
            for family, label in target_labels.items():
                provider_key = EXPANDED_MARKET_REGISTRY[family]["providerKey"]
                summary = _summarize_event_market_payload(payload, provider_key)
                a = accum[label]
                a["saw200"] = True
                a["books"].update(summary["availableBooks"])
                if summary["bookCoverage"] > 0:
                    a["events"].add(event_id)
                a["line"] = bool(a["line"] or summary["lineAvailability"])
                a["price"] = bool(a["price"] or summary["priceAvailability"])
                a["ts"] = bool(a["ts"] or summary["timestampAvailability"])
                a["usable"] = int(a["usable"] + int(summary["usableOutcomes"]))
        elif status == 422 and isinstance(payload, dict) and payload.get("error_code") == "INVALID_MARKET":
            for family, label in target_labels.items():
                a = accum[label]
                a["invalid"] = True
                per_target[label]["errors"].append(
                    {
                        "status": status,
                        "detail": payload,
                        "eventId": event_id,
                    }
                )
        else:
            for family, label in target_labels.items():
                a = accum[label]
                a["request_failed"] = True
                per_target[label]["errors"].append(
                    {
                        "status": status,
                        "detail": payload if isinstance(payload, dict) else {"message": "request failed"},
                        "eventId": event_id,
                    }
                )

    for family, label in target_labels.items():
        provider_key = EXPANDED_MARKET_REGISTRY[family]["providerKey"]
        a = accum[label]
        books = sorted(a["books"])
        summary = {
            "marketKey": provider_key,
            "providerAvailability": len(a["events"]) > 0,
            "bookCoverage": len(books),
            "eventCoverage": len(a["events"]),
            "lineAvailability": bool(a["line"]),
            "priceAvailability": bool(a["price"]),
            "timestampAvailability": bool(a["ts"]),
            "usableOutcomes": int(a["usable"]),
            "availableBooks": books,
            "marketDepthStatus": _market_depth_status(len(books)),
        }
        if a["invalid"]:
            status_label = "PROVIDER_UNSUPPORTED"
        elif a["saw200"] and len(a["events"]) > 0 and int(a["usable"]) > 0:
            status_label = "AVAILABLE"
        elif a["saw200"]:
            status_label = "CURRENTLY_NO_MARKET_DATA"
        elif a["request_failed"]:
            status_label = "REQUEST_FAILED"
        else:
            status_label = "UNKNOWN"

        per_target[label]["summary"] = summary
        per_target[label]["status"] = status_label
        per_target[label]["supported"] = status_label in {"AVAILABLE", "CURRENTLY_NO_MARKET_DATA"}

    return {
        "targets": per_target,
        "estimatedRequestCost": request_count,
        "quota": quota,
        "eventSamples": [
            {
                "eventId": str(e.get("id") or ""),
                "awayTeam": str(e.get("away_team") or ""),
                "homeTeam": str(e.get("home_team") or ""),
                "commenceTime": str(e.get("commence_time") or ""),
            }
            for e in sampled_events
            if str(e.get("id") or "")
        ],
        "eventPayloadById": event_payload_map,
        "quotaAccounting": {
            "creditsUsed": quota.get("used"),
            "creditsRemaining": quota.get("remaining"),
            "lastRequestCost": quota.get("last"),
            "expandedMarketRequestCount": request_count,
        },
    }


def phase2b_market_foundation_audit() -> dict[str, Any]:
    discovery = discover_expanded_markets()
    targets = discovery.get("targets") or {}

    def _is_supported(label: str) -> bool:
        return bool((targets.get(label) or {}).get("supported"))

    market_summary: dict[str, dict[str, Any]] = {}
    for fam, meta in PHASE2B_MARKET_FAMILIES.items():
        provider_labels = {
            "TEAM_TOTAL": "TEAM_TOTAL",
            "FIRST_HALF_SPREAD": "1H_SPREAD",
            "FIRST_HALF_MONEYLINE": "1H_MONEYLINE",
            "FIRST_HALF_TOTAL": "1H_TOTAL",
        }
        data_available = _is_supported(provider_labels[fam])
        market_summary[fam] = {
            "dataAvailable": data_available,
            "modelAvailable": bool(meta["modelAvailable"]),
            "modelValidated": bool(meta["modelValidated"]),
            "shadowEligible": bool(meta["shadowEligible"] and data_available and meta["modelAvailable"]),
            "productionEligible": False,
            "crossMarketComparable": False,
            "requiredModelData": list(meta.get("requiredModelData") or []),
        }

    return {
        "providerAudit": discovery,
        "markets": market_summary,
        "collectionStatus": expanded_market_collection_status(),
        "teamTotalResearch": team_total_model_research_validation(),
    }


def expanded_market_collection_status() -> dict[str, Any]:
    _ensure_schema()
    con = _connect()
    rows = con.execute(
        """
        SELECT market_family, event_id, bookmaker, market_timestamp, fetched_at, market_depth_status
        FROM shadow_market_snapshots
        WHERE market_family IN ('TEAM_TOTAL', 'FIRST_HALF_SPREAD', 'FIRST_HALF_MONEYLINE', 'FIRST_HALF_TOTAL')
        """
    ).fetchall()
    con.close()

    by_family: dict[str, dict[str, Any]] = {}
    for fam in ["TEAM_TOTAL", "FIRST_HALF_SPREAD", "FIRST_HALF_MONEYLINE", "FIRST_HALF_TOTAL"]:
        fam_rows = [r for r in rows if str(r["market_family"]) == fam]
        books = sorted({str(r["bookmaker"] or "") for r in fam_rows if str(r["bookmaker"] or "")})
        timestamps = [
            str(r["market_timestamp"] or r["fetched_at"] or "")
            for r in fam_rows
            if str(r["market_timestamp"] or r["fetched_at"] or "")
        ]
        meta = PHASE2B_MARKET_FAMILIES.get(fam, {})
        by_family[fam] = {
            "eventsCollected": len({str(r["event_id"]) for r in fam_rows if str(r["event_id"]) }),
            "rowsCollected": len(fam_rows),
            "availableBooks": books,
            "bookCoverageCount": len(books),
            "marketDepthStatus": _market_depth_status(len(books)),
            "earliestTimestamp": min(timestamps) if timestamps else None,
            "latestTimestamp": max(timestamps) if timestamps else None,
            "modelStatus": {
                "modelAvailable": bool(meta.get("modelAvailable")),
                "modelValidated": bool(meta.get("modelValidated")),
                "shadowRecommendationEligible": bool(meta.get("shadowEligible")),
                "productionEligible": False,
            },
            "mode": "DATA_COLLECTION" if not bool(meta.get("shadowEligible")) else "MODEL_BACKED_SHADOW_RECOMMENDATION",
        }

    return {"markets": by_family}


def _select_first_column(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _team_total_research_from_df(df: pd.DataFrame) -> dict[str, Any]:
    required = {"home_score", "away_score", "model_margin", "model_total"}
    if not required.issubset(set(df.columns)):
        return {
            "ready": False,
            "validated": False,
            "reason": "missing required columns",
        }

    home_actual = pd.to_numeric(df["home_score"], errors="coerce")
    away_actual = pd.to_numeric(df["away_score"], errors="coerce")
    model_margin = pd.to_numeric(df["model_margin"], errors="coerce")
    model_total = pd.to_numeric(df["model_total"], errors="coerce")

    valid = pd.DataFrame(
        {
            "home_actual": home_actual,
            "away_actual": away_actual,
            "model_margin": model_margin,
            "model_total": model_total,
        }
    ).dropna()
    if valid.empty:
        return {
            "ready": False,
            "validated": False,
            "reason": "no valid rows",
        }

    home_expected = (valid["model_total"] + valid["model_margin"]) / 2.0
    away_expected = (valid["model_total"] - valid["model_margin"]) / 2.0

    home_resid = valid["home_actual"] - home_expected
    away_resid = valid["away_actual"] - away_expected

    def _rmse(vals: pd.Series) -> float:
        return float((vals.pow(2).mean()) ** 0.5)

    residual_pool = pd.concat([home_resid, away_resid], ignore_index=True).dropna()
    residual_values = residual_pool.to_numpy(dtype=float)

    home_line_col = _select_first_column(df, ["home_team_total_line", "home_team_total", "home_team_total_point"])
    away_line_col = _select_first_column(df, ["away_team_total_line", "away_team_total", "away_team_total_point"])
    home_price_col = _select_first_column(df, ["home_team_total_price", "home_team_total_over_price"])
    away_price_col = _select_first_column(df, ["away_team_total_price", "away_team_total_over_price"])

    line_rows = []
    if home_line_col is not None or away_line_col is not None:
        for idx, row in valid.iterrows():
            if home_line_col and pd.notna(df.loc[idx, home_line_col]):
                line_rows.append(("home", float(row["home_actual"]), float(home_expected.loc[idx]), float(df.loc[idx, home_line_col])))
            if away_line_col and pd.notna(df.loc[idx, away_line_col]):
                line_rows.append(("away", float(row["away_actual"]), float(away_expected.loc[idx]), float(df.loc[idx, away_line_col])))

    prob_eval: dict[str, Any] = {
        "lineSampleSize": len(line_rows),
        "brierOver": None,
        "logLossOver": None,
        "calibrationECEOver": None,
        "maxSymmetryError": None,
        "pushRate": None,
        "roiEdgeHistoricallyAvailable": bool(home_price_col is not None or away_price_col is not None),
    }

    if len(line_rows) >= 25 and len(residual_values) >= 50:
        y_over: list[float] = []
        p_over: list[float] = []
        symmetry_errors: list[float] = []
        push_count = 0

        for _, actual_points, expected_points, line in line_rows:
            sims = pd.Series((expected_points + residual_values).round())
            p_o = float((sims > line).mean())
            p_p = float((sims == line).mean())
            p_u = float((sims < line).mean())
            symmetry_errors.append(abs(1.0 - (p_o + p_p + p_u)))

            if actual_points == line:
                push_count += 1
                continue
            y_over.append(1.0 if actual_points > line else 0.0)
            p_over.append(p_o)

        prob_eval["maxSymmetryError"] = max(symmetry_errors) if symmetry_errors else None
        prob_eval["pushRate"] = float(push_count / len(line_rows)) if line_rows else None
        if y_over and len(y_over) == len(p_over):
            prob_eval["brierOver"] = _brier(y_over, p_over)
            prob_eval["logLossOver"] = _logloss(y_over, p_over)
            prob_eval["calibrationECEOver"] = _ece(y_over, p_over)

    sample_size = int(len(valid))
    ready = sample_size >= 200
    validated = bool(
        ready
        and prob_eval["lineSampleSize"] >= 100
        and prob_eval["brierOver"] is not None
        and prob_eval["logLossOver"] is not None
        and (prob_eval["maxSymmetryError"] is not None and float(prob_eval["maxSymmetryError"]) < 1e-6)
    )

    return {
        "ready": ready,
        "validated": validated,
        "sampleSize": sample_size,
        "identityChecks": {
            "totalConsistencyMaxAbs": float(((home_expected + away_expected) - valid["model_total"]).abs().max()),
            "marginConsistencyMaxAbs": float(((home_expected - away_expected) - valid["model_margin"]).abs().max()),
        },
        "homeMetrics": {
            "mae": float(home_resid.abs().mean()),
            "rmse": _rmse(home_resid),
            "residualMean": float(home_resid.mean()),
            "residualStd": float(home_resid.std(ddof=0)),
        },
        "awayMetrics": {
            "mae": float(away_resid.abs().mean()),
            "rmse": _rmse(away_resid),
            "residualMean": float(away_resid.mean()),
            "residualStd": float(away_resid.std(ddof=0)),
        },
        "probabilityValidation": prob_eval,
        "historicalRoiEdgeValidation": "UNAVAILABLE" if not prob_eval["roiEdgeHistoricallyAvailable"] else "AVAILABLE",
    }


def team_total_model_research_validation() -> dict[str, Any]:
    walkforward = OUTPUTS_ROOT / "walkforward_multiseason_predictions.csv"
    if not walkforward.exists():
        return {
            "ready": False,
            "validated": False,
            "reason": "walkforward_multiseason_predictions.csv missing",
        }

    try:
        df = pd.read_csv(walkforward)
    except (OSError, pd.errors.EmptyDataError) as exc:
        return {
            "ready": False,
            "validated": False,
            "reason": f"failed to read walkforward data: {exc}",
        }

    return _team_total_research_from_df(df)


def ingest_expanded_market_snapshots(discovery: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    _ensure_schema()
    if discovery is None:
        discovery = discover_expanded_markets()

    saved = 0
    request_count = 0
    quota = dict((discovery.get("quota") or {}))
    quota_safety_threshold = int(os.getenv("ODDS_API_EXPANDED_QUOTA_SAFETY_THRESHOLD", "500"))
    con = _connect()
    id_to_event = {str(e.get("eventId") or ""): e for e in (discovery.get("eventSamples") or []) if str(e.get("eventId") or "")}
    payload_by_event = dict(discovery.get("eventPayloadById") or {})
    projection_lookup = _load_projection_lookup()
    prospective_rows: list[dict[str, Any]] = []

    def _quota_remaining(q: dict[str, Any]) -> Optional[int]:
        return _safe_int((q or {}).get("remaining"))

    target_map = {
        "TEAM_TOTAL": "TEAM_TOTAL",
        "FIRST_HALF_SPREAD": "1H_SPREAD",
        "FIRST_HALF_MONEYLINE": "1H_MONEYLINE",
        "FIRST_HALF_TOTAL": "1H_TOTAL",
    }
    active_keys = [
        EXPANDED_MARKET_REGISTRY[fam]["providerKey"]
        for fam, label in target_map.items()
        if bool((discovery.get("targets") or {}).get(label, {}).get("supported"))
    ]

    remaining = _quota_remaining(quota)
    if remaining is not None and remaining <= quota_safety_threshold:
        con.close()
        return {
            "rowsSaved": 0,
            "eventsProcessed": 0,
            "requestCount": 0,
            "quota": quota,
            "quotaAccounting": {
                "creditsUsed": quota.get("used"),
                "creditsRemaining": quota.get("remaining"),
                "lastRequestCost": quota.get("last"),
                "requestsMadeThisRun": 0,
                "expandedMarketRequestsThisRun": 0,
            },
            "degraded": True,
            "degradationReason": "QUOTA_SAFETY_THRESHOLD",
            "prospectiveCapture": {
                "rowsReceived": 0,
                "currentInserted": 0,
                "openingInserted": 0,
                "closingInserted": 0,
                "duplicateRejectionCount": 0,
                "staleSnapshotCount": 0,
                "postKickoffRejectedCount": 0,
                "missingFieldCount": 0,
            },
        }

    for event_id, event_meta in id_to_event.items():
        payload = payload_by_event.get(event_id)
        if not isinstance(payload, dict):
            request_count += 1
            status, headers, fetched_payload = _call_odds_api_event_odds(event_id, active_keys)
            quota = {
                "remaining": headers.get("x-requests-remaining"),
                "used": headers.get("x-requests-used"),
                "last": headers.get("x-requests-last"),
            }
            if status != 200 or not isinstance(fetched_payload, dict):
                continue
            payload = fetched_payload

        books_for_market: dict[str, set[str]] = {k: set() for k in active_keys}
        best_price_for_market: dict[tuple[str, str, str, str], tuple[float, str]] = {}

        for book in payload.get("bookmakers", []) or []:
            book_key = str(book.get("key") or "")
            for market in book.get("markets", []) or []:
                mk = str(market.get("key") or "")
                if mk not in books_for_market:
                    continue
                if book_key:
                    books_for_market[mk].add(book_key)
                for outcome in market.get("outcomes", []) or []:
                    side = str(outcome.get("name") or "").strip().lower()
                    team_code = str(outcome.get("description") or "").strip().upper()
                    point = _safe_float(outcome.get("point"))
                    price = _safe_float(outcome.get("price"))
                    if mk in {"h2h_h1", "spreads_h1"} and side not in {"home", "away"}:
                        home = str(event_meta.get("homeTeam") or "").strip().lower()
                        away = str(event_meta.get("awayTeam") or "").strip().lower()
                        if side == home:
                            side = "home"
                        elif side == away:
                            side = "away"
                    key = (mk, side, str(point), team_code)
                    if price is not None and (key not in best_price_for_market or price > best_price_for_market[key][0]):
                        best_price_for_market[key] = (price, book_key)

        for book in payload.get("bookmakers", []) or []:
            bookmaker = str(book.get("key") or "")
            for market in book.get("markets", []) or []:
                market_key = str(market.get("key") or "")
                if market_key not in active_keys:
                    continue

                family = next(
                    fam for fam, meta in EXPANDED_MARKET_REGISTRY.items() if meta["providerKey"] == market_key
                )
                period = EXPANDED_MARKET_REGISTRY[family]["period"]
                market_ts = str(market.get("last_update") or book.get("last_update") or payload.get("commence_time") or "")
                fetched_at = _utc_now_iso()
                available_books = sorted(books_for_market.get(market_key) or set())
                book_cov = len(available_books)
                depth = _market_depth_status(book_cov)
                consensus = 1 if book_cov >= 2 else 0

                for outcome in market.get("outcomes", []) or []:
                    raw_name = str(outcome.get("name") or "").strip()
                    side = raw_name.lower()
                    team_code = str(outcome.get("description") or "").strip().upper() or None
                    if market_key in {"h2h_h1", "spreads_h1"} and side not in {"home", "away"}:
                        home = str(event_meta.get("homeTeam") or "").strip().lower()
                        away = str(event_meta.get("awayTeam") or "").strip().lower()
                        if side == home:
                            side = "home"
                        elif side == away:
                            side = "away"
                    line = _safe_float(outcome.get("point"))
                    price = _safe_float(outcome.get("price"))
                    if market_key in {"team_totals", "totals_h1", "team_totals_h1", "totals"} and side not in {"over", "under"}:
                        side = side if side in {"over", "under"} else ""

                    selection = raw_name
                    if team_code:
                        selection = f"{team_code} {raw_name}".strip()

                    best_key = (market_key, side, str(line), str(team_code or ""))
                    best_book = best_price_for_market.get(best_key, (None, None))[1]
                    source_snapshot_id = _sha256(
                        _canonical_json(
                            {
                                "eventId": event_id,
                                "marketKey": market_key,
                                "selection": selection,
                                "line": line,
                                "price": price,
                                "sportsbook": bookmaker,
                                "marketTimestamp": market_ts,
                            }
                        )
                    )

                    payload_row = {
                        "eventId": event_id,
                        "providerEventId": event_id,
                        "marketFamily": family,
                        "providerMarketKey": market_key,
                        "phase": "PREGAME",
                        "period": period,
                        "gameStateTimestamp": None,
                        "teamCode": team_code,
                        "selection": selection,
                        "side": side,
                        "line": line,
                        "price": price,
                        "sportsbook": bookmaker,
                        "marketTimestamp": market_ts,
                        "fetchedAt": fetched_at,
                        "sourceSnapshotId": source_snapshot_id,
                        "bookCoverageCount": book_cov,
                        "availableBooks": available_books,
                        "bestPriceBook": best_book,
                        "consensusAvailable": bool(consensus),
                        "marketDepthStatus": depth,
                    }
                    canonical = _canonical_json(payload_row)
                    p_hash = _sha256(canonical)
                    idem = _sha256(f"shadow-market:{p_hash}")
                    snapshot_id = str(uuid.uuid5(uuid.NAMESPACE_URL, idem))

                    before = con.total_changes
                    con.execute(
                        """
                        INSERT OR IGNORE INTO shadow_market_snapshots (
                            snapshot_id, captured_at_utc,
                            event_id, provider_event_id,
                            market_family, market_key, phase, period, game_state_timestamp, team_code, selection, side,
                            line, price, bookmaker, market_timestamp, fetched_at, source_snapshot_id,
                            book_coverage_count, available_books, best_price_book, consensus_available, market_depth_status,
                            payload_hash, canonical_payload, idempotency_key
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        [
                            snapshot_id,
                            _utc_now_iso(),
                            event_id,
                            event_id,
                            family,
                            market_key,
                            "PREGAME",
                            period,
                            None,
                            team_code,
                            selection,
                            side,
                            line,
                            price,
                            bookmaker,
                            market_ts,
                            fetched_at,
                            source_snapshot_id,
                            book_cov,
                            json.dumps(available_books, separators=(",", ":")),
                            best_book,
                            consensus,
                            depth,
                            p_hash,
                            canonical,
                            idem,
                        ],
                    )
                    if con.total_changes > before:
                        saved += 1

                    implied = _implied_probability(float(price)) if price is not None else None
                    model_state, recommendations = _row_market_metadata(
                        market_key=_normalize_market(market_key),
                        market_family=family,
                        side=side,
                        team_code=team_code,
                    )
                    projected_total = None
                    projected_margin = None
                    derived_home = None
                    derived_away = None
                    selected_team = None
                    if family == "TEAM_TOTAL":
                        projection = projection_lookup.get(event_id)
                        if projection is not None:
                            projected_total = _safe_float(projection.get("model_total_baseline"))
                            projected_margin = _safe_float(projection.get("model_margin_home"))
                            if projected_total is not None and projected_margin is not None:
                                derived_home = (float(projected_total) + float(projected_margin)) / 2.0
                                derived_away = float(projected_total) - float(derived_home)
                                home_team = str(event_meta.get("homeTeam") or "").strip().upper()
                                away_team = str(event_meta.get("awayTeam") or "").strip().upper()
                                if str(team_code or "").upper() == home_team:
                                    selected_team = derived_home
                                elif str(team_code or "").upper() == away_team:
                                    selected_team = derived_away

                    season_row, week_row = _extract_season_week_from_game_id(
                        event_id,
                        _parse_commence(event_meta.get("commenceTime")),
                    )
                    prospective_rows.append(
                        {
                            "season": int(season_row),
                            "week": int(week_row),
                            "eventId": event_id,
                            "providerEventId": event_id,
                            "commenceTime": str(event_meta.get("commenceTime") or ""),
                            "marketFamily": family,
                            "marketKey": _normalize_market(market_key),
                            "phase": "PREGAME",
                            "period": period,
                            "teamCode": team_code,
                            "selection": selection,
                            "side": side,
                            "line": line,
                            "price": price,
                            "sportsbook": bookmaker,
                            "bookmakerKey": bookmaker,
                            "marketTimestamp": market_ts,
                            "fetchedAt": fetched_at,
                            "sourceSnapshotId": source_snapshot_id,
                            "bookCoverageCount": book_cov,
                            "availableBooks": available_books,
                            "marketDepthStatus": depth,
                            "allBooks": [
                                {
                                    "book": bookmaker,
                                    "line": line,
                                    "price": price,
                                    "side": side,
                                    "teamCode": team_code,
                                }
                            ],
                            "bestPrice": price,
                            "bestPriceBook": best_book or bookmaker,
                            "consensusLine": line if consensus else None,
                            "medianLine": line,
                            "projectedGameTotal": projected_total,
                            "projectedHomeMargin": projected_margin,
                            "derivedProjectedHomePoints": derived_home,
                            "derivedProjectedAwayPoints": derived_away,
                            "selectedTeamProjectedPoints": selected_team,
                            "rawProbability": None,
                            "calibratedProbability": None,
                            "pushProbability": None,
                            "lossProbability": None,
                            "marketImpliedProbability": implied,
                            "marketNoVigProbability": None,
                            "edge": None,
                            "ev": None,
                            "fairValue": None,
                            "playableTo": None,
                            "siScore": None,
                            "marketRank": None,
                            "globalResearchScore": None,
                            "globalResearchRank": None,
                            "productionEligible": False,
                            "crossMarketComparable": False,
                            "marketValidationStatus": "UNAVAILABLE_TWO_SIDED_MARKET",
                            "modelState": model_state,
                            "shadowRecommendations": recommendations,
                            "modelVersion": settings.DEFAULT_MODEL_VERSION,
                            "probabilityEngineVersion": settings.DEFAULT_PROBABILITY_ENGINE_VERSION,
                            "calibrationVersion": settings.DEFAULT_CALIBRATION_VERSION,
                            "rankingVersion": settings.DEFAULT_RANKING_VERSION,
                            "qualificationPolicyVersion": settings.DEFAULT_QUALIFICATION_POLICY_VERSION,
                            "gitCommitHash": settings.DEFAULT_GIT_COMMIT_HASH,
                            "gameStateTimestamp": None,
                            "gameQuarter": None,
                            "gameClock": None,
                            "possession": None,
                        }
                    )

    con.commit()
    con.close()
    prospective_capture = _capture_prospective_rows(prospective_rows)
    return {
        "rowsSaved": saved,
        "eventsProcessed": len(id_to_event),
        "requestCount": request_count,
        "quota": quota,
        "quotaAccounting": {
            "creditsUsed": quota.get("used"),
            "creditsRemaining": quota.get("remaining"),
            "lastRequestCost": quota.get("last"),
            "requestsMadeThisRun": request_count,
            "expandedMarketRequestsThisRun": request_count,
        },
        "degraded": False,
        "prospectiveCapture": prospective_capture,
    }


def discover_player_props() -> dict[str, Any]:
    sample_size = max(1, int(os.getenv("PLAYER_PROP_EVENT_SAMPLE_SIZE", "2")))
    requested_keys = list(PLAYER_PROP_TARGET_MARKETS.keys())
    request_count = 0
    fallback_key_requests = 0
    quota = {}
    events_queried = 0
    sampled_players: list[dict[str, Any]] = []

    per_market: dict[str, dict[str, Any]] = {}
    for key in requested_keys:
        per_market[key] = {
            "providerKey": key,
            "propType": PLAYER_PROP_TARGET_MARKETS[key],
            "books": set(),
            "events": set(),
            "outcomes": 0,
            "lineSupplied": False,
            "priceSupplied": False,
            "playerNameSupplied": False,
            "timestampSupplied": False,
            "sawSuccess": False,
            "sawMarket": False,
            "invalid": False,
            "quotaBlocked": False,
            "requestFailed": False,
            "unknown": False,
        }

    extra_markets: set[str] = set()
    event_status, event_headers, events_payload = _call_odds_api_events()
    if event_headers:
        quota = {
            "remaining": event_headers.get("x-requests-remaining"),
            "used": event_headers.get("x-requests-used"),
            "last": event_headers.get("x-requests-last"),
        }

    event_samples: list[dict[str, Any]] = []
    event_payload_map: dict[str, Any] = {}
    if event_status == 200 and isinstance(events_payload, list):
        event_samples = events_payload[:sample_size]

    for event in event_samples:
        event_id = str(event.get("id") or "")
        if not event_id:
            continue
        events_queried += 1
        request_count += 1
        status, headers, payload = _call_odds_api_event_odds(event_id, requested_keys)
        quota = {
            "remaining": headers.get("x-requests-remaining"),
            "used": headers.get("x-requests-used"),
            "last": headers.get("x-requests-last"),
        }

        if status == 429:
            for key in requested_keys:
                per_market[key]["quotaBlocked"] = True
            continue

        if status == 422 and isinstance(payload, dict) and payload.get("error_code") == "INVALID_MARKET":
            # Controlled fallback: probe each key on this event to classify unsupported keys.
            for key in requested_keys:
                fallback_key_requests += 1
                request_count += 1
                s2, h2, p2 = _call_odds_api_event_odds(event_id, [key])
                quota = {
                    "remaining": h2.get("x-requests-remaining"),
                    "used": h2.get("x-requests-used"),
                    "last": h2.get("x-requests-last"),
                }
                if s2 == 200 and isinstance(p2, dict):
                    event_payload_map[f"{event_id}:{key}"] = p2
                    per_market[key]["sawSuccess"] = True
                    for book in p2.get("bookmakers", []) or []:
                        book_key = _normalize_bookmaker_key(book.get("key"))
                        has_ts = bool(book.get("last_update"))
                        for market in book.get("markets", []) or []:
                            if str(market.get("key") or "") != key:
                                continue
                            per_market[key]["sawMarket"] = True
                            if market.get("last_update"):
                                has_ts = True
                            if has_ts:
                                per_market[key]["timestampSupplied"] = True
                            per_market[key]["books"].add(book_key)
                            per_market[key]["events"].add(event_id)
                            for outcome in market.get("outcomes", []) or []:
                                per_market[key]["outcomes"] += 1
                                if _safe_float(outcome.get("point")) is not None:
                                    per_market[key]["lineSupplied"] = True
                                if _safe_float(outcome.get("price")) is not None:
                                    per_market[key]["priceSupplied"] = True
                                player_name = str(outcome.get("description") or outcome.get("name") or "").strip()
                                if player_name:
                                    per_market[key]["playerNameSupplied"] = True
                                if len(sampled_players) < 200:
                                    sampled_players.append(
                                        {
                                            "providerMarketKey": key,
                                            "eventId": event_id,
                                            "eventAwayTeam": str(event.get("away_team") or ""),
                                            "eventHomeTeam": str(event.get("home_team") or ""),
                                            "book": book_key,
                                            "name": str(outcome.get("name") or "").strip(),
                                            "description": str(outcome.get("description") or "").strip(),
                                            "team": str(outcome.get("team") or ""),
                                            "providerPlayerId": str(outcome.get("player_id") or "") or None,
                                            "line": _safe_float(outcome.get("point")),
                                            "price": _safe_float(outcome.get("price")),
                                            "marketTimestamp": str(market.get("last_update") or book.get("last_update") or ""),
                                        }
                                    )
                elif s2 == 422 and isinstance(p2, dict) and p2.get("error_code") == "INVALID_MARKET":
                    per_market[key]["invalid"] = True
                elif s2 == 429:
                    per_market[key]["quotaBlocked"] = True
                elif s2 >= 500 or s2 == 0:
                    per_market[key]["requestFailed"] = True
                else:
                    per_market[key]["unknown"] = True
            continue

        if status != 200 or not isinstance(payload, dict):
            for key in requested_keys:
                if status == 429:
                    per_market[key]["quotaBlocked"] = True
                elif status >= 500 or status == 0:
                    per_market[key]["requestFailed"] = True
                else:
                    per_market[key]["unknown"] = True
            continue

        event_payload_map[event_id] = payload
        for book in payload.get("bookmakers", []) or []:
            book_key = _normalize_bookmaker_key(book.get("key"))
            base_ts = bool(book.get("last_update"))
            for market in book.get("markets", []) or []:
                mk = str(market.get("key") or "")
                if mk.startswith("player_") and mk not in PLAYER_PROP_TARGET_MARKETS:
                    extra_markets.add(mk)
                if mk not in per_market:
                    continue
                m = per_market[mk]
                m["sawSuccess"] = True
                m["sawMarket"] = True
                m["books"].add(book_key)
                m["events"].add(event_id)
                if base_ts or market.get("last_update"):
                    m["timestampSupplied"] = True
                for outcome in market.get("outcomes", []) or []:
                    m["outcomes"] += 1
                    if _safe_float(outcome.get("point")) is not None:
                        m["lineSupplied"] = True
                    if _safe_float(outcome.get("price")) is not None:
                        m["priceSupplied"] = True
                    player_name = str(outcome.get("description") or outcome.get("name") or "").strip()
                    if player_name:
                        m["playerNameSupplied"] = True
                    if len(sampled_players) < 200:
                        sampled_players.append(
                            {
                                "providerMarketKey": mk,
                                "eventId": event_id,
                                "eventAwayTeam": str(event.get("away_team") or ""),
                                "eventHomeTeam": str(event.get("home_team") or ""),
                                "book": book_key,
                                "name": str(outcome.get("name") or "").strip(),
                                "description": str(outcome.get("description") or "").strip(),
                                "team": str(outcome.get("team") or ""),
                                "providerPlayerId": str(outcome.get("player_id") or "") or None,
                                "line": _safe_float(outcome.get("point")),
                                "price": _safe_float(outcome.get("price")),
                                "marketTimestamp": str(market.get("last_update") or book.get("last_update") or ""),
                            }
                        )

    markets_out: list[dict[str, Any]] = []
    for key in requested_keys:
        m = per_market[key]
        classification = "UNKNOWN"
        if m["invalid"]:
            classification = "PROVIDER_UNSUPPORTED"
        elif m["quotaBlocked"]:
            classification = "QUOTA_BLOCKED"
        elif m["requestFailed"]:
            classification = "REQUEST_FAILED"
        elif m["sawMarket"] and m["outcomes"] > 0:
            classification = "AVAILABLE"
        elif m["sawSuccess"]:
            classification = "CURRENTLY_NO_MARKET_DATA"
        elif m["unknown"]:
            classification = "UNKNOWN"

        markets_out.append(
            {
                "providerKey": key,
                "propType": m["propType"],
                "classification": classification,
                "availability": classification == "AVAILABLE",
                "bookCount": len(m["books"]),
                "outcomeCount": int(m["outcomes"]),
                "lineSupplied": bool(m["lineSupplied"]),
                "priceSupplied": bool(m["priceSupplied"]),
                "playerNameSupplied": bool(m["playerNameSupplied"]),
                "timestampSupplied": bool(m["timestampSupplied"]),
                "eventsSampled": len(m["events"]),
            }
        )

    events_count = max(1, events_queried)
    estimated_credits_per_event = float(round(request_count / events_count, 4))
    estimated_full_slate_cost = float(round(estimated_credits_per_event * 16.0, 2))

    return {
        "status": "PASS" if any(m["classification"] == "AVAILABLE" for m in markets_out) else "FAIL",
        "markets": markets_out,
        "otherPropMarkets": sorted(extra_markets),
        "sampledPlayers": sampled_players,
        "eventSamples": [
            {
                "eventId": str(e.get("id") or ""),
                "awayTeam": str(e.get("away_team") or ""),
                "homeTeam": str(e.get("home_team") or ""),
                "commenceTime": str(e.get("commence_time") or ""),
            }
            for e in event_samples
            if str(e.get("id") or "")
        ],
        "eventPayloadById": event_payload_map,
        "quota": quota,
        "quotaTelemetry": {
            "requestsRemaining": quota.get("remaining"),
            "requestsUsed": quota.get("used"),
            "lastRequestCost": quota.get("last"),
            "eventsQueried": events_queried,
            "marketsRequested": len(requested_keys),
            "requestsMade": request_count,
            "fallbackKeyRequests": fallback_key_requests,
            "estimatedCreditsPerEvent": estimated_credits_per_event,
            "estimatedFullSlateCost": estimated_full_slate_cost,
        },
        "recommendedCollectionCadence": "Every 30 minutes pregame, tighten to every 10 minutes inside 90 minutes to kickoff.",
    }


def player_identity_mapping_plan(sampled_players: list[dict[str, Any]]) -> dict[str, Any]:
    identity_keys: set[tuple[str, Optional[str], Optional[str], tuple[str, ...]]] = set()
    resolution_details: list[dict[str, Any]] = []
    for p in sampled_players:
        raw = str(p.get("description") or p.get("name") or "").strip()
        if not raw:
            continue
        team = _normalize_player_prop_team_code(p.get("team"))
        event_team_codes = {
            _normalize_player_prop_team_code(p.get("eventAwayTeam")),
            _normalize_player_prop_team_code(p.get("eventHomeTeam")),
        }
        event_team_codes = {t for t in event_team_codes if t}
        provider_player_id = str(p.get("providerPlayerId") or "").strip() or None
        identity_keys.add((raw, team, provider_player_id, tuple(sorted(event_team_codes))))

    exact = 0
    normalized = 0
    ambiguous = 0
    unmatched = 0
    ambiguous_examples: list[dict[str, Any]] = []
    unmatched_players: list[str] = []

    for raw, team, provider_player_id, event_teams_tuple in sorted(identity_keys):
        event_team_codes = set(event_teams_tuple)
        resolved = _resolve_player_identity(
            raw,
            team,
            provider_player_id=provider_player_id,
            event_team_codes=event_team_codes,
        )
        status = str(resolved.get("matchStatus") or "UNMATCHED")
        if status == "EXACT":
            exact += 1
        elif status == "NORMALIZED":
            normalized += 1
        elif status == "AMBIGUOUS":
            ambiguous += 1
            if len(ambiguous_examples) < 20:
                ambiguous_examples.append(
                    {
                        "providerPlayerName": raw,
                        "normalizedPlayerName": resolved.get("normalizedPlayerName"),
                        "team": team,
                        "reason": resolved.get("reason"),
                    }
                )
        else:
            unmatched += 1
            if len(unmatched_players) < 50:
                unmatched_players.append(raw)

        resolution_details.append(
            {
                "providerPlayerName": raw,
                "normalizedPlayerName": resolved.get("normalizedPlayerName"),
                "matchStatus": resolved.get("matchStatus"),
                "reason": resolved.get("reason"),
            }
        )

    total = max(1, len(identity_keys))
    return {
        "totalDistinctProviderPlayers": len(identity_keys),
        "exactMatchRate": exact / total,
        "normalizedMatchRate": normalized / total,
        "ambiguousRate": ambiguous / total,
        "unmatchedRate": unmatched / total,
        "ambiguousCount": ambiguous,
        "unmatchedCount": unmatched,
        "ambiguousExamples": ambiguous_examples,
        "unmatchedPlayers": unmatched_players,
        "resolutionDetails": resolution_details,
        "feasible": ambiguous == 0,
    }


def player_prop_market_contract() -> dict[str, Any]:
    return {
        "marketFamily": "PLAYER_PROP",
        "period": "FULL_GAME",
        "phase": "PREGAME",
        "fields": [
            "eventId",
            "providerEventId",
            "marketFamily",
            "propType",
            "period",
            "phase",
            "playerId",
            "playerName",
            "team",
            "side",
            "point",
            "price",
            "sportsbook",
            "bookmakerKey",
            "marketTimestamp",
            "fetchedAt",
            "sourceSnapshotId",
            "productionEligible",
            "crossMarketComparable",
            "marketValidationStatus",
        ],
        "modelFields": {
            "modelAvailable": False,
            "modelValidated": False,
            "shadowRecommendationEligible": False,
            "productionEligible": False,
            "crossMarketComparable": False,
            "marketValidationStatus": "DATA_COLLECTION_ONLY",
        },
    }


def _player_prop_opening_exists(con: sqlite3.Connection, row: dict[str, Any]) -> bool:
    found = con.execute(
        """
        SELECT 1
        FROM player_prop_market_snapshots
        WHERE event_id = ?
          AND prop_type = ?
          AND normalized_player_name = ?
          AND ifnull(side, '') = ?
          AND ifnull(point, 0.0) = ifnull(?, 0.0)
          AND sportsbook = ?
          AND phase = 'PREGAME'
          AND state_label = 'OPENING'
        LIMIT 1
        """,
        [
            row.get("eventId"),
            row.get("propType"),
            row.get("normalizedPlayerName"),
            row.get("side") or "",
            row.get("point"),
            row.get("sportsbook"),
        ],
    ).fetchone()
    return found is not None


def _persist_player_prop_state_row(
    con: sqlite3.Connection,
    *,
    row: dict[str, Any],
    state_label: str,
    closing_status: Optional[str],
    closing_cutoff_utc: Optional[str],
    closing_max_age_seconds: Optional[int],
) -> bool:
    payload = dict(row)
    payload["stateLabel"] = state_label
    payload["closingStatus"] = closing_status
    payload["closingCutoffUTC"] = closing_cutoff_utc
    payload["closingMaxAgeSeconds"] = closing_max_age_seconds
    canonical = _canonical_json(payload)
    payload_hash = _sha256(canonical)
    idem = _sha256(f"player-prop:{payload_hash}")
    snapshot_id = str(uuid.uuid5(uuid.NAMESPACE_URL, idem))

    values = [
        snapshot_id,
        _utc_now_iso(),
        row.get("season"),
        row.get("week"),
        row.get("eventId"),
        row.get("providerEventId"),
        row.get("commenceTime"),
        "PLAYER_PROP",
        row.get("propType"),
        row.get("providerMarketKey"),
        row.get("period") or "FULL_GAME",
        row.get("phase") or "PREGAME",
        state_label,
        closing_status,
        closing_cutoff_utc,
        closing_max_age_seconds,
        row.get("providerPlayerName"),
        row.get("normalizedPlayerName"),
        row.get("playerMatchStatus"),
        row.get("providerPlayerId"),
        row.get("canonicalPlayerId"),
        row.get("playerName"),
        row.get("team"),
        row.get("opponent"),
        row.get("position"),
        row.get("selection"),
        row.get("side"),
        row.get("point"),
        row.get("price"),
        row.get("sportsbook"),
        row.get("bookmakerKey"),
        row.get("marketTimestamp"),
        row.get("fetchedAt"),
        row.get("sourceSnapshotId"),
        row.get("bookCoverageCount"),
        json.dumps(row.get("availableBooks") or [], separators=(",", ":")),
        row.get("marketDepthStatus"),
        json.dumps(row.get("allBooks") or [], separators=(",", ":")),
        row.get("bestMarketBook"),
        row.get("bestMarketPoint"),
        row.get("bestMarketPrice"),
        row.get("marketNoVigProbability"),
        row.get("noVigStatus"),
        0,
        0,
        "DATA_COLLECTION_ONLY",
        0,
        0,
        0,
        settings.DEFAULT_MODEL_VERSION,
        settings.DEFAULT_PROBABILITY_ENGINE_VERSION,
        settings.DEFAULT_CALIBRATION_VERSION,
        settings.DEFAULT_RANKING_VERSION,
        settings.DEFAULT_QUALIFICATION_POLICY_VERSION,
        settings.DEFAULT_GIT_COMMIT_HASH,
        row.get("gameStateTimestamp"),
        row.get("gameQuarter"),
        row.get("gameClock"),
        payload_hash,
        canonical,
        idem,
    ]

    before = con.total_changes
    con.execute(
        f"""
        INSERT OR IGNORE INTO player_prop_market_snapshots (
            snapshot_id, captured_at_utc,
            season, week, event_id, provider_event_id, commence_time,
            market_family, prop_type, provider_market_key,
            period, phase, state_label,
            closing_status, closing_cutoff_utc, closing_max_age_seconds,
            provider_player_name, normalized_player_name, player_match_status,
            provider_player_id, canonical_player_id,
            player_name, team, opponent, position,
            selection, side, point, price,
            sportsbook, bookmaker_key,
            market_timestamp, fetched_at, source_snapshot_id,
            book_coverage_count, available_books, market_depth_status, all_books,
            best_market_book, best_market_point, best_market_price,
            market_no_vig_probability, no_vig_status,
            production_eligible, cross_market_comparable, market_validation_status,
            model_available, model_validated, shadow_recommendation_eligible,
            model_version, probability_engine_version, calibration_version,
            ranking_version, qualification_policy_version, git_commit_hash,
            game_state_timestamp, game_quarter, game_clock,
            payload_hash, canonical_payload, idempotency_key
        ) VALUES ({','.join(['?'] * len(values))})
        """,
        values,
    )
    return con.total_changes > before


def ingest_player_prop_market_snapshots(discovery: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    _ensure_schema()
    if discovery is None:
        discovery = discover_player_props()

    payload_by_event = dict(discovery.get("eventPayloadById") or {})
    event_samples = list(discovery.get("eventSamples") or [])
    if not payload_by_event and event_samples:
        requested = list(PLAYER_PROP_TARGET_MARKETS.keys())
        for e in event_samples:
            event_id = str(e.get("eventId") or "")
            if not event_id:
                continue
            status, _, payload = _call_odds_api_event_odds(event_id, requested)
            if status == 200 and isinstance(payload, dict):
                payload_by_event[event_id] = payload

    rows_received = 0
    current_inserted = 0
    opening_inserted = 0
    closing_inserted = 0
    stale_rejected = 0
    post_kickoff_rejected = 0
    duplicates = 0

    con = _connect()

    def _merge_fallback_event_payload(event_id: str) -> Optional[dict[str, Any]]:
        merged_books: dict[str, dict[str, Any]] = {}
        prefix = f"{event_id}:"
        for key, payload in payload_by_event.items():
            if not str(key).startswith(prefix) or not isinstance(payload, dict):
                continue
            for book in payload.get("bookmakers", []) or []:
                book_key = _normalize_bookmaker_key(book.get("key"))
                if not book_key:
                    continue
                entry = merged_books.get(book_key)
                if entry is None:
                    entry = {
                        "key": book.get("key"),
                        "title": book.get("title"),
                        "last_update": book.get("last_update"),
                        "markets": [],
                    }
                    merged_books[book_key] = entry
                if book.get("last_update"):
                    entry["last_update"] = book.get("last_update")

                existing_market_keys = {
                    str(m.get("key") or "")
                    for m in (entry.get("markets") or [])
                }
                for market in book.get("markets", []) or []:
                    mk = str(market.get("key") or "")
                    if mk in existing_market_keys:
                        continue
                    entry["markets"].append(market)
                    existing_market_keys.add(mk)

        if not merged_books:
            return None
        return {"bookmakers": list(merged_books.values())}

    for event in event_samples:
        event_id = str(event.get("eventId") or "")
        if not event_id:
            continue
        payload = payload_by_event.get(event_id)
        if not isinstance(payload, dict):
            payload = _merge_fallback_event_payload(event_id)
        if not isinstance(payload, dict):
            continue

        event_team_codes = {
            _normalize_player_prop_team_code(event.get("awayTeam")),
            _normalize_player_prop_team_code(event.get("homeTeam")),
        }
        event_team_codes = {t for t in event_team_codes if t}

        event_meta_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

        for book in payload.get("bookmakers", []) or []:
            book_key = _normalize_bookmaker_key(book.get("key"))
            book_display = _normalize_bookmaker_display(book.get("title") or book.get("key"), book_key)
            for market in book.get("markets", []) or []:
                mk = str(market.get("key") or "")
                if mk not in PLAYER_PROP_TARGET_MARKETS:
                    continue
                prop_type = PLAYER_PROP_TARGET_MARKETS[mk]
                m_ts = str(market.get("last_update") or book.get("last_update") or event.get("commenceTime") or "")
                for outcome in market.get("outcomes", []) or []:
                    raw_name = str(outcome.get("name") or "").strip()
                    raw_desc = str(outcome.get("description") or "").strip()
                    side = raw_name.upper() if raw_name.lower() in {"over", "under"} else None
                    if side:
                        provider_player_name = raw_desc or raw_name
                    elif raw_name.lower() in {"yes", "no"} and raw_desc:
                        provider_player_name = raw_desc
                    else:
                        provider_player_name = raw_name or raw_desc
                    team_hint = _normalize_player_prop_team_code(outcome.get("team"))
                    provider_player_id = str(outcome.get("player_id") or "").strip() or None
                    identity = _resolve_player_identity(
                        provider_player_name,
                        team_hint,
                        provider_player_id=provider_player_id,
                        event_team_codes=event_team_codes,
                    )
                    normalized_player = str(identity.get("normalizedPlayerName") or "")
                    point = _safe_float(outcome.get("point"))
                    price = _safe_float(outcome.get("price"))
                    selection = (
                        f"{provider_player_name} {side} {point:g}" if side and point is not None
                        else f"{provider_player_name} {side}" if side
                        else provider_player_name
                    )
                    key = (prop_type, normalized_player, str(side or ""))
                    event_meta_by_key.setdefault(key, []).append(
                        {
                            "eventId": event_id,
                            "providerEventId": event_id,
                            "commenceTime": str(event.get("commenceTime") or ""),
                            "propType": prop_type,
                            "providerMarketKey": mk,
                            "period": "FULL_GAME",
                            "phase": "PREGAME",
                            "providerPlayerName": provider_player_name,
                            "normalizedPlayerName": normalized_player,
                            "playerMatchStatus": identity.get("matchStatus"),
                            "providerPlayerId": provider_player_id,
                            "canonicalPlayerId": identity.get("canonicalPlayerId"),
                            "playerName": identity.get("canonicalPlayerName") or provider_player_name,
                            "team": identity.get("team"),
                            "opponent": identity.get("opponent"),
                            "position": identity.get("position"),
                            "selection": selection,
                            "side": side,
                            "point": point,
                            "price": price,
                            "sportsbook": book_display,
                            "bookmakerKey": book_key,
                            "marketTimestamp": m_ts,
                            "fetchedAt": _utc_now_iso(),
                            "sourceSnapshotId": _sha256(
                                _canonical_json(
                                    {
                                        "eventId": event_id,
                                        "providerMarketKey": mk,
                                        "player": provider_player_name,
                                        "side": side,
                                        "point": point,
                                        "price": price,
                                        "bookmakerKey": book_key,
                                        "marketTimestamp": m_ts,
                                    }
                                )
                            ),
                            "gameStateTimestamp": None,
                            "gameQuarter": None,
                            "gameClock": None,
                        }
                    )

        for _, quotes in event_meta_by_key.items():
            available_books = sorted({str(q.get("bookmakerKey") or "") for q in quotes if str(q.get("bookmakerKey") or "")})
            book_count = len(available_books)
            depth = _market_depth_status(book_count)
            sorted_quotes = sorted(
                quotes,
                key=lambda q: _player_prop_sort_key(
                    q.get("side"),
                    _safe_float(q.get("point")),
                    _safe_float(q.get("price")),
                ),
                reverse=True,
            )
            best = sorted_quotes[0]

            for quote in quotes:
                quote["availableBooks"] = available_books
                quote["bookCoverageCount"] = book_count
                quote["marketDepthStatus"] = depth
                quote["allBooks"] = [
                    {
                        "sportsbook": q.get("sportsbook"),
                        "bookmakerKey": q.get("bookmakerKey"),
                        "point": q.get("point"),
                        "price": q.get("price"),
                        "side": q.get("side"),
                    }
                    for q in quotes
                ]
                quote["bestMarketBook"] = best.get("sportsbook")
                quote["bestMarketPoint"] = best.get("point")
                quote["bestMarketPrice"] = best.get("price")
                novig, novig_status = _player_prop_two_sided_no_vig(quotes, quote)
                quote["marketNoVigProbability"] = novig
                quote["noVigStatus"] = novig_status

                rows_received += 1
                if _persist_player_prop_state_row(
                    con,
                    row=quote,
                    state_label="CURRENT",
                    closing_status=None,
                    closing_cutoff_utc=None,
                    closing_max_age_seconds=None,
                ):
                    current_inserted += 1
                else:
                    duplicates += 1

                if not _player_prop_opening_exists(con, quote):
                    if _persist_player_prop_state_row(
                        con,
                        row=quote,
                        state_label="OPENING",
                        closing_status=None,
                        closing_cutoff_utc=None,
                        closing_max_age_seconds=None,
                    ):
                        opening_inserted += 1
                    else:
                        duplicates += 1

                closing_ok, close_status, close_cutoff, close_age = _closing_cutoff_details(
                    commence_time=quote.get("commenceTime"),
                    market_timestamp=quote.get("marketTimestamp"),
                    fetched_at=quote.get("fetchedAt"),
                )
                if closing_ok:
                    if _persist_player_prop_state_row(
                        con,
                        row=quote,
                        state_label="CLOSING",
                        closing_status="AVAILABLE",
                        closing_cutoff_utc=close_cutoff,
                        closing_max_age_seconds=close_age,
                    ):
                        closing_inserted += 1
                    else:
                        duplicates += 1
                elif close_status == "STALE_REJECTED":
                    stale_rejected += 1
                elif close_status == "POST_KICKOFF_REJECTED":
                    post_kickoff_rejected += 1

    con.commit()
    con.close()

    return {
        "rowsReceived": rows_received,
        "currentInserted": current_inserted,
        "openingInserted": opening_inserted,
        "closingInserted": closing_inserted,
        "duplicateRejectionCount": duplicates,
        "staleSnapshotCount": stale_rejected,
        "postKickoffRejectedCount": post_kickoff_rejected,
    }


def player_prop_grading_source_audit() -> dict[str, Any]:
    try:
        import duckdb  # type: ignore
    except Exception:
        return {
            "statusByPropType": {
                prop: "MISSING_STAT_SOURCE"
                for prop in PLAYER_PROP_TARGET_MARKETS.values()
            },
            "availableStatColumns": [],
            "reason": "duckdb unavailable",
        }

    db = MODEL_ROOT / "database" / "nfl_model.duckdb"
    if not db.exists():
        return {
            "statusByPropType": {
                prop: "MISSING_STAT_SOURCE"
                for prop in PLAYER_PROP_TARGET_MARKETS.values()
            },
            "availableStatColumns": [],
            "reason": "nfl_model.duckdb not found",
        }

    con = duckdb.connect(str(db), read_only=True)
    try:
        cols = con.execute(
            """
            SELECT lower(column_name)
            FROM information_schema.columns
            WHERE table_schema = 'main'
            """
        ).fetchall()
    finally:
        con.close()

    available = {str(r[0]) for r in cols}
    status: dict[str, str] = {}
    for prop_type, candidates in PLAYER_PROP_GRADING_COLUMN_CANDIDATES.items():
        status[prop_type] = "GRADING_READY" if any(c.lower() in available for c in candidates) else "MISSING_STAT_SOURCE"

    return {
        "statusByPropType": status,
        "availableStatColumns": sorted(available),
    }


def player_prop_coverage_report() -> dict[str, Any]:
    _ensure_schema()
    con = _connect()
    rows = con.execute(
        """
        SELECT *
        FROM player_prop_market_snapshots
        WHERE phase = 'PREGAME'
        """
    ).fetchall()
    con.close()

    grading = player_prop_grading_source_audit()
    by_state = {"OPENING": 0, "CURRENT": 0, "CLOSING": 0}
    by_prop_books: dict[str, set[str]] = {}
    for r in rows:
        state = str(r["state_label"] or "")
        if state in by_state:
            by_state[state] += 1
        prop = str(r["prop_type"] or "")
        by_prop_books.setdefault(prop, set()).add(str(r["bookmaker_key"] or ""))

    identities = {
        (
            str(r["event_id"] or ""),
            str(r["prop_type"] or ""),
            str(r["normalized_player_name"] or ""),
            str(r["side"] or ""),
            str(r["point"]),
            str(r["bookmaker_key"] or ""),
        )
        for r in rows
    }

    exact = sum(1 for r in rows if str(r["player_match_status"] or "") == "EXACT")
    normalized = sum(1 for r in rows if str(r["player_match_status"] or "") == "NORMALIZED")
    ambiguous = sum(1 for r in rows if str(r["player_match_status"] or "") == "AMBIGUOUS")
    unmatched = sum(1 for r in rows if str(r["player_match_status"] or "") == "UNMATCHED")
    total = max(1, exact + normalized + ambiguous + unmatched)

    ts_values = [
        str(r["market_timestamp"] or r["fetched_at"] or "")
        for r in rows
        if str(r["market_timestamp"] or r["fetched_at"] or "")
    ]

    return {
        "eventsCaptured": len({str(r["event_id"] or "") for r in rows if str(r["event_id"] or "")}),
        "uniquePlayersCaptured": len({str(r["normalized_player_name"] or "") for r in rows if str(r["normalized_player_name"] or "")}),
        "propMarketsCaptured": len({str(r["prop_type"] or "") for r in rows if str(r["prop_type"] or "")}),
        "quotesCaptured": len(rows),
        "booksPerPropFamily": {k: len(v) for k, v in by_prop_books.items()},
        "earliestSnapshot": min(ts_values) if ts_values else None,
        "latestSnapshot": max(ts_values) if ts_values else None,
        "openingCoverage": by_state["OPENING"] / max(1, len(identities)),
        "currentCoverage": by_state["CURRENT"] / max(1, len(identities)),
        "closingCoverage": by_state["CLOSING"] / max(1, len(identities)),
        "gradingReadiness": grading.get("statusByPropType") or {},
        "identityMatchRates": {
            "EXACT": exact / total,
            "NORMALIZED": normalized / total,
            "AMBIGUOUS": ambiguous / total,
            "UNMATCHED": unmatched / total,
            "AMBIGUOUS_COUNT": ambiguous,
            "UNMATCHED_COUNT": unmatched,
        },
        "modelStatus": {
            "MODEL_AVAILABLE": False,
            "MODEL_VALIDATED": False,
            "SHADOW_RECOMMENDATION_ELIGIBLE": False,
            "PRODUCTION_ELIGIBLE": False,
        },
    }


def player_prop_model_interface_contract() -> dict[str, Any]:
    return {
        "futureAttachableFields": [
            "projectedStat",
            "rawProbability",
            "calibratedProbability",
            "pushProbability",
            "fairPrice",
            "edge",
            "EV",
            "PlayableTo",
            "siScore",
        ],
        "notes": "Design-only interface; no model values are populated in this phase.",
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
