from __future__ import annotations

from typing import Any


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

_TEAM_ALIASES = {
    "JAC": "JAX",
    "LA": "LAR",
    "WSH": "WAS",
    "OAK": "LV",
}


def normalize_team_id(value: Any) -> str:
    token = str(value or "").strip().upper()
    if not token:
        raise ValueError("team_id must be a non-empty string")
    token = _TEAM_ALIASES.get(token, token)
    if token not in _TEAM_SET:
        raise ValueError(f"Unknown team id: {value}")
    return token
