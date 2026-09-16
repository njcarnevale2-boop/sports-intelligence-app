from __future__ import annotations

import sqlite3

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
    monkeypatch.setattr(snapshot_route, "build_snapshot_id", lambda payload: "snap-complete")
    monkeypatch.setattr(snapshot_route, "snapshot_exists", lambda snapshot_id: False)
    monkeypatch.setattr(snapshot_route, "store_snapshot", lambda payload: "snap-complete")
    monkeypatch.setattr(snapshot_route, "delete_snapshot", lambda snapshot_id: True)
    monkeypatch.setattr(snapshot_route, "record_personal_wager_from_payload", lambda payload, decision_id=None, source_snapshot_id=None: {"wagerId": "wager-1"})
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


def test_snapshot_contract_missing_identity_fails_closed(monkeypatch):
    store_calls = {"count": 0}

    def _store_should_not_run(payload: dict):
        store_calls["count"] += 1
        return "snap-partial"

    monkeypatch.setattr(snapshot_route, "store_snapshot", _store_should_not_run)

    response = client.post("/api/recommendation/snapshot", json={"eventId": "evt-contract-1"})
    assert response.status_code == 200

    body = response.json()
    assert body["success"] is False
    assert body["trackingStatus"] == "FAILED"
    assert body["snapshotRecorded"] is False
    assert body["ledgerRecorded"] is False
    assert body["reason"] == "season, week, and eventId are required"
    assert store_calls["count"] == 0


def test_snapshot_contract_ledger_error_rolls_back_new_snapshot(monkeypatch):
    rollback_calls = {"count": 0}

    monkeypatch.setattr(snapshot_route, "build_snapshot_id", lambda payload: "snap-rollback")
    monkeypatch.setattr(snapshot_route, "snapshot_exists", lambda snapshot_id: False)
    monkeypatch.setattr(snapshot_route, "store_snapshot", lambda payload: "snap-rollback")

    def _delete_snapshot(snapshot_id: str):
        rollback_calls["count"] += 1
        return True

    monkeypatch.setattr(snapshot_route, "delete_snapshot", _delete_snapshot)

    def _raise_validation_error(payload: dict):
        raise ValueError("season, week, and eventId are required")

    monkeypatch.setattr(snapshot_route, "record_my_card_decision_from_payload", _raise_validation_error)

    response = client.post("/api/recommendation/snapshot", json=_base_payload())
    assert response.status_code == 200

    body = response.json()
    assert body["success"] is False
    assert body["trackingStatus"] == "FAILED"
    assert body["snapshotRecorded"] is False
    assert body["ledgerRecorded"] is False
    assert body["reason"] == "season, week, and eventId are required"
    assert rollback_calls["count"] == 1


def test_snapshot_contract_repeat_uses_existing_snapshot_without_rollback(monkeypatch):
    store_calls = {"count": 0}
    rollback_calls = {"count": 0}

    monkeypatch.setattr(snapshot_route, "build_snapshot_id", lambda payload: "snap-existing")
    monkeypatch.setattr(snapshot_route, "snapshot_exists", lambda snapshot_id: True)

    def _store_snapshot(payload: dict):
        store_calls["count"] += 1
        return "snap-existing"

    def _delete_snapshot(snapshot_id: str):
        rollback_calls["count"] += 1
        return True

    monkeypatch.setattr(snapshot_route, "store_snapshot", _store_snapshot)
    monkeypatch.setattr(snapshot_route, "delete_snapshot", _delete_snapshot)
    monkeypatch.setattr(snapshot_route, "record_personal_wager_from_payload", lambda payload, decision_id=None, source_snapshot_id=None: {"wagerId": "wager-existing"})
    monkeypatch.setattr(
        snapshot_route,
        "record_my_card_decision_from_payload",
        lambda payload: {"decisionId": "decision-existing", "decisionVersion": 1, "created": False},
    )

    response = client.post("/api/recommendation/snapshot", json=_base_payload())
    assert response.status_code == 200

    body = response.json()
    assert body["success"] is True
    assert body["trackingStatus"] == "COMPLETE"
    assert body["snapshotId"] == "snap-existing"
    assert store_calls["count"] == 0
    assert rollback_calls["count"] == 0


def test_snapshot_contract_failed_when_snapshot_not_recorded(monkeypatch):
    monkeypatch.setattr(snapshot_route, "build_snapshot_id", lambda payload: "snap-fail-store")
    monkeypatch.setattr(snapshot_route, "snapshot_exists", lambda snapshot_id: False)
    monkeypatch.setattr(snapshot_route, "store_snapshot", lambda payload: None)
    monkeypatch.setattr(snapshot_route, "record_personal_wager_from_payload", lambda payload, decision_id=None, source_snapshot_id=None: {"wagerId": "wager-3"})

    response = client.post("/api/recommendation/snapshot", json=_base_payload())
    assert response.status_code == 200

    body = response.json()
    assert body["success"] is False
    assert body["trackingStatus"] == "FAILED"
    assert body["snapshotRecorded"] is False
    assert body["ledgerRecorded"] is False


def test_snapshot_contract_exact_retry_is_idempotent(monkeypatch, tmp_path):
    import duckdb
    import app.services.decision_ledger as dl
    import app.services.recommendation_snapshot as rs

    ledger_db = tmp_path / "ledger.db"
    snapshot_db = tmp_path / "snapshots.duckdb"
    duckdb.connect(str(snapshot_db)).close()

    monkeypatch.setattr(dl, "_DB_PATH", ledger_db)
    monkeypatch.setattr(rs, "_DB_PATH", snapshot_db)

    def _list_games(week=None):
        if week is None:
            return {"availableWeeks": [1]}
        if int(week) == 1:
            return {
                "games": [
                    {
                        "eventId": "evt-idem-1",
                        "season": 2026,
                        "week": 1,
                    }
                ]
            }
        return {"games": []}

    monkeypatch.setattr(snapshot_route.games_service, "list_games", _list_games)

    payload = {
        "eventId": "evt-idem-1",
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
        "qualificationStatus": "QUALIFIED",
        "qualificationReasons": ["edge", "ev"],
        "siScore": 86.0,
        "siGrade": "A-",
        "siRank": 1,
        "modelProbability": 0.58,
        "calibratedProbability": 0.57,
        "pushProbability": 0.0,
        "lossProbability": 0.43,
        "edge": 0.04,
        "rawEdge": 0.04,
        "calibratedEdge": 0.03,
        "currentEV": 0.06,
        "evPerDollar": 0.06,
        "oddsProvider": "line_movement_board",
        "marketTimestamp": "2026-09-13T15:00:00+00:00",
        "amountRisked": 50.0,
        "unitsRisked": 0.5,
        "unitSizeAtBet": 100.0,
    }

    r1 = client.post("/api/recommendation/snapshot", json=payload)
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["success"] is True
    assert b1["trackingStatus"] == "COMPLETE"

    r2 = client.post("/api/recommendation/snapshot", json=payload)
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["success"] is True
    assert b2["trackingStatus"] == "COMPLETE"

    assert b2["snapshotId"] == b1["snapshotId"]
    assert b2["decisionId"] == b1["decisionId"]
    assert b2["decisionVersion"] == b1["decisionVersion"] == 1
    assert b2["decisionCreated"] is False

    con = sqlite3.connect(str(ledger_db))
    con.row_factory = sqlite3.Row
    decision_rows = con.execute(
        "SELECT decision_id, decision_version, season, week, event_id, publication_type FROM decision_ledger WHERE source_snapshot_id = ?",
        [b1["snapshotId"]],
    ).fetchall()
    wager_rows = con.execute(
        "SELECT wager_id, decision_id FROM personal_wager_ledger WHERE source_snapshot_id = ?",
        [b1["snapshotId"]],
    ).fetchall()
    publications_count = con.execute("SELECT COUNT(*) FROM sia3_publications").fetchone()[0]
    slots_count = con.execute("SELECT COUNT(*) FROM sia3_publication_slots").fetchone()[0]
    con.close()

    dcon = duckdb.connect(str(snapshot_db), read_only=True)
    snapshot_count = dcon.execute(
        "SELECT COUNT(*) FROM recommendation_snapshots WHERE snapshot_id = ?",
        [b1["snapshotId"]],
    ).fetchone()[0]
    dcon.close()

    assert int(snapshot_count) == 1
    assert len(decision_rows) == 1
    assert len(wager_rows) == 1
    assert decision_rows[0]["decision_id"] == b1["decisionId"]
    assert int(decision_rows[0]["decision_version"]) == 1
    assert int(decision_rows[0]["season"]) == 2026
    assert int(decision_rows[0]["week"]) == 1
    assert decision_rows[0]["event_id"] == "evt-idem-1"
    assert decision_rows[0]["publication_type"] == "MY_CARD"
    assert wager_rows[0]["decision_id"] == b1["decisionId"]
    assert int(publications_count) == 0
    assert int(slots_count) == 0


def test_snapshot_contract_material_quote_change_creates_new_decision(monkeypatch, tmp_path):
    import duckdb
    import app.services.decision_ledger as dl
    import app.services.recommendation_snapshot as rs

    ledger_db = tmp_path / "ledger.db"
    snapshot_db = tmp_path / "snapshots.duckdb"
    duckdb.connect(str(snapshot_db)).close()

    monkeypatch.setattr(dl, "_DB_PATH", ledger_db)
    monkeypatch.setattr(rs, "_DB_PATH", snapshot_db)

    def _list_games(week=None):
        if week is None:
            return {"availableWeeks": [1]}
        if int(week) == 1:
            return {
                "games": [
                    {
                        "eventId": "evt-idem-2",
                        "season": 2026,
                        "week": 1,
                    }
                ]
            }
        return {"games": []}

    monkeypatch.setattr(snapshot_route.games_service, "list_games", _list_games)

    base = {
        "eventId": "evt-idem-2",
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
        "qualificationStatus": "QUALIFIED",
        "qualificationReasons": ["edge", "ev"],
        "siScore": 86.0,
        "siGrade": "A-",
        "siRank": 1,
        "modelProbability": 0.58,
        "calibratedProbability": 0.57,
        "pushProbability": 0.0,
        "lossProbability": 0.43,
        "edge": 0.04,
        "rawEdge": 0.04,
        "calibratedEdge": 0.03,
        "currentEV": 0.06,
        "evPerDollar": 0.06,
        "oddsProvider": "line_movement_board",
        "marketTimestamp": "2026-09-13T15:00:00+00:00",
        "amountRisked": 50.0,
        "unitsRisked": 0.5,
        "unitSizeAtBet": 100.0,
    }
    changed = dict(base)
    changed["price"] = -105.0

    r1 = client.post("/api/recommendation/snapshot", json=base)
    r2 = client.post("/api/recommendation/snapshot", json=changed)
    assert r1.status_code == 200 and r2.status_code == 200
    b1 = r1.json()
    b2 = r2.json()
    assert b1["success"] is True and b2["success"] is True
    assert b1["snapshotId"] != b2["snapshotId"]
    assert b1["decisionId"] != b2["decisionId"]
    assert b1["decisionVersion"] == 1
    assert b2["decisionVersion"] == 2

    con = sqlite3.connect(str(ledger_db))
    decisions = con.execute(
        "SELECT decision_id, decision_version FROM decision_ledger WHERE publication_type = 'MY_CARD' AND event_id = 'evt-idem-2' ORDER BY decision_version",
    ).fetchall()
    wagers = con.execute(
        "SELECT wager_id FROM personal_wager_ledger WHERE event_id = 'evt-idem-2'",
    ).fetchall()
    con.close()

    assert len(decisions) == 2
    assert len(wagers) == 2
