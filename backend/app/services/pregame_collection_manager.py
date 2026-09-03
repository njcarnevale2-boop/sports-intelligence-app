from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.services import shadow_markets
from app.services.games import service as games_service
from app.services.odds_status import evaluate_optional_provider_request


TRACKED_MARKET_FAMILIES = ("SPREAD", "MONEYLINE", "TOTAL")
RESEARCH_ONLY_MARKET_FAMILIES = ("TEAM_TOTAL", "FIRST_HALF_SPREAD", "FIRST_HALF_MONEYLINE", "FIRST_HALF_TOTAL")
DEFAULT_PROP_ALLOWLIST = (
    "player_pass_yds",
    "player_pass_tds",
    "player_rush_yds",
    "player_reception_yds",
    "player_receptions",
    "player_anytime_td",
)
TELEMETRY_PROVIDER = "the-odds-api"
PLAYER_PROP_ENDPOINT_TYPE = "EVENT_ODDS"
PLAYER_PROP_REGION = "us"
VERIFIED_PLAYER_PROP_MARKET_SET = frozenset(
    {
        "player_pass_yds",
        "player_pass_tds",
        "player_rush_yds",
        "player_reception_yds",
        "player_receptions",
        "player_anytime_td",
    }
)
VERIFIED_PLAYER_PROP_CREDITS_PER_REQUEST = 6.0
LIFECYCLE_OPENING = "OPENING"
LIFECYCLE_GAME_DAY = "GAME_DAY"
LIFECYCLE_CLOSING = "CLOSING"
LIFECYCLE_CLOSED = "CLOSED"
STANDARD_LIFECYCLE_STATES = (LIFECYCLE_OPENING, LIFECYCLE_GAME_DAY, LIFECYCLE_CLOSING)
PLAYER_PROP_LIFECYCLE_STATES = (LIFECYCLE_GAME_DAY,)
LIFECYCLE_TO_STORAGE_STATE = {
    LIFECYCLE_OPENING: "OPENING",
    LIFECYCLE_GAME_DAY: "CURRENT",
    LIFECYCLE_CLOSING: "CLOSING",
}
WINDOW_ORDER = {
    LIFECYCLE_OPENING: 0,
    LIFECYCLE_GAME_DAY: 1,
    LIFECYCLE_CLOSING: 2,
    LIFECYCLE_CLOSED: 3,
}


@dataclass(frozen=True)
class ManagerConfig:
    dry_run: bool
    max_requests_per_run: int
    max_estimated_credits_per_run: float
    allow_unknown_credit_cost: bool
    daily_estimated_credit_budget: Optional[float]
    opening_window_hours: int
    closing_window_hours: int
    prop_allowlist: tuple[str, ...]
    player_prop_collection_enabled: bool


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_commence(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _resolve_week(week: Optional[int]) -> int:
    if week is not None:
        return int(week)
    all_games = games_service.list_games()
    available = all_games.get("availableWeeks") or []
    if available:
        return int(available[0])
    return 1


def _resolve_prop_allowlist(raw_allowlist: Optional[list[str]] = None) -> tuple[str, ...]:
    configured: list[str]
    if raw_allowlist is not None:
        configured = [str(item or "").strip() for item in raw_allowlist]
    else:
        env_raw = os.getenv("PREGAME_PLAYER_PROP_ALLOWLIST", "")
        configured = [item.strip() for item in env_raw.split(",") if item.strip()] if env_raw else list(DEFAULT_PROP_ALLOWLIST)

    supported = set(shadow_markets.PLAYER_PROP_TARGET_MARKETS.keys())
    filtered = [key for key in configured if key in supported]

    # Ensure deterministic ordering and dedupe while preserving first occurrence.
    ordered: list[str] = []
    seen: set[str] = set()
    for key in filtered:
        if key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return tuple(ordered)


def _resolve_config(
    *,
    dry_run: bool = True,
    max_requests_per_run: Optional[int] = None,
    max_estimated_credits_per_run: Optional[float] = None,
    daily_estimated_credit_budget: Optional[float] = None,
    estimated_credits_per_request: Optional[float] = None,  # retained for backward compatibility; not used by verified rule.
    deterministic_credit_rule_verified: Optional[bool] = None,
    allow_unknown_credit_cost: bool = False,
    prop_allowlist: Optional[list[str]] = None,
) -> ManagerConfig:
    return ManagerConfig(
        dry_run=bool(dry_run),
        max_requests_per_run=int(max_requests_per_run if max_requests_per_run is not None else int(os.getenv("PREGAME_MAX_REQUESTS_PER_RUN", "25"))),
        max_estimated_credits_per_run=float(max_estimated_credits_per_run if max_estimated_credits_per_run is not None else float(os.getenv("PREGAME_MAX_ESTIMATED_CREDITS_PER_RUN", "25"))),
        allow_unknown_credit_cost=bool(allow_unknown_credit_cost),
        daily_estimated_credit_budget=float(daily_estimated_credit_budget) if daily_estimated_credit_budget is not None else _to_float(os.getenv("PREGAME_DAILY_ESTIMATED_CREDIT_BUDGET")),
        opening_window_hours=int(os.getenv("PREGAME_OPENING_WINDOW_HOURS", "24")),
        closing_window_hours=int(os.getenv("PREGAME_CLOSING_WINDOW_HOURS", "2")),
        prop_allowlist=_resolve_prop_allowlist(prop_allowlist),
        player_prop_collection_enabled=_env_bool("PLAYER_PROP_COLLECTION_ENABLED", False),
    )


def _ensure_manager_schema() -> None:
    shadow_markets._ensure_schema()
    con = shadow_markets._connect()
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS pregame_collection_request_telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            collected_at_utc TEXT NOT NULL,
            provider TEXT,
            request_type TEXT,
            endpoint TEXT,
            endpoint_type TEXT,
            region TEXT,
            markets_requested TEXT,
            market_count INTEGER,
            events_requested TEXT,
            request_count INTEGER NOT NULL DEFAULT 0,
            estimated_credits REAL,
            actual_credits REAL,
            quota_remaining REAL,
            quota_used REAL,
            skipped INTEGER NOT NULL DEFAULT 0,
            skip_reason TEXT,
            duplicate_requests_prevented INTEGER NOT NULL DEFAULT 0,
            credit_cost_estimate_mismatch INTEGER
        )
        """
    )
    existing = {
        str(row[1])
        for row in con.execute("PRAGMA table_info(pregame_collection_request_telemetry)").fetchall()
    }
    for col_name, definition in [
        ("endpoint_type", "TEXT"),
        ("region", "TEXT"),
        ("market_count", "INTEGER"),
        ("credit_cost_estimate_mismatch", "INTEGER"),
    ]:
        if col_name not in existing:
            con.execute(f"ALTER TABLE pregame_collection_request_telemetry ADD COLUMN {col_name} {definition}")
    con.commit()
    con.close()


def _record_telemetry(
    *,
    run_id: str,
    provider: Optional[str],
    request_type: str,
    endpoint: str,
    endpoint_type: str,
    region: str,
    markets_requested: list[str],
    market_count: int,
    events_requested: list[str],
    request_count: int,
    estimated_credits: Optional[float],
    actual_credits: Optional[float],
    quota_remaining: Optional[float],
    quota_used: Optional[float],
    skipped: bool,
    skip_reason: Optional[str],
    duplicate_requests_prevented: int,
    credit_cost_estimate_mismatch: Optional[bool] = None,
) -> None:
    con = shadow_markets._connect()
    con.execute(
        """
        INSERT INTO pregame_collection_request_telemetry (
            run_id, collected_at_utc, provider, request_type, endpoint,
            endpoint_type, region, markets_requested, market_count, events_requested, request_count,
            estimated_credits, actual_credits, quota_remaining, quota_used,
            skipped, skip_reason, duplicate_requests_prevented, credit_cost_estimate_mismatch
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            run_id,
            _utc_now().replace(microsecond=0).isoformat(),
            provider,
            request_type,
            endpoint,
            endpoint_type,
            region,
            json.dumps(markets_requested, separators=(",", ":")),
            int(market_count),
            json.dumps(events_requested, separators=(",", ":")),
            int(request_count),
            estimated_credits,
            actual_credits,
            quota_remaining,
            quota_used,
            1 if skipped else 0,
            skip_reason,
            int(duplicate_requests_prevented),
            None if credit_cost_estimate_mismatch is None else (1 if credit_cost_estimate_mismatch else 0),
        ],
    )
    con.commit()
    con.close()


def _estimate_credits_for_request_shape(*, endpoint_type: str, region: str, markets: list[str]) -> dict[str, Any]:
    endpoint_key = str(endpoint_type or "").strip().upper()
    region_key = str(region or "").strip().lower()
    market_list = [str(m or "").strip() for m in markets]
    market_set = set(market_list)

    exact_market_match = len(market_list) == len(VERIFIED_PLAYER_PROP_MARKET_SET) and market_set == VERIFIED_PLAYER_PROP_MARKET_SET
    if endpoint_key == PLAYER_PROP_ENDPOINT_TYPE and region_key == PLAYER_PROP_REGION and exact_market_match:
        return {
            "status": "VERIFIED",
            "creditsPerRequest": VERIFIED_PLAYER_PROP_CREDITS_PER_REQUEST,
        }

    return {
        "status": "UNKNOWN",
        "creditsPerRequest": None,
    }


def _lifecycle_window_for_event(commence_time: Optional[str], *, config: ManagerConfig, now: datetime) -> str:
    kickoff = _parse_commence(commence_time)
    if kickoff is None:
        return LIFECYCLE_GAME_DAY
    if kickoff <= now:
        return LIFECYCLE_CLOSED

    delta = kickoff - now
    if delta <= timedelta(hours=config.closing_window_hours):
        return LIFECYCLE_CLOSING
    if delta <= timedelta(hours=config.opening_window_hours):
        return LIFECYCLE_GAME_DAY
    return LIFECYCLE_OPENING


def _target_state_for_event(commence_time: Optional[str], *, config: ManagerConfig, now: datetime) -> Optional[str]:
    window = _lifecycle_window_for_event(commence_time, config=config, now=now)
    if window == LIFECYCLE_CLOSED:
        return None
    return LIFECYCLE_TO_STORAGE_STATE.get(window, "CURRENT")


def _load_week_events(week: Optional[int] = None) -> tuple[int, list[dict[str, Any]]]:
    resolved_week = _resolve_week(week)
    payload = games_service.list_games(week=resolved_week)
    return resolved_week, list(payload.get("games") or [])


def _resolve_season_for_week_games(games: list[dict[str, Any]]) -> Optional[int]:
    counts: dict[int, int] = {}
    for game in games:
        try:
            season = int(game.get("season"))
        except (TypeError, ValueError):
            continue
        counts[season] = int(counts.get(season, 0)) + 1

    if not counts:
        return None
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _load_line_board_market_presence() -> dict[str, set[str]]:
    board = shadow_markets._load_line_board()
    if board.empty:
        return {}
    board = board.copy()
    board["api_event_id"] = board["api_event_id"].astype(str)
    board["market"] = board["market"].astype(str).str.strip().str.lower().map(shadow_markets._normalize_market)

    mapping = {
        "spread": "SPREAD",
        "moneyline": "MONEYLINE",
        "total": "TOTAL",
    }
    out: dict[str, set[str]] = {}
    for _, row in board.iterrows():
        event_id = str(row.get("api_event_id") or "")
        family = mapping.get(str(row.get("market") or ""))
        if not event_id or not family:
            continue
        out.setdefault(event_id, set()).add(family)
    return out


def _state_exists_for_market(event_id: str, family: str, state: str) -> bool:
    con = shadow_markets._connect()
    row = con.execute(
        """
        SELECT 1
        FROM prospective_market_snapshots
        WHERE event_id = ?
          AND market_family = ?
          AND phase = 'PREGAME'
          AND state_label = ?
        LIMIT 1
        """,
        [event_id, family, state],
    ).fetchone()
    con.close()
    return row is not None


def _state_exists_for_player_prop_event(event_id: str, state: str) -> bool:
    con = shadow_markets._connect()
    row = con.execute(
        """
        SELECT 1
        FROM player_prop_market_snapshots
        WHERE event_id = ?
          AND phase = 'PREGAME'
          AND state_label = ?
        LIMIT 1
        """,
        [event_id, state],
    ).fetchone()
    con.close()
    return row is not None


def _load_market_state_index() -> dict[tuple[str, str, str], dict[str, Any]]:
    con = shadow_markets._connect()
    rows = con.execute(
        """
        SELECT
            event_id,
            market_family,
            state_label,
            MAX(captured_at_utc) AS captured_at_utc,
            MAX(book_coverage_count) AS book_coverage_count
        FROM prospective_market_snapshots
        WHERE phase = 'PREGAME'
        GROUP BY event_id, market_family, state_label
        """
    ).fetchall()
    con.close()

    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        event_id = str(row["event_id"] or "")
        family = str(row["market_family"] or "").upper()
        state = str(row["state_label"] or "").upper()
        if not event_id or not family or not state:
            continue
        out[(event_id, family, state)] = {
            "capturedAtUTC": row["captured_at_utc"],
            "bookDepth": _to_int(row["book_coverage_count"]),
        }
    return out


def _load_player_prop_state_index() -> dict[tuple[str, str], dict[str, Any]]:
    con = shadow_markets._connect()
    rows = con.execute(
        """
        SELECT
            event_id,
            state_label,
            MAX(captured_at_utc) AS captured_at_utc,
            COUNT(DISTINCT bookmaker_key) AS book_coverage_count
        FROM player_prop_market_snapshots
        WHERE phase = 'PREGAME'
        GROUP BY event_id, state_label
        """
    ).fetchall()
    con.close()

    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        event_id = str(row["event_id"] or "")
        state = str(row["state_label"] or "").upper()
        if not event_id or not state:
            continue
        out[(event_id, state)] = {
            "capturedAtUTC": row["captured_at_utc"],
            "bookDepth": _to_int(row["book_coverage_count"]),
        }
    return out


def _has_any_market_state(event_id: str, family: str) -> bool:
    return any(_state_exists_for_market(event_id, family, LIFECYCLE_TO_STORAGE_STATE[state]) for state in STANDARD_LIFECYCLE_STATES)


def _has_any_player_prop_state(event_id: str) -> bool:
    return any(_state_exists_for_player_prop_event(event_id, LIFECYCLE_TO_STORAGE_STATE[state]) for state in STANDARD_LIFECYCLE_STATES)


def _lifecycle_status(*, window: str, lifecycle_state: str, captured: bool) -> str:
    if captured:
        return "CAPTURED"
    if window == LIFECYCLE_CLOSED:
        return "CLOSED"

    current_order = int(WINDOW_ORDER.get(window, WINDOW_ORDER[LIFECYCLE_GAME_DAY]))
    state_order = int(WINDOW_ORDER.get(lifecycle_state, WINDOW_ORDER[LIFECYCLE_GAME_DAY]))
    if state_order < current_order:
        return "MISSED"
    if state_order == current_order:
        return "DUE"
    return "FUTURE"


def _player_prop_lifecycle_status(*, window: str, captured: bool) -> str:
    if captured:
        return "CAPTURED"
    if window == LIFECYCLE_CLOSED:
        return "CLOSED"
    if window == LIFECYCLE_OPENING:
        return "FUTURE"
    if window == LIFECYCLE_GAME_DAY:
        return "DUE"
    if window == LIFECYCLE_CLOSING:
        return "MISSED"
    return "CLOSED"


def _next_collection_state_from_statuses(*, window: str, standard_statuses: dict[str, dict[str, str]], player_prop_status: str) -> Optional[str]:
    if window == LIFECYCLE_CLOSED:
        return None

    for lifecycle_state in STANDARD_LIFECYCLE_STATES:
        for family in TRACKED_MARKET_FAMILIES:
            if standard_statuses.get(family, {}).get(lifecycle_state) == "DUE":
                return lifecycle_state

    if player_prop_status == "DUE":
        return LIFECYCLE_GAME_DAY

    for lifecycle_state in STANDARD_LIFECYCLE_STATES:
        for family in TRACKED_MARKET_FAMILIES:
            if standard_statuses.get(family, {}).get(lifecycle_state) == "FUTURE":
                return lifecycle_state

    if player_prop_status == "FUTURE":
        return LIFECYCLE_GAME_DAY
    return None


def build_pregame_collection_plan(
    *,
    week: Optional[int] = None,
    dry_run: bool = True,
    max_requests_per_run: Optional[int] = None,
    max_estimated_credits_per_run: Optional[float] = None,
    daily_estimated_credit_budget: Optional[float] = None,
    estimated_credits_per_request: Optional[float] = None,
    deterministic_credit_rule_verified: Optional[bool] = None,
    allow_unknown_credit_cost: bool = False,
    allow_unknown_weekly_usage: bool = False,
    override_quota_guards: bool = False,
    prop_allowlist: Optional[list[str]] = None,
    now_utc: Optional[datetime] = None,
) -> dict[str, Any]:
    _ensure_manager_schema()
    config = _resolve_config(
        dry_run=dry_run,
        max_requests_per_run=max_requests_per_run,
        max_estimated_credits_per_run=max_estimated_credits_per_run,
        daily_estimated_credit_budget=daily_estimated_credit_budget,
        estimated_credits_per_request=estimated_credits_per_request,
        deterministic_credit_rule_verified=deterministic_credit_rule_verified,
        allow_unknown_credit_cost=allow_unknown_credit_cost,
        prop_allowlist=prop_allowlist,
    )
    now = now_utc or _utc_now()

    resolved_week, games = _load_week_events(week=week)
    line_board_markets = _load_line_board_market_presence()

    spread_due = 0
    moneyline_due = 0
    total_due = 0
    player_prop_due = 0
    duplicates_prevented = 0

    player_prop_due_event_ids: list[str] = []
    market_due_event_ids: dict[str, list[str]] = {"SPREAD": [], "MONEYLINE": [], "TOTAL": []}

    events_evaluated = 0
    for game in games:
        event_id = str(game.get("eventId") or "")
        if not event_id:
            continue
        target_state = _target_state_for_event(game.get("commenceTime"), config=config, now=now)
        if target_state is None:
            continue

        events_evaluated += 1
        supported_families = line_board_markets.get(event_id, set())

        for family in TRACKED_MARKET_FAMILIES:
            if family not in supported_families:
                continue
            exists = _state_exists_for_market(event_id, family, target_state)
            if exists:
                duplicates_prevented += 1
                continue
            market_due_event_ids[family].append(event_id)
            if family == "SPREAD":
                spread_due += 1
            elif family == "MONEYLINE":
                moneyline_due += 1
            elif family == "TOTAL":
                total_due += 1

        # Player props remain a GAME_DAY-only lifecycle even when the standard
        # pregame runner is evaluating other windows.
        if target_state != LIFECYCLE_TO_STORAGE_STATE[LIFECYCLE_GAME_DAY]:
            continue

        prop_exists = _state_exists_for_player_prop_event(event_id, target_state)
        if prop_exists:
            duplicates_prevented += 1
            continue
        player_prop_due += 1
        player_prop_due_event_ids.append(event_id)

    player_prop_collection_enabled = bool(config.player_prop_collection_enabled)
    player_prop_skip_reason = None if player_prop_collection_enabled else "PLAYER_PROP_COLLECTION_DISABLED"
    planned_requests = player_prop_due if player_prop_collection_enabled else 0
    if player_prop_collection_enabled:
        estimate_contract = _estimate_credits_for_request_shape(
            endpoint_type=PLAYER_PROP_ENDPOINT_TYPE,
            region=PLAYER_PROP_REGION,
            markets=list(config.prop_allowlist),
        )
        estimated_credits_per_request = estimate_contract.get("creditsPerRequest")
        estimated_credits_status = str(estimate_contract.get("status") or "UNKNOWN")
        estimated_credits = (
            float(round(float(estimated_credits_per_request) * planned_requests, 4))
            if estimated_credits_per_request is not None
            else None
        )
    else:
        estimated_credits_per_request = None
        estimated_credits_status = "DISABLED"
        estimated_credits = 0.0

    api_today = _api_usage_today()
    skip_reasons: list[str] = []
    if planned_requests > config.max_requests_per_run:
        skip_reasons.append("REQUEST_BUDGET_EXCEEDED")
    if estimated_credits is not None and estimated_credits > config.max_estimated_credits_per_run:
        skip_reasons.append("RUN_CREDIT_BUDGET_EXCEEDED")
    if estimated_credits is not None and config.daily_estimated_credit_budget is not None:
        daily_after = float(api_today["estimatedCreditsToday"] or 0.0) + estimated_credits
        if daily_after > float(config.daily_estimated_credit_budget):
            skip_reasons.append("DAILY_CREDIT_BUDGET_EXCEEDED")

    quota_guard = evaluate_optional_provider_request(
        estimated_credits=_to_float(estimated_credits),
        allow_unknown_credit_cost=bool(config.allow_unknown_credit_cost),
        allow_unknown_weekly_usage=bool(allow_unknown_weekly_usage),
        override_quota_guards=bool(override_quota_guards),
    )
    if (not bool(config.dry_run)) and (not bool(quota_guard.get("allowed"))):
        skip_reasons.append(str(quota_guard.get("reason") or "QUOTA_GUARD_BLOCKED"))

    return {
        "manager": "SIA_PREGAME_DATA_COLLECTION_MANAGER_V1",
        "week": resolved_week,
        "dryRun": config.dry_run,
        "playerPropCollectionEnabled": player_prop_collection_enabled,
        "playerPropCollectionSkipReason": player_prop_skip_reason,
        "eventsFound": len(games),
        "eventsEvaluated": events_evaluated,
        "snapshotsDue": {
            "spread": spread_due,
            "moneyline": moneyline_due,
            "total": total_due,
            "playerProp": player_prop_due,
        },
        "plannedRequests": planned_requests,
        "estimatedRequests": planned_requests,
        "estimatedCreditsPerRequest": estimated_credits_per_request,
        "estimatedCredits": estimated_credits,
        "estimatedCreditsStatus": estimated_credits_status,
        "duplicatesPrevented": duplicates_prevented,
        "requestsSkipped": len(skip_reasons),
        "skipReasons": skip_reasons,
        "quotaSafety": quota_guard.get("quotaSafety"),
        "quotaWarnings": quota_guard.get("warnings") or [],
        "allowUnknownCreditCost": config.allow_unknown_credit_cost,
        "allowUnknownWeeklyUsage": bool(allow_unknown_weekly_usage),
        "overrideQuotaGuards": bool(override_quota_guards),
        "requestBudget": {
            "maxRequestsPerRun": config.max_requests_per_run,
            "pass": planned_requests <= config.max_requests_per_run,
        },
        "creditBudget": {
            "maxEstimatedCreditsPerRun": config.max_estimated_credits_per_run,
            "dailyBudget": config.daily_estimated_credit_budget,
            "pass": (
                True
                if estimated_credits is None
                else (estimated_credits <= config.max_estimated_credits_per_run)
                and (
                    config.daily_estimated_credit_budget is None
                    or float(api_today["estimatedCreditsToday"] or 0.0) + estimated_credits <= float(config.daily_estimated_credit_budget)
                )
            ),
            "known": estimated_credits is not None,
        },
        "playerProp": {
            "collectionEnabled": player_prop_collection_enabled,
            "collectionSkipReason": player_prop_skip_reason,
            "endpointType": PLAYER_PROP_ENDPOINT_TYPE,
            "region": PLAYER_PROP_REGION,
            "allowlistProviderMarkets": list(config.prop_allowlist),
            "allowlistPropTypes": [shadow_markets.PLAYER_PROP_TARGET_MARKETS[m] for m in config.prop_allowlist],
            "statePolicy": {
                "openingWindowHours": config.opening_window_hours,
                "closingWindowHours": config.closing_window_hours,
                "labels": [LIFECYCLE_OPENING, LIFECYCLE_GAME_DAY, LIFECYCLE_CLOSING],
                "storageStateLabels": LIFECYCLE_TO_STORAGE_STATE,
                "pregameOnly": True,
            },
            "dueEventIds": player_prop_due_event_ids,
        },
        "marketDueEventIds": market_due_event_ids,
        "apiToday": api_today,
    }


def _api_usage_today() -> dict[str, Any]:
    _ensure_manager_schema()
    con = shadow_markets._connect()
    day_start = _utc_now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    rows = con.execute(
        """
        SELECT request_count, estimated_credits, actual_credits, quota_remaining, quota_used,
               skipped, skip_reason, duplicate_requests_prevented
        FROM pregame_collection_request_telemetry
        WHERE collected_at_utc >= ?
        """,
        [day_start],
    ).fetchall()
    con.close()

    requests_today = sum(int(r["request_count"] or 0) for r in rows)
    estimated_today = sum(float(r["estimated_credits"] or 0.0) for r in rows)

    actual_values = [float(r["actual_credits"]) for r in rows if r["actual_credits"] is not None]
    quota_remaining_values = [float(r["quota_remaining"]) for r in rows if r["quota_remaining"] is not None]
    quota_used_values = [float(r["quota_used"]) for r in rows if r["quota_used"] is not None]

    return {
        "requestsToday": requests_today,
        "estimatedCreditsToday": round(estimated_today, 4),
        "actualCreditsToday": round(sum(actual_values), 4) if actual_values else None,
        "quotaRemaining": quota_remaining_values[-1] if quota_remaining_values else None,
        "quotaUsed": quota_used_values[-1] if quota_used_values else None,
        "duplicateRequestsPrevented": sum(int(r["duplicate_requests_prevented"] or 0) for r in rows),
        "requestsSkippedByQuotaGuard": sum(1 for r in rows if int(r["skipped"] or 0) == 1 and str(r["skip_reason"] or "").startswith("QUOTA")),
    }


def run_pregame_collection_manager(
    *,
    week: Optional[int] = None,
    dry_run: bool = True,
    max_requests_per_run: Optional[int] = None,
    max_estimated_credits_per_run: Optional[float] = None,
    daily_estimated_credit_budget: Optional[float] = None,
    estimated_credits_per_request: Optional[float] = None,
    deterministic_credit_rule_verified: Optional[bool] = None,
    allow_unknown_credit_cost: bool = False,
    allow_unknown_weekly_usage: bool = False,
    override_quota_guards: bool = False,
    prop_allowlist: Optional[list[str]] = None,
) -> dict[str, Any]:
    _ensure_manager_schema()

    plan = build_pregame_collection_plan(
        week=week,
        dry_run=dry_run,
        max_requests_per_run=max_requests_per_run,
        max_estimated_credits_per_run=max_estimated_credits_per_run,
        daily_estimated_credit_budget=daily_estimated_credit_budget,
        estimated_credits_per_request=estimated_credits_per_request,
        deterministic_credit_rule_verified=deterministic_credit_rule_verified,
        allow_unknown_credit_cost=allow_unknown_credit_cost,
        allow_unknown_weekly_usage=allow_unknown_weekly_usage,
        override_quota_guards=override_quota_guards,
        prop_allowlist=prop_allowlist,
    )
    run_id = f"pregame-collect-{uuid.uuid4()}"

    if plan["skipReasons"]:
        _record_telemetry(
            run_id=run_id,
            provider=TELEMETRY_PROVIDER,
            request_type="PREGAME_COLLECTION_RUN",
            endpoint="/events/{eventId}/odds",
            endpoint_type="EVENT_ODDS",
            region="us",
            markets_requested=list(plan["playerProp"].get("allowlistProviderMarkets") or []),
            market_count=len(list(plan["playerProp"].get("allowlistProviderMarkets") or [])),
            events_requested=list(plan["playerProp"].get("dueEventIds") or []),
            request_count=0,
            estimated_credits=plan.get("estimatedCredits"),
            actual_credits=None,
            quota_remaining=None,
            quota_used=None,
            skipped=True,
            skip_reason=plan["skipReasons"][0],
            duplicate_requests_prevented=int(plan.get("duplicatesPrevented") or 0),
            credit_cost_estimate_mismatch=None,
        )
        return {
            "runId": run_id,
            "status": "SKIPPED",
            "dryRun": bool(plan.get("dryRun")),
            "plan": plan,
            "execution": {
                "providerRequests": 0,
                "coreCapture": None,
                "playerPropIngestion": None,
                "skipped": True,
                "skipReason": plan["skipReasons"][0],
            },
        }

    if bool(plan.get("dryRun")):
        _record_telemetry(
            run_id=run_id,
            provider=TELEMETRY_PROVIDER,
            request_type="PREGAME_COLLECTION_DRY_RUN",
            endpoint="/events/{eventId}/odds",
            endpoint_type="EVENT_ODDS",
            region="us",
            markets_requested=list(plan["playerProp"].get("allowlistProviderMarkets") or []),
            market_count=len(list(plan["playerProp"].get("allowlistProviderMarkets") or [])),
            events_requested=list(plan["playerProp"].get("dueEventIds") or []),
            request_count=0,
            estimated_credits=plan.get("estimatedCredits"),
            actual_credits=None,
            quota_remaining=None,
            quota_used=None,
            skipped=True,
            skip_reason="DRY_RUN",
            duplicate_requests_prevented=int(plan.get("duplicatesPrevented") or 0),
            credit_cost_estimate_mismatch=None,
        )
        return {
            "runId": run_id,
            "status": "DRY_RUN",
            "dryRun": True,
            "plan": plan,
            "execution": {
                "providerRequests": 0,
                "coreCapture": None,
                "playerPropIngestion": None,
                "skipped": True,
                "skipReason": "DRY_RUN",
            },
        }

    due_prop_events = list(plan["playerProp"].get("dueEventIds") or [])
    allowlist = list(plan["playerProp"].get("allowlistProviderMarkets") or [])
    player_prop_collection_enabled = bool(plan.get("playerPropCollectionEnabled"))
    player_prop_skip_reason = plan.get("playerPropCollectionSkipReason")
    if not player_prop_collection_enabled:
        due_prop_events = []

    if plan.get("estimatedCredits") is None and due_prop_events and not bool(plan.get("allowUnknownCreditCost")):
        _record_telemetry(
            run_id=run_id,
            provider=TELEMETRY_PROVIDER,
            request_type="PREGAME_COLLECTION_RUN",
            endpoint="/events/{eventId}/odds",
            endpoint_type="EVENT_ODDS",
            region="us",
            markets_requested=allowlist,
            market_count=len(allowlist),
            events_requested=due_prop_events,
            request_count=0,
            estimated_credits=None,
            actual_credits=None,
            quota_remaining=None,
            quota_used=None,
            skipped=True,
            skip_reason="UNKNOWN_PROVIDER_CREDIT_COST",
            duplicate_requests_prevented=int(plan.get("duplicatesPrevented") or 0),
            credit_cost_estimate_mismatch=None,
        )
        return {
            "runId": run_id,
            "status": "SKIPPED",
            "dryRun": False,
            "plan": plan,
            "execution": {
                "providerRequests": 0,
                "actualRequests": 0,
                "coreCapture": None,
                "playerPropIngestion": None,
                "skipped": True,
                "skipReason": "UNKNOWN_PROVIDER_CREDIT_COST",
            },
        }

    event_samples: list[dict[str, Any]] = []
    payload_by_event: dict[str, Any] = {}
    requests_made = 0
    actual_credits_total = 0.0
    actual_credits_seen = False
    credit_cost_estimate_mismatch = False
    last_quota_remaining: Optional[float] = None
    last_quota_used: Optional[float] = None

    _, games = _load_week_events(week=plan.get("week"))
    season_for_week = _resolve_season_for_week_games(games)

    # Core spread/moneyline/total capture uses local canonical line board snapshots.
    core_capture = shadow_markets.capture_prospective_from_line_board(
        week=plan.get("week"),
        season=season_for_week,
    )

    games_by_id = {str(g.get("eventId") or ""): g for g in games if str(g.get("eventId") or "")}
    per_request_estimated = _to_float(plan.get("estimatedCreditsPerRequest"))

    for event_id in due_prop_events:
        requests_made += 1
        status, headers, payload = shadow_markets._call_odds_api_event_odds(event_id, allowlist)

        last_cost = _to_float(headers.get("x-requests-last"))
        quota_remaining = _to_float(headers.get("x-requests-remaining"))
        quota_used = _to_float(headers.get("x-requests-used"))
        if last_cost is not None:
            actual_credits_seen = True
            actual_credits_total += last_cost
        if quota_remaining is not None:
            last_quota_remaining = quota_remaining
        if quota_used is not None:
            last_quota_used = quota_used
        request_mismatch: Optional[bool] = None
        if per_request_estimated is not None and last_cost is not None:
            request_mismatch = abs(float(last_cost) - float(per_request_estimated)) > 1e-9
            if request_mismatch:
                credit_cost_estimate_mismatch = True

        if status != 200 or not isinstance(payload, dict):
            _record_telemetry(
                run_id=run_id,
                provider=TELEMETRY_PROVIDER,
                request_type="PLAYER_PROP_EVENT_ODDS",
                endpoint="/events/{eventId}/odds",
                endpoint_type="EVENT_ODDS",
                region="us",
                markets_requested=allowlist,
                market_count=len(allowlist),
                events_requested=[event_id],
                request_count=1,
                estimated_credits=per_request_estimated,
                actual_credits=last_cost,
                quota_remaining=quota_remaining,
                quota_used=quota_used,
                skipped=True,
                skip_reason=f"HTTP_{status}",
                duplicate_requests_prevented=0,
                credit_cost_estimate_mismatch=request_mismatch,
            )
            continue

        game = games_by_id.get(event_id, {})
        event_samples.append(
            {
                "eventId": event_id,
                "awayTeam": str(game.get("awayAbbreviation") or game.get("awayTeam") or ""),
                "homeTeam": str(game.get("homeAbbreviation") or game.get("homeTeam") or ""),
                "commenceTime": str(game.get("commenceTime") or ""),
            }
        )
        payload_by_event[event_id] = payload

        _record_telemetry(
            run_id=run_id,
            provider=TELEMETRY_PROVIDER,
            request_type="PLAYER_PROP_EVENT_ODDS",
            endpoint="/events/{eventId}/odds",
            endpoint_type="EVENT_ODDS",
            region="us",
            markets_requested=allowlist,
            market_count=len(allowlist),
            events_requested=[event_id],
            request_count=1,
            estimated_credits=per_request_estimated,
            actual_credits=last_cost,
            quota_remaining=quota_remaining,
            quota_used=quota_used,
            skipped=False,
            skip_reason=None,
            duplicate_requests_prevented=0,
            credit_cost_estimate_mismatch=request_mismatch,
        )

    discovery = {
        "eventSamples": event_samples,
        "eventPayloadById": payload_by_event,
        "quota": {
            "remaining": last_quota_remaining,
            "used": last_quota_used,
            "last": None,
        },
    }
    player_prop_ingestion = (
        {"status": "DISABLED", "skipReason": str(player_prop_skip_reason or "PLAYER_PROP_COLLECTION_DISABLED")}
        if not player_prop_collection_enabled
        else shadow_markets.ingest_player_prop_market_snapshots(discovery=discovery)
    )

    return {
        "runId": run_id,
        "status": "COMPLETED",
        "dryRun": False,
        "plan": plan,
        "execution": {
            "providerRequests": requests_made,
            "actualRequests": requests_made,
            "coreCapture": core_capture,
            "playerPropIngestion": player_prop_ingestion,
            "playerPropCollectionEnabled": player_prop_collection_enabled,
            "playerPropCollectionSkipReason": player_prop_skip_reason,
            "actualCreditsConsumed": round(actual_credits_total, 4) if actual_credits_seen else None,
            "creditCostEstimateMismatch": credit_cost_estimate_mismatch,
            "quotaRemaining": last_quota_remaining,
            "quotaUsed": last_quota_used,
        },
    }


def _coverage_for_market_family(family: str) -> dict[str, Optional[float]]:
    con = shadow_markets._connect()
    rows = con.execute(
        """
        SELECT event_id, state_label
        FROM prospective_market_snapshots
        WHERE phase = 'PREGAME'
          AND market_family = ?
        """,
        [family],
    ).fetchall()
    con.close()

    events = {str(r["event_id"] or "") for r in rows if str(r["event_id"] or "")}
    if not events:
        return {
            "openingCoverage": 0.0,
            "currentCoverage": 0.0,
            "closingCoverage": 0.0,
        }

    def _coverage(state: str) -> float:
        covered = {str(r["event_id"] or "") for r in rows if str(r["state_label"] or "") == state and str(r["event_id"] or "")}
        return float(len(covered) / len(events))

    return {
        "openingCoverage": _coverage("OPENING"),
        "currentCoverage": _coverage("CURRENT"),
        "closingCoverage": _coverage("CLOSING"),
    }


def pregame_collection_status_report(*, week: Optional[int] = None) -> dict[str, Any]:
    _ensure_manager_schema()
    resolved_week, games = _load_week_events(week=week)
    props = shadow_markets.player_prop_coverage_report()
    api_today = _api_usage_today()

    spread = _coverage_for_market_family("SPREAD")
    moneyline = _coverage_for_market_family("MONEYLINE")
    total = _coverage_for_market_family("TOTAL")

    return {
        "manager": "SIA_PREGAME_DATA_COLLECTION_MANAGER_V1",
        "week": resolved_week,
        "playerPropCollectionEnabled": _env_bool("PLAYER_PROP_COLLECTION_ENABLED", False),
        "eventsTracked": len([g for g in games if str(g.get("eventId") or "")]),
        "markets": {
            "spread": spread,
            "moneyline": moneyline,
            "total": total,
            "playerProps": {
                "eventsCaptured": props.get("eventsCaptured"),
                "uniquePlayers": props.get("uniquePlayersCaptured"),
                "propMarkets": props.get("propMarketsCaptured"),
                "quotes": props.get("quotesCaptured"),
                "openingCoverage": props.get("openingCoverage"),
                "gameDayCoverage": props.get("currentCoverage"),
                "closingCoverage": props.get("closingCoverage"),
            },
        },
        "api": {
            "requestsToday": api_today.get("requestsToday"),
            "estimatedCreditsToday": api_today.get("estimatedCreditsToday"),
            "actualCreditsToday": api_today.get("actualCreditsToday"),
            "quotaRemaining": api_today.get("quotaRemaining"),
            "quotaUsed": api_today.get("quotaUsed"),
            "duplicateRequestsPrevented": api_today.get("duplicateRequestsPrevented"),
            "requestsSkippedByQuotaGuard": api_today.get("requestsSkippedByQuotaGuard"),
        },
    }


def _grading_workflow_status(*, now_utc: datetime) -> dict[str, int]:
    con = shadow_markets._connect()
    rows = con.execute(
        """
        SELECT i.event_id, i.commence_time, o.candidate_id AS outcome_candidate_id
        FROM shadow_publication_items i
        LEFT JOIN shadow_outcomes o ON o.candidate_id = i.candidate_id
        """
    ).fetchall()
    con.close()

    by_event: dict[str, list[bool]] = {}
    for row in rows:
        event_id = str(row["event_id"] or "")
        if not event_id:
            continue
        kickoff = _parse_commence(row["commence_time"])
        if kickoff is None or kickoff > now_utc:
            continue
        by_event.setdefault(event_id, []).append(row["outcome_candidate_id"] is not None)

    games_graded = 0
    games_awaiting = 0
    for settled_flags in by_event.values():
        if settled_flags and all(settled_flags):
            games_graded += 1
        elif settled_flags:
            games_awaiting += 1

    return {
        "gamesAwaitingGrading": games_awaiting,
        "gamesGraded": games_graded,
    }


def _regular_season_player_prop_credit_projection() -> dict[str, Any]:
    base = games_service.list_games()
    available = sorted({int(w) for w in (base.get("availableWeeks") or []) if w is not None})
    regular_season_weeks = list(range(1, 19))
    available_regular = [w for w in available if w in regular_season_weeks]
    missing_regular = [w for w in regular_season_weeks if w not in set(available_regular)]

    eligible_games = 0
    for week in available_regular:
        payload = games_service.list_games(week=week)
        eligible_games += len([g for g in (payload.get("games") or []) if str(g.get("eventId") or "")])

    available_playoff = [w for w in available if w > 18]
    playoff_games = 0
    for week in available_playoff:
        payload = games_service.list_games(week=week)
        playoff_games += len([g for g in (payload.get("games") or []) if str(g.get("eventId") or "")])

    return {
        "regularSeason": {
            "status": "FULL" if not missing_regular else "PARTIAL",
            "weeksAvailable": available_regular,
            "weeksMissing": missing_regular,
            "eligibleGames": eligible_games,
            "projectedCredits": float(eligible_games * VERIFIED_PLAYER_PROP_CREDITS_PER_REQUEST),
        },
        "playoffs": {
            "weeksAvailable": available_playoff,
            "eligibleGames": playoff_games,
            "projectedCredits": float(playoff_games * VERIFIED_PLAYER_PROP_CREDITS_PER_REQUEST),
        },
    }


def build_pregame_collection_schedule_v1(
    *,
    week: Optional[int] = None,
    now_utc: Optional[datetime] = None,
    prop_allowlist: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Deterministic pregame scheduling policy report with zero provider calls."""
    _ensure_manager_schema()
    config = _resolve_config(dry_run=True, prop_allowlist=prop_allowlist)
    now = now_utc or _utc_now()
    resolved_week, games = _load_week_events(week=week)
    line_board_markets = _load_line_board_market_presence()
    market_state_index = _load_market_state_index()
    player_prop_state_index = _load_player_prop_state_index()

    window_breakdown = {
        LIFECYCLE_OPENING: 0,
        LIFECYCLE_GAME_DAY: 0,
        LIFECYCLE_CLOSING: 0,
        LIFECYCLE_CLOSED: 0,
    }
    events_out: list[dict[str, Any]] = []

    standard_captured = 0
    standard_due = 0
    standard_missed = 0
    standard_future = 0
    opening_captured = 0
    opening_due = 0
    opening_future = 0
    game_day_captured = 0
    game_day_due = 0
    game_day_future = 0
    closing_captured = 0
    closing_due = 0
    closing_future = 0
    player_prop_captured = 0
    player_prop_due = 0
    player_prop_missed = 0
    player_prop_future = 0

    standard_due_by_state = {
        LIFECYCLE_OPENING: 0,
        LIFECYCLE_GAME_DAY: 0,
        LIFECYCLE_CLOSING: 0,
    }
    standard_provider_requests_by_state = {
        LIFECYCLE_OPENING: 0,
        LIFECYCLE_GAME_DAY: 0,
        LIFECYCLE_CLOSING: 0,
    }

    player_prop_due_by_state = {
        LIFECYCLE_GAME_DAY: 0,
    }

    market_family_coverage = {
        "SPREAD": 0,
        "MONEYLINE": 0,
        "TOTAL": 0,
    }

    for game in games:
        event_id = str(game.get("eventId") or "")
        if not event_id:
            continue

        window = _lifecycle_window_for_event(game.get("commenceTime"), config=config, now=now)
        window_breakdown[window] = int(window_breakdown.get(window, 0)) + 1
        supported_families = line_board_markets.get(event_id, set())

        market_blocks: dict[str, dict[str, str]] = {}
        market_state_details: dict[str, dict[str, dict[str, Any]]] = {}
        for family in TRACKED_MARKET_FAMILIES:
            statuses: dict[str, str] = {}
            has_captured = False
            per_state_details: dict[str, dict[str, Any]] = {}

            tracked = family in supported_families
            for lifecycle_state in STANDARD_LIFECYCLE_STATES:
                storage_state = LIFECYCLE_TO_STORAGE_STATE[lifecycle_state]
                snapshot_meta = market_state_index.get((event_id, family, storage_state), {})
                captured = bool(snapshot_meta) or _state_exists_for_market(event_id, family, storage_state)
                has_captured = has_captured or captured
                statuses[lifecycle_state] = _lifecycle_status(window=window, lifecycle_state=lifecycle_state, captured=captured)
                per_state_details[lifecycle_state] = {
                    "state": lifecycle_state,
                    "storageState": storage_state,
                    "status": statuses[lifecycle_state],
                    "captured": captured,
                    "capturedAtUTC": snapshot_meta.get("capturedAtUTC"),
                    "bookDepth": snapshot_meta.get("bookDepth"),
                    "providerRequestRequired": "NO",
                }

            tracked = tracked or has_captured
            if not tracked:
                statuses = {state: "NOT_TRACKED" for state in STANDARD_LIFECYCLE_STATES}
                for lifecycle_state in STANDARD_LIFECYCLE_STATES:
                    per_state_details[lifecycle_state].update(
                        {
                            "status": "NOT_TRACKED",
                            "captured": False,
                            "capturedAtUTC": None,
                            "bookDepth": None,
                        }
                    )
            else:
                market_family_coverage[family] = int(market_family_coverage.get(family, 0)) + 1

            for lifecycle_state, status in statuses.items():
                if status == "CAPTURED":
                    standard_captured += 1
                    if lifecycle_state == LIFECYCLE_OPENING:
                        opening_captured += 1
                    elif lifecycle_state == LIFECYCLE_GAME_DAY:
                        game_day_captured += 1
                    elif lifecycle_state == LIFECYCLE_CLOSING:
                        closing_captured += 1
                elif status == "DUE":
                    standard_due += 1
                    standard_due_by_state[lifecycle_state] = int(standard_due_by_state.get(lifecycle_state, 0)) + 1
                    standard_provider_requests_by_state[lifecycle_state] = int(standard_provider_requests_by_state.get(lifecycle_state, 0))
                    if lifecycle_state == LIFECYCLE_OPENING:
                        opening_due += 1
                    elif lifecycle_state == LIFECYCLE_GAME_DAY:
                        game_day_due += 1
                    elif lifecycle_state == LIFECYCLE_CLOSING:
                        closing_due += 1
                elif status == "MISSED":
                    standard_missed += 1
                elif status == "FUTURE":
                    standard_future += 1
                    if lifecycle_state == LIFECYCLE_OPENING:
                        opening_future += 1
                    elif lifecycle_state == LIFECYCLE_GAME_DAY:
                        game_day_future += 1
                    elif lifecycle_state == LIFECYCLE_CLOSING:
                        closing_future += 1

            market_blocks[family] = statuses
            market_state_details[family] = per_state_details

        prop_storage_state = LIFECYCLE_TO_STORAGE_STATE[LIFECYCLE_GAME_DAY]
        prop_meta = player_prop_state_index.get((event_id, prop_storage_state), {})
        prop_captured = bool(prop_meta) or _state_exists_for_player_prop_event(event_id, prop_storage_state)
        prop_has_any = any(idx_event_id == event_id for idx_event_id, _ in player_prop_state_index.keys()) or _has_any_player_prop_state(event_id)
        prop_status = _player_prop_lifecycle_status(window=window, captured=prop_captured)
        prop_tracked = prop_has_any or bool(config.prop_allowlist)
        if not prop_tracked:
            prop_status = "NOT_TRACKED"

        if prop_status == "CAPTURED":
            player_prop_captured += 1
        elif prop_status == "DUE":
            player_prop_due += 1
            player_prop_due_by_state[LIFECYCLE_GAME_DAY] = int(player_prop_due_by_state.get(LIFECYCLE_GAME_DAY, 0)) + 1
        elif prop_status == "MISSED":
            player_prop_missed += 1
        elif prop_status == "FUTURE":
            player_prop_future += 1

        next_state = _next_collection_state_from_statuses(
            window=window,
            standard_statuses=market_blocks,
            player_prop_status=prop_status,
        )

        player_prop_request_cost = verified_cost = _estimate_credits_for_request_shape(
            endpoint_type=PLAYER_PROP_ENDPOINT_TYPE,
            region=PLAYER_PROP_REGION,
            markets=list(config.prop_allowlist),
        ).get("creditsPerRequest")

        events_out.append(
            {
                "eventId": event_id,
                "awayTeam": str(game.get("awayAbbreviation") or game.get("awayTeam") or ""),
                "homeTeam": str(game.get("homeAbbreviation") or game.get("homeTeam") or ""),
                "matchup": f"{str(game.get('awayAbbreviation') or game.get('awayTeam') or '')} @ {str(game.get('homeAbbreviation') or game.get('homeTeam') or '')}",
                "kickoff": str(game.get("commenceTime") or ""),
                "currentLifecycleWindow": window,
                "nextCollectionState": next_state,
                "nextCollectionWindow": next_state,
                "standardOpeningStatus": {
                    "SPREAD": market_blocks["SPREAD"][LIFECYCLE_OPENING],
                    "MONEYLINE": market_blocks["MONEYLINE"][LIFECYCLE_OPENING],
                    "TOTAL": market_blocks["TOTAL"][LIFECYCLE_OPENING],
                },
                "standardGameDayStatus": {
                    "SPREAD": market_blocks["SPREAD"][LIFECYCLE_GAME_DAY],
                    "MONEYLINE": market_blocks["MONEYLINE"][LIFECYCLE_GAME_DAY],
                    "TOTAL": market_blocks["TOTAL"][LIFECYCLE_GAME_DAY],
                },
                "standardClosingStatus": {
                    "SPREAD": market_blocks["SPREAD"][LIFECYCLE_CLOSING],
                    "MONEYLINE": market_blocks["MONEYLINE"][LIFECYCLE_CLOSING],
                    "TOTAL": market_blocks["TOTAL"][LIFECYCLE_CLOSING],
                },
                "playerPropGameDayStatus": prop_status,
                "playerPropRequestCostCredits": player_prop_request_cost,
                "postKickoffCollectionAllowed": "NO",
                "spread": market_blocks["SPREAD"],
                "moneyline": market_blocks["MONEYLINE"],
                "total": market_blocks["TOTAL"],
                "playerProps": {LIFECYCLE_GAME_DAY: prop_status},
                "stateTelemetry": {
                    "SPREAD": market_state_details["SPREAD"],
                    "MONEYLINE": market_state_details["MONEYLINE"],
                    "TOTAL": market_state_details["TOTAL"],
                    "PLAYER_PROPS": {
                        LIFECYCLE_GAME_DAY: {
                            "state": LIFECYCLE_GAME_DAY,
                            "storageState": prop_storage_state,
                            "status": prop_status,
                            "captured": prop_captured,
                            "capturedAtUTC": prop_meta.get("capturedAtUTC"),
                            "bookDepth": prop_meta.get("bookDepth"),
                            "providerRequestRequired": "YES" if prop_status == "DUE" and bool(config.player_prop_collection_enabled) else "NO",
                        }
                    },
                },
            }
        )

    estimate_contract = _estimate_credits_for_request_shape(
        endpoint_type=PLAYER_PROP_ENDPOINT_TYPE,
        region=PLAYER_PROP_REGION,
        markets=list(config.prop_allowlist),
    )
    verified_status = str(estimate_contract.get("status") or "UNKNOWN")
    verified_per_request = _to_float(estimate_contract.get("creditsPerRequest"))
    verified_credits_due = float(player_prop_due * verified_per_request) if verified_per_request is not None else None
    if not bool(config.player_prop_collection_enabled):
        verified_status = "DISABLED"
        verified_per_request = None
        verified_credits_due = 0.0

    grading = _grading_workflow_status(now_utc=now)
    season_projection = _regular_season_player_prop_credit_projection()

    next_collection_window = None
    for lifecycle_state in STANDARD_LIFECYCLE_STATES:
        if int(standard_due_by_state.get(lifecycle_state, 0)) > 0:
            next_collection_window = lifecycle_state
            break
    if next_collection_window is None and int(player_prop_due_by_state.get(LIFECYCLE_GAME_DAY, 0)) > 0:
        next_collection_window = LIFECYCLE_GAME_DAY

    covered_standard_families = [family for family in TRACKED_MARKET_FAMILIES if int(market_family_coverage.get(family, 0)) > 0]
    uncovered_standard_families = [family for family in TRACKED_MARKET_FAMILIES if family not in set(covered_standard_families)]

    return {
        "manager": "SIA_PREGAME_COLLECTION_SCHEDULE_V1",
        "generatedAtUTC": now.replace(microsecond=0).isoformat(),
        "week": resolved_week,
        "playerPropCollectionEnabled": bool(config.player_prop_collection_enabled),
        "eventsTracked": len(events_out),
        "policy": {
            "windows": {
                "openingHoursGreaterThan": config.opening_window_hours,
                "gameDayHoursAtMost": config.opening_window_hours,
                "gameDayHoursGreaterThan": config.closing_window_hours,
                "closingHoursAtMost": config.closing_window_hours,
            },
            "standardMarketLifecycle": list(STANDARD_LIFECYCLE_STATES),
            "playerPropLifecycle": list(PLAYER_PROP_LIFECYCLE_STATES),
            "storageStateLabels": LIFECYCLE_TO_STORAGE_STATE,
            "lifecycleNormalization": {
                "operatorFacing": {"OPENING": "OPENING", "GAME_DAY": "GAME_DAY", "CLOSING": "CLOSING"},
                "storage": {"OPENING": "OPENING", "GAME_DAY": "CURRENT", "CLOSING": "CLOSING"},
            },
            "postgameState": "POSTGAME_WORKFLOW_ONLY",
            "continuousPolling": "NO",
            "postKickoffSportsbookCollection": "NO",
            "canonicalScheduleSource": "backend/app/services/pregame_collection_manager.py:build_pregame_collection_schedule_v1",
            "canonicalScheduledMarkets": {
                "standard": list(TRACKED_MARKET_FAMILIES),
                "playerProps": list(PLAYER_PROP_LIFECYCLE_STATES),
                "researchOnlyNotScheduled": list(RESEARCH_ONLY_MARKET_FAMILIES),
            },
        },
        "events": events_out,
        "totals": {
            "events": len(events_out),
            "windowBreakdown": window_breakdown,
            "standardFamilyCoverage": {
                "coveredFamilies": covered_standard_families,
                "uncoveredFamilies": uncovered_standard_families,
                "eventsByFamily": market_family_coverage,
            },
            "standardSnapshotsCaptured": standard_captured,
            "standardSnapshotsDue": standard_due,
            "standardSnapshotsMissed": standard_missed,
            "standardSnapshotsFuture": standard_future,
            "playerPropSnapshotsCaptured": player_prop_captured,
            "playerPropSnapshotsDue": player_prop_due,
            "playerPropSnapshotsMissed": player_prop_missed,
            "playerPropSnapshotsFuture": player_prop_future,
            "openingCaptured": opening_captured,
            "openingDue": opening_due,
            "openingFuture": opening_future,
            "gameDayCaptured": game_day_captured,
            "gameDayDue": game_day_due,
            "gameDayFuture": game_day_future,
            "closingCaptured": closing_captured,
            "closingDue": closing_due,
            "closingFuture": closing_future,
            "standardDueByState": standard_due_by_state,
            "playerPropDueByState": player_prop_due_by_state,
            "nextCollectionWindow": next_collection_window,
            "plannedStandardProviderRequests": 0,
            "plannedPlayerPropProviderRequests": player_prop_due if bool(config.player_prop_collection_enabled) else 0,
            "standardProviderRequestsRequired": 0,
            "playerPropProviderRequestsRequired": player_prop_due if bool(config.player_prop_collection_enabled) else 0,
            "standardProviderRequestsByState": standard_provider_requests_by_state,
            "standardProviderVerifiedCreditCost": "ZERO",
            "playerPropVerifiedCreditCostStatus": verified_status,
            "verifiedPlayerPropCreditsDue": verified_credits_due,
            "providerRequestsMade": 0,
            "providerCreditsSpent": 0,
            "gamesAwaitingGrading": int(grading.get("gamesAwaitingGrading") or 0),
            "gamesGraded": int(grading.get("gamesGraded") or 0),
            "postgameSportsbookRequests": 0,
        },
        "weeklyCostModel": {
            "playerPropDueGames": player_prop_due,
            "verifiedCreditsPerGameDayCapture": verified_per_request,
            "projectedWeekCredits": verified_credits_due,
        },
        "seasonProjection": season_projection,
        "firewalls": {
            "officialProductionMarket": "SPREAD",
            "moneylineProductionEligible": False,
            "totalProductionEligible": False,
            "playerPropProductionEligible": False,
            "playerPropRecommendations": "DISABLED",
            "teamTotalRecommendations": "DISABLED",
            "firstHalfRecommendations": "DISABLED",
            "crossMarketComparable": False,
            "universalSIA3": "DISABLED",
            "playerPropCollectionEnabled": bool(config.player_prop_collection_enabled),
            "livePolling": "NO",
            "productionSpreadEngineChanged": "NO",
            "qualificationThresholdsChanged": "NO",
        },
    }
