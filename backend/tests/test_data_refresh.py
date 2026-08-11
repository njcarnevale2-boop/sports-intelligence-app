from fastapi.testclient import TestClient

from app.main import app
from app.services.data_refresh import refresh_all_data


client = TestClient(app)


def test_refresh_all_data_returns_expected_summary():
    result = refresh_all_data()

    assert result["success"] is True
    assert "duration" in result
    assert result["gamesUpdated"] >= 0
    assert result["opportunitiesUpdated"] >= 0
    assert "timestamp" in result


def test_admin_refresh_endpoint_returns_summary():
    response = client.post("/api/admin/refresh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["gamesUpdated"] >= 0
    assert payload["opportunitiesUpdated"] >= 0
    assert "timestamp" in payload
