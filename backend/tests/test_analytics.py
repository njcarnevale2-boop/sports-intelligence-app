from app.services.analytics import AnalyticsService


def test_analytics_summary_aggregates_events_without_sensitive_metadata() -> None:
    service = AnalyticsService()

    service.record_event(
        event_type="OpportunityViewed",
        page="/opportunities/abc",
        opportunity_id="abc",
        user_id=1,
        metadata={"source": "list", "email": "secret@example.com"},
    )
    service.record_event(
        event_type="OpportunityOpened",
        page="/opportunities/abc",
        opportunity_id="abc",
        user_id=1,
        metadata={"source": "card"},
    )
    service.record_event(
        event_type="BriefingViewed",
        page="/briefing",
        opportunity_id=None,
        user_id=2,
        metadata={"source": "hero"},
    )

    summary = service.get_admin_summary()

    assert summary["dailyActiveUsers"] == 2
    assert summary["mostViewedOpportunities"] == [{"opportunityId": "abc", "count": 2}]
    assert summary["mostUsedFeatures"] == [
        {"eventType": "OpportunityViewed", "count": 1},
        {"eventType": "OpportunityOpened", "count": 1},
        {"eventType": "BriefingViewed", "count": 1},
    ]
    assert summary["averageSessionEvents"] == 1.0
    assert summary["eventCounts"]["OpportunityViewed"] == 1
    assert summary["eventCounts"]["OpportunityOpened"] == 1
    assert summary["eventCounts"]["BriefingViewed"] == 1

    stored = service.get_events()
    assert stored[0].metadata["source"] == "list"
    assert "email" not in stored[0].metadata
