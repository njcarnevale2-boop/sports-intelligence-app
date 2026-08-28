from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from app.runtime_paths import runtime_paths
from app.services.social_history import get_social_summary, store_ingestion_run, store_signals
from app.services.social_sources import (
    SOURCE_TYPE_NATIONAL_REPORTER,
    SOURCE_TYPE_OTHER_VERIFIED,
    SOURCE_TYPE_TEAM_BEAT,
    SOURCE_TYPE_TEAM_OFFICIAL,
    get_social_source_summary,
    get_social_sources,
)


log = logging.getLogger("social_intelligence")

MODEL_ROOT = runtime_paths.root
GAME_PROJECTIONS = runtime_paths.current_game_projections_csv

PROVIDER_NAME = "MOCK"
DATA_STATUS = "MOCK"

VERIFIED_STATUSES = {"CORROBORATED", "OFFICIAL"}
UNVERIFIED_STATUSES = {"RUMOR", "REPORTED"}
PERSONNEL_CATEGORIES = {
    "DEPTH_CHART",
    "FIRST_TEAM_REPS",
    "OFFENSIVE_LINE_CHANGE",
    "SECONDARY_CHANGE",
    "QB_CHANGE",
    "ROLE_CHANGE",
}
TREND_CATEGORIES = {"SCHEME_CHANGE", "TRAVEL", "DISCIPLINE", "OTHER"}

SOURCE_TYPE_BONUS = {
    SOURCE_TYPE_TEAM_OFFICIAL: 18.0,
    SOURCE_TYPE_NATIONAL_REPORTER: 12.0,
    SOURCE_TYPE_TEAM_BEAT: 8.0,
    SOURCE_TYPE_OTHER_VERIFIED: 5.0,
}

MARKET_RELEVANCE_WEIGHT = {
    "LOW": 0.5,
    "MEDIUM": 1.0,
    "HIGH": 1.5,
}


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


class SocialIntelligenceService:
    def __init__(
        self,
        registry: Optional[List[Dict[str, Any]]] = None,
        mock_templates: Optional[List[Dict[str, Any]]] = None,
        event_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
        persist_history: bool = True,
        now_provider: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.registry = registry or get_social_sources(active_only=False, include_national=True)
        self.sources_by_handle = {
            str(source["handle"]): source
            for source in self.registry
            if str(source.get("handle") or "").strip()
        }
        self.mock_templates = mock_templates or self._default_mock_templates()
        self.persist_history = persist_history
        self.now_provider = now_provider
        self._event_lookup_override = event_lookup
        self._cached_signals: List[Dict[str, Any]] = []
        self._cached_schedule_mtime: Optional[float] = None
        self._cached_event_lookup: Dict[str, Dict[str, Any]] = event_lookup or {}
        self._last_ingestion: Optional[str] = None

    def metadata(self) -> Dict[str, Any]:
        if not self._cached_signals:
            self.ingest_mock_signals()

        source_summary = get_social_source_summary()
        history_summary = get_social_summary()
        return {
            "provider": PROVIDER_NAME,
            "isLive": False,
            "dataStatus": DATA_STATUS,
            "sourcesActive": max(source_summary.get("sourcesActive", 0), history_summary.get("sourcesActive", 0)),
            "signalsDetected": history_summary.get("signalsDetected", len(self._cached_signals)),
            "corroboratedSignals": history_summary.get("corroboratedSignals", 0),
            "officialSignals": history_summary.get("officialSignals", 0),
            "lastIngestion": history_summary.get("lastIngestion") or self._last_ingestion,
            "errors": [history_summary.get("lastError")] if history_summary.get("lastError") else [],
        }

    def ingest_mock_signals(self, force: bool = False) -> List[Dict[str, Any]]:
        schedule_mtime = self._schedule_mtime()
        if not force and self._cached_signals and schedule_mtime == self._cached_schedule_mtime:
            return self._cached_signals

        event_lookup = self._load_event_lookup(force=force)
        team_event_lookup = self._team_event_lookup(event_lookup)
        raw_signals = self._build_raw_signals(team_event_lookup)
        aggregated_signals = self._aggregate_raw_signals(raw_signals)

        self._cached_signals = aggregated_signals
        self._cached_schedule_mtime = schedule_mtime
        self._last_ingestion = self._now().isoformat()

        if self.persist_history:
            stored_count = store_signals(aggregated_signals, provider=PROVIDER_NAME, is_live=False)
            log.info("Stored %d social signals to history", stored_count)

            source_summary = get_social_source_summary()
            store_ingestion_run(
                {
                    "provider": PROVIDER_NAME,
                    "isLive": False,
                    "dataStatus": DATA_STATUS,
                    "sourcesActive": source_summary.get("sourcesActive", 0),
                    "signalsDetected": len(aggregated_signals),
                    "corroboratedSignals": len([signal for signal in aggregated_signals if signal["status"] == "CORROBORATED"]),
                    "officialSignals": len([signal for signal in aggregated_signals if signal["status"] == "OFFICIAL"]),
                    "lastIngestion": self._last_ingestion,
                    "errors": [],
                }
            )

        return aggregated_signals

    def team_social_intelligence(self, team: str, event_id: Optional[str] = None) -> Dict[str, Any]:
        team_code = str(team or "").strip().upper()
        signals = [
            signal
            for signal in self.ingest_mock_signals()
            if signal.get("team") == team_code and (event_id is None or signal.get("eventId") == event_id)
        ]

        if not signals:
            return {
                "team": team_code,
                "socialScore": 50.0,
                "injurySignals": [],
                "personnelSignals": [],
                "trendSignals": [],
                "highestImpactSignal": None,
                "verifiedSignals": [],
                "unverifiedSignals": [],
                "summary": "No mock social signals are currently attached to this team.",
                "provider": PROVIDER_NAME,
                "isLive": False,
                "dataStatus": DATA_STATUS,
            }

        ordered = sorted(
            signals,
            key=lambda signal: (
                abs(float(signal.get("estimatedPointImpact", 0.0) or 0.0)),
                float(signal.get("confidence", 0.0) or 0.0),
            ),
            reverse=True,
        )
        verified = [signal for signal in ordered if signal["status"] in VERIFIED_STATUSES]
        unverified = [signal for signal in ordered if signal["status"] in UNVERIFIED_STATUSES or signal["status"] == "DISMISSED"]

        score_delta = sum(
            float(signal.get("gameImpact", 0.0) or 0.0) * (float(signal.get("confidence", 0.0) or 0.0) / 100.0) * 12.0
            for signal in ordered
        )
        social_score = round(clamp(50.0 + score_delta), 1)
        highest = ordered[0]

        return {
            "team": team_code,
            "socialScore": social_score,
            "injurySignals": [signal for signal in ordered if signal["category"] in {"INJURY", "PRACTICE_STATUS", "SNAP_RESTRICTION"}],
            "personnelSignals": [signal for signal in ordered if signal["category"] in PERSONNEL_CATEGORIES],
            "trendSignals": [signal for signal in ordered if signal["category"] in TREND_CATEGORIES],
            "highestImpactSignal": highest,
            "verifiedSignals": verified,
            "unverifiedSignals": unverified,
            "summary": self._team_summary(team_code, highest, len(verified), len(unverified), social_score),
            "provider": PROVIDER_NAME,
            "isLive": False,
            "dataStatus": DATA_STATUS,
        }

    def get_game_social_context(self, event_id: str) -> Dict[str, Any]:
        event_lookup = self._load_event_lookup()
        event = event_lookup.get(str(event_id), None)

        if event is None:
            return {
                "eventId": event_id,
                "available": False,
                "provider": PROVIDER_NAME,
                "isLive": False,
                "dataStatus": DATA_STATUS,
                "reason": "Game not found in current schedule.",
                "keySignals": [],
            }

        away_team = event["awayTeam"]
        home_team = event["homeTeam"]

        away_context = self.team_social_intelligence(away_team, event_id=event_id)
        home_context = self.team_social_intelligence(home_team, event_id=event_id)
        key_signals = sorted(
            away_context["verifiedSignals"] + away_context["unverifiedSignals"] + home_context["verifiedSignals"] + home_context["unverifiedSignals"],
            key=lambda signal: (
                abs(float(signal.get("estimatedPointImpact", 0.0) or 0.0)),
                float(signal.get("confidence", 0.0) or 0.0),
            ),
            reverse=True,
        )[:5]

        confidence = 0.0
        if key_signals:
            confidence = round(sum(float(signal.get("confidence", 0.0) or 0.0) for signal in key_signals) / len(key_signals), 1)

        net_social_advantage = round(float(home_context["socialScore"]) - float(away_context["socialScore"]), 1)
        metadata = self.metadata()

        return {
            "eventId": event_id,
            "available": True,
            "awayTeam": away_team,
            "homeTeam": home_team,
            "awaySocialScore": away_context["socialScore"],
            "homeSocialScore": home_context["socialScore"],
            "netSocialAdvantage": net_social_advantage,
            "keySignals": key_signals,
            "confidence": confidence,
            "summary": self._game_summary(away_team, home_team, net_social_advantage, key_signals),
            "awayTeamReport": away_context,
            "homeTeamReport": home_context,
            "provider": metadata["provider"],
            "isLive": metadata["isLive"],
            "dataStatus": metadata["dataStatus"],
            "sourcesActive": metadata["sourcesActive"],
            "signalsDetected": len(key_signals),
            "corroboratedSignals": len([signal for signal in key_signals if signal["status"] == "CORROBORATED"]),
            "officialSignals": len([signal for signal in key_signals if signal["status"] == "OFFICIAL"]),
            "lastIngestion": metadata["lastIngestion"],
            "errors": metadata["errors"],
        }

    def _now(self) -> datetime:
        if self.now_provider is not None:
            return self.now_provider()
        return datetime.now(timezone.utc)

    def _schedule_mtime(self) -> Optional[float]:
        if self._event_lookup_override is not None:
            return None
        try:
            return GAME_PROJECTIONS.stat().st_mtime
        except OSError:
            return None

    def _load_event_lookup(self, force: bool = False) -> Dict[str, Dict[str, Any]]:
        if self._event_lookup_override is not None:
            return self._event_lookup_override

        schedule_mtime = self._schedule_mtime()
        if not force and self._cached_event_lookup and schedule_mtime == self._cached_schedule_mtime:
            return self._cached_event_lookup

        lookup: Dict[str, Dict[str, Any]] = {}
        if GAME_PROJECTIONS.exists():
            try:
                df = pd.read_csv(GAME_PROJECTIONS)
                df["api_event_id"] = df["api_event_id"].astype(str)
                for _, row in df.iterrows():
                    event_id = str(row.get("api_event_id", "")).strip()
                    if not event_id:
                        continue
                    lookup[event_id] = {
                        "eventId": event_id,
                        "awayTeam": str(row.get("away_team", "")).strip().upper(),
                        "homeTeam": str(row.get("home_team", "")).strip().upper(),
                        "commenceTime": str(row.get("commence_time", "")).strip(),
                    }
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not load event lookup for social intelligence: %s", exc)

        self._cached_event_lookup = lookup
        return lookup

    def _team_event_lookup(self, event_lookup: Dict[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        team_lookup: Dict[str, List[Dict[str, Any]]] = {}
        for event in event_lookup.values():
            team_lookup.setdefault(event["awayTeam"], []).append(event)
            team_lookup.setdefault(event["homeTeam"], []).append(event)
        return team_lookup

    def _build_raw_signals(self, team_event_lookup: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        now = self._now()
        raw_signals: List[Dict[str, Any]] = []

        for index, template in enumerate(self.mock_templates, start=1):
            team = str(template.get("team", "")).strip().upper()
            event_candidates = team_event_lookup.get(team, [])
            event_id = str(template.get("eventId") or (event_candidates[0]["eventId"] if event_candidates else "")).strip() or None

            source_handle = str(template.get("sourceHandle", "")).strip()
            source = self.sources_by_handle.get(source_handle, {
                "name": f"Mock source for {team}",
                "handle": source_handle or f"mock_{team.lower()}_source",
                "sourceType": SOURCE_TYPE_OTHER_VERIFIED,
                "credibilityScore": 55,
                "tier": "WATCHLIST",
                "priority": 99,
                "active": True,
                "verified": False,
            })

            timestamp = now - timedelta(hours=float(template.get("hoursAgo", 1) or 1))
            raw_signals.append(
                {
                    "signalId": f"social_{team.lower()}_{index}",
                    "groupKey": template.get("groupKey") or f"{team}:{template.get('category')}:{template.get('player') or 'team'}",
                    "timestamp": timestamp.isoformat(),
                    "team": team,
                    "player": template.get("player"),
                    "position": template.get("position"),
                    "category": str(template.get("category", "OTHER")).upper(),
                    "severity": str(template.get("severity", "LOW")).upper(),
                    "sourceName": source["name"],
                    "sourceHandle": source["handle"],
                    "sourceType": source["sourceType"],
                    "sourceCredibility": int(source["credibilityScore"]),
                    "textSummary": str(template.get("textSummary", "Mock social signal.")).strip(),
                    "status": str(template.get("status", "REPORTED")).upper(),
                    "estimatedPointImpact": round(float(template.get("estimatedPointImpact", 0.0) or 0.0), 2),
                    "marketRelevance": str(template.get("marketRelevance", "MEDIUM")).upper(),
                    "gameImpact": round(float(template.get("gameImpact", 0.0) or 0.0), 2),
                    "eventId": event_id,
                }
            )

        return raw_signals

    def _aggregate_raw_signals(self, raw_signals: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for signal in raw_signals:
            grouped.setdefault(str(signal["groupKey"]), []).append(signal)

        aggregated: List[Dict[str, Any]] = []
        for group_key, group in grouped.items():
            ordered = sorted(
                group,
                key=lambda signal: (
                    int(signal.get("sourceCredibility", 0) or 0),
                    -self._source_priority(signal.get("sourceType")),
                ),
                reverse=True,
            )
            primary = ordered[0]
            unique_sources = {
                str(signal.get("sourceHandle", "")).strip().lower()
                for signal in ordered
                if str(signal.get("sourceHandle", "")).strip()
            }
            corroboration_count = max(0, len(unique_sources) - 1)
            status = self._resolve_status(ordered)
            confidence = self._confidence_for_group(ordered, status)
            timestamp = min(
                datetime.fromisoformat(str(signal["timestamp"]))
                for signal in ordered
            ).astimezone(timezone.utc)

            aggregated.append(
                {
                    "signalId": f"signal_{abs(hash(group_key))}",
                    "timestamp": timestamp.isoformat(),
                    "team": primary.get("team"),
                    "player": primary.get("player"),
                    "position": primary.get("position"),
                    "category": primary.get("category"),
                    "severity": primary.get("severity"),
                    "sourceName": primary.get("sourceName"),
                    "sourceHandle": primary.get("sourceHandle"),
                    "sourceType": primary.get("sourceType"),
                    "sourceCredibility": primary.get("sourceCredibility"),
                    "textSummary": primary.get("textSummary"),
                    "corroborationCount": corroboration_count,
                    "confidence": confidence,
                    "status": status,
                    "estimatedPointImpact": round(
                        max((abs(float(item.get("estimatedPointImpact", 0.0) or 0.0)) for item in ordered), default=0.0),
                        2,
                    ),
                    "marketRelevance": self._highest_market_relevance(ordered),
                    "gameImpact": round(sum(float(item.get("gameImpact", 0.0) or 0.0) for item in ordered) / len(ordered), 2),
                    "eventId": primary.get("eventId"),
                    "provider": PROVIDER_NAME,
                    "isLive": False,
                    "subsequentLineMovement": None,
                    "closingLine": None,
                    "gameResult": None,
                }
            )

        return sorted(
            aggregated,
            key=lambda signal: (
                abs(float(signal.get("estimatedPointImpact", 0.0) or 0.0)),
                float(signal.get("confidence", 0.0) or 0.0),
            ),
            reverse=True,
        )

    def _resolve_status(self, group: Sequence[Dict[str, Any]]) -> str:
        statuses = {str(signal.get("status", "REPORTED")).upper() for signal in group}
        source_types = {str(signal.get("sourceType", "")).upper() for signal in group}
        official_confirmation = any(bool(signal.get("officialConfirmation", False)) for signal in group)

        if "DISMISSED" in statuses:
            return "DISMISSED"
        if official_confirmation or SOURCE_TYPE_TEAM_OFFICIAL in source_types:
            return "OFFICIAL"
        if len(group) >= 2:
            return "CORROBORATED"
        if "RUMOR" in statuses:
            return "RUMOR"
        return "REPORTED"

    def _confidence_for_group(self, group: Sequence[Dict[str, Any]], status: str) -> float:
        primary = max(group, key=lambda signal: int(signal.get("sourceCredibility", 0) or 0))
        base_credibility = float(primary.get("sourceCredibility", 0.0) or 0.0) * 0.55
        corroboration_bonus = 0.0
        unique_sources = {
            str(signal.get("sourceHandle", "")).strip().lower()
            for signal in group
            if str(signal.get("sourceHandle", "")).strip()
        }
        if len(unique_sources) >= 3:
            corroboration_bonus = 24.0
        elif len(unique_sources) == 2:
            corroboration_bonus = 14.0

        source_bonus = SOURCE_TYPE_BONUS.get(str(primary.get("sourceType", "")).upper(), 0.0)
        newest_timestamp = max(datetime.fromisoformat(str(signal["timestamp"])) for signal in group)
        age_hours = max((self._now() - newest_timestamp.astimezone(timezone.utc)).total_seconds() / 3600.0, 0.0)
        if age_hours <= 2:
            recency_bonus = 10.0
        elif age_hours <= 8:
            recency_bonus = 6.0
        elif age_hours <= 24:
            recency_bonus = 3.0
        else:
            recency_bonus = 0.0

        official_bonus = 18.0 if status == "OFFICIAL" else 0.0
        rumor_penalty = -10.0 if status == "RUMOR" else 0.0
        dismissed_penalty = -30.0 if status == "DISMISSED" else 0.0

        return round(clamp(base_credibility + corroboration_bonus + source_bonus + recency_bonus + official_bonus + rumor_penalty + dismissed_penalty), 1)

    def _highest_market_relevance(self, group: Sequence[Dict[str, Any]]) -> str:
        ordered = sorted(
            (str(signal.get("marketRelevance", "MEDIUM")).upper() for signal in group),
            key=lambda label: MARKET_RELEVANCE_WEIGHT.get(label, 1.0),
            reverse=True,
        )
        return ordered[0] if ordered else "MEDIUM"

    def _source_priority(self, source_type: Any) -> int:
        text = str(source_type or "").upper()
        if text == SOURCE_TYPE_TEAM_OFFICIAL:
            return 4
        if text == SOURCE_TYPE_NATIONAL_REPORTER:
            return 3
        if text == SOURCE_TYPE_TEAM_BEAT:
            return 2
        return 1

    def _team_summary(
        self,
        team: str,
        highest_signal: Dict[str, Any],
        verified_count: int,
        unverified_count: int,
        social_score: float,
    ) -> str:
        status = highest_signal.get("status", "REPORTED")
        player = highest_signal.get("player") or "team-level personnel note"
        category = str(highest_signal.get("category", "OTHER")).replace("_", " ").lower()
        return (
            f"{team} carries a mock social score of {social_score:.1f}. "
            f"Top signal: {player} ({category}) is currently {status.lower()}. "
            f"Verified signals: {verified_count}; unverified signals: {unverified_count}."
        )

    def _game_summary(
        self,
        away_team: str,
        home_team: str,
        net_social_advantage: float,
        key_signals: Sequence[Dict[str, Any]],
    ) -> str:
        if not key_signals:
            return f"No mock social signals are attached to the {away_team} at {home_team} matchup."

        lead = key_signals[0]
        lead_player = lead.get("player") or "team personnel"
        lead_status = str(lead.get("status", "REPORTED")).lower()
        if net_social_advantage > 0:
            edge_text = f"{home_team} holds the stronger mock social context by {net_social_advantage:.1f} points"
        elif net_social_advantage < 0:
            edge_text = f"{away_team} holds the stronger mock social context by {abs(net_social_advantage):.1f} points"
        else:
            edge_text = "The matchup social context is roughly neutral"
        return f"{edge_text}. Highest-impact signal: {lead_player} is currently {lead_status}."

    def _default_mock_templates(self) -> List[Dict[str, Any]]:
        return [
            {
                "team": "BUF",
                "player": "Mock WR1",
                "position": "WR",
                "category": "PRACTICE_STATUS",
                "severity": "MODERATE",
                "sourceHandle": "mock_buf_beat",
                "textSummary": "Mock example: veteran receiver was limited during a controlled practice period.",
                "status": "REPORTED",
                "hoursAgo": 2,
                "estimatedPointImpact": 0.3,
                "marketRelevance": "MEDIUM",
                "gameImpact": -0.25,
                "groupKey": "BUF:WR1:PRACTICE_STATUS",
            },
            {
                "team": "BUF",
                "player": "Mock WR1",
                "position": "WR",
                "category": "PRACTICE_STATUS",
                "severity": "MODERATE",
                "sourceHandle": "mock_national_buf",
                "textSummary": "Mock example: second trusted source echoed the limited-workload report for the same receiver.",
                "status": "REPORTED",
                "hoursAgo": 1,
                "estimatedPointImpact": 0.3,
                "marketRelevance": "MEDIUM",
                "gameImpact": -0.2,
                "groupKey": "BUF:WR1:PRACTICE_STATUS",
            },
            {
                "team": "MIA",
                "player": "Mock LT",
                "position": "LT",
                "category": "OFFENSIVE_LINE_CHANGE",
                "severity": "LOW",
                "sourceHandle": "mock_mia_official",
                "textSummary": "Mock example: team communications noted a planned first-team left tackle rotation.",
                "status": "OFFICIAL",
                "officialConfirmation": True,
                "hoursAgo": 3,
                "estimatedPointImpact": 0.2,
                "marketRelevance": "MEDIUM",
                "gameImpact": 0.15,
                "groupKey": "MIA:LT:OFFENSIVE_LINE_CHANGE",
            },
            {
                "team": "KC",
                "player": "Mock RB",
                "position": "RB",
                "category": "SNAP_RESTRICTION",
                "severity": "LOW",
                "sourceHandle": "mock_kc_beat",
                "textSummary": "Mock example: beat reporter suggested a lighter opening workload for a featured back.",
                "status": "RUMOR",
                "hoursAgo": 4,
                "estimatedPointImpact": 0.15,
                "marketRelevance": "LOW",
                "gameImpact": -0.1,
                "groupKey": "KC:RB:SNAP_RESTRICTION",
            },
            {
                "team": "KC",
                "player": "Mock RB",
                "position": "RB",
                "category": "SNAP_RESTRICTION",
                "severity": "LOW",
                "sourceHandle": "mock_kc_official",
                "textSummary": "Mock example: official team messaging dismissed the earlier workload speculation.",
                "status": "DISMISSED",
                "officialConfirmation": True,
                "hoursAgo": 1,
                "estimatedPointImpact": 0.0,
                "marketRelevance": "LOW",
                "gameImpact": 0.0,
                "groupKey": "KC:RB:SNAP_RESTRICTION",
            },
            {
                "team": "DAL",
                "player": "Mock QB2",
                "position": "QB",
                "category": "QB_CHANGE",
                "severity": "HIGH",
                "sourceHandle": "mock_dal_official",
                "textSummary": "Mock example: the club announced a backup quarterback would handle a package of first-team reps.",
                "status": "OFFICIAL",
                "officialConfirmation": True,
                "hoursAgo": 5,
                "estimatedPointImpact": 0.7,
                "marketRelevance": "HIGH",
                "gameImpact": -0.55,
                "groupKey": "DAL:QB2:QB_CHANGE",
            },
            {
                "team": "PHI",
                "player": None,
                "position": None,
                "category": "TRAVEL",
                "severity": "LOW",
                "sourceHandle": "mock_verified_phi",
                "textSummary": "Mock example: verified travel monitor flagged a delayed team arrival window.",
                "status": "REPORTED",
                "hoursAgo": 6,
                "estimatedPointImpact": 0.1,
                "marketRelevance": "LOW",
                "gameImpact": -0.08,
                "groupKey": "PHI:TEAM:TRAVEL",
            },
            {
                "team": "SF",
                "player": "Mock CB1",
                "position": "CB",
                "category": "SECONDARY_CHANGE",
                "severity": "MODERATE",
                "sourceHandle": "mock_sf_beat",
                "textSummary": "Mock example: local coverage noted a first-team corner rotation on the outside.",
                "status": "REPORTED",
                "hoursAgo": 8,
                "estimatedPointImpact": 0.25,
                "marketRelevance": "MEDIUM",
                "gameImpact": -0.2,
                "groupKey": "SF:CB1:SECONDARY_CHANGE",
            },
        ]


social_intelligence_service = SocialIntelligenceService()