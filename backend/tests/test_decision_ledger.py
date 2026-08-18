from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
ADMIN_HEADERS = {"x-admin-token": "dev-admin-token"}


def _decision_payload(event_id: str, price: float = -110.0, si_score: float = 80.0):
    return {
        "publishedAtUTC": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "season": 2026,
        "week": 1,
        "eventId": event_id,
        "commenceTime": "2026-09-13T17:00:00+00:00",
        "awayTeam": "NO",
        "homeTeam": "ATL",
        "selection": "NO +7",
        "market": "spreads",
        "side": "away",
        "point": 7.0,
        "price": price,
        "sportsbook": "DraftKings",
        "rawProbability": 0.57,
        "calibratedProbability": 0.59,
        "pushProbability": 0.02,
        "lossProbability": 0.39,
        "rawEdge": 0.032,
        "calibratedEdge": 0.041,
        "currentEV": 0.054,
        "fairLine": -128.0,
        "truePlayableTo": -118.0,
        "truePlayableToStatus": "AVAILABLE",
        "siScore": si_score,
        "siGrade": "A-",
        "siRank": 1,
        "recommendation": "BET",
        "qualificationStatus": "QUALIFIED",
        "qualificationReasons": ["edge", "ev"],
        "oddsProvider": "the_odds_api",
        "oddsTimestamp": "2026-09-13T15:00:00+00:00",
        "modelTimestamp": "2026-09-13T14:58:00+00:00",
        "marketTimestamp": "2026-09-13T15:00:00+00:00",
        "sourceSnapshotId": "odds-snap-1",
    }


def _post_decision(payload):
    return client.post(
        "/api/admin/ledger/decisions",
        headers=ADMIN_HEADERS,
        json={"publicationType": "SIA_3", "payload": payload},
    )


def test_mutation_requires_admin_token(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    payload = _decision_payload("evt-auth")
    response = client.post("/api/admin/ledger/decisions", json={"publicationType": "SIA_3", "payload": payload})
    assert response.status_code == 401


def test_decision_creation_immutable_versioning_and_idempotency(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    base = _decision_payload("evt-v1")
    r1 = _post_decision(base)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["created"] is True
    assert d1["decisionVersion"] == 1
    assert d1["supersedesDecisionId"] is None

    r1_repeat = _post_decision(base)
    assert r1_repeat.status_code == 200
    d1_repeat = r1_repeat.json()
    assert d1_repeat["created"] is False
    assert d1_repeat["decisionId"] == d1["decisionId"]
    assert d1_repeat["decisionVersion"] == 1

    changed_price = dict(base)
    changed_price["price"] = -115.0
    r2 = _post_decision(changed_price)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["created"] is True
    assert d2["decisionVersion"] == 2
    assert d2["supersedesDecisionId"] == d1["decisionId"]

    changed_score = dict(changed_price)
    changed_score["siScore"] = 76.4
    r3 = _post_decision(changed_score)
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["created"] is True
    assert d3["decisionVersion"] == 3
    assert d3["supersedesDecisionId"] == d2["decisionId"]


def test_hash_validation_and_tamper_detection(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    db = tmp_path / "ledger.db"
    monkeypatch.setattr(dl, "_DB_PATH", db)

    r1 = _post_decision(_decision_payload("evt-hash"))
    assert r1.status_code == 200
    decision_id = r1.json()["decisionId"]

    valid = client.get(f"/api/admin/ledger/hash/{decision_id}")
    assert valid.status_code == 200
    assert valid.json()["valid"] is True

    con = sqlite3.connect(str(db))
    con.execute("UPDATE decision_ledger SET si_score = ? WHERE decision_id = ?", [95.0, decision_id])
    con.commit()
    con.close()

    invalid = client.get(f"/api/admin/ledger/hash/{decision_id}")
    assert invalid.status_code == 200
    assert invalid.json()["valid"] is False


def test_sia3_publication_slots_and_rank_order_preserved(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    d1 = _post_decision(_decision_payload("evt-r1")).json()
    d2 = _post_decision(_decision_payload("evt-r2")).json()

    payload = {
        "publicationType": "SIA_3",
        "publishedAtUTC": "2026-09-13T16:00:00+00:00",
        "season": 2026,
        "week": 1,
        "isOfficial": False,
        "slots": [
            {
                "decisionId": d1["decisionId"],
                "slotLabel": "BET",
                "qualificationStatus": "QUALIFIED",
            },
            {
                "decisionId": d2["decisionId"],
                "slotLabel": "BET",
                "qualificationStatus": "QUALIFIED",
            },
            {
                "slotLabel": "WATCH",
                "qualificationStatus": "NOT_QUALIFIED",
            },
        ],
    }

    pub = client.post("/api/admin/ledger/publications/sia3", headers=ADMIN_HEADERS, json=payload)
    assert pub.status_code == 200
    body = pub.json()
    assert body["rank1DecisionId"] == d1["decisionId"]
    assert body["rank2DecisionId"] == d2["decisionId"]
    assert body["rank3DecisionId"] is None
    assert body["slots"][2]["slotLabel"] == "WATCH"
    assert body["qualifiedPickCount"] == 2

    repeat = client.post("/api/admin/ledger/publications/sia3", headers=ADMIN_HEADERS, json=payload)
    assert repeat.status_code == 200
    assert repeat.json()["created"] is False
    assert repeat.json()["publicationId"] == body["publicationId"]


def test_publication_supports_zero_to_three_qualified(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    d1 = _post_decision(_decision_payload("evt-q1")).json()["decisionId"]
    d2 = _post_decision(_decision_payload("evt-q2")).json()["decisionId"]
    d3 = _post_decision(_decision_payload("evt-q3")).json()["decisionId"]

    for count in [3, 2, 1, 0]:
        slots = []
        ids = [d1, d2, d3]
        for i in range(3):
            if i < count:
                slots.append({"decisionId": ids[i], "slotLabel": "BET", "qualificationStatus": "QUALIFIED"})
            else:
                slots.append({"slotLabel": "WATCH", "qualificationStatus": "NOT_QUALIFIED"})

        response = client.post(
            "/api/admin/ledger/publications/sia3",
            headers=ADMIN_HEADERS,
            json={
                "publicationType": "SIA_3",
                "publishedAtUTC": f"2026-09-1{count}T16:00:00+00:00",
                "season": 2026,
                "week": count + 1,
                "isOfficial": count == 3,
                "slots": slots,
            },
        )
        assert response.status_code == 200
        assert response.json()["qualifiedPickCount"] == count


def test_outcome_append_and_profit_win_loss_push(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    decision_id = _post_decision(_decision_payload("evt-outcome")).json()["decisionId"]

    win = client.post(
        "/api/admin/ledger/outcomes",
        headers=ADMIN_HEADERS,
        json={
            "decisionId": decision_id,
            "capturedAtUTC": "2026-09-13T23:30:00+00:00",
            "closingLine": 6.5,
            "closingPrice": -110,
            "closingSportsbook": "DraftKings",
            "closingTimestamp": "2026-09-13T16:58:00+00:00",
            "finalAwayScore": 24,
            "finalHomeScore": 20,
            "betResult": "WIN",
        },
    )
    assert win.status_code == 200
    assert win.json()["profitPerDollar"] == 0.909091

    repeat = client.post(
        "/api/admin/ledger/outcomes",
        headers=ADMIN_HEADERS,
        json={
            "decisionId": decision_id,
            "capturedAtUTC": "2026-09-13T23:30:00+00:00",
            "closingLine": 6.5,
            "closingPrice": -110,
            "closingSportsbook": "DraftKings",
            "closingTimestamp": "2026-09-13T16:58:00+00:00",
            "finalAwayScore": 24,
            "finalHomeScore": 20,
            "betResult": "WIN",
        },
    )
    assert repeat.status_code == 200
    assert repeat.json()["created"] is False

    d2 = _post_decision(_decision_payload("evt-outcome-loss", price=120)).json()["decisionId"]
    loss = client.post(
        "/api/admin/ledger/outcomes",
        headers=ADMIN_HEADERS,
        json={"decisionId": d2, "betResult": "LOSS"},
    )
    assert loss.status_code == 200
    assert loss.json()["profitPerDollar"] == -1.0

    d3 = _post_decision(_decision_payload("evt-outcome-push", price=120)).json()["decisionId"]
    push = client.post(
        "/api/admin/ledger/outcomes",
        headers=ADMIN_HEADERS,
        json={"decisionId": d3, "betResult": "PUSH"},
    )
    assert push.status_code == 200
    assert push.json()["profitPerDollar"] == 0.0


def test_outcome_missing_closing_line_and_snapshot_linkage(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    decision_id = _post_decision(_decision_payload("evt-missing-closing")).json()["decisionId"]

    with patch.object(dl, "get_closing_line") as mocked_closing:
        mocked_closing.return_value = type("C", (), {"closing_status": "NOT_CAPTURED", "closing_point": None, "closing_price": None, "closing_timestamp": None})()

        response = client.post(
            "/api/admin/ledger/outcomes",
            headers=ADMIN_HEADERS,
            json={
                "decisionId": decision_id,
                "betResult": "LOSS",
                "sourceSnapshotId": "close-snap-none",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["closingLine"] is None
        assert body["closingPrice"] is None


def test_decision_list_and_model_version_fields(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    _post_decision(_decision_payload("evt-list"))

    listing = client.get("/api/admin/ledger/decisions?season=2026&week=1&latestOnly=true")
    assert listing.status_code == 200
    payload = listing.json()
    assert payload["count"] >= 1
    item = payload["items"][0]
    assert item["modelVersion"]
    assert item["probabilityEngineVersion"]
    assert item["calibrationVersion"]
    assert item["rankingVersion"]
    assert item["qualificationPolicyVersion"]
    assert item["oddsTimestamp"] == "2026-09-13T15:00:00+00:00"


def test_admin_audit_and_prospective_performance_endpoints(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    d1 = _post_decision(_decision_payload("evt-perf-1")).json()["decisionId"]
    d2 = _post_decision(_decision_payload("evt-perf-2")).json()["decisionId"]

    pub = client.post(
        "/api/admin/ledger/publications/sia3",
        headers=ADMIN_HEADERS,
        json={
            "publicationType": "SIA_3",
            "publishedAtUTC": "2026-09-12T16:00:00+00:00",
            "season": 2026,
            "week": 1,
            "isOfficial": True,
            "slots": [
                {"decisionId": d1, "slotLabel": "BET", "qualificationStatus": "QUALIFIED"},
                {"decisionId": d2, "slotLabel": "BET", "qualificationStatus": "QUALIFIED"},
                {"slotLabel": "WATCH", "qualificationStatus": "NOT_QUALIFIED"},
            ],
        },
    )
    assert pub.status_code == 200

    client.post("/api/admin/ledger/outcomes", headers=ADMIN_HEADERS, json={"decisionId": d1, "betResult": "WIN", "closingLine": 6.5})
    client.post("/api/admin/ledger/outcomes", headers=ADMIN_HEADERS, json={"decisionId": d2, "betResult": "LOSS", "closingLine": 4.5})

    audit = client.get("/api/admin/ledger/audit")
    assert audit.status_code == 200
    a = audit.json()
    assert a["decisionsRecorded"] >= 2
    assert a["officialSia3Publications"] >= 1
    assert "ledgerIntegrity" in a
    assert "auditRows" in a

    perf = client.get("/api/admin/ledger/performance")
    assert perf.status_code == 200
    p = perf.json()
    assert p["datasetLabel"] == "PROSPECTIVE AUDITED TRACK RECORD"
    assert p["historicalLabel"] == "MARKET-REFERENCE BACKTEST"
    assert "byRank" in p
