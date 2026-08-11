from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class AnalyticsEvent:
    event_type: str
    timestamp: datetime
    user_id: Optional[int]
    opportunity_id: Optional[str]
    page: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


class AnalyticsService:
    def __init__(self) -> None:
        self._events: List[AnalyticsEvent] = []
        self._sessions: Dict[Optional[int], List[AnalyticsEvent]] = defaultdict(list)

    def record_event(
        self,
        event_type: str,
        page: Optional[str] = None,
        opportunity_id: Optional[str] = None,
        user_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AnalyticsEvent:
        sanitized_metadata = self._sanitize_metadata(metadata or {})
        event = AnalyticsEvent(
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            user_id=user_id,
            opportunity_id=opportunity_id,
            page=page,
            metadata=sanitized_metadata,
        )
        self._events.append(event)
        self._sessions[user_id].append(event)
        return event

    def get_events(self) -> List[AnalyticsEvent]:
        return list(self._events)

    def get_admin_summary(self) -> Dict[str, Any]:
        if not self._events:
            return {
                "dailyActiveUsers": 0,
                "mostViewedOpportunities": [],
                "mostUsedFeatures": [],
                "averageSessionEvents": 0.0,
                "eventCounts": {},
            }

        event_counts = Counter(event.event_type for event in self._events)
        opportunity_counts = Counter(
            event.opportunity_id for event in self._events if event.opportunity_id
        )
        active_users = {event.user_id for event in self._events if event.user_id is not None}
        feature_order = []
        for event in self._events:
            if event.event_type not in feature_order:
                feature_order.append(event.event_type)

        most_viewed_opportunities = [
            {"opportunityId": opportunity_id, "count": count}
            for opportunity_id, count in sorted(
                opportunity_counts.items(), key=lambda item: (-item[1], item[0])
            )[:5]
        ]
        most_used_features = [
            {"eventType": event_type, "count": event_counts[event_type]}
            for event_type in feature_order
            if event_counts[event_type] > 0
        ][:5]
        average_session_events = sum(len(events) for events in self._sessions.values()) / max(1, len(self._events))

        return {
            "dailyActiveUsers": len(active_users),
            "mostViewedOpportunities": most_viewed_opportunities,
            "mostUsedFeatures": most_used_features,
            "averageSessionEvents": round(average_session_events, 2),
            "eventCounts": dict(sorted(event_counts.items())),
        }

    def _sanitize_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        sensitive_keys = {"password", "token", "secret", "authorization", "api_key", "email"}
        sanitized: Dict[str, Any] = {}
        for key, value in metadata.items():
            if str(key).lower() in sensitive_keys:
                continue
            if isinstance(value, dict):
                sanitized[key] = self._sanitize_metadata(value)
            else:
                sanitized[key] = value
        return sanitized
