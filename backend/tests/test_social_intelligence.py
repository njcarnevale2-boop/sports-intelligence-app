from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.services.social_intelligence import SocialIntelligenceService


client = TestClient(app)


def _fixed_now() -> datetime:
    return datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc)


def _registry() -> list[dict]:
    return [
        {"team": "BUF", "name": "Mock BUF Beat", "handle": "buf_beat", "sourceType": "TEAM_BEAT", "credibilityScore": 76, "priority": 1, "active": True},
        {"team": "BUF", "name": "Mock BUF National", "handle": "buf_nat", "sourceType": "NATIONAL_REPORTER", "credibilityScore": 84, "priority": 2, "active": True},
        {"team": "BUF", "name": "Mock BUF Official", "handle": "buf_off", "sourceType": "TEAM_OFFICIAL", "credibilityScore": 96, "priority": 0, "active": True},
        {"team": "MIA", "name": "Mock MIA Official", "handle": "mia_off", "sourceType": "TEAM_OFFICIAL", "credibilityScore": 95, "priority": 0, "active": True},
        {"team": "KC", "name": "Mock KC Beat", "handle": "kc_beat", "sourceType": "TEAM_BEAT", "credibilityScore": 74, "priority": 1, "active": True},
        {"team": "KC", "name": "Mock KC Official", "handle": "kc_off", "sourceType": "TEAM_OFFICIAL", "credibilityScore": 95, "priority": 0, "active": True},
    ]


def _event_lookup() -> dict[str, dict]:
    return {
        "evt-buf-mia": {"eventId": "evt-buf-mia", "awayTeam": "BUF", "homeTeam": "MIA", "commenceTime": "2026-09-10T20:15:00+00:00"},
        "evt-kc-dal": {"eventId": "evt-kc-dal", "awayTeam": "KC", "homeTeam": "DAL", "commenceTime": "2026-09-11T00:20:00+00:00"},
    }


def _service(mock_templates: list[dict]) -> SocialIntelligenceService:
    return SocialIntelligenceService(
        registry=_registry(),
        mock_templates=mock_templates,
        event_lookup=_event_lookup(),
        persist_history=False,
        now_provider=_fixed_now,
    )


def test_single_source_report() -> None:
    service = _service(
        [
            {
                "team": "BUF",
                "player": "Mock WR",
                "position": "WR",
                "category": "PRACTICE_STATUS",
                "severity": "MODERATE",
                "sourceHandle": "buf_beat",
                "textSummary": "Mock example: receiver was limited.",
                "status": "REPORTED",
                "hoursAgo": 2,
                "estimatedPointImpact": 0.3,
                "marketRelevance": "MEDIUM",
                "gameImpact": -0.2,
            }
        ]
    )

    signals = service.ingest_mock_signals(force=True)
    assert len(signals) == 1
    assert signals[0]["status"] == "REPORTED"
    assert signals[0]["corroborationCount"] == 0
    assert 45 <= signals[0]["confidence"] <= 80


def test_multi_source_corroboration() -> None:
    service = _service(
        [
            {
                "team": "BUF",
                "player": "Mock WR",
                "position": "WR",
                "category": "PRACTICE_STATUS",
                "severity": "MODERATE",
                "sourceHandle": "buf_beat",
                "textSummary": "Mock example: receiver was limited.",
                "status": "REPORTED",
                "hoursAgo": 2,
                "estimatedPointImpact": 0.3,
                "marketRelevance": "MEDIUM",
                "gameImpact": -0.2,
                "groupKey": "BUF:WR:PRACTICE_STATUS",
            },
            {
                "team": "BUF",
                "player": "Mock WR",
                "position": "WR",
                "category": "PRACTICE_STATUS",
                "severity": "MODERATE",
                "sourceHandle": "buf_nat",
                "textSummary": "Mock example: second source confirmed the limited tag.",
                "status": "REPORTED",
                "hoursAgo": 1,
                "estimatedPointImpact": 0.3,
                "marketRelevance": "MEDIUM",
                "gameImpact": -0.1,
                "groupKey": "BUF:WR:PRACTICE_STATUS",
            },
        ]
    )

    signal = service.ingest_mock_signals(force=True)[0]
    assert signal["status"] == "CORROBORATED"
    assert signal["corroborationCount"] == 1
    assert signal["confidence"] >= 70


def test_official_confirmation() -> None:
    service = _service(
        [
            {
                "team": "MIA",
                "player": "Mock LT",
                "position": "LT",
                "category": "OFFENSIVE_LINE_CHANGE",
                "severity": "LOW",
                "sourceHandle": "mia_off",
                "textSummary": "Mock example: official lineup note.",
                "status": "OFFICIAL",
                "hoursAgo": 1,
                "estimatedPointImpact": 0.2,
                "marketRelevance": "MEDIUM",
                "gameImpact": 0.1,
            }
        ]
    )

    signal = service.ingest_mock_signals(force=True)[0]
    assert signal["status"] == "OFFICIAL"
    assert signal["confidence"] >= 85


def test_rumor_signal() -> None:
    service = _service(
        [
            {
                "team": "KC",
                "player": "Mock RB",
                "position": "RB",
                "category": "SNAP_RESTRICTION",
                "severity": "LOW",
                "sourceHandle": "kc_beat",
                "textSummary": "Mock example: workload rumor.",
                "status": "RUMOR",
                "hoursAgo": 3,
                "estimatedPointImpact": 0.1,
                "marketRelevance": "LOW",
                "gameImpact": -0.1,
            }
        ]
    )

    signal = service.ingest_mock_signals(force=True)[0]
    assert signal["status"] == "RUMOR"
    assert signal["confidence"] < 60


def test_dismissed_signal() -> None:
    service = _service(
        [
            {
                "team": "KC",
                "player": "Mock RB",
                "position": "RB",
                "category": "SNAP_RESTRICTION",
                "severity": "LOW",
                "sourceHandle": "kc_beat",
                "textSummary": "Mock example: workload rumor.",
                "status": "RUMOR",
                "hoursAgo": 4,
                "estimatedPointImpact": 0.1,
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
                "sourceHandle": "kc_off",
                "textSummary": "Mock example: official dismissal.",
                "status": "DISMISSED",
                "hoursAgo": 1,
                "estimatedPointImpact": 0.0,
                "marketRelevance": "LOW",
                "gameImpact": 0.0,
                "groupKey": "KC:RB:SNAP_RESTRICTION",
            },
        ]
    )

    signal = service.ingest_mock_signals(force=True)[0]
    assert signal["status"] == "DISMISSED"
    assert signal["confidence"] < 70


def test_missing_player_is_supported() -> None:
    service = _service(
        [
            {
                "team": "BUF",
                "player": None,
                "position": None,
                "category": "TRAVEL",
                "severity": "LOW",
                "sourceHandle": "buf_nat",
                "textSummary": "Mock example: travel note.",
                "status": "REPORTED",
                "hoursAgo": 5,
                "estimatedPointImpact": 0.05,
                "marketRelevance": "LOW",
                "gameImpact": -0.05,
            }
        ]
    )

    signal = service.ingest_mock_signals(force=True)[0]
    assert signal["player"] is None
    assert signal["category"] == "TRAVEL"


def test_team_aggregation() -> None:
    service = _service(
        [
            {
                "team": "BUF",
                "player": "Mock WR",
                "position": "WR",
                "category": "PRACTICE_STATUS",
                "severity": "MODERATE",
                "sourceHandle": "buf_beat",
                "textSummary": "Mock example: limited receiver.",
                "status": "REPORTED",
                "hoursAgo": 2,
                "estimatedPointImpact": 0.3,
                "marketRelevance": "MEDIUM",
                "gameImpact": -0.2,
                "groupKey": "BUF:WR:PRACTICE_STATUS",
            },
            {
                "team": "BUF",
                "player": "Mock WR",
                "position": "WR",
                "category": "PRACTICE_STATUS",
                "severity": "MODERATE",
                "sourceHandle": "buf_nat",
                "textSummary": "Mock example: corroborated limited receiver.",
                "status": "REPORTED",
                "hoursAgo": 1,
                "estimatedPointImpact": 0.3,
                "marketRelevance": "MEDIUM",
                "gameImpact": -0.1,
                "groupKey": "BUF:WR:PRACTICE_STATUS",
            },
        ]
    )

    team_context = service.team_social_intelligence("BUF", event_id="evt-buf-mia")
    assert team_context["socialScore"] != 50.0
    assert len(team_context["injurySignals"]) == 1
    assert len(team_context["verifiedSignals"]) == 1
    assert "BUF" in team_context["summary"]


def test_game_aggregation() -> None:
    service = _service(
        [
            {
                "team": "BUF",
                "player": "Mock WR",
                "position": "WR",
                "category": "PRACTICE_STATUS",
                "severity": "MODERATE",
                "sourceHandle": "buf_nat",
                "textSummary": "Mock example: away-team concern.",
                "status": "REPORTED",
                "hoursAgo": 2,
                "estimatedPointImpact": 0.3,
                "marketRelevance": "MEDIUM",
                "gameImpact": -0.2,
            },
            {
                "team": "MIA",
                "player": "Mock LT",
                "position": "LT",
                "category": "OFFENSIVE_LINE_CHANGE",
                "severity": "LOW",
                "sourceHandle": "mia_off",
                "textSummary": "Mock example: home-team official note.",
                "status": "OFFICIAL",
                "hoursAgo": 1,
                "estimatedPointImpact": 0.2,
                "marketRelevance": "MEDIUM",
                "gameImpact": 0.15,
            },
        ]
    )

    game_context = service.get_game_social_context("evt-buf-mia")
    assert game_context["available"] is True
    assert game_context["awayTeam"] == "BUF"
    assert game_context["homeTeam"] == "MIA"
    assert len(game_context["keySignals"]) == 2
    assert isinstance(game_context["netSocialAdvantage"], float)


def test_mock_provider_labeling() -> None:
    service = _service([])
    metadata = service.metadata()
    assert metadata["provider"] == "MOCK"
    assert metadata["isLive"] is False
    game_context = service.get_game_social_context("evt-buf-mia")
    assert game_context["provider"] == "MOCK"
    assert game_context["dataStatus"] == "MOCK"


def test_social_api_endpoint_returns_mock_payload() -> None:
    games_response = client.get("/api/games")
    assert games_response.status_code == 200
    event_id = games_response.json()["games"][0]["eventId"]

    response = client.get(f"/api/games/{event_id}/social-intelligence")
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "MOCK"
    assert payload["isLive"] is False
    assert "keySignals" in payload