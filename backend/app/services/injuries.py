from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from app.providers.provider_manager import ProviderManager

log = logging.getLogger("injuries")

# ALLOW_MOCK_FALLBACK only applies when INJURY_PROVIDER=mock.
# When a live provider is active (ESPN, SportsRadar) this flag is ignored so
# that a successful LIVE response with 0 records is never silently replaced
# by mock data that could mislead users about real injury status.
_ALLOW_MOCK = os.getenv("ALLOW_MOCK_FALLBACK", "true").lower() in {"1", "true", "yes"}


class InjuryAnalyzer:
    """
    Evaluate NFL injury data with realistic positional weighting.

    Data priority
    ─────────────
    1. Live provider (INJURY_PROVIDER=espn / sportsradar)
       • LIVE + N records  → return records, status=LIVE
       • LIVE + 0 records  → return empty, status=LIVE   ← no mock fallthrough
       • provider error    → fall to cache
    2. DuckDB cached snapshot  → status=CACHED
    3. Mock data  → only when INJURY_PROVIDER=mock (never silently in prod)
    4. UNAVAILABLE  → no data, no mock allowed

    DEVELOPMENT NOTE: The ESPN public injury endpoint
    (site.api.espn.com) is an unofficial, undocumented API used for
    development convenience. It must be reviewed and replaced with a
    contracted data provider before any commercial or production launch.
    """

    def __init__(self, injuries: Optional[List[Dict[str, Any]]] = None):
        self.provider_manager = ProviderManager()
        self.provider = self.provider_manager.get_injury_provider()
        self.provider_metadata = self.provider.get_metadata()
        self._data_status = "MOCK"
        self._last_updated: Optional[str] = None

        if injuries is not None:
            # Explicitly supplied list — used in tests and direct callers
            self.injuries = injuries
            self._data_status = "MOCK"
        else:
            self.injuries = self._load_injuries()

    def _using_mock_provider(self) -> bool:
        return self.provider_manager.injury_provider_name == "mock"

    def _load_injuries(self) -> List[Dict[str, Any]]:
        """Return injuries and set _data_status; never silently mixes sources."""
        from app.services.injury_history import (
            detect_changes, get_cached_injuries, store_changes, store_snapshot,
        )

        # ── live provider path ──────────────────────────────────────────────
        if hasattr(self.provider, "fetch_injuries"):
            fetch_error: Optional[str] = None
            try:
                result = self.provider.fetch_injuries()
                provider_name = result.get("provider", self.provider.provider_name)
                injuries     = result.get("injuries", [])
                record_count = len(injuries)
                is_live      = result.get("dataStatus") == "LIVE"

                if is_live:
                    # Successful live response — commit immediately regardless of count
                    if injuries:
                        changes = detect_changes(injuries, provider_name)
                        if changes:
                            store_changes(changes)
                            log.info("Detected %d injury status changes", len(changes))
                        store_snapshot(injuries, provider_name)

                    log.info(
                        "Live injury fetch: provider=%s records=%d", provider_name, record_count
                    )
                    self.provider_metadata = {
                        **self.provider_metadata,
                        "provider":    provider_name,
                        "isLive":      True,
                        "dataStatus":  "LIVE",
                        "lastUpdated": result.get("lastUpdated"),
                        "recordCount": record_count,
                    }
                    self._data_status  = "LIVE"
                    self._last_updated = result.get("lastUpdated")
                    return injuries   # ← exit here; never fall through when LIVE

                # Provider returned a non-LIVE status (e.g. UNAVAILABLE from its own logic)
                fetch_error = f"Provider returned dataStatus={result.get('dataStatus')}"
                log.info("Live provider non-LIVE response: %s", fetch_error)

            except Exception as exc:
                fetch_error = str(exc)
                log.warning("Live injury fetch exception: %s", exc)

        # ── cached fallback (provider failure or non-live response) ─────────
        cached = get_cached_injuries()
        if cached and cached.get("injuries"):
            record_count = len(cached["injuries"])
            log.info("Using cached injury data (%d records)", record_count)
            self.provider_metadata = {
                **self.provider_metadata,
                "isLive":      False,
                "dataStatus":  "CACHED",
                "lastUpdated": cached.get("lastUpdated"),
                "recordCount": record_count,
            }
            self._data_status  = "CACHED"
            self._last_updated = cached.get("lastUpdated")
            return cached["injuries"]

        # ── mock — only for explicit mock provider ──────────────────────────
        if self._using_mock_provider() and _ALLOW_MOCK:
            log.info("Using mock injury data (INJURY_PROVIDER=mock)")
            self.provider_metadata = {
                **self.provider_metadata,
                "isLive":      False,
                "dataStatus":  "MOCK",
                "recordCount": 0,
            }
            self._data_status = "MOCK"
            return self._mock_injuries()

        # ── unavailable ─────────────────────────────────────────────────────
        log.warning("Injury data unavailable (provider=%s)", self.provider_manager.injury_provider_name)
        self.provider_metadata = {
            **self.provider_metadata,
            "isLive":      False,
            "dataStatus":  "UNAVAILABLE",
            "recordCount": 0,
        }
        self._data_status = "UNAVAILABLE"
        return []

    def analyze(self) -> Dict[str, Any]:
        """Return compact report with aggregate and per-team analysis."""

        team_groups: Dict[str, List[Dict[str, Any]]] = {}

        for injury in self.injuries:
            team = str(injury.get("team", "UNKNOWN")).upper()
            team_groups.setdefault(team, []).append(injury)

        team_reports: Dict[str, Dict[str, Any]] = {}
        overall_scores: List[float] = []

        for team_name in sorted(team_groups):
            team_report = self._analyze_team(team_name, team_groups[team_name])
            team_reports[team_name] = team_report
            overall_scores.append(team_report["injuryScore"])

        overall_score = round(
            clamp(sum(overall_scores) / max(len(overall_scores), 1), 0, 100),
            1,
        )
        overall_offensive = round(
            clamp(
                sum(team_reports[team]["offensiveImpact"] for team in team_reports)
                / max(len(team_reports), 1),
                0,
                100,
            ),
            1,
        )
        overall_defensive = round(
            clamp(
                sum(team_reports[team]["defensiveImpact"] for team in team_reports)
                / max(len(team_reports), 1),
                0,
                100,
            ),
            1,
        )
        overall_special = round(
            clamp(
                sum(team_reports[team]["specialTeamsImpact"] for team in team_reports)
                / max(len(team_reports), 1),
                0,
                100,
            ),
            1,
        )
        overall_point_adjustment = round(
            clamp(
                sum(team_reports[team]["pointAdjustment"] for team in team_reports),
                0,
                8,
            ),
            1,
        )

        overall_key_players = self._top_key_players(
            [
                item
                for team_report in team_reports.values()
                for item in team_report["keyPlayers"]
            ]
        )

        return {
            "injuryScore": overall_score,
            "offensiveImpact": overall_offensive,
            "defensiveImpact": overall_defensive,
            "specialTeamsImpact": overall_special,
            "pointAdjustment": overall_point_adjustment,
            "keyPlayers": overall_key_players,
            "summary": self._build_summary(overall_score),
            "teams": team_reports,
            "providerMetadata": self.provider_metadata,
            "dataMode": self._data_status.lower(),
            "provider":    self.provider_metadata.get("provider", "Unknown"),
            # isLive is authoritative from _data_status, not provider_metadata
            "isLive":      self._data_status == "LIVE",
            "lastUpdated": self._last_updated or self.provider_metadata.get("lastUpdated"),
            "dataStatus":  self._data_status,
            "recordCount": self.provider_metadata.get("recordCount", len(self.injuries)),
        }

    def _analyze_team(self, team: str, injuries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Produce a single team-level injury snapshot.
        """

        scoring_details: List[Dict[str, Any]] = []

        for injury in injuries:
            severity = self._severity_score(injury)
            position_weight = self._position_weight(injury)
            burden_score = round(
                clamp(position_weight * severity * 1.15, 0, 100),
                1,
            )
            point_impact = self._estimated_point_impact(injury)
            category = self._impact_category(injury)

            scoring_details.append(
                {
                    "player": injury.get("player", "Unknown"),
                    "team": team,
                    "position": injury.get("position", "Unknown"),
                    "status": injury.get("status", "unknown"),
                    "starter": injury.get("starter", False),
                    "impact": injury.get("impact", 0),
                    "severity": round(severity, 1),
                    "weightedImpact": burden_score,
                    "estimatedPointImpact": round(point_impact, 1),
                    "category": category,
                }
            )

        injury_score = round(
            clamp(sum(item["weightedImpact"] for item in scoring_details) * 2.2, 0, 100),
            1,
        )
        offensive_impact = round(
            clamp(
                sum(
                    item["weightedImpact"]
                    for item in scoring_details
                    if item["category"] == "offense"
                )
                * 2.5,
                0,
                100,
            ),
            1,
        )
        defensive_impact = round(
            clamp(
                sum(
                    item["weightedImpact"]
                    for item in scoring_details
                    if item["category"] == "defense"
                )
                * 2.5,
                0,
                100,
            ),
            1,
        )
        special_teams_impact = round(
            clamp(
                sum(
                    item["weightedImpact"]
                    for item in scoring_details
                    if item["category"] == "special_teams"
                )
                * 2.5,
                0,
                100,
            ),
            1,
        )
        point_adjustment = round(
            clamp(sum(item["estimatedPointImpact"] for item in scoring_details), 0, 8),
            1,
        )
        key_players = self._top_key_players(scoring_details)

        return {
            "injuryScore": injury_score,
            "offensiveImpact": offensive_impact,
            "defensiveImpact": defensive_impact,
            "specialTeamsImpact": special_teams_impact,
            "pointAdjustment": point_adjustment,
            "keyPlayers": key_players,
            "summary": self._build_summary(injury_score),
        }

    def _mock_injuries(self) -> List[Dict[str, Any]]:
        """
        A compact mock dataset with realistic positional value.

        The weighting intentionally makes:
        - QB matter more than RB
        - LT matter significantly
        - CB1 matter significantly
        - backup WR barely move the score
        """

        return [
            {
                "player": "Josh Allen",
                "team": "BUF",
                "position": "QB",
                "status": "questionable",
                "starter": True,
                "impact": 9,
            },
            {
                "player": "Trent Williams",
                "team": "SF",
                "position": "LT",
                "status": "out",
                "starter": True,
                "impact": 8,
            },
            {
                "player": "Darius Slay",
                "team": "PHI",
                "position": "CB1",
                "status": "doubtful",
                "starter": True,
                "impact": 7,
            },
            {
                "player": "Tony Pollard",
                "team": "TEN",
                "position": "RB",
                "status": "questionable",
                "starter": True,
                "impact": 5,
            },
            {
                "player": "Jalen Tolbert",
                "team": "DAL",
                "position": "WR",
                "status": "probable",
                "starter": False,
                "impact": 2,
            },
        ]

    def _position_weight(self, injury: Dict[str, Any]) -> float:
        """
        Use realistic football weighting so the engine reflects positional importance.
        """

        position = str(injury.get("position", "")).upper()

        weights = {
            "QB": 1.00,
            "LT": 0.90,
            "RT": 0.78,
            "C": 0.72,
            "LG": 0.68,
            "RG": 0.68,
            "CB1": 0.80,
            "CB": 0.68,
            "S": 0.62,
            "EDGE": 0.70,
            "DE": 0.66,
            "DT": 0.64,
            "LB": 0.60,
            "RB": 0.56,
            "WR": 0.40,
            "TE": 0.44,
            "K": 0.22,
            "P": 0.18,
        }

        base_weight = weights.get(position, 0.35)

        # Starters matter more than backups, because the loss of a full-time
        # contributor tends to hurt more than the loss of a rotational player.
        if injury.get("starter", False):
            base_weight *= 1.15

        return base_weight

    def _severity_score(self, injury: Dict[str, Any]) -> float:
        """
        Convert status and impact into a 0-10 severity score.
        """

        status = str(injury.get("status", "")).lower()
        impact = float(injury.get("impact", 0) or 0)

        status_weights = {
            "out": 1.00,
            "doubtful": 0.85,
            "questionable": 0.65,
            "probable": 0.40,
            "healthy": 0.10,
        }

        severity = status_weights.get(status, 0.30) * (impact / 10.0) * 10.0

        # High-impact players can move the metric further even if the status is
        # only questionable, which keeps the engine realistic without overreacting.
        if impact >= 8:
            severity += 1.2
        elif impact >= 6:
            severity += 0.7
        elif impact >= 4:
            severity += 0.3

        return clamp(severity, 0.0, 10.0)

    def _estimated_point_impact(self, injury: Dict[str, Any]) -> float:
        """
        Translate a player injury into a realistic estimated spread impact in points.
        This is intentionally capped to keep total team adjustment within roughly 0-8 points.
        """

        position = str(injury.get("position", "")).upper()
        status = str(injury.get("status", "")).lower()
        impact = float(injury.get("impact", 0) or 0)
        starter = bool(injury.get("starter", False))

        base_points = 0.0

        if position == "QB":
            if status == "out":
                base_points = 5.2
            elif status == "doubtful":
                base_points = 3.6
            elif status == "questionable":
                base_points = 2.2
            else:
                base_points = 0.8
        elif position == "LT":
            if status == "out":
                base_points = 1.2
            elif status == "doubtful":
                base_points = 0.9
            elif status == "questionable":
                base_points = 0.6
            else:
                base_points = 0.2
        elif position == "CB1":
            if status == "out":
                base_points = 0.9
            elif status == "doubtful":
                base_points = 0.7
            elif status == "questionable":
                base_points = 0.4
            else:
                base_points = 0.1
        elif position == "RB":
            if status == "out":
                base_points = 0.8
            elif status == "doubtful":
                base_points = 0.5
            elif status == "questionable":
                base_points = 0.3
            else:
                base_points = 0.1
        elif position == "WR":
            if status == "out":
                base_points = 0.3
            elif status == "doubtful":
                base_points = 0.2
            elif status == "questionable":
                base_points = 0.1
            else:
                base_points = 0.05
        else:
            if status == "out":
                base_points = 0.5
            elif status == "doubtful":
                base_points = 0.35
            elif status == "questionable":
                base_points = 0.2
            else:
                base_points = 0.05

        # Starters deserve a little extra weight because their absence can shift the
        # game script more meaningfully than a reserve's.
        if starter:
            base_points += 0.2

        if impact >= 8:
            base_points += 0.4
        elif impact >= 6:
            base_points += 0.2

        return clamp(base_points, 0.0, 8.0)

    def _impact_category(self, injury: Dict[str, Any]) -> str:
        """
        Group injuries into offense, defense, or special teams based on the position.
        """

        position = str(injury.get("position", "")).upper()

        if position in {"QB", "LT", "RT", "C", "LG", "RG", "RB", "WR", "TE"}:
            return "offense"
        if position in {"CB1", "CB", "S", "EDGE", "DE", "DT", "LB"}:
            return "defense"
        return "special_teams"

    def _top_key_players(self, scoring_details: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Return the three most meaningful injuries.
        """

        ranked = sorted(
            scoring_details,
            key=lambda item: (
                item["weightedImpact"],
                item["estimatedPointImpact"],
            ),
            reverse=True,
        )

        return [
            {
                "player": item["player"],
                "team": item["team"],
                "position": item["position"],
                "status": item["status"],
                "starter": item["starter"],
                "severity": round(item["severity"], 1),
                "weightedImpact": round(item["weightedImpact"], 1),
                "estimatedPointImpact": round(item["estimatedPointImpact"], 1),
            }
            for item in ranked[:3]
        ]

    def _build_summary(self, injury_score: float) -> str:
        """
        Create a natural-language summary for the UI.
        """

        if injury_score <= 15:
            return "Minimal injury concern."
        if injury_score <= 30:
            return "Light injury burden."
        if injury_score <= 50:
            return "Moderate injury burden."
        if injury_score <= 70:
            return "Significant injury burden."
        return "Severe injury burden."


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    """Clamp a numeric value to a bounded range."""

    return max(minimum, min(maximum, value))
