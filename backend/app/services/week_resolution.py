from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd

from app.runtime_paths import runtime_paths


SCHEDULE_CONTEXT = runtime_paths.schedule_context_latest_csv
GAME_PROJECTIONS = runtime_paths.current_game_projections_csv
LINE_MOVEMENT_BOARD = runtime_paths.line_movement_board_csv
RANKED_BET_BOARD = runtime_paths.ranked_bet_board_csv


_TEAM_ALIASES = {
    "ARI": "ARI",
    "ATL": "ATL",
    "BAL": "BAL",
    "BUF": "BUF",
    "CAR": "CAR",
    "CHI": "CHI",
    "CIN": "CIN",
    "CLE": "CLE",
    "DAL": "DAL",
    "DEN": "DEN",
    "DET": "DET",
    "GB": "GB",
    "HOU": "HOU",
    "IND": "IND",
    "JAX": "JAX",
    "JAC": "JAX",
    "KC": "KC",
    "LAC": "LAC",
    "LAR": "LAR",
    "LA": "LAR",
    "LV": "LV",
    "OAK": "LV",
    "MIA": "MIA",
    "MIN": "MIN",
    "NE": "NE",
    "NO": "NO",
    "NYG": "NYG",
    "NYJ": "NYJ",
    "PHI": "PHI",
    "PIT": "PIT",
    "SEA": "SEA",
    "SF": "SF",
    "TB": "TB",
    "TEN": "TEN",
    "WAS": "WAS",
    "WSH": "WAS",
}

_PROVIDER_TEAM_NAMES = {
    "Arizona Cardinals": "ARI",
    "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR",
    "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN",
    "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN",
    "Detroit Lions": "DET",
    "Green Bay Packers": "GB",
    "Houston Texans": "HOU",
    "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC",
    "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR",
    "Las Vegas Raiders": "LV",
    "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN",
    "New England Patriots": "NE",
    "New Orleans Saints": "NO",
    "New York Giants": "NYG",
    "New York Jets": "NYJ",
    "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT",
    "Seattle Seahawks": "SEA",
    "San Francisco 49ers": "SF",
    "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN",
    "Washington Commanders": "WAS",
}

_FINAL_STATUSES = {
    "final",
    "complete",
    "completed",
    "closed",
    "post",
    "full_time",
    "fulltime",
    "ft",
    "ended",
}

_IN_PROGRESS_STATUSES = {
    "live",
    "in_progress",
    "inprogress",
    "halftime",
    "q1",
    "q2",
    "q3",
    "q4",
    "ot",
    "overtime",
}

_UPCOMING_STATUSES = {
    "scheduled",
    "pre",
    "pregame",
    "not_started",
    "notstarted",
}


@dataclass(frozen=True)
class CanonicalWeekResult:
    season: Optional[int]
    week: Optional[int]
    status: str
    source: str
    reason: str
    next_kickoff_utc: Optional[str]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "week": self.week,
            "status": self.status,
            "source": self.source,
            "reason": self.reason,
            "nextKickoffUtc": self.next_kickoff_utc,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class WeekReadinessResult:
    season: Optional[int]
    week: Optional[int]
    status: str
    schedule_ready: bool
    markets_ready: bool
    projections_ready: bool
    rankings_ready: bool
    warnings: tuple[str, ...]
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "week": self.week,
            "status": self.status,
            "scheduleReady": self.schedule_ready,
            "marketsReady": self.markets_ready,
            "projectionsReady": self.projections_ready,
            "rankingsReady": self.rankings_ready,
            "warnings": list(self.warnings),
            "details": self.details,
        }


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, str(default))).strip())
    except (TypeError, ValueError):
        return default


def _completion_buffer_hours() -> int:
    return max(2, _env_int("NFL_WEEK_COMPLETION_BUFFER_HOURS", 6))


def _stale_hours() -> int:
    return max(1, _env_int("NFL_WEEK_CONTEXT_STALE_HOURS", 72))


def _utc_now(now_utc: Optional[datetime]) -> datetime:
    if now_utc is None:
        return datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        return now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(timezone.utc)


def _parse_iso_utc(value: Any) -> Optional[datetime]:
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


def _normalize_team_code(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw in _PROVIDER_TEAM_NAMES:
        return _PROVIDER_TEAM_NAMES[raw]
    upper = raw.upper()
    if upper in _TEAM_ALIASES:
        return _TEAM_ALIASES[upper]
    return upper


def _parse_status_token(value: Any) -> str:
    token = str(value or "").strip().lower()
    if not token:
        return ""
    token = token.replace("-", "_").replace(" ", "_")
    return token


def _status_from_projection_row(row: dict[str, Any]) -> tuple[Optional[str], bool]:
    for key in ("status", "game_status", "state"):
        token = _parse_status_token(row.get(key))
        if not token:
            continue
        if token in _FINAL_STATUSES:
            return "FINAL", True
        if token in _IN_PROGRESS_STATUSES:
            return "IN_PROGRESS", True
        if token in _UPCOMING_STATUSES:
            return "UPCOMING", True

    for key in ("is_final", "final", "completed"):
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip().lower()
        if text in {"1", "true", "yes"}:
            return "FINAL", True
        if text in {"0", "false", "no"}:
            return "UPCOMING", True

    return None, False


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _load_schedule_rows() -> list[dict[str, Any]]:
    path = SCHEDULE_CONTEXT.resolve()
    if not path.exists():
        return []

    try:
        df = pd.read_csv(path)
    except Exception:
        return []

    required = {"season", "week", "gameday", "away_team", "home_team"}
    if df.empty or not required.issubset(set(df.columns)):
        return []

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        season = _safe_int(row.get("season"))
        week = _safe_int(row.get("week"))
        gameday = str(row.get("gameday") or "").strip()
        away = _normalize_team_code(row.get("away_team"))
        home = _normalize_team_code(row.get("home_team"))
        if season is None or week is None or week < 1:
            continue
        if not gameday or not away or not home:
            continue
        rows.append(
            {
                "season": season,
                "week": week,
                "gameday": gameday,
                "away_team": away,
                "home_team": home,
            }
        )
    return rows


def _load_projection_rows() -> list[dict[str, Any]]:
    path = GAME_PROJECTIONS.resolve()
    if not path.exists():
        return []

    try:
        df = pd.read_csv(path)
    except Exception:
        return []

    if df.empty:
        return []

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        kickoff = _parse_iso_utc(row.get("commence_time"))
        away = _normalize_team_code(row.get("away_team"))
        home = _normalize_team_code(row.get("home_team"))
        event_id = str(row.get("api_event_id") or "").strip()
        if not away or not home:
            continue

        projection_row = row.to_dict()
        status, status_reliable = _status_from_projection_row(projection_row)
        rows.append(
            {
                "event_id": event_id,
                "away_team": away,
                "home_team": home,
                "kickoff": kickoff,
                "status": status,
                "status_reliable": status_reliable,
            }
        )
    return rows


def _matches_schedule_gameday(schedule_gameday: str, kickoff: datetime) -> bool:
    try:
        game_day = datetime.fromisoformat(str(schedule_gameday).strip()).date()
    except ValueError:
        return False
    kickoff_day = kickoff.date()
    return kickoff_day == game_day or kickoff_day == (game_day + timedelta(days=1))


def _projected_game_state(*, now_utc: datetime, kickoff: Optional[datetime], explicit_status: Optional[str], explicit_reliable: bool, completion_buffer_hours: int) -> str:
    if explicit_reliable and explicit_status in {"FINAL", "IN_PROGRESS"}:
        return explicit_status

    if kickoff is None:
        return "UNKNOWN"

    if explicit_reliable and explicit_status == "UPCOMING" and kickoff > now_utc:
        return "UPCOMING"

    completion_cutoff = kickoff + timedelta(hours=completion_buffer_hours)
    if kickoff > now_utc:
        return "UPCOMING"
    if now_utc < completion_cutoff:
        return "IN_PROGRESS"
    return "FINAL"


def _build_schedule_index(rows: list[dict[str, Any]]) -> dict[tuple[int, int], list[dict[str, Any]]]:
    out: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (int(row["season"]), int(row["week"]))
        out.setdefault(key, []).append(row)
    return out


def _match_projection_for_schedule_row(
    schedule_row: dict[str, Any],
    projection_rows: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    away = str(schedule_row.get("away_team") or "")
    home = str(schedule_row.get("home_team") or "")
    gameday = str(schedule_row.get("gameday") or "")

    for prow in projection_rows:
        if str(prow.get("away_team") or "") != away:
            continue
        if str(prow.get("home_team") or "") != home:
            continue
        kickoff = prow.get("kickoff")
        if kickoff is None or not isinstance(kickoff, datetime):
            continue
        if _matches_schedule_gameday(gameday, kickoff):
            return prow

    return None


def resolve_canonical_week_metadata(*, now_utc: Optional[datetime] = None) -> dict[str, Any]:
    now = _utc_now(now_utc)
    completion_buffer_hours = _completion_buffer_hours()
    stale_hours = _stale_hours()

    schedule_rows = _load_schedule_rows()
    if not schedule_rows:
        return CanonicalWeekResult(
            season=None,
            week=None,
            status="NOT_READY",
            source="schedule_context_latest",
            reason="SCHEDULE_CONTEXT_MISSING_OR_INVALID",
            next_kickoff_utc=None,
            warnings=("schedule_context_latest has no usable schedule rows",),
        ).to_dict()

    warnings: list[str] = []
    try:
        age_hours = (now - datetime.fromtimestamp(SCHEDULE_CONTEXT.resolve().stat().st_mtime, tz=timezone.utc)).total_seconds() / 3600.0
        if age_hours > float(stale_hours):
            warnings.append(f"schedule_context_latest appears stale ({age_hours:.1f}h old)")
    except Exception:
        warnings.append("schedule_context_latest staleness could not be verified")

    projection_rows = _load_projection_rows()
    if not projection_rows:
        warnings.append("current_game_projections has no kickoff/status rows")

    by_week = _build_schedule_index(schedule_rows)
    week_entries: list[dict[str, Any]] = []

    for (season, week), rows in by_week.items():
        states = {"upcoming": 0, "in_progress": 0, "final": 0, "unknown": 0}
        next_kickoff: Optional[datetime] = None
        earliest_kickoff: Optional[datetime] = None

        for row in rows:
            matched = _match_projection_for_schedule_row(row, projection_rows)
            kickoff = matched.get("kickoff") if matched else None
            explicit_status = matched.get("status") if matched else None
            explicit_reliable = bool(matched.get("status_reliable")) if matched else False

            state = _projected_game_state(
                now_utc=now,
                kickoff=kickoff,
                explicit_status=explicit_status,
                explicit_reliable=explicit_reliable,
                completion_buffer_hours=completion_buffer_hours,
            )

            if state == "UPCOMING":
                states["upcoming"] += 1
            elif state == "IN_PROGRESS":
                states["in_progress"] += 1
            elif state == "FINAL":
                states["final"] += 1
            else:
                states["unknown"] += 1

            if kickoff is not None:
                if earliest_kickoff is None or kickoff < earliest_kickoff:
                    earliest_kickoff = kickoff
                if kickoff >= now and (next_kickoff is None or kickoff < next_kickoff):
                    next_kickoff = kickoff

        week_entries.append(
            {
                "season": season,
                "week": week,
                "states": states,
                "next_kickoff": next_kickoff,
                "earliest_kickoff": earliest_kickoff,
            }
        )

    week_entries.sort(
        key=lambda item: (
            item["earliest_kickoff"] or datetime.max.replace(tzinfo=timezone.utc),
            int(item["season"]),
            int(item["week"]),
        )
    )

    active = [
        item
        for item in week_entries
        if int(item["states"]["upcoming"]) > 0 or int(item["states"]["in_progress"]) > 0
    ]

    selected: Optional[dict[str, Any]] = active[0] if active else None
    if selected is None:
        future = [item for item in week_entries if item.get("next_kickoff") is not None]
        future.sort(key=lambda item: item["next_kickoff"])
        selected = future[0] if future else None

    if selected is None:
        return CanonicalWeekResult(
            season=None,
            week=None,
            status="NOT_READY",
            source="schedule_context_latest",
            reason="NO_RESOLVABLE_WEEK",
            next_kickoff_utc=None,
            warnings=tuple(warnings or ["no week entries could be resolved"]),
        ).to_dict()

    states = selected["states"]
    if int(states["upcoming"]) > 0 or int(states["in_progress"]) > 0:
        status = "ACTIVE"
        reason = "WEEK_HAS_UPCOMING_OR_IN_PROGRESS_GAMES"
    elif selected.get("next_kickoff") is not None:
        status = "UPCOMING"
        reason = "NEXT_UPCOMING_KICKOFF_WEEK"
    else:
        status = "DEGRADED"
        reason = "NO_UPCOMING_KICKOFF_FOUND"

    if warnings and status == "ACTIVE":
        status = "DEGRADED"

    next_kickoff = selected.get("next_kickoff")
    return CanonicalWeekResult(
        season=int(selected["season"]),
        week=int(selected["week"]),
        status=status,
        source="schedule_context_plus_local_kickoffs",
        reason=reason,
        next_kickoff_utc=None if next_kickoff is None else next_kickoff.replace(microsecond=0).isoformat(),
        warnings=tuple(warnings),
    ).to_dict()


def _canonical_schedule_keys(canonical: dict[str, Any], schedule_rows: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    season = _safe_int(canonical.get("season"))
    week = _safe_int(canonical.get("week"))
    if season is None or week is None:
        return set()
    out: set[tuple[str, str, str]] = set()
    for row in schedule_rows:
        if int(row.get("season") or -1) != season or int(row.get("week") or -1) != week:
            continue
        out.add((str(row.get("gameday") or ""), str(row.get("away_team") or ""), str(row.get("home_team") or "")))
    return {key for key in out if key[0] and key[1] and key[2]}


def _find_missing_matchups(
    schedule_rows: list[dict[str, Any]],
    projection_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    matched: set[tuple[str, str, str]] = set()
    for schedule_row in schedule_rows:
        gameday = str(schedule_row.get("gameday") or "")
        away = _normalize_team_code(schedule_row.get("away_team"))
        home = _normalize_team_code(schedule_row.get("home_team"))
        if not gameday or not away or not home:
            continue
        for projection_row in projection_rows:
            proj_away = _normalize_team_code(projection_row.get("away_team"))
            proj_home = _normalize_team_code(projection_row.get("home_team"))
            if proj_away != away or proj_home != home:
                continue
            kickoff = projection_row.get("kickoff")
            if kickoff is None or not isinstance(kickoff, datetime):
                continue
            if _matches_schedule_gameday(gameday, kickoff):
                matched.add((gameday, away, home))

    missing: list[dict[str, Any]] = []
    for schedule_row in schedule_rows:
        gameday = str(schedule_row.get("gameday") or "")
        away = _normalize_team_code(schedule_row.get("away_team"))
        home = _normalize_team_code(schedule_row.get("home_team"))
        if not gameday or not away or not home:
            continue
        if (gameday, away, home) in matched:
            continue

        raw_away = str(schedule_row.get("away_team") or "").strip()
        raw_home = str(schedule_row.get("home_team") or "").strip()
        if raw_away.upper() in {"LA", "LAR"} or raw_home.upper() in {"LA", "LAR"}:
            reason = "TEAM_ALIAS_NORMALIZATION_REQUIRED"
        elif not away or not home:
            reason = "UNKNOWN_TEAM_CODE"
        elif not any(
            _normalize_team_code(row.get("away_team")) == away and _normalize_team_code(row.get("home_team")) == home
            for row in projection_rows
        ):
            reason = "NO_PROJECTION_FOR_MATCHUP"
        else:
            reason = "NO_COVERING_KICKOFF_MATCH"

        missing.append(
            {
                "gameday": gameday,
                "away_team": away,
                "home_team": home,
                "reason": reason,
            }
        )

    return missing


def _coverage_from_rows(
    *,
    path_ref: Any,
    schedule_keys: set[tuple[str, str, str]],
    away_col: str,
    home_col: str,
    kickoff_col: str,
) -> dict[str, Any]:
    path = path_ref.resolve()
    if not path.exists():
        return {"matched": 0, "expected": len(schedule_keys), "ratio": 0.0, "rows": 0, "exists": False}

    try:
        df = pd.read_csv(path)
    except Exception:
        return {"matched": 0, "expected": len(schedule_keys), "ratio": 0.0, "rows": 0, "exists": True, "error": "read_failed"}

    if df.empty:
        return {"matched": 0, "expected": len(schedule_keys), "ratio": 0.0, "rows": 0, "exists": True}

    required = {away_col, home_col, kickoff_col}
    if not required.issubset(set(df.columns)):
        return {
            "matched": 0,
            "expected": len(schedule_keys),
            "ratio": 0.0,
            "rows": int(len(df)),
            "exists": True,
            "error": "missing_required_columns",
        }

    schedule_by_matchup: dict[tuple[str, str], set[str]] = {}
    for gameday, away, home in schedule_keys:
        schedule_by_matchup.setdefault((away, home), set()).add(gameday)

    matched_keys: set[tuple[str, str, str]] = set()
    for _, row in df.iterrows():
        away = _normalize_team_code(row.get(away_col))
        home = _normalize_team_code(row.get(home_col))
        kickoff = _parse_iso_utc(row.get(kickoff_col))
        if not away or not home or kickoff is None:
            continue

        schedule_days = schedule_by_matchup.get((away, home), set())
        for gameday in schedule_days:
            if _matches_schedule_gameday(gameday, kickoff):
                matched_keys.add((gameday, away, home))

    expected = len(schedule_keys)
    matched = len(matched_keys)
    ratio = (float(matched) / float(expected)) if expected > 0 else 0.0
    return {
        "matched": matched,
        "expected": expected,
        "ratio": round(ratio, 4),
        "rows": int(len(df)),
        "exists": True,
    }


def build_week_readiness(*, canonical: Optional[dict[str, Any]] = None, now_utc: Optional[datetime] = None) -> dict[str, Any]:
    _ = _utc_now(now_utc)
    canonical_meta = canonical or resolve_canonical_week_metadata(now_utc=now_utc)
    schedule_rows = _load_schedule_rows()
    schedule_keys = _canonical_schedule_keys(canonical_meta, schedule_rows)

    schedule_ready = len(schedule_keys) > 0
    projection_cov = _coverage_from_rows(
        path_ref=GAME_PROJECTIONS,
        schedule_keys=schedule_keys,
        away_col="away_team",
        home_col="home_team",
        kickoff_col="commence_time",
    )
    market_cov = _coverage_from_rows(
        path_ref=LINE_MOVEMENT_BOARD,
        schedule_keys=schedule_keys,
        away_col="away_team",
        home_col="home_team",
        kickoff_col="commence_time",
    )
    ranking_cov = _coverage_from_rows(
        path_ref=RANKED_BET_BOARD,
        schedule_keys=schedule_keys,
        away_col="away_team",
        home_col="home_team",
        kickoff_col="commence_time",
    )

    missing_matchups = _find_missing_matchups(schedule_rows, _load_projection_rows())
    missing_reason_counts: dict[str, int] = {}
    for item in missing_matchups:
        missing_reason_counts[item["reason"]] = missing_reason_counts.get(item["reason"], 0) + 1

    projections_ready = schedule_ready and projection_cov.get("matched", 0) == projection_cov.get("expected", 0) and projection_cov.get("expected", 0) > 0
    markets_ready = schedule_ready and market_cov.get("matched", 0) == market_cov.get("expected", 0) and market_cov.get("expected", 0) > 0
    rankings_ready = schedule_ready and ranking_cov.get("matched", 0) > 0

    warnings: list[str] = []
    if not schedule_ready:
        warnings.append("canonical week has no schedule rows")
    if schedule_ready and not projections_ready:
        warnings.append("current_game_projections does not fully cover canonical week schedule")
    if schedule_ready and not markets_ready:
        warnings.append("line_movement_board does not fully cover canonical week schedule")
    if schedule_ready and not rankings_ready:
        warnings.append("ranked_bet_board has no canonical week coverage")

    if not schedule_ready or not projections_ready:
        status = "NOT_READY"
    elif not markets_ready or not rankings_ready:
        status = "DEGRADED"
    else:
        status = "READY"

    return WeekReadinessResult(
        season=_safe_int(canonical_meta.get("season")),
        week=_safe_int(canonical_meta.get("week")),
        status=status,
        schedule_ready=schedule_ready,
        markets_ready=markets_ready,
        projections_ready=projections_ready,
        rankings_ready=rankings_ready,
        warnings=tuple(warnings),
        details={
            "scheduleEvents": len(schedule_keys),
            "projectionCoverage": projection_cov,
            "marketCoverage": market_cov,
            "rankingCoverage": ranking_cov,
            "missingMatchups": missing_matchups,
            "missingReasonCounts": missing_reason_counts,
            "canonicalWeek": canonical_meta,
        },
    ).to_dict()
