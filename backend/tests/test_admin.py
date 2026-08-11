from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_admin_status_endpoint_returns_metrics():
    response = client.get("/api/admin/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["apiHealth"] in {"healthy", "degraded"}
    assert "lastRefresh" in payload
    assert "gamesLoaded" in payload
    assert "opportunitiesLoaded" in payload
    assert "databaseStatus" in payload
    assert "queueStatus" in payload
    assert "errorLog" in payload


def test_admin_refresh_endpoint_returns_summary():
    response = client.post("/api/admin/refresh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "timestamp" in payload
