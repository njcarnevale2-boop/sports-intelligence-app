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


def _provenance_payload() -> dict:
    return {
        "modelTimestamp": "2026-09-13T14:58:00+00:00",
        "modelVersion": "sia_model_v2026_preseason",
        "probabilityEngineVersion": "empirical_residual_engine_v2026_preseason",
        "calibrationVersion": "guarded_isotonic_v2026_preseason",
        "rankingVersion": "ranking_calibrated_edge_v2026",
        "qualificationPolicyVersion": "qualification_explicit_policy_v2026",
    }


def _actionable_payload(event_id: str = "evt-actionable-1") -> dict:
    return {
        "season": 2026,
        "week": 1,
        "eventId": event_id,
        "commenceTime": "2026-09-13T17:00:00+00:00",
        "awayTeam": "NO",
        "homeTeam": "ATL",
        "selection": "NO +7",
        "market": "spread",
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
        "rawModelProbability": 0.58,
        "calibratedProbability": 0.57,
        "pushProbability": 0.0,
        "lossProbability": 0.43,
        "impliedProbability": 0.5238,
        "marketNoVigProbability": 0.519,
        "edge": 0.04,
        "rawEdge": 0.04,
        "calibratedEdge": 0.03,
        "currentEV": 0.06,
        "evPerDollar": 0.06,
        "oddsProvider": "line_movement_board",
        "quoteTimestamp": "2026-09-13T14:59:00+00:00",
        "marketTimestamp": "2026-09-13T15:00:00+00:00",
        "amountRisked": 50.0,
        "unitsRisked": 0.5,
        "unitSizeAtBet": 100.0,
        "fullKellyFraction": 0.024,
        "fractionalKellyFraction": 0.0048,
        "bankrollPercent": 0.48,
        "recommendedAmount": 4.8,
        "recommendedUnits": 0.05,
        "bankrollBasis": 1000.0,
        "currentExecution": {
            "status": "AVAILABLE",
            "sportsbook": "DraftKings",
            "point": 7.0,
            "price": -110.0,
            "quoteTimestamp": "2026-09-13T14:59:00+00:00",
            "currentMarketTimestamp": "2026-09-13T15:00:00+00:00",
        },
        "currentQualification": {"status": "QUALIFIED", "actionable": True},
        "currentSizing": {
            "status": "AVAILABLE",
            "fullKellyFraction": 0.024,
            "fractionalKellyFraction": 0.0048,
            "bankrollPercent": 0.48,
            "recommendedAmount": 4.8,
            "recommendedUnits": 0.05,
            "unitSize": 100.0,
            "bankrollBasis": 1000.0,
        },
        **_provenance_payload(),
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


def test_snapshot_contract_missing_actionable_provenance_fails_closed(monkeypatch, tmp_path):
    import duckdb
    import app.services.decision_ledger as dl
    import app.services.recommendation_snapshot as rs

    ledger_db = tmp_path / "ledger-missing-provenance.db"
    snapshot_db = tmp_path / "snapshots-missing-provenance.duckdb"
    duckdb.connect(str(snapshot_db)).close()
    monkeypatch.setattr(dl, "_DB_PATH", ledger_db)
    monkeypatch.setattr(rs, "_DB_PATH", snapshot_db)

    rollback_calls = {"count": 0}

    monkeypatch.setattr(snapshot_route, "build_snapshot_id", lambda payload: "snap-missing-provenance")
    monkeypatch.setattr(snapshot_route, "snapshot_exists", lambda snapshot_id: False)
    monkeypatch.setattr(snapshot_route, "store_snapshot", lambda payload: "snap-missing-provenance")
    monkeypatch.setattr(snapshot_route, "record_personal_wager_from_payload", lambda payload, decision_id=None, source_snapshot_id=None: {"wagerId": "wager-should-not-exist"})

    def _delete_snapshot(snapshot_id: str):
        rollback_calls["count"] += 1
        return True

    monkeypatch.setattr(snapshot_route, "delete_snapshot", _delete_snapshot)

    payload = _actionable_payload("evt-missing-provenance")
    payload.pop("modelVersion")
    response = client.post("/api/recommendation/snapshot", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["trackingStatus"] == "FAILED"
    assert body["snapshotRecorded"] is False
    assert body["ledgerRecorded"] is False
    assert "Missing required actionable evidence" in body["reason"]
    assert rollback_calls["count"] == 0


def test_snapshot_contract_missing_actionable_provenance_keeps_existing_snapshot(monkeypatch, tmp_path):
    import duckdb
    import app.services.decision_ledger as dl
    import app.services.recommendation_snapshot as rs

    ledger_db = tmp_path / "ledger-existing-missing-provenance.db"
    snapshot_db = tmp_path / "snapshots-existing-missing-provenance.duckdb"
    duckdb.connect(str(snapshot_db)).close()
    monkeypatch.setattr(dl, "_DB_PATH", ledger_db)
    monkeypatch.setattr(rs, "_DB_PATH", snapshot_db)

    rollback_calls = {"count": 0}
    store_calls = {"count": 0}

    monkeypatch.setattr(snapshot_route, "build_snapshot_id", lambda payload: "snap-existing-missing-provenance")
    monkeypatch.setattr(snapshot_route, "snapshot_exists", lambda snapshot_id: True)

    def _store_snapshot(payload: dict):
        store_calls["count"] += 1
        return "snap-existing-missing-provenance"

    monkeypatch.setattr(snapshot_route, "store_snapshot", _store_snapshot)

    def _delete_snapshot(snapshot_id: str):
        rollback_calls["count"] += 1
        return True

    monkeypatch.setattr(snapshot_route, "delete_snapshot", _delete_snapshot)

    payload = _actionable_payload("evt-existing-missing-provenance")
    payload.pop("modelVersion")
    response = client.post("/api/recommendation/snapshot", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["trackingStatus"] == "FAILED"
    assert "Missing required actionable evidence" in body["reason"]
    assert store_calls["count"] == 0
    assert rollback_calls["count"] == 0


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

    payload = _actionable_payload("evt-idem-1")

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
    decision_row = con.execute(
        "SELECT model_version, probability_engine_version, calibration_version, ranking_version, qualification_policy_version, model_timestamp, market_timestamp, published_at_utc FROM decision_ledger WHERE decision_id = ?",
        [b1["decisionId"]],
    ).fetchone()
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
    assert decision_row["model_version"] == payload["modelVersion"]
    assert decision_row["probability_engine_version"] == payload["probabilityEngineVersion"]
    assert decision_row["calibration_version"] == payload["calibrationVersion"]
    assert decision_row["ranking_version"] == payload["rankingVersion"]
    assert decision_row["qualification_policy_version"] == payload["qualificationPolicyVersion"]
    assert decision_row["model_timestamp"] == payload["modelTimestamp"]
    assert decision_row["market_timestamp"] == payload["marketTimestamp"]

    dcon = duckdb.connect(str(snapshot_db), read_only=True)
    snapshot_row = dcon.execute(
        "SELECT model_version, probability_engine_version, calibration_version, ranking_version, qualification_policy_version, model_timestamp, raw_model_probability, calibrated_probability, push_probability, loss_probability, implied_probability, market_no_vig_probability, raw_edge, calibrated_edge, full_kelly_fraction, fractional_kelly_fraction, bankroll_percent, recommended_amount, recommended_units, unit_size_at_bet, bankroll_basis, quote_timestamp, market_timestamp, decision_id FROM recommendation_snapshots WHERE snapshot_id = ?",
        [b1["snapshotId"]],
    ).fetchone()
    dcon.close()
    assert snapshot_row[0] == payload["modelVersion"]
    assert snapshot_row[1] == payload["probabilityEngineVersion"]
    assert snapshot_row[2] == payload["calibrationVersion"]
    assert snapshot_row[3] == payload["rankingVersion"]
    assert snapshot_row[4] == payload["qualificationPolicyVersion"]
    assert str(snapshot_row[5]).startswith("2026-09-13 14:58:00")
    assert float(snapshot_row[6]) == payload["rawModelProbability"]
    assert float(snapshot_row[7]) == payload["calibratedProbability"]
    assert float(snapshot_row[8]) == payload["pushProbability"]
    assert float(snapshot_row[9]) == payload["lossProbability"]
    assert float(snapshot_row[10]) == payload["impliedProbability"]
    assert float(snapshot_row[11]) == payload["marketNoVigProbability"]
    assert float(snapshot_row[12]) == payload["rawEdge"]
    assert float(snapshot_row[13]) == payload["calibratedEdge"]
    assert float(snapshot_row[14]) == payload["fullKellyFraction"]
    assert float(snapshot_row[15]) == payload["fractionalKellyFraction"]
    assert float(snapshot_row[16]) == payload["bankrollPercent"]
    assert float(snapshot_row[17]) == payload["recommendedAmount"]
    assert float(snapshot_row[18]) == payload["recommendedUnits"]
    assert float(snapshot_row[19]) == payload["unitSizeAtBet"]
    assert float(snapshot_row[20]) == payload["bankrollBasis"]
    assert str(snapshot_row[21]).startswith("2026-09-13 14:59:00")
    assert str(snapshot_row[22]).startswith("2026-09-13 15:00:00")
    assert snapshot_row[23] == b1["decisionId"]


def test_snapshot_schema_preserves_null_provenance_for_rows_without_values(monkeypatch, tmp_path):
    import duckdb
    import app.services.recommendation_snapshot as rs

    snapshot_db = tmp_path / "snapshots-null-provenance.duckdb"
    duckdb.connect(str(snapshot_db)).close()
    monkeypatch.setattr(rs, "_DB_PATH", snapshot_db)

    snapshot_id = rs.store_snapshot(
        {
            "season": 2026,
            "week": 1,
            "eventId": "evt-null-snapshot-provenance",
            "commenceTime": "2026-09-13T17:00:00+00:00",
            "market": "spreads",
            "side": "away",
            "point": 7.0,
            "price": -110.0,
            "sportsbook": "DraftKings",
            "selection": "NO +7",
            "modelProbability": 0.58,
            "edge": 0.04,
            "evPerDollar": 0.06,
        }
    )
    assert snapshot_id

    con = duckdb.connect(str(snapshot_db), read_only=True)
    row = con.execute(
        "SELECT model_version, probability_engine_version, calibration_version, ranking_version, qualification_policy_version, model_timestamp, quote_timestamp, market_timestamp, raw_model_probability, calibrated_probability, push_probability, loss_probability, implied_probability, market_no_vig_probability, raw_edge, calibrated_edge, full_kelly_fraction, fractional_kelly_fraction, bankroll_percent, recommended_amount, recommended_units, unit_size_at_bet, bankroll_basis, decision_id FROM recommendation_snapshots WHERE snapshot_id = ?",
        [snapshot_id],
    ).fetchone()
    con.close()

    assert row[0] is None
    assert row[1] is None
    assert row[2] is None
    assert row[3] is None
    assert row[4] is None
    assert row[5] is None
    assert row[6] is None
    assert row[7] is None
    assert row[8] is None
    assert row[9] is None
    assert row[10] is None
    assert row[11] is None
    assert row[12] is None
    assert row[13] is None
    assert row[14] is None
    assert row[15] is None
    assert row[16] is None
    assert row[17] is None
    assert row[18] is None
    assert row[19] is None
    assert row[20] is None
    assert row[21] is None
    assert row[22] is None
    assert row[23] is None


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

    base = _actionable_payload("evt-idem-2")
    changed = dict(base)
    changed["price"] = -105.0
    changed["currentExecution"] = dict(base["currentExecution"])
    changed["currentExecution"]["price"] = -105.0

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


def test_snapshot_identity_changes_on_model_probability_change(monkeypatch, tmp_path):
    import duckdb
    import app.services.decision_ledger as dl
    import app.services.recommendation_snapshot as rs

    ledger_db = tmp_path / "ledger-modelprob.db"
    snapshot_db = tmp_path / "snapshots-modelprob.duckdb"
    duckdb.connect(str(snapshot_db)).close()

    monkeypatch.setattr(dl, "_DB_PATH", ledger_db)
    monkeypatch.setattr(rs, "_DB_PATH", snapshot_db)

    def _list_games(week=None):
        if week is None:
            return {"availableWeeks": [1]}
        return {"games": [{"eventId": "evt-modelprob", "season": 2026, "week": 1}]}

    monkeypatch.setattr(snapshot_route.games_service, "list_games", _list_games)

    base = _actionable_payload("evt-modelprob")
    changed = dict(base)
    changed["rawModelProbability"] = 0.61
    changed["modelProbability"] = 0.61

    r1 = client.post("/api/recommendation/snapshot", json=base).json()
    r2 = client.post("/api/recommendation/snapshot", json=changed).json()
    assert r1["success"] is True and r2["success"] is True
    assert r1["snapshotId"] != r2["snapshotId"]


def test_snapshot_identity_changes_on_ev_change(monkeypatch, tmp_path):
    import duckdb
    import app.services.decision_ledger as dl
    import app.services.recommendation_snapshot as rs

    ledger_db = tmp_path / "ledger-ev.db"
    snapshot_db = tmp_path / "snapshots-ev.duckdb"
    duckdb.connect(str(snapshot_db)).close()

    monkeypatch.setattr(dl, "_DB_PATH", ledger_db)
    monkeypatch.setattr(rs, "_DB_PATH", snapshot_db)

    def _list_games(week=None):
        if week is None:
            return {"availableWeeks": [1]}
        return {"games": [{"eventId": "evt-ev", "season": 2026, "week": 1}]}

    monkeypatch.setattr(snapshot_route.games_service, "list_games", _list_games)

    base = _actionable_payload("evt-ev")
    changed = dict(base)
    changed["evPerDollar"] = 0.08
    changed["currentEV"] = 0.08

    r1 = client.post("/api/recommendation/snapshot", json=base).json()
    r2 = client.post("/api/recommendation/snapshot", json=changed).json()
    assert r1["success"] is True and r2["success"] is True
    assert r1["snapshotId"] != r2["snapshotId"]


def test_snapshot_identity_changes_on_sizing_change(monkeypatch, tmp_path):
    import duckdb
    import app.services.decision_ledger as dl
    import app.services.recommendation_snapshot as rs

    ledger_db = tmp_path / "ledger-sizing.db"
    snapshot_db = tmp_path / "snapshots-sizing.duckdb"
    duckdb.connect(str(snapshot_db)).close()

    monkeypatch.setattr(dl, "_DB_PATH", ledger_db)
    monkeypatch.setattr(rs, "_DB_PATH", snapshot_db)

    def _list_games(week=None):
        if week is None:
            return {"availableWeeks": [1]}
        return {"games": [{"eventId": "evt-sizing", "season": 2026, "week": 1}]}

    monkeypatch.setattr(snapshot_route.games_service, "list_games", _list_games)

    base = _actionable_payload("evt-sizing")
    changed = dict(base)
    changed["recommendedUnits"] = 0.09
    changed["currentSizing"] = dict(base["currentSizing"])
    changed["currentSizing"]["recommendedUnits"] = 0.09

    r1 = client.post("/api/recommendation/snapshot", json=base).json()
    r2 = client.post("/api/recommendation/snapshot", json=changed).json()
    assert r1["success"] is True and r2["success"] is True
    assert r1["snapshotId"] != r2["snapshotId"]


def test_snapshot_identity_changes_on_provenance_change(monkeypatch, tmp_path):
    import duckdb
    import app.services.decision_ledger as dl
    import app.services.recommendation_snapshot as rs

    ledger_db = tmp_path / "ledger-provenance.db"
    snapshot_db = tmp_path / "snapshots-provenance.duckdb"
    duckdb.connect(str(snapshot_db)).close()

    monkeypatch.setattr(dl, "_DB_PATH", ledger_db)
    monkeypatch.setattr(rs, "_DB_PATH", snapshot_db)

    def _list_games(week=None):
        if week is None:
            return {"availableWeeks": [1]}
        return {"games": [{"eventId": "evt-provenance", "season": 2026, "week": 1}]}

    monkeypatch.setattr(snapshot_route.games_service, "list_games", _list_games)

    base = _actionable_payload("evt-provenance")
    changed = dict(base)
    changed["modelVersion"] = "sia_model_v2026_postseason"

    r1 = client.post("/api/recommendation/snapshot", json=base).json()
    r2 = client.post("/api/recommendation/snapshot", json=changed).json()
    assert r1["success"] is True and r2["success"] is True
    assert r1["snapshotId"] != r2["snapshotId"]


def test_snapshot_identity_ignores_recommended_at_request_time(monkeypatch, tmp_path):
    import app.services.recommendation_snapshot as rs

    snapshot_db = tmp_path / "snapshots-seed.duckdb"
    monkeypatch.setattr(rs, "_DB_PATH", snapshot_db)

    p1 = _actionable_payload("evt-seed")
    p2 = dict(p1)
    p2["requestTime"] = "2026-09-16T13:09:00+00:00"
    p2["recommendedAt"] = "2026-09-16T13:09:01+00:00"

    assert rs.build_snapshot_id(p1) == rs.build_snapshot_id(p2)


def test_backlink_failure_after_canonical_success_is_non_fatal(monkeypatch, tmp_path):
    import duckdb
    import app.services.decision_ledger as dl
    import app.services.recommendation_snapshot as rs

    ledger_db = tmp_path / "ledger-backlink-failure.db"
    snapshot_db = tmp_path / "snapshots-backlink-failure.duckdb"
    duckdb.connect(str(snapshot_db)).close()

    monkeypatch.setattr(dl, "_DB_PATH", ledger_db)
    monkeypatch.setattr(rs, "_DB_PATH", snapshot_db)

    def _list_games(week=None):
        if week is None:
            return {"availableWeeks": [1]}
        return {"games": [{"eventId": "evt-backlink-failure", "season": 2026, "week": 1}]}

    monkeypatch.setattr(snapshot_route.games_service, "list_games", _list_games)

    def _raise_link_error(snapshot_id: str, decision_id: str):
        raise RuntimeError("duckdb write unavailable")

    monkeypatch.setattr(snapshot_route, "link_snapshot_decision", _raise_link_error)

    payload = _actionable_payload("evt-backlink-failure")
    response = client.post("/api/recommendation/snapshot", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["trackingStatus"] == "COMPLETE"
    assert "warning" in body

    con = sqlite3.connect(str(ledger_db))
    decision_count = con.execute("SELECT COUNT(*) FROM decision_ledger WHERE publication_type = 'MY_CARD'").fetchone()[0]
    wager_count = con.execute("SELECT COUNT(*) FROM personal_wager_ledger").fetchone()[0]
    linked_count = con.execute(
        "SELECT COUNT(*) FROM decision_ledger WHERE source_snapshot_id = ?",
        [body["snapshotId"]],
    ).fetchone()[0]
    con.close()

    dcon = duckdb.connect(str(snapshot_db), read_only=True)
    snapshot_count = dcon.execute(
        "SELECT COUNT(*) FROM recommendation_snapshots WHERE snapshot_id = ?",
        [body["snapshotId"]],
    ).fetchone()[0]
    dcon.close()

    assert int(snapshot_count) == 1
    assert int(decision_count) == 1
    assert int(wager_count) == 1
    assert int(linked_count) == 1


def test_backlink_conflict_never_switches_and_no_duplicates(monkeypatch, tmp_path):
    import duckdb
    import app.services.decision_ledger as dl
    import app.services.recommendation_snapshot as rs

    ledger_db = tmp_path / "ledger-backlink-conflict.db"
    snapshot_db = tmp_path / "snapshots-backlink-conflict.duckdb"
    duckdb.connect(str(snapshot_db)).close()

    monkeypatch.setattr(dl, "_DB_PATH", ledger_db)
    monkeypatch.setattr(rs, "_DB_PATH", snapshot_db)

    def _list_games(week=None):
        if week is None:
            return {"availableWeeks": [1]}
        return {"games": [{"eventId": "evt-backlink-conflict", "season": 2026, "week": 1}]}

    monkeypatch.setattr(snapshot_route.games_service, "list_games", _list_games)

    payload = _actionable_payload("evt-backlink-conflict")
    r1 = client.post("/api/recommendation/snapshot", json=payload)
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["success"] is True

    con = duckdb.connect(str(snapshot_db))
    con.execute(
        "UPDATE recommendation_snapshots SET decision_id = ? WHERE snapshot_id = ?",
        ["different-decision-id", b1["snapshotId"]],
    )
    con.close()

    r2 = client.post("/api/recommendation/snapshot", json=payload)
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["success"] is True
    assert b2["trackingStatus"] == "COMPLETE"
    assert "warning" in b2
    assert "conflict" in str(b2["warning"]).lower()
    assert b2["decisionId"] == b1["decisionId"]

    con = sqlite3.connect(str(ledger_db))
    decision_count = con.execute("SELECT COUNT(*) FROM decision_ledger WHERE publication_type = 'MY_CARD'").fetchone()[0]
    wager_count = con.execute("SELECT COUNT(*) FROM personal_wager_ledger").fetchone()[0]
    con.close()

    dcon = duckdb.connect(str(snapshot_db), read_only=True)
    stored_decision = dcon.execute(
        "SELECT decision_id FROM recommendation_snapshots WHERE snapshot_id = ?",
        [b1["snapshotId"]],
    ).fetchone()[0]
    dcon.close()

    assert int(decision_count) == 1
    assert int(wager_count) == 1
    assert stored_decision == "different-decision-id"


def test_retry_repairs_backlink_without_duplicates(monkeypatch, tmp_path):
    import duckdb
    import app.services.decision_ledger as dl
    import app.services.recommendation_snapshot as rs

    ledger_db = tmp_path / "ledger-backlink-repair.db"
    snapshot_db = tmp_path / "snapshots-backlink-repair.duckdb"
    duckdb.connect(str(snapshot_db)).close()

    monkeypatch.setattr(dl, "_DB_PATH", ledger_db)
    monkeypatch.setattr(rs, "_DB_PATH", snapshot_db)

    def _list_games(week=None):
        if week is None:
            return {"availableWeeks": [1]}
        return {"games": [{"eventId": "evt-backlink-repair", "season": 2026, "week": 1}]}

    monkeypatch.setattr(snapshot_route.games_service, "list_games", _list_games)

    calls = {"n": 0}

    def _flaky_link(snapshot_id: str, decision_id: str):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient duckdb issue")
        return rs.link_snapshot_decision(snapshot_id, decision_id)

    monkeypatch.setattr(snapshot_route, "link_snapshot_decision", _flaky_link)

    payload = _actionable_payload("evt-backlink-repair")
    r1 = client.post("/api/recommendation/snapshot", json=payload)
    r2 = client.post("/api/recommendation/snapshot", json=payload)
    assert r1.status_code == 200 and r2.status_code == 200
    b1 = r1.json()
    b2 = r2.json()

    assert b1["success"] is True and b2["success"] is True
    assert b1["snapshotId"] == b2["snapshotId"]
    assert b1["decisionId"] == b2["decisionId"]

    con = sqlite3.connect(str(ledger_db))
    decision_count = con.execute("SELECT COUNT(*) FROM decision_ledger WHERE publication_type = 'MY_CARD'").fetchone()[0]
    wager_count = con.execute("SELECT COUNT(*) FROM personal_wager_ledger").fetchone()[0]
    con.close()

    dcon = duckdb.connect(str(snapshot_db), read_only=True)
    rows = dcon.execute(
        "SELECT decision_id FROM recommendation_snapshots WHERE snapshot_id = ?",
        [b1["snapshotId"]],
    ).fetchall()
    dcon.close()

    assert len(rows) == 1
    assert rows[0][0] == b1["decisionId"]
    assert int(decision_count) == 1
    assert int(wager_count) == 1
