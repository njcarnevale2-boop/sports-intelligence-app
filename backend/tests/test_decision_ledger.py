from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
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
        "recommendedPlayableTo": -112.0,
        "recommendedPlayableToStatus": "AVAILABLE",
        "recommendedPlayableToReason": "TEST",
        "boundaryDistancePoints": 2.0,
        "boundaryDistanceBucket": "2.0",
        "boundaryCrossesZero": False,
        "boundaryUnderdogToFavorite": False,
        "boundaryCrossesKey3": True,
        "boundaryCrossesKey7": True,
        "observedQuoteAvailable": True,
        "executionBoundaryMode": "OBSERVED_PLUS_MODEL_SIMULATION",
        "executionBoundaryResearch": {
            "mode": "OBSERVED_PLUS_MODEL_SIMULATION",
            "observedExecution": {
                "quoteObserved": True,
                "line": 7.0,
                "price": -110.0,
                "sportsbook": "DraftKings",
                "quoteTimestamp": "2026-09-13T15:00:00+00:00",
            },
            "theoreticalBoundary": {
                "line": 3.0,
                "status": "AVAILABLE",
                "reason": "TEST",
                "distanceFromCurrent": 4.0,
                "distanceBucket": "3.0+",
            },
            "transitionFlags": {
                "crossesZero": False,
                "underdogToFavorite": False,
                "crossesKeyNumber3": True,
                "crossesKeyNumber7": True,
            },
            "degradationPath": [
                {"pointsWorse": 0.0, "line": 7.0, "quoteObserved": True},
                {"pointsWorse": 1.0, "line": 6.0, "quoteObserved": False},
            ],
            "simulatedOnly": False,
        },
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


def test_publication_route_rejects_lowvig_alias_and_accepts_control_case(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    blocked_decision = _decision_payload("evt-route-lowvig")
    blocked_decision["sportsbook"] = "LOW-VIG.AG"
    blocked_payload = {
        "publicationType": "SIA_3",
        "publishedAtUTC": "2026-09-13T16:00:00+00:00",
        "season": 2026,
        "week": 1,
        "isOfficial": True,
        "slots": [
            {
                "decision": blocked_decision,
                "slotLabel": "BET",
                "qualificationStatus": "QUALIFIED",
            },
            {"slotLabel": "WATCH", "qualificationStatus": "NOT_QUALIFIED"},
            {"slotLabel": "WATCH", "qualificationStatus": "NOT_QUALIFIED"},
        ],
    }

    blocked = client.post("/api/admin/ledger/publications/sia3", headers=ADMIN_HEADERS, json=blocked_payload)
    assert blocked.status_code == 400
    assert "excluded sportsbook" in blocked.json()["detail"].lower()

    control_payload = {
        "publicationType": "SIA_3",
        "publishedAtUTC": "2026-09-13T16:00:00+00:00",
        "season": 2026,
        "week": 1,
        "isOfficial": True,
        "slots": [
            {
                "decision": _decision_payload("evt-route-control"),
                "slotLabel": "BET",
                "qualificationStatus": "QUALIFIED",
            },
            {"slotLabel": "WATCH", "qualificationStatus": "NOT_QUALIFIED"},
            {"slotLabel": "WATCH", "qualificationStatus": "NOT_QUALIFIED"},
        ],
    }

    allowed = client.post("/api/admin/ledger/publications/sia3", headers=ADMIN_HEADERS, json=control_payload)
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["isOfficial"] is True
    assert body["rank1DecisionId"] is not None
    assert body["slots"][0]["qualificationStatus"] == "QUALIFIED"


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
    assert item["recommendedPlayableTo"] == -112.0
    assert item["executionBoundaryMode"] == "OBSERVED_PLUS_MODEL_SIMULATION"
    assert item["executionBoundaryResearch"]["mode"] == "OBSERVED_PLUS_MODEL_SIMULATION"


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
    assert "executionBoundaryResearch" in p
    assert "distanceBuckets" in p["executionBoundaryResearch"]


def test_recommendation_snapshot_auto_records_my_card_decision(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl
    import app.routes.recommendation_snapshot as snapshot_route

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")
    monkeypatch.setattr(snapshot_route, "store_snapshot", lambda payload: "snap-123")

    payload = {
        "season": 2026,
        "week": 1,
        "eventId": "evt-my-card-1",
        "commenceTime": "2026-09-13T17:00:00+00:00",
        "awayTeam": "NO",
        "homeTeam": "ATL",
        "selection": "NO +7",
        "market": "spreads",
        "side": "away",
        "point": 7.0,
        "price": -110.0,
        "sportsbook": "DraftKings",
        "modelProbability": 0.57,
        "calibratedProbability": 0.59,
        "pushProbability": 0.02,
        "lossProbability": 0.39,
        "edge": 0.032,
        "currentEV": 0.054,
        "evPerDollar": 0.054,
        "fairLine": -128.0,
        "truePlayableTo": -118.0,
        "truePlayableToStatus": "AVAILABLE",
        "siScore": 80.0,
        "siGrade": "A-",
        "siRank": 1,
        "recommendation": "BET",
        "qualificationReasons": ["edge", "ev"],
        "oddsProvider": "the_odds_api",
        "oddsTimestamp": "2026-09-13T15:00:00+00:00",
        "marketTimestamp": "2026-09-13T15:00:00+00:00",
    }

    response = client.post("/api/recommendation/snapshot", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["snapshotId"] == "snap-123"
    assert body["decisionId"]
    assert body["decisionVersion"] == 1
    assert body["decisionCreated"] is True

    decision = client.get(f"/api/admin/ledger/decisions/{body['decisionId']}")
    assert decision.status_code == 200
    stored = decision.json()
    assert stored["publicationType"] == "MY_CARD"
    assert stored["sourceSnapshotId"] == "snap-123"


def test_publish_official_sia3_from_preview_requires_overrides(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    preview = {
        "publishedAtUTC": "2026-09-13T16:00:00+00:00",
        "season": 2026,
        "week": 1,
        "staleSlotCount": 1,
        "missingSnapshotLinkageCount": 1,
        "slots": [
            {
                "rank": 1,
                "slotLabel": "BET",
                "qualificationStatus": "QUALIFIED",
                "decision": _decision_payload("evt-preview-1"),
            }
        ],
    }

    with patch.object(dl.settings, "OFFICIAL_SIA3_CADENCE", "WEEKLY"):
        with pytest.raises(ValueError, match="Stale odds"):
            dl.publish_official_sia3_from_preview(preview)

        with pytest.raises(ValueError, match="snapshot linkage"):
            dl.publish_official_sia3_from_preview(preview, override_stale=True)

        published = dl.publish_official_sia3_from_preview(
            preview,
            override_stale=True,
            override_missing_linkage=True,
        )

    assert published["isOfficial"] is True
    assert published["qualifiedPickCount"] == 1


def test_official_preview_filters_non_production_markets(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")
    monkeypatch.setattr(
        dl,
        "_snapshot_linkage",
        lambda **kwargs: {
            "verified": True,
            "reason": "VERIFIED",
            "sourceSnapshotId": "snap-1",
            "oddsTimestamp": "2026-09-13T15:00:00+00:00",
            "snapshotAgeMinutes": 1.0,
            "linePriceMatch": True,
        },
    )

    opportunities = [
        {
            "eventId": "evt-ml",
            "commenceTime": "2026-09-13T17:00:00+00:00",
            "awayTeam": "NO",
            "homeTeam": "ATL",
            "pick": "NO",
            "market": "moneyline",
            "side": "away",
            "point": None,
            "price": 130,
            "book": "DraftKings",
            "qualificationStatus": "QUALIFIED",
            "productionEligible": False,
        },
        {
            "eventId": "evt-sp",
            "commenceTime": "2026-09-13T17:00:00+00:00",
            "awayTeam": "NO",
            "homeTeam": "ATL",
            "pick": "NO +3",
            "market": "spread",
            "side": "away",
            "point": 3.0,
            "price": -110,
            "book": "DraftKings",
            "qualificationStatus": "QUALIFIED",
            "productionEligible": True,
        },
    ]

    preview = dl.build_official_sia3_preview(opportunities, season=2026, week=1)
    decisions = [s.get("decision") for s in preview.get("slots", []) if s.get("decision")]
    assert decisions
    assert all(str(d.get("market") or "").lower() in {"spread", "spreads"} for d in decisions)


def test_official_publish_rejects_non_production_market_family(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    preview = {
        "publishedAtUTC": "2026-09-13T16:00:00+00:00",
        "season": 2026,
        "week": 1,
        "staleSlotCount": 0,
        "missingSnapshotLinkageCount": 0,
        "slots": [
            {
                "rank": 1,
                "slotLabel": "BET",
                "qualificationStatus": "QUALIFIED",
                "decision": {
                    **_decision_payload("evt-ml-reject"),
                    "market": "moneyline",
                    "selection": "NO",
                    "point": None,
                    "price": 130,
                },
            }
        ],
    }

    with pytest.raises(ValueError, match="rejects non-production"):
        dl.publish_official_sia3_from_preview(preview)


def test_auto_append_outcomes_from_scores_appends_once(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    decision_id = _post_decision(_decision_payload("evt-score-1")).json()["decisionId"]

    first = dl.auto_append_outcomes_from_scores(
        fetch_scores_fn=lambda event_id: {"finalAwayScore": 24, "finalHomeScore": 20} if event_id == "evt-score-1" else None
    )
    assert first["checked"] == 1
    assert first["appended"] == 1
    assert first["pending"] == 0

    second = dl.auto_append_outcomes_from_scores(
        fetch_scores_fn=lambda event_id: {"finalAwayScore": 24, "finalHomeScore": 20} if event_id == "evt-score-1" else None
    )
    assert second["checked"] == 0
    assert second["appended"] == 0
    assert second["pending"] == 0

    con = sqlite3.connect(str(tmp_path / "ledger.db"))
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT decision_id, bet_result, final_away_score, final_home_score FROM decision_outcomes WHERE decision_id = ? ORDER BY id DESC LIMIT 1",
        [decision_id],
    ).fetchone()
    con.close()
    assert row is not None
    assert row["bet_result"] == "LOSS"
    assert row["final_away_score"] == 24
    assert row["final_home_score"] == 20


def test_official_preview_and_publish_routes_enforce_admin_token_and_overrides(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    preview_payload = {
        "publishedAtUTC": "2026-09-13T16:00:00+00:00",
        "season": 2026,
        "week": 1,
        "maxOddsAgeMinutes": 60,
        "staleSlotCount": 1,
        "missingSnapshotLinkageCount": 1,
        "slots": [
            {
                "rank": 1,
                "slotLabel": "BET",
                "qualificationStatus": "QUALIFIED",
                "decision": _decision_payload("evt-route-1"),
                "snapshotVerified": False,
                "snapshotVerificationReason": "NO_SNAPSHOT_RECORD",
                "oddsAgeMinutes": 120,
                "isStale": True,
            }
        ],
        "dataTimestamp": "2026-09-13T15:00:00+00:00",
        "dataStatus": "LIVE",
    }

    monkeypatch.setattr("app.routes.decision_ledger._resolve_week_and_season", lambda week: (2026, 1))
    monkeypatch.setattr("app.routes.decision_ledger.get_opportunities", lambda **kwargs: {"opportunities": [], "snapshotId": "snap-live-1"})
    monkeypatch.setattr("app.routes.decision_ledger.build_official_sia3_preview", lambda opportunities, season, week, **kwargs: dict(preview_payload))

    unauth_preview = client.get("/api/admin/ledger/official-sia3/preview")
    assert unauth_preview.status_code == 401

    preview = client.get("/api/admin/ledger/official-sia3/preview", headers=ADMIN_HEADERS)
    assert preview.status_code == 200
    assert preview.json()["staleSlotCount"] == 1

    blocked = client.post("/api/admin/ledger/official-sia3/publish", headers=ADMIN_HEADERS, json={})
    assert blocked.status_code == 422

    stale = client.post(
        "/api/admin/ledger/official-sia3/publish",
        headers=ADMIN_HEADERS,
        json={"snapshotId": "snap-stale"},
    )
    assert stale.status_code == 400
    assert "stale" in stale.json()["detail"].lower()

    allowed = client.post(
        "/api/admin/ledger/official-sia3/publish",
        headers=ADMIN_HEADERS,
        json={"snapshotId": "snap-live-1", "overrideStaleOdds": True, "overrideMissingSnapshotLinkage": True},
    )
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["publication"]["isOfficial"] is True


def _publish_official_slot(decision_id: str, *, week: int = 1):
    return client.post(
        "/api/admin/ledger/publications/sia3",
        headers=ADMIN_HEADERS,
        json={
            "publicationType": "SIA_3",
            "publishedAtUTC": f"2026-09-{12 + week:02d}T16:00:00+00:00",
            "season": 2026,
            "week": week,
            "isOfficial": True,
            "slots": [
                {"decisionId": decision_id, "slotLabel": "BET", "qualificationStatus": "QUALIFIED"},
                {"slotLabel": "WATCH", "qualificationStatus": "NOT_QUALIFIED"},
                {"slotLabel": "WATCH", "qualificationStatus": "NOT_QUALIFIED"},
            ],
        },
    )


def test_official_postgame_lifecycle_win_idempotent_three_runs(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    db_path = tmp_path / "ledger.db"
    monkeypatch.setattr(dl, "_DB_PATH", db_path)

    payload = _decision_payload("evt-official-win")
    payload["selection"] = "ATL -3"
    payload["side"] = "home"
    payload["point"] = -3.0

    decision_id = _post_decision(payload).json()["decisionId"]
    publication = _publish_official_slot(decision_id, week=1)
    assert publication.status_code == 200

    with patch.object(dl, "get_closing_line") as mocked_closing:
        mocked_closing.return_value = type(
            "C",
            (),
            {
                "closing_status": "AVAILABLE",
                "closing_point": -4.0,
                "closing_price": -110.0,
                "closing_timestamp": datetime.fromisoformat("2026-09-13T16:59:00+00:00"),
            },
        )()

        run1 = dl.run_official_postgame_lifecycle(
            fetch_scores_fn=lambda event_id: {
                "status": "FINAL",
                "finalAwayScore": 17,
                "finalHomeScore": 24,
                "sourceSnapshotId": "score-snap-1",
            }
            if event_id == "evt-official-win"
            else None
        )
        assert run1["checked"] == 1
        assert run1["settled"] == 1
        assert run1["resultBreakdown"]["WIN"] == 1
        assert run1["closingLineAttached"] == 1
        assert run1["clvAvailable"] == 1
        assert run1["promotionProgress"]["sampleCount"] == 1

        run2 = dl.run_official_postgame_lifecycle(
            fetch_scores_fn=lambda event_id: {
                "status": "FINAL",
                "finalAwayScore": 17,
                "finalHomeScore": 24,
            }
            if event_id == "evt-official-win"
            else None
        )
        assert run2["checked"] == 0
        assert run2["settled"] == 0
        assert run2["promotionProgress"]["sampleCount"] == 1

        run3 = dl.run_official_postgame_lifecycle(
            fetch_scores_fn=lambda event_id: {
                "status": "FINAL",
                "finalAwayScore": 17,
                "finalHomeScore": 24,
            }
            if event_id == "evt-official-win"
            else None
        )
        assert run3["checked"] == 0
        assert run3["settled"] == 0
        assert run3["promotionProgress"]["sampleCount"] == 1

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM decision_outcomes WHERE decision_id = ?", [decision_id]).fetchall()
    con.close()
    assert len(rows) == 1
    assert rows[0]["bet_result"] == "WIN"


def test_official_postgame_lifecycle_loss_and_push(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    loss_payload = _decision_payload("evt-official-loss")
    loss_payload["selection"] = "ATL -3"
    loss_payload["side"] = "home"
    loss_payload["point"] = -3.0

    push_payload = _decision_payload("evt-official-push")
    push_payload["selection"] = "ATL -3"
    push_payload["side"] = "home"
    push_payload["point"] = -3.0

    loss_id = _post_decision(loss_payload).json()["decisionId"]
    push_id = _post_decision(push_payload).json()["decisionId"]
    assert _publish_official_slot(loss_id, week=2).status_code == 200
    assert _publish_official_slot(push_id, week=3).status_code == 200

    with patch.object(dl, "get_closing_line") as mocked_closing:
        mocked_closing.return_value = type(
            "C",
            (),
            {
                "closing_status": "AVAILABLE",
                "closing_point": -3.5,
                "closing_price": -110.0,
                "closing_timestamp": datetime.fromisoformat("2026-09-13T16:59:00+00:00"),
            },
        )()

        result = dl.run_official_postgame_lifecycle(
            fetch_scores_fn=lambda event_id: {
                "evt-official-loss": {"status": "FINAL", "finalAwayScore": 24, "finalHomeScore": 20},
                "evt-official-push": {"status": "FINAL", "finalAwayScore": 20, "finalHomeScore": 23},
            }.get(event_id)
        )

    assert result["checked"] == 2
    assert result["settled"] == 2
    assert result["resultBreakdown"]["LOSS"] == 1
    assert result["resultBreakdown"]["PUSH"] == 1


def test_official_postgame_lifecycle_missing_closing_line_still_grades(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    payload = _decision_payload("evt-official-no-closing")
    payload["selection"] = "ATL -3"
    payload["side"] = "home"
    payload["point"] = -3.0
    decision_id = _post_decision(payload).json()["decisionId"]
    assert _publish_official_slot(decision_id, week=4).status_code == 200

    with patch.object(dl, "get_closing_line") as mocked_closing:
        mocked_closing.return_value = type(
            "C",
            (),
            {
                "closing_status": "NOT_CAPTURED",
                "closing_point": None,
                "closing_price": None,
                "closing_timestamp": None,
            },
        )()

        result = dl.run_official_postgame_lifecycle(
            fetch_scores_fn=lambda event_id: {
                "status": "FINAL",
                "finalAwayScore": 17,
                "finalHomeScore": 24,
            }
            if event_id == "evt-official-no-closing"
            else None
        )

    assert result["settled"] == 1
    assert result["closingLineAttached"] == 0
    assert result["closingLineMissing"] == 1
    assert result["clvPending"] == 1


def test_official_postgame_lifecycle_game_not_final_and_invalid_score_safety(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    pending_payload = _decision_payload("evt-official-pending")
    pending_payload["selection"] = "ATL -3"
    pending_payload["side"] = "home"
    pending_payload["point"] = -3.0

    invalid_payload = _decision_payload("evt-official-invalid")
    invalid_payload["selection"] = "ATL -3"
    invalid_payload["side"] = "home"
    invalid_payload["point"] = -3.0

    pending_id = _post_decision(pending_payload).json()["decisionId"]
    invalid_id = _post_decision(invalid_payload).json()["decisionId"]
    assert _publish_official_slot(pending_id, week=5).status_code == 200
    assert _publish_official_slot(invalid_id, week=6).status_code == 200

    result = dl.run_official_postgame_lifecycle(
        fetch_scores_fn=lambda event_id: {
            "evt-official-pending": {"status": "IN_PROGRESS"},
            "evt-official-invalid": {"status": "FINAL", "finalAwayScore": "xx", "finalHomeScore": 17},
        }.get(event_id)
    )

    assert result["checked"] == 2
    assert result["settled"] == 0
    assert result["skipped"]["gameNotFinal"] == 1
    assert result["skipped"]["invalidScore"] == 1


def test_official_postgame_lifecycle_ignores_non_official_decisions(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")
    _post_decision(_decision_payload("evt-non-official"))

    result = dl.run_official_postgame_lifecycle(
        fetch_scores_fn=lambda event_id: {"status": "FINAL", "finalAwayScore": 21, "finalHomeScore": 17}
    )
    assert result["checked"] == 0
    assert result["settled"] == 0


def _my_card_payload(event_id: str, *, market: str, side: str, point: float | None, price: float) -> dict:
    return {
        "season": 2026,
        "week": 1,
        "eventId": event_id,
        "commenceTime": "2026-09-13T17:00:00+00:00",
        "awayTeam": "NO",
        "homeTeam": "ATL",
        "selection": "TEST PICK",
        "market": market,
        "side": side,
        "point": point,
        "price": price,
        "sportsbook": "DraftKings",
        "siScore": 81.0,
        "siGrade": "A-",
        "modelProbability": 0.57,
        "calibratedProbability": 0.59,
        "impliedProbability": 0.52,
        "rawEdge": 0.03,
        "currentEV": 0.05,
        "recommendation": "BET",
    }


def test_personal_wager_persistence_and_pending_bankroll_math(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    wager = dl.record_personal_wager_from_payload(
        {
            **_my_card_payload("evt-pending-1", market="spread", side="away", point=3.0, price=-110.0),
            "amountRisked": 150.0,
            "unitsRisked": 1.5,
            "unitSizeAtBet": 100.0,
        },
        decision_id=None,
        source_snapshot_id="snap-1",
    )

    assert wager["created"] is True
    assert wager["result"] == "PENDING"
    assert wager["amountRisked"] == 150.0
    assert wager["unitsRisked"] == 1.5
    assert wager["unitSizeAtBet"] == 100.0
    assert wager["modelProbabilityAtBet"] == 0.57
    assert wager["calibratedProbabilityAtBet"] == 0.59

    dashboard = dl.get_personal_wager_dashboard()
    assert dashboard["startingBankroll"] == 1000.0
    assert dashboard["currentBankroll"] == 1000.0
    assert dashboard["totalPL"] == 0.0
    assert dashboard["totalUnits"] == 0.0
    assert dashboard["roi"] is None
    assert dashboard["pendingExposure"] == 150.0
    assert dashboard["wins"] == 0
    assert dashboard["losses"] == 0
    assert dashboard["pushes"] == 0


def test_personal_settlement_spread_moneyline_total_push_and_roi(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    spread_decision = dl.record_my_card_decision_from_payload(
        _my_card_payload("evt-spread-win", market="spread", side="away", point=3.0, price=-110.0)
    )
    moneyline_decision = dl.record_my_card_decision_from_payload(
        _my_card_payload("evt-ml-win", market="moneyline", side="home", point=None, price=150.0)
    )
    total_decision = dl.record_my_card_decision_from_payload(
        _my_card_payload("evt-total-loss", market="total", side="over", point=44.5, price=-105.0)
    )
    push_decision = dl.record_my_card_decision_from_payload(
        _my_card_payload("evt-total-push", market="total", side="over", point=44.0, price=-110.0)
    )

    dl.record_personal_wager_from_payload(
        {**_my_card_payload("evt-spread-win", market="spread", side="away", point=3.0, price=-110.0), "amountRisked": 110.0},
        decision_id=spread_decision["decisionId"],
    )
    dl.record_personal_wager_from_payload(
        {**_my_card_payload("evt-ml-win", market="moneyline", side="home", point=None, price=150.0), "amountRisked": 100.0},
        decision_id=moneyline_decision["decisionId"],
    )
    dl.record_personal_wager_from_payload(
        {**_my_card_payload("evt-total-loss", market="total", side="over", point=44.5, price=-105.0), "amountRisked": 105.0},
        decision_id=total_decision["decisionId"],
    )
    dl.record_personal_wager_from_payload(
        {**_my_card_payload("evt-total-push", market="total", side="over", point=44.0, price=-110.0), "amountRisked": 100.0},
        decision_id=push_decision["decisionId"],
    )
    dl.record_personal_wager_from_payload(
        {**_my_card_payload("evt-pending-keep", market="spread", side="home", point=-2.5, price=-110.0), "amountRisked": 120.0},
        decision_id=None,
    )

    with patch.object(dl, "append_outcome") as mocked_append_outcome:
        def _fake_append(payload: dict):
            decision_id = str(payload["decisionId"])
            mapping = {
                spread_decision["decisionId"]: {"betResult": "WIN", "closingLine": 2.5, "closingPrice": -110.0, "clv": 0.5, "clvType": "POINTS"},
                moneyline_decision["decisionId"]: {"betResult": "WIN", "closingLine": None, "closingPrice": 140.0, "clv": None, "clvType": None},
                total_decision["decisionId"]: {"betResult": "LOSS", "closingLine": 45.0, "closingPrice": -110.0, "clv": -0.5, "clvType": "POINTS"},
                push_decision["decisionId"]: {"betResult": "PUSH", "closingLine": 44.0, "closingPrice": -110.0, "clv": 0.0, "clvType": "POINTS"},
            }
            out = mapping[decision_id]
            return {
                "decisionId": decision_id,
                "betResult": out["betResult"],
                "closingLine": out["closingLine"],
                "closingPrice": out["closingPrice"],
                "clv": out["clv"],
                "clvType": out["clvType"],
            }

        mocked_append_outcome.side_effect = _fake_append

        out = dl.run_personal_postgame_lifecycle(
            fetch_scores_fn=lambda event_id: {
                "evt-spread-win": {"status": "FINAL", "finalAwayScore": 24, "finalHomeScore": 20},
                "evt-ml-win": {"status": "FINAL", "finalAwayScore": 17, "finalHomeScore": 21},
                "evt-total-loss": {"status": "FINAL", "finalAwayScore": 20, "finalHomeScore": 24},
                "evt-total-push": {"status": "FINAL", "finalAwayScore": 20, "finalHomeScore": 24},
                "evt-pending-keep": None,
            }.get(event_id)
        )

    assert out["settled"] == 4
    assert out["skipped"]["missingFinalScore"] == 1

    dashboard = dl.get_personal_wager_dashboard()
    assert dashboard["wins"] == 2
    assert dashboard["losses"] == 1
    assert dashboard["pushes"] == 1
    assert dashboard["pendingCount"] == 1
    assert dashboard["pendingExposure"] == 120.0
    assert dashboard["totalPL"] == 145.0
    assert dashboard["totalUnits"] == 1.45
    assert dashboard["currentBankroll"] == 1145.0
    assert dashboard["settledRisk"] == 415.0
    assert dashboard["roi"] == round(145.0 / 415.0, 6)
    assert dashboard["averageClvPoints"] == pytest.approx(0.0, rel=1e-6)


def test_personal_settlement_idempotent_and_immutable_recommendation_fields(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")
    decision = dl.record_my_card_decision_from_payload(
        _my_card_payload("evt-idem", market="spread", side="away", point=3.0, price=-110.0)
    )
    dl.record_personal_wager_from_payload(
        {**_my_card_payload("evt-idem", market="spread", side="away", point=3.0, price=-110.0), "amountRisked": 110.0},
        decision_id=decision["decisionId"],
    )

    with patch.object(dl, "append_outcome", return_value={"decisionId": decision["decisionId"], "betResult": "WIN", "closingLine": 2.5, "closingPrice": -110.0, "clv": 0.5, "clvType": "POINTS"}):
        first = dl.run_personal_postgame_lifecycle(
            fetch_scores_fn=lambda event_id: {"status": "FINAL", "finalAwayScore": 21, "finalHomeScore": 17}
        )
        second = dl.run_personal_postgame_lifecycle(
            fetch_scores_fn=lambda event_id: {"status": "FINAL", "finalAwayScore": 21, "finalHomeScore": 17}
        )

    assert first["settled"] == 1
    assert second["settled"] == 0

    wagers = dl.list_personal_wagers()
    assert len(wagers) == 1
    wager = wagers[0]
    assert wager["result"] == "WIN"
    assert wager["modelProbabilityAtBet"] == 0.57
    assert wager["calibratedProbabilityAtBet"] == 0.59
    assert wager["impliedProbabilityAtBet"] == 0.52


def test_existing_my_card_decisions_are_discovered_and_settled(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")
    legacy_one = dl.record_my_card_decision_from_payload(
        _my_card_payload("evt-legacy-1", market="spread", side="away", point=3.0, price=-110.0)
    )
    legacy_two = dl.record_my_card_decision_from_payload(
        _my_card_payload("evt-legacy-2", market="total", side="under", point=45.0, price=-110.0)
    )

    with patch.object(dl, "append_outcome") as mocked_append_outcome:
        def _fake_append(payload: dict):
            return {
                "decisionId": payload["decisionId"],
                "betResult": "WIN" if payload["decisionId"] == legacy_one["decisionId"] else "LOSS",
                "closingLine": 2.5,
                "closingPrice": -110.0,
                "clv": 0.25,
                "clvType": "POINTS",
            }

        mocked_append_outcome.side_effect = _fake_append
        out = dl.run_personal_postgame_lifecycle(
            fetch_scores_fn=lambda event_id: {
                "evt-legacy-1": {"status": "FINAL", "finalAwayScore": 24, "finalHomeScore": 20},
                "evt-legacy-2": {"status": "FINAL", "finalAwayScore": 21, "finalHomeScore": 24},
            }.get(event_id)
        )

    assert out["seeded"] == 2
    assert out["settled"] == 2
    dashboard = dl.get_personal_wager_dashboard()
    assert dashboard["count"] == 2
    assert dashboard["pendingCount"] == 0
    assert dashboard["unknownStakeCount"] == 2
    assert dashboard["unknownStakeSettledCount"] == 2
    assert dashboard["settledRisk"] == 0.0
    assert dashboard["roi"] is None
    assert dashboard["totalPL"] == 0.0
    assert dashboard["currentBankroll"] == 1000.0

    wagers = dl.list_personal_wagers()
    assert len(wagers) == 2
    assert all(w["amountRisked"] is None for w in wagers)
    assert all(w["unitsRisked"] is None for w in wagers)
    assert {w["result"] for w in wagers} == {"WIN", "PUSH"}


def test_ensure_schema_is_idempotent_and_preserves_existing_ledger_rows(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    db_path = tmp_path / "ledger.db"
    monkeypatch.setattr(dl, "_DB_PATH", db_path)

    con = sqlite3.connect(str(db_path))
    con.executescript(
        """
        CREATE TABLE decision_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id TEXT NOT NULL UNIQUE,
            decision_group_id TEXT NOT NULL,
            decision_version INTEGER NOT NULL,
            supersedes_decision_id TEXT,
            publication_type TEXT NOT NULL,
            published_at_utc TEXT NOT NULL,
            season INTEGER NOT NULL,
            week INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            commence_time TEXT,
            away_team TEXT,
            home_team TEXT,
            selection TEXT NOT NULL,
            market TEXT NOT NULL,
            side TEXT,
            point REAL,
            price REAL,
            sportsbook TEXT,
            raw_probability REAL,
            calibrated_probability REAL,
            push_probability REAL,
            loss_probability REAL,
            raw_edge REAL,
            calibrated_edge REAL,
            current_ev REAL,
            fair_line REAL,
            true_playable_to REAL,
            true_playable_to_status TEXT,
            si_score REAL,
            si_grade TEXT,
            si_rank INTEGER,
            recommendation TEXT,
            qualification_status TEXT,
            qualification_reasons_json TEXT,
            model_version TEXT,
            probability_engine_version TEXT,
            calibration_version TEXT,
            si_score_version TEXT,
            ranking_version TEXT,
            qualification_policy_version TEXT,
            git_commit_hash TEXT,
            odds_provider TEXT,
            odds_timestamp TEXT,
            model_timestamp TEXT,
            market_timestamp TEXT,
            source_snapshot_id TEXT,
            payload_hash TEXT NOT NULL,
            canonical_payload TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            recorded_at_utc TEXT NOT NULL
        );

        CREATE TABLE decision_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            outcome_id TEXT NOT NULL UNIQUE,
            decision_id TEXT NOT NULL,
            captured_at_utc TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            canonical_payload TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            recorded_at_utc TEXT NOT NULL
        );

        CREATE TABLE personal_wager_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wager_id TEXT NOT NULL UNIQUE,
            placed_at_utc TEXT NOT NULL,
            event_id TEXT NOT NULL,
            commence_time TEXT,
            away_team TEXT,
            home_team TEXT,
            market TEXT,
            side TEXT,
            sportsbook TEXT,
            line REAL,
            american_odds REAL,
            amount_risked REAL NOT NULL,
            units_risked REAL NOT NULL,
            unit_size_at_bet REAL NOT NULL,
            decision_id TEXT,
            source_snapshot_id TEXT,
            sia_confidence_score REAL,
            sia_tier TEXT,
            model_probability_at_bet REAL,
            calibrated_probability_at_bet REAL,
            implied_probability_at_bet REAL,
            edge_at_bet REAL,
            ev_at_bet REAL,
            opening_line REAL,
            recommendation_line REAL,
            closing_line REAL,
            closing_price REAL,
            clv_points REAL,
            clv_percent REAL,
            result TEXT NOT NULL DEFAULT 'PENDING',
            amount_won_lost REAL,
            units_won_lost REAL,
            settled_at_utc TEXT,
            recorded_at_utc TEXT NOT NULL
        );

        INSERT INTO decision_ledger (
            decision_id,
            decision_group_id,
            decision_version,
            publication_type,
            published_at_utc,
            season,
            week,
            event_id,
            selection,
            market,
            payload_hash,
            canonical_payload,
            idempotency_key,
            recorded_at_utc
        ) VALUES (
            'dec-existing',
            'grp-existing',
            1,
            'MY_CARD',
            '2026-09-13T17:00:00+00:00',
            2026,
            1,
            'evt-existing',
            'NO +3',
            'spread',
            'h1',
            '{}',
            'idem-existing',
            '2026-09-13T17:00:00+00:00'
        );

        INSERT INTO decision_outcomes (
            outcome_id,
            decision_id,
            captured_at_utc,
            payload_hash,
            canonical_payload,
            idempotency_key,
            recorded_at_utc
        ) VALUES (
            'out-existing',
            'dec-existing',
            '2026-09-13T23:00:00+00:00',
            'h2',
            '{}',
            'idem-out-existing',
            '2026-09-13T23:00:00+00:00'
        );
        """
    )
    con.commit()
    con.close()

    dl._ensure_schema()
    dl._ensure_schema()

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    decision_count = con.execute("SELECT COUNT(*) AS c FROM decision_ledger WHERE decision_id = 'dec-existing'").fetchone()["c"]
    outcome_count = con.execute("SELECT COUNT(*) AS c FROM decision_outcomes WHERE outcome_id = 'out-existing'").fetchone()["c"]
    p_cols = {
        str(row["name"]): int(row["notnull"])
        for row in con.execute("PRAGMA table_info(personal_wager_ledger)").fetchall()
    }
    con.close()

    assert decision_count == 1
    assert outcome_count == 1
    assert p_cols["amount_risked"] == 0
    assert p_cols["units_risked"] == 0
    assert p_cols["unit_size_at_bet"] == 0


def test_personal_settlement_does_not_interfere_with_official_flow(tmp_path, monkeypatch):
    import app.services.decision_ledger as dl

    monkeypatch.setattr(dl, "_DB_PATH", tmp_path / "ledger.db")

    official_payload = _decision_payload("evt-official-alone")
    official_id = _post_decision(official_payload).json()["decisionId"]
    assert _publish_official_slot(official_id, week=8).status_code == 200

    out = dl.run_personal_postgame_lifecycle(
        fetch_scores_fn=lambda event_id: {"status": "FINAL", "finalAwayScore": 17, "finalHomeScore": 24}
    )
    assert out["checked"] == 0
    assert out["settled"] == 0

    con = sqlite3.connect(str(tmp_path / "ledger.db"))
    count = con.execute("SELECT COUNT(*) FROM decision_outcomes").fetchone()[0]
    con.close()
    assert count == 0
