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
