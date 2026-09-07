from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_games_endpoint_returns_complete_slate_with_required_fields() -> None:
    response = client.get("/api/games")
    assert response.status_code == 200

    payload = response.json()
    games = payload["games"]

    assert payload["count"] == len(games)
    assert len(games) >= 200

    required_fields = {
        "eventId",
        "season",
        "week",
        "gameDate",
        "commenceTime",
        "awayTeam",
        "homeTeam",
        "status",
        "betStatus",
        "qualificationStatus",
        "spreadSource",
    }
    assert required_fields.issubset(set(games[0].keys()))


def test_games_endpoint_sorts_chronologically() -> None:
    response = client.get("/api/games")
    assert response.status_code == 200

    games = response.json()["games"]
    kickoff_times = [_parse_iso(item["commenceTime"]) for item in games]

    assert kickoff_times == sorted(kickoff_times)


def test_games_endpoint_filters_by_week() -> None:
    baseline = client.get("/api/games")
    assert baseline.status_code == 200

    weeks = baseline.json()["availableWeeks"]
    assert weeks

    week = weeks[0]
    response = client.get(f"/api/games?week={week}")
    assert response.status_code == 200

    games = response.json()["games"]
    assert games
    assert all(item["week"] == week for item in games)


def test_games_endpoint_filters_by_date() -> None:
    baseline = client.get("/api/games")
    assert baseline.status_code == 200

    dates = baseline.json()["availableDates"]
    assert dates

    date = dates[0]
    response = client.get(f"/api/games?date={date}")
    assert response.status_code == 200

    games = response.json()["games"]
    assert games
    assert all(item["gameDate"] == date for item in games)


def test_games_include_games_without_opportunity_enrichment() -> None:
    response = client.get("/api/games")
    assert response.status_code == 200

    games = response.json()["games"]
    assert any(item.get("bestOpportunity") is None for item in games)
    assert any(item.get("sportsIntelligenceScore") is None for item in games)


def test_game_social_intelligence_endpoint_returns_mock_safe_payload() -> None:
    baseline = client.get("/api/games")
    assert baseline.status_code == 200

    event_id = baseline.json()["games"][0]["eventId"]
    response = client.get(f"/api/games/{event_id}/social-intelligence")
    assert response.status_code == 200

    payload = response.json()
    assert payload["provider"] == "MOCK"
    assert payload["isLive"] is False
    assert "keySignals" in payload


def test_game_opportunity_endpoint_always_returns_intelligence_report() -> None:
    games_response = client.get("/api/games")
    assert games_response.status_code == 200

    event_id = games_response.json()["games"][0]["eventId"]
    response = client.get(f"/api/games/{event_id}/opportunity")
    assert response.status_code == 200

    payload = response.json()
    assert payload["eventId"] == event_id
    assert "intelligenceReport" in payload
    assert "opportunity" in payload

    opportunity = payload["opportunity"]
    if opportunity is not None:
        assert "fairPrice" in opportunity
        assert "fairLine" in opportunity
        assert "truePlayableTo" in opportunity
        assert "truePlayableToStatus" in opportunity
        assert "truePlayableToReason" in opportunity
        assert "worstObservedPlayablePrice" in opportunity
        assert "worstObservedPlayablePriceStatus" in opportunity
        assert "worstObservedPlayablePriceReason" in opportunity
        assert "playableTo" in opportunity
        assert "playableToStatus" in opportunity
        assert "playableToReason" in opportunity
        assert "currentWinProbability" in opportunity
        assert "currentPushProbability" in opportunity
        assert "currentLossProbability" in opportunity
        assert "currentEV" in opportunity
        assert "minimumPlayableEV" in opportunity
        assert "bestAvailablePrice" in opportunity
        assert "bestAvailableLine" in opportunity
        assert opportunity["playableToStatus"] in {"AVAILABLE", "UNAVAILABLE"}
        assert opportunity["truePlayableToStatus"] in {"AVAILABLE", "UNAVAILABLE"}
        assert opportunity.get("playableTo") == opportunity.get("worstObservedPlayablePrice")
        if opportunity.get("currentWinProbability") is not None:
            total_prob = (
                float(opportunity.get("currentWinProbability") or 0)
                + float(opportunity.get("currentPushProbability") or 0)
                + float(opportunity.get("currentLossProbability") or 0)
            )
            assert abs(total_prob - 1.0) < 1e-6

    report = payload["intelligenceReport"]
    assert report["betStatus"] in {"STRONG BET", "QUALIFIED", "LEAN", "NO QUALIFIED BET", "INSUFFICIENT DATA"}
    assert "qualificationStatus" in report
    assert isinstance(report.get("qualificationReasons", []), list)
    assert report.get("betTrigger", {}).get("available") is False
    assert report.get("betTrigger", {}).get("message") == "Actionable price not currently available"


def test_game_opportunity_lifecycle_contract_is_exposed_read_only() -> None:
    games_response = client.get("/api/games")
    assert games_response.status_code == 200

    event_id = games_response.json()["games"][0]["eventId"]
    response = client.get(f"/api/games/{event_id}/opportunity")
    assert response.status_code == 200

    payload = response.json()
    assert "lifecycle" in payload
    lifecycle = payload["lifecycle"]
    assert lifecycle["eventId"] == event_id
    assert lifecycle["lifecycleState"] in {"WATCH", "QUALIFIED", "NO_LONGER_QUALIFIED", "SUPERSEDED"}
    assert "summary" in lifecycle
    assert "comparison" in lifecycle
    compare = lifecycle["comparison"]
    assert "qualificationChanged" in compare
    assert "productionEligibilityChanged" in compare
    assert "lineChanged" in compare
    assert "priceChanged" in compare
    assert compare["qualificationChanged"] is False
    assert compare["productionEligibilityChanged"] is False
    assert compare["lineChanged"] is False
    assert compare["priceChanged"] is False
    assert lifecycle["previousSnapshotAvailable"] is False

    lifecycle_response = client.get(f"/api/games/{event_id}/opportunity/lifecycle")
    assert lifecycle_response.status_code == 200
    assert lifecycle_response.json()["eventId"] == event_id
    assert lifecycle_response.json()["lifecycleState"] == lifecycle["lifecycleState"]


def test_lifecycle_missing_history_is_explicitly_unavailable() -> None:
    from app.routes.opportunities import _build_opportunity_lifecycle

    current = {
        "market": "spread",
        "qualificationStatus": "QUALIFIED",
        "recommendation": "STRONG BET",
        "productionEligible": True,
        "point": 2.5,
        "price": -110,
    }

    lifecycle = _build_opportunity_lifecycle("evt-test", current)
    assert lifecycle["previousSnapshotAvailable"] is False
    assert lifecycle["comparison"]["qualificationChanged"] is False
    assert lifecycle["comparison"]["lineChanged"] is False
    assert lifecycle["comparison"]["priceChanged"] is False
    assert lifecycle["lifecycleState"] == "QUALIFIED"


def test_lifecycle_represented_when_qualified_history_disappears() -> None:
    from app.routes.opportunities import _build_opportunity_lifecycle

    previous = {
        "market": "spread",
        "qualificationStatus": "QUALIFIED",
        "recommendation": "STRONG BET",
        "productionEligible": True,
        "point": 2.5,
        "price": -110,
    }

    lifecycle = _build_opportunity_lifecycle("evt-test", None, previous)
    assert lifecycle["previousSnapshotAvailable"] is True
    assert lifecycle["lifecycleState"] == "NO_LONGER_QUALIFIED"
    assert lifecycle["comparison"]["qualificationChanged"] is True
