"""
ESPN public injury provider — no API key required.

Fetches the current NFL injury report from the ESPN public API and
normalises each player record into the internal injury schema consumed
by InjuryAnalyzer.

Internal schema per record:
  player       – display name
  team         – NFL abbreviation (e.g. "BUF")
  position     – position abbreviation (e.g. "QB")
  positionGroup – offense / defense / special_teams
  status       – Questionable / Doubtful / Out / IR / Active
  practiceStatus – Limited / Full / DNP / Unknown
  starter      – bool (True if listed as a starter-level impact player)
  impact       – float 0-1 (derived from status + position)
  notes        – free-text injury detail
  lastUpdated  – ISO timestamp from the feed or fetch time
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from app.providers.base_provider import BaseProvider

log = logging.getLogger("espn_injury_provider")

_ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
_TIMEOUT_SECONDS = 30

# Map ESPN status strings → normalised status
_STATUS_MAP: Dict[str, str] = {
    "questionable": "Questionable",
    "doubtful": "Doubtful",
    "out": "Out",
    "ir": "IR",
    "day-to-day": "Questionable",
    "probable": "Probable",
    "active": "Active",
    "did not participate": "Out",
    "did not practice": "DNP",
    "limited participation": "Limited",
    "full participation": "Full",
}

# Position group mapping
_OFFENSE = {"QB", "RB", "FB", "WR", "TE", "T", "G", "C", "OL", "OT", "OG"}
_DEFENSE = {"DE", "DT", "NT", "LB", "OLB", "ILB", "MLB", "CB", "S", "FS", "SS", "DB", "DL", "LB"}
_SPECIAL = {"K", "P", "LS", "KR", "PR"}

# High-impact positions for starter heuristic
_HIGH_IMPACT_POSITIONS = {"QB", "RB", "WR", "TE", "T", "G", "DE", "DT", "LB", "CB", "S"}

# NFL abbreviation normalisation (ESPN uses different codes sometimes)
_ESPN_ABBR_MAP = {
    "WSH": "WAS",
    "JAC": "JAX",
    "LAR": "LAR",
    "LA":  "LAR",
}


def _position_group(pos: str) -> str:
    pos = pos.upper().strip()
    if pos in _OFFENSE:
        return "offense"
    if pos in _DEFENSE:
        return "defense"
    if pos in _SPECIAL:
        return "special_teams"
    return "offense"  # default for unknown


def _status_impact(status: str) -> float:
    s = status.lower()
    if s in ("out", "ir"):
        return 0.9
    if s == "doubtful":
        return 0.7
    if s == "questionable":
        return 0.5
    if s in ("dnp", "did not practice"):
        return 0.6
    if s == "limited":
        return 0.3
    return 0.1


class ESPNInjuryProvider(BaseProvider):
    provider_name = "ESPN (Public)"

    def fetch_data(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._fetch_injuries()

    def get_metadata(self) -> Dict[str, Any]:
        meta = super().get_metadata()
        meta.update({
            "provider": self.provider_name,
            "isLive": True,
            "status": "Live",
            "requiresCredentials": False,
        })
        return meta

    # ── public ──────────────────────────────────────────────────────────────

    def fetch_injuries(self) -> Dict[str, Any]:
        return self._fetch_injuries()

    # ── private ──────────────────────────────────────────────────────────────

    def _fetch_injuries(self) -> Dict[str, Any]:
        fetch_time = datetime.now(timezone.utc).isoformat()
        try:
            resp = requests.get(_ESPN_URL, timeout=_TIMEOUT_SECONDS,
                                headers={"Accept": "application/json"})
            resp.raise_for_status()
            raw = resp.json()
        except requests.RequestException as exc:
            log.warning("ESPN injury fetch failed: %s", exc)
            return {
                "injuries": [],
                "provider": self.provider_name,
                "isLive": False,
                "dataStatus": "UNAVAILABLE",
                "lastUpdated": fetch_time,
                "error": str(exc)[:300],
            }

        injuries = self._normalise(raw, fetch_time)
        log.info("ESPN injury fetch: %d records", len(injuries))
        return {
            "injuries": injuries,
            "provider": self.provider_name,
            "isLive": True,
            "dataStatus": "LIVE",   # successful HTTP response; empty == no current injuries
            "lastUpdated": fetch_time,
            "rawCount": len(injuries),
        }

    def _normalise(self, raw: Any, fetch_time: str) -> List[Dict[str, Any]]:
        """Parse the ESPN response and return normalised injury records."""
        records: List[Dict[str, Any]] = []

        injury_list = []
        if isinstance(raw, dict):
            # Typical shape: {"injuries": [...]}
            injury_list = raw.get("injuries", []) or []
            # Also handle nested {"items": [...]}
            if not injury_list:
                injury_list = raw.get("items", []) or []

        for item in injury_list:
            if not isinstance(item, dict):
                continue
            record = self._parse_item(item, fetch_time)
            if record:
                records.append(record)

        return records

    def _parse_item(self, item: Dict[str, Any], fetch_time: str) -> Optional[Dict[str, Any]]:
        details = item.get("details") or item  # some payloads flatten details

        athlete = details.get("athlete") or item.get("athlete") or {}
        if not athlete:
            return None

        # Player name
        player_name = (
            athlete.get("displayName")
            or f"{athlete.get('firstName', '')} {athlete.get('lastName', '')}".strip()
            or "Unknown"
        )

        # Team abbreviation
        team_obj = athlete.get("team") or {}
        abbr_raw = (team_obj.get("abbreviation") or "").upper()
        team_abbr = _ESPN_ABBR_MAP.get(abbr_raw, abbr_raw) or "UNK"

        # Position
        pos_obj = athlete.get("position") or {}
        position = (pos_obj.get("abbreviation") or pos_obj.get("name") or "UNK").upper()

        # Status
        raw_status = (
            item.get("status")
            or details.get("status")
            or details.get("fantasyStatus", {}).get("description")
            or "Unknown"
        )
        status = _STATUS_MAP.get(str(raw_status).lower().strip(), str(raw_status).strip())

        # Practice status
        practice_status = "Unknown"
        for key in ("shortComment", "longComment", "comment"):
            comment = details.get(key, "") or ""
            if "limited" in comment.lower():
                practice_status = "Limited"
                break
            if "full" in comment.lower():
                practice_status = "Full"
                break
            if "did not" in comment.lower() or "dnp" in comment.lower():
                practice_status = "DNP"
                break

        # Injury detail / notes
        injury_type = details.get("type") or details.get("detail") or ""
        if isinstance(injury_type, dict):
            injury_type = injury_type.get("name") or injury_type.get("text") or ""
        notes = str(injury_type).strip()

        # Heuristic starter flag: high-impact positions with significant status
        is_starter = (
            position in _HIGH_IMPACT_POSITIONS
            and status in ("Out", "Doubtful", "Questionable", "IR")
        )

        impact = _status_impact(status)

        # Timestamp
        last_updated = details.get("date") or fetch_time

        return {
            "player": player_name,
            "team": team_abbr,
            "position": position,
            "positionGroup": _position_group(position),
            "status": status,
            "practiceStatus": practice_status,
            "starter": is_starter,
            "impact": impact,
            "notes": notes,
            "lastUpdated": last_updated,
        }
