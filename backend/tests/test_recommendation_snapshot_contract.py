from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.routes import recommendation_snapshot as snapshot_route


client = TestClient(app)


def _base_payload() -> dict:
    return {
        "season": 2026,
        "week": 1,
        "eventId": "evt-contract-1",
        "commenceTime": "2026-09-13T17:00:00+00:00",
        "awayTeam": "NO",
        "homeTeam": "ATL",
        "selection": "NO +7",
        "market": "spreads",
        "side": "away",
        "point": 7.0,
        "price": -110.0,
        "sportsbook": "DraftKings",
        "recommendation": "BET",
    }


def test_snapshot_contract_complete(monkeypatch):
    monkeypatch.setattr(snapshot_route, "store_snapshot", lambda payload: "snap-complete")
    monkeypatch.setattr(
        snapshot_route,
        "record_my_card_decision_from_payload",
        lambda payload: {"decisionId": "decision-1", "decisionVersion": 1, "created": True},
    )

    response = client.post("/api/recommendation/snapshot", json=_base_payload())
    assert response.status_code == 200

    body = response.json()
    assert body["success"] is True
    assert body["trackingStatus"] == "COMPLETE"
    assert body["snapshotRecorded"] is True
    assert body["ledgerRecorded"] is True
    assert body["snapshotId"] == "snap-complete"
    assert body["decisionId"] == "decision-1"


def test_snapshot_contract_partial_snapshot_preserved(monkeypatch):
    monkeypatch.setattr(snapshot_route, "store_snapshot", lambda payload: "snap-partial")

    def _raise_validation_error(payload: dict):
        raise ValueError("season, week, and eventId are required")

    monkeypatch.setattr(snapshot_route, "record_my_card_decision_from_payload", _raise_validation_error)

    response = client.post("/api/recommendation/snapshot", json={"eventId": "evt-contract-1"})
    assert response.status_code == 200

    body = response.json()
    assert body["success"] is True
    assert body["trackingStatus"] == "PARTIAL"
    assert body["snapshotRecorded"] is True
    assert body["ledgerRecorded"] is False
    assert body["snapshotId"] == "snap-partial"
    assert "Performance tracking could not be fully started" in body["warning"]
    assert body["trackingDetail"] == "season, week, and eventId are required"


def test_snapshot_contract_failed_when_snapshot_not_recorded(monkeypatch):
    monkeypatch.setattr(snapshot_route, "store_snapshot", lambda payload: None)

    response = client.post("/api/recommendation/snapshot", json=_base_payload())
    assert response.status_code == 200

    body = response.json()
    assert body["success"] is False
    assert body["trackingStatus"] == "FAILED"
    assert body["snapshotRecorded"] is False
    assert body["ledgerRecorded"] is False
