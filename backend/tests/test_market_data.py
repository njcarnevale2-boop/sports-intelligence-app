from fastapi.testclient import TestClient

from app.main import app
from app.services.market_data import MarketDataService


client = TestClient(app)


def test_markets_endpoint_returns_transparency_metadata() -> None:
    response = client.get("/api/markets")
    assert response.status_code == 200

    payload = response.json()
    assert "provider" in payload
    assert "lastUpdated" in payload
    assert "dataStatus" in payload
    assert payload["dataStatus"] in {"LIVE", "CACHED", "MOCK", "FILE", "UNAVAILABLE"}


def test_market_event_snapshot_contains_best_lines_and_consensus() -> None:
    all_markets = client.get("/api/markets")
    assert all_markets.status_code == 200
    events = all_markets.json().get("events", [])

    if not events:
        return

    event_id = events[0]["eventId"]
    response = client.get(f"/api/markets/{event_id}")
    assert response.status_code == 200

    snapshot = response.json()
    assert snapshot["eventId"] == event_id
    assert "bestAwaySpread" in snapshot
    assert "bestHomeSpread" in snapshot
    assert "bestAwayMoneyline" in snapshot
    assert "bestHomeMoneyline" in snapshot
    assert "bestOver" in snapshot
    assert "bestUnder" in snapshot
    assert "consensusSpread" in snapshot
    assert "consensusTotal" in snapshot
    assert "consensusMoneyline" in snapshot


def test_line_movement_endpoint_exposes_snapshot_status() -> None:
    response = client.get("/api/line-movement?limit=50")
    assert response.status_code == 200

    payload = response.json()
    assert "provider" in payload
    assert "lastUpdated" in payload
    assert "dataStatus" in payload
    assert "lineHistory" in payload
    assert "closingLineAvailable" in payload["lineHistory"]


def test_best_line_engine_handles_spread_and_totals() -> None:
    service = MarketDataService()
    records = [
        {"market": "spread", "side": "away", "sportsbook": "A", "point": 2.5, "americanOdds": -110, "lastUpdated": "2026-01-01T00:00:00+00:00"},
        {"market": "spread", "side": "away", "sportsbook": "B", "point": 3.0, "americanOdds": -125, "lastUpdated": "2026-01-01T00:00:00+00:00"},
        {"market": "spread", "side": "away", "sportsbook": "C", "point": 3.0, "americanOdds": -105, "lastUpdated": "2026-01-01T00:00:00+00:00"},
        {"market": "total", "side": "over", "sportsbook": "A", "point": 46.5, "americanOdds": -110, "lastUpdated": "2026-01-01T00:00:00+00:00"},
        {"market": "total", "side": "over", "sportsbook": "B", "point": 46.0, "americanOdds": -120, "lastUpdated": "2026-01-01T00:00:00+00:00"},
        {"market": "total", "side": "over", "sportsbook": "C", "point": 46.0, "americanOdds": -105, "lastUpdated": "2026-01-01T00:00:00+00:00"},
    ]

    best_away_spread = service.best_line(records, "spread", "away")
    assert best_away_spread is not None
    assert best_away_spread.sportsbook == "C"

    best_over = service.best_line(records, "total", "over")
    assert best_over is not None
    assert best_over.sportsbook == "C"
