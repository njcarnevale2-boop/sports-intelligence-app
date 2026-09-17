from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .contracts import FinalGameResult, PowerSnapshot, PowerTeamRating


CANONICAL_NFL_TEAMS: tuple[str, ...] = (
    "ARI",
    "ATL",
    "BAL",
    "BUF",
    "CAR",
    "CHI",
    "CIN",
    "CLE",
    "DAL",
    "DEN",
    "DET",
    "GB",
    "HOU",
    "IND",
    "JAX",
    "KC",
    "LAC",
    "LAR",
    "LV",
    "MIA",
    "MIN",
    "NE",
    "NO",
    "NYG",
    "NYJ",
    "PHI",
    "PIT",
    "SEA",
    "SF",
    "TB",
    "TEN",
    "WAS",
)

_TEAM_SET = set(CANONICAL_NFL_TEAMS)
_ORDER = {team: i for i, team in enumerate(CANONICAL_NFL_TEAMS)}


def canonical_team_sort_key(team_id: str) -> int:
    if not isinstance(team_id, str) or not team_id.strip():
        raise ValueError("team_id must be a non-empty string")
    if team_id not in _ORDER:
        raise ValueError(f"Unknown team id: {team_id}")
    return _ORDER[team_id]


def _validate_team_id(team_id: str) -> None:
    if not isinstance(team_id, str) or not team_id.strip():
        raise ValueError("team_id must be a non-empty string")
    if team_id not in _TEAM_SET:
        raise ValueError(f"Unknown team id: {team_id}")


def _validate_finite(value: float, field_name: str) -> None:
    if not isinstance(value, (float, int)):
        raise ValueError(f"Non-numeric {field_name}")
    if not math.isfinite(float(value)):
        raise ValueError(f"Non-finite {field_name}")


def _validate_score(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def _validate_int(value: Any, field_name: str, *, positive: bool = False, non_negative: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if positive and value <= 0:
        raise ValueError(f"{field_name} must be positive")
    if non_negative and value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def _validate_required_string(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def parse_kickoff_utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("kickoff_utc must be a non-empty string")

    text = value.strip()
    if not text:
        raise ValueError("kickoff_utc is required")
    text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Invalid kickoff_utc: {value}") from exc


def canonicalize_teams(teams: tuple[PowerTeamRating, ...]) -> tuple[PowerTeamRating, ...]:
    return tuple(sorted(teams, key=lambda t: canonical_team_sort_key(t.team_id)))


def validate_snapshot(snapshot: PowerSnapshot) -> None:
    _validate_int(getattr(snapshot, "season", None), "season", positive=True)
    _validate_int(getattr(snapshot, "through_week", None), "through_week", non_negative=True)

    teams = getattr(snapshot, "teams", None)
    if teams is None:
        raise ValueError("Snapshot teams must be provided")
    if not isinstance(teams, (tuple, list)):
        raise ValueError("Snapshot teams must be a list or tuple of PowerTeamRating")

    if len(teams) != 32:
        raise ValueError("Snapshot must contain exactly 32 teams")

    seen: set[str] = set()
    for index, team in enumerate(teams):
        if not isinstance(team, PowerTeamRating):
            raise ValueError(f"Invalid team entry at index {index}: expected PowerTeamRating")

        _validate_team_id(team.team_id)
        if team.team_id in seen:
            raise ValueError(f"Duplicate team in snapshot: {team.team_id}")
        seen.add(team.team_id)
        _validate_finite(team.power, f"power[{team.team_id}]")

    if seen != _TEAM_SET:
        missing = sorted(_TEAM_SET - seen)
        extra = sorted(seen - _TEAM_SET)
        raise ValueError(f"Snapshot team set mismatch: missing={missing} extra={extra}")


def validate_final_result(result: FinalGameResult) -> None:
    _validate_int(getattr(result, "season", None), "season", positive=True)
    _validate_int(getattr(result, "week", None), "week", positive=True)
    _validate_required_string(getattr(result, "game_id", None), "game_id")
    parse_kickoff_utc(getattr(result, "kickoff_utc", None))

    home_team = getattr(result, "home_team", None)
    away_team = getattr(result, "away_team", None)

    _validate_team_id(home_team)
    _validate_team_id(away_team)
    if home_team == away_team:
        raise ValueError(f"home_team and away_team cannot match for game {result.game_id}")

    _validate_required_string(getattr(result, "source_result_version", None), "source_result_version")
    _validate_score(getattr(result, "home_score", None), "home_score")
    _validate_score(getattr(result, "away_score", None), "away_score")
