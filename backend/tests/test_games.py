from datetime import datetime

import pytest
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
        "betStatus",
        "qualificationStatus",
        "spreadSource",
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


def test_game_opportunity_endpoint_always_returns_intelligence_report() -> None:
    games_response = client.get("/api/games")
    assert games_response.status_code == 200

    event_id = games_response.json()["games"][0]["eventId"]
    response = client.get(f"/api/games/{event_id}/opportunity")
    assert response.status_code == 200

    payload = response.json()
    assert payload["eventId"] == event_id
    assert "intelligenceReport" in payload
    assert "opportunity" in payload

    opportunity = payload["opportunity"]
    if opportunity is not None:
        assert "fairPrice" in opportunity
        assert "fairLine" in opportunity
        assert "truePlayableTo" in opportunity
        assert "truePlayableToStatus" in opportunity
        assert "truePlayableToReason" in opportunity
        assert "worstObservedPlayablePrice" in opportunity
        assert "worstObservedPlayablePriceStatus" in opportunity
        assert "worstObservedPlayablePriceReason" in opportunity
        assert "playableTo" in opportunity
        assert "playableToStatus" in opportunity
        assert "playableToReason" in opportunity
        assert "currentWinProbability" in opportunity
        assert "currentPushProbability" in opportunity
        assert "currentLossProbability" in opportunity
        assert "currentEV" in opportunity
        assert "minimumPlayableEV" in opportunity
        assert "bestAvailablePrice" in opportunity
        assert "bestAvailableLine" in opportunity
        assert opportunity["playableToStatus"] in {"AVAILABLE", "UNAVAILABLE"}
        assert opportunity["truePlayableToStatus"] in {"AVAILABLE", "UNAVAILABLE"}
        assert opportunity.get("playableTo") == opportunity.get("worstObservedPlayablePrice")
        if opportunity.get("currentWinProbability") is not None:
            total_prob = (
                float(opportunity.get("currentWinProbability") or 0)
                + float(opportunity.get("currentPushProbability") or 0)
                + float(opportunity.get("currentLossProbability") or 0)
            )
            assert abs(total_prob - 1.0) < 1e-6

    report = payload["intelligenceReport"]
    assert report["betStatus"] in {"STRONG BET", "QUALIFIED", "LEAN", "NO QUALIFIED BET", "INSUFFICIENT DATA"}
    assert "qualificationStatus" in report
    assert isinstance(report.get("qualificationReasons", []), list)
    assert report.get("betTrigger", {}).get("available") is False
    assert report.get("betTrigger", {}).get("message") == "Actionable price not currently available"


def test_game_opportunity_lifecycle_contract_is_exposed_read_only() -> None:
    games_response = client.get("/api/games")
    assert games_response.status_code == 200

    event_id = games_response.json()["games"][0]["eventId"]
    response = client.get(f"/api/games/{event_id}/opportunity")
    assert response.status_code == 200

    payload = response.json()
    assert "lifecycle" in payload
    lifecycle = payload["lifecycle"]
    assert lifecycle["eventId"] == event_id
    assert lifecycle["lifecycleState"] in {"WATCH", "QUALIFIED", "NO_LONGER_QUALIFIED", "SUPERSEDED"}
    assert "summary" in lifecycle
    assert "comparison" in lifecycle
    compare = lifecycle["comparison"]
    assert "qualificationChanged" in compare
    assert "productionEligibilityChanged" in compare
    assert "lineChanged" in compare
    assert "priceChanged" in compare
    assert compare["qualificationChanged"] is False
    assert compare["productionEligibilityChanged"] is False
    assert compare["lineChanged"] is False
    assert compare["priceChanged"] is False
    assert lifecycle["previousSnapshotAvailable"] is False

    lifecycle_response = client.get(f"/api/games/{event_id}/opportunity/lifecycle")
    assert lifecycle_response.status_code == 200
    assert lifecycle_response.json()["eventId"] == event_id
    assert lifecycle_response.json()["lifecycleState"] == lifecycle["lifecycleState"]


def test_lifecycle_missing_history_is_explicitly_unavailable() -> None:
    from app.routes.opportunities import _build_opportunity_lifecycle

    current = {
        "market": "spread",
        "qualificationStatus": "QUALIFIED",
        "recommendation": "STRONG BET",
        "productionEligible": True,
        "point": 2.5,
        "price": -110,
    }

    lifecycle = _build_opportunity_lifecycle("evt-test", current)
    assert lifecycle["previousSnapshotAvailable"] is False
    assert lifecycle["comparison"]["qualificationChanged"] is False
    assert lifecycle["comparison"]["lineChanged"] is False
    assert lifecycle["comparison"]["priceChanged"] is False
    assert lifecycle["lifecycleState"] == "QUALIFIED"


def test_lifecycle_represented_when_qualified_history_disappears() -> None:
    from app.routes.opportunities import _build_opportunity_lifecycle

    previous = {
        "market": "spread",
        "qualificationStatus": "QUALIFIED",
        "recommendation": "STRONG BET",
        "productionEligible": True,
        "point": 2.5,
        "price": -110,
    }

    lifecycle = _build_opportunity_lifecycle("evt-test", None, previous)
    assert lifecycle["previousSnapshotAvailable"] is True
    assert lifecycle["lifecycleState"] == "NO_LONGER_QUALIFIED"
    assert lifecycle["comparison"]["qualificationChanged"] is True


def test_lifecycle_qualified_transition_regression_and_guardrails() -> None:
    from app.routes.opportunities import _opportunity_lifecycle_state

    previous = {
        "market": "spread",
        "qualificationStatus": "QUALIFIED",
        "recommendation": "STRONG BET",
        "productionEligible": True,
        "point": 2.5,
        "price": -110,
    }
    current = {
        "market": "spread",
        "qualificationStatus": "WATCH",
        "recommendation": "WATCH",
        "productionEligible": True,
        "point": 3.0,
        "price": -105,
    }

    assert _opportunity_lifecycle_state(current, previous_snapshot=previous) == "NO_LONGER_QUALIFIED"
    assert _opportunity_lifecycle_state({
        "market": "spread",
        "qualificationStatus": "QUALIFIED",
        "recommendation": "STRONG BET",
        "productionEligible": True,
        "point": 2.5,
        "price": -110,
    }, previous_snapshot=None) == "QUALIFIED"
    assert _opportunity_lifecycle_state({
        "market": "spread",
        "qualificationStatus": "WATCH",
        "recommendation": "WATCH",
        "productionEligible": True,
        "point": 2.5,
        "price": -110,
    }, previous_snapshot=None) == "WATCH"


def test_opportunity_history_is_stable_and_idempotent(tmp_path, monkeypatch) -> None:
    import app.services.opportunity_history as oh

    monkeypatch.setattr(oh, "_DB_PATH", tmp_path / "opp-history.db")
    oh._ensure_schema()

    first = {
        "eventId": "evt-100",
        "market": "spread",
        "side": "away",
        "sportsbook": "DraftKings",
        "point": 3.5,
        "price": -110,
        "qualificationStatus": "WATCH",
        "recommendation": "WATCH",
        "productionEligible": True,
        "snapshotId": "snap-100-a",
        "modelVersion": "m-v1",
        "probabilityEngineVersion": "p-v1",
        "calibrationVersion": "c-v1",
        "rankingVersion": "r-v1",
        "qualificationPolicyVersion": "q-v1",
        "gitCommitHash": "abc123",
    }

    first_record = oh.record_history_snapshot(first)
    assert first_record["opportunityKey"] == oh.canonical_opportunity_key("evt-100", "spread", "away")
    assert first_record["previousSnapshotAvailable"] is False
    assert first_record["currentState"] == "WATCH"

    duplicate = oh.record_history_snapshot(first)
    assert duplicate["historyId"] == first_record["historyId"]
    assert duplicate["idempotent"] is True

    second = dict(first)
    second["point"] = 2.5
    second["price"] = -105
    second["qualificationStatus"] = "QUALIFIED"
    second["recommendation"] = "STRONG BET"
    second["snapshotId"] = "snap-100-b"

    second_record = oh.record_history_snapshot(second)
    assert second_record["previousSnapshotAvailable"] is True
    assert second_record["previousHistoryId"] == first_record["historyId"]
    assert second_record["currentState"] == "QUALIFIED"
    assert second_record["transitionReason"] == "WATCH_TO_QUALIFIED"

    history = oh.read_history_for_event("evt-100", limit=10)
    assert len(history) == 2
    assert history[0]["historyId"] == second_record["historyId"]


def test_opportunity_history_distinguishes_logical_identity_from_quote_identity(tmp_path, monkeypatch) -> None:
    import app.services.opportunity_history as oh

    monkeypatch.setattr(oh, "_DB_PATH", tmp_path / "opp-history-quote.db")
    oh._ensure_schema()

    draftkings = {
        "eventId": "evt-200",
        "market": "spread",
        "side": "home",
        "sportsbook": "DraftKings",
        "point": 3.0,
        "price": -110,
        "qualificationStatus": "QUALIFIED",
        "productionEligible": True,
        "recommendation": "STRONG BET",
        "snapshotId": "snap-200-dk",
    }
    fanduel = dict(draftkings)
    fanduel["sportsbook"] = "FanDuel"
    fanduel["point"] = 2.5
    fanduel["price"] = -105
    fanduel["snapshotId"] = "snap-200-fd"

    first = oh.record_history_snapshot(draftkings)
    second = oh.record_history_snapshot(fanduel)

    assert first["opportunityKey"] == second["opportunityKey"]
    assert first["quoteKey"] != second["quoteKey"]
    assert second["previousHistoryId"] == first["historyId"]


def test_opportunity_history_missing_prior_state_remains_unavailable(tmp_path, monkeypatch) -> None:
    import app.services.opportunity_history as oh

    monkeypatch.setattr(oh, "_DB_PATH", tmp_path / "opp-history-missing.db")
    oh._ensure_schema()

    record = oh.record_history_snapshot({
        "eventId": "evt-300",
        "market": "spread",
        "side": "away",
        "sportsbook": "FanDuel",
        "point": 4.0,
        "price": -110,
        "qualificationStatus": "QUALIFIED",
        "productionEligible": True,
        "recommendation": "STRONG BET",
        "snapshotId": "snap-300-a",
    })

    assert record["previousSnapshotAvailable"] is False
    assert record["currentState"] == "QUALIFIED"
    assert record["transitionReason"] == "NO_PRIOR_STATE"


def test_opportunity_history_database_has_no_unique_same_source_constraint(tmp_path, monkeypatch) -> None:
    import sqlite3

    import app.services.opportunity_history as oh

    monkeypatch.setattr(oh, "_DB_PATH", tmp_path / "opp-history-db-constraint.db")
    oh._ensure_schema()

    con = sqlite3.connect(str(oh._DB_PATH))
    schema_sql = con.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'opportunity_history'"
    ).fetchone()[0]
    con.close()

    assert "UNIQUE(opportunity_key, source_snapshot_id)" not in schema_sql
    assert "PRIMARY KEY" in schema_sql


def test_opportunity_history_same_source_snapshot_distinguishes_qualification_change(tmp_path, monkeypatch) -> None:
    import app.services.opportunity_history as oh

    monkeypatch.setattr(oh, "_DB_PATH", tmp_path / "opp-history-same-source.db")
    oh._ensure_schema()

    first = {
        "eventId": "evt-350",
        "market": "spread",
        "side": "away",
        "sportsbook": "DraftKings",
        "point": 3.5,
        "price": -110,
        "qualificationStatus": "WATCH",
        "recommendation": "WATCH",
        "productionEligible": True,
        "sourceSnapshotId": "snap-350-shared",
        "modelVersion": "m-v1",
        "qualificationPolicyVersion": "q-v1",
    }

    first_record = oh.record_history_snapshot(first)
    second = dict(first)
    second["qualificationStatus"] = "QUALIFIED"
    second["recommendation"] = "STRONG BET"
    second_record = oh.record_history_snapshot(second)

    assert first_record["sourceSnapshotId"] == second_record["sourceSnapshotId"]
    assert first_record["historyId"] != second_record["historyId"]
    assert second_record["previousHistoryId"] == first_record["historyId"]
    assert second_record["transitionReason"] == "WATCH_TO_QUALIFIED"


def test_opportunity_history_reads_are_deterministic_for_same_timestamps(tmp_path, monkeypatch) -> None:
    import app.services.opportunity_history as oh

    monkeypatch.setattr(oh, "_DB_PATH", tmp_path / "opp-history-ordering.db")
    oh._ensure_schema()

    base = {
        "eventId": "evt-360",
        "market": "spread",
        "side": "home",
        "sportsbook": "DraftKings",
        "point": 2.5,
        "price": -110,
        "qualificationStatus": "WATCH",
        "recommendation": "WATCH",
        "productionEligible": True,
        "sourceSnapshotId": "snap-360-shared",
        "observedAtUTC": "2026-09-07T00:00:00+00:00",
    }
    first = oh.record_history_snapshot(base)
    second = dict(base)
    second["recommendation"] = "LEAN"
    second["qualificationStatus"] = "QUALIFIED"
    second_record = oh.record_history_snapshot(second)

    rows = oh.read_history_for_event("evt-360", limit=10)
    assert [r["historyId"] for r in rows][:2] == [second_record["historyId"], first["historyId"]]
    assert oh.latest_history_for_opportunity("evt-360", "spread", "home")["historyId"] == second_record["historyId"]


def test_opportunity_history_route_records_generated_snapshot_history(tmp_path, monkeypatch) -> None:
    import app.routes.opportunities as route
    import app.services.opportunity_history as oh

    monkeypatch.setattr(oh, "_DB_PATH", tmp_path / "opp-history-route.db")
    oh._ensure_schema()

    board = tmp_path / "ranked_bet_board.csv"
    board.write_text(
        "api_event_id,market,side,point,price,model_prob,implied_prob_raw,recommendation,qualification_status,confidence_score,data_completeness,edge_pp,ev_per_dollar,sportsbook,away_team,home_team,rank\n"
        "evt-500,spread,home,3.5,-110,0.55,0.5,STRONG BET,QUALIFIED,80,1.0,0.05,0.07,DraftKings,TeamA,TeamB,1\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(route, "RANKED_BET_BOARD", board)
    monkeypatch.setattr(route, "_record_history_for_snapshot", lambda snapshot_id, opportunities, observed_at_utc=None: [
        oh.record_history_snapshot(
            oh.build_history_snapshot_from_opportunity(
                opportunities[0],
                source_snapshot_id=snapshot_id,
                observed_at_utc=observed_at_utc,
            )
        )
    ])

    calls = []
    original = route._record_history_for_snapshot
    def fake_record(snapshot_id, opportunities, observed_at_utc=None):
        calls.append(snapshot_id)
        return original(snapshot_id, opportunities, observed_at_utc=observed_at_utc)
    monkeypatch.setattr(route, "_record_history_for_snapshot", fake_record)

    from app.services.games import service as games_service

    monkeypatch.setattr(games_service, "list_games", lambda week=None, game_date=None: {"games": [{"eventId": "evt-500"}], "availableWeeks": [1]})

    result = route.get_opportunities(limit=10, best_lines_only=True, week=1)
    assert result["snapshotId"]
    assert calls == [result["snapshotId"]]
    history = oh.read_history_for_event("evt-500", limit=10)
    assert len(history) == 1
    assert history[0]["sourceSnapshotId"] == result["snapshotId"]
    assert history[0]["qualificationStatus"] == "QUALIFIED"


def test_opportunity_history_missing_provenance_is_skipped_safely(tmp_path, monkeypatch) -> None:
    import app.routes.opportunities as route
    import app.services.opportunity_history as oh

    monkeypatch.setattr(oh, "_DB_PATH", tmp_path / "opp-history-missing-provenance.db")
    oh._ensure_schema()

    records = route._record_history_for_snapshot(None, [{"eventId": "evt-600", "market": "spread", "side": "away", "qualificationStatus": "QUALIFIED"}])
    assert records == []

    with pytest.raises(ValueError):
        oh.build_history_snapshot_from_opportunity({"eventId": "evt-600", "market": "spread", "side": "away"}, source_snapshot_id="")


def test_history_db_path_resolves_to_persistent_data_in_render(monkeypatch) -> None:
    import app.services.opportunity_history as oh

    monkeypatch.setattr(oh, "_DB_PATH", None)
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", "/data/NFL_Analytics_OS_v1_9")
    monkeypatch.delenv("OPPORTUNITY_HISTORY_DB_PATH", raising=False)

    assert str(oh.resolve_history_db_path()) == "/data/NFL_Analytics_OS_v1_9/opportunity_history.sqlite3"


def test_history_db_path_rejects_backend_app_location_in_render(monkeypatch) -> None:
    import app.services.opportunity_history as oh

    monkeypatch.setattr(oh, "_DB_PATH", None)
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("OPPORTUNITY_HISTORY_DB_PATH", "backend/app/.opportunity_history.sqlite3")

    with pytest.raises(RuntimeError):
        oh.resolve_history_db_path()


def test_history_db_local_test_path_still_works(tmp_path, monkeypatch) -> None:
    import app.services.opportunity_history as oh

    monkeypatch.setattr(oh, "_DB_PATH", None)
    monkeypatch.setenv("RENDER", "false")
    monkeypatch.setenv("OPPORTUNITY_HISTORY_DB_PATH", str(tmp_path / "opportunity_history_test.sqlite3"))

    oh._ensure_schema()
    resolved = oh.resolve_history_db_path()
    assert resolved.exists()
    assert str(resolved).startswith(str(tmp_path))


def test_refresh_history_records_only_real_persisted_provenance(tmp_path, monkeypatch) -> None:
    import duckdb

    import app.runtime_jobs.odds_refresh as refresh_job
    import app.services.opportunity_history as oh

    monkeypatch.setattr(oh, "_DB_PATH", tmp_path / "opp-history-refresh-provenance.db")
    oh._ensure_schema()

    con = duckdb.connect(str(tmp_path / "odds-refresh-snapshot.duckdb"))
    con.execute(
        "CREATE TABLE odds_snapshots (fetched_at TIMESTAMP, api_event_id VARCHAR, commence_time TIMESTAMP, home_team VARCHAR, away_team VARCHAR, home_code VARCHAR, away_code VARCHAR, bookmaker_key VARCHAR, bookmaker_title VARCHAR, market_key VARCHAR, outcome_name VARCHAR, outcome_code VARCHAR, point DOUBLE, price DOUBLE, implied_prob DOUBLE, snapshot_type VARCHAR, source VARCHAR)"
    )
    con.execute(
        "INSERT INTO odds_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            "2026-09-07T00:00:00+00:00",
            "evt-610",
            "2026-09-07T18:00:00+00:00",
            "TeamA",
            "TeamB",
            "TEAMA",
            "TEAMB",
            "draftkings",
            "DraftKings",
            "spreads",
            "TeamA",
            "home",
            3.5,
            -110,
            0.524,
            "current",
            "the_odds_api",
        ],
    )
    con.commit()

    records = refresh_job._record_history_from_persisted_snapshot(
        con,
        source_snapshot_id="odds-refresh:2026-09-07T00:00:00+00:00Z",
        fetched_at=datetime.fromisoformat("2026-09-07T00:00:00+00:00"),
    )
    con.close()

    assert len(records) == 1
    assert records[0]["sourceSnapshotId"] == "odds-refresh:2026-09-07T00:00:00+00:00Z"
    assert records[0]["sportsbook"] == "DraftKings"
    assert records[0]["point"] == 3.5
    assert records[0]["price"] == -110
    assert records[0]["qualificationStatus"] is None
    assert records[0]["recommendation"] is None


def test_refresh_history_write_failure_does_not_fail_refresh_or_repeat_provider_call(tmp_path, monkeypatch) -> None:
    from datetime import timedelta, timezone

    import app.runtime_jobs.odds_refresh as refresh_job

    root = tmp_path / "NFL_Analytics_OS_v1_9"
    (root / "database").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(root))
    monkeypatch.setenv("RENDER", "false")

    monkeypatch.setattr(refresh_job, "_load_regular_season_event_keys", lambda: set())
    monkeypatch.setattr(refresh_job, "_load_target_regular_season_match_index", lambda now_utc: ({}, None))
    monkeypatch.setattr(refresh_job, "_evaluate_core_quota_guard", lambda: {"allowed": True})

    calls = {"provider": 0, "history": 0}

    class _FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload
            self.headers = {
                "x-requests-remaining": "100",
                "x-requests-used": "1",
                "x-requests-last": "1",
            }

        def json(self):
            return self._payload

    kickoff = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    provider_payload = [
        {
            "id": "evt-700",
            "commence_time": kickoff,
            "home_team": "Arizona Cardinals",
            "away_team": "Atlanta Falcons",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "markets": [
                        {
                            "key": "spreads",
                            "outcomes": [
                                {"name": "Arizona Cardinals", "point": -2.5, "price": -110},
                            ],
                        }
                    ],
                }
            ],
        }
    ]

    def _fake_execute(signature, *, api_key):
        calls["provider"] += 1
        return _FakeResponse(provider_payload)

    def _fake_history(*args, **kwargs):
        calls["history"] += 1
        raise RuntimeError("simulated-history-db-error")

    monkeypatch.setattr(refresh_job, "_execute_core_request", _fake_execute)
    monkeypatch.setattr(refresh_job, "_record_history_from_persisted_snapshot", _fake_history)

    out = refresh_job.run_refresh()

    assert out["providerRequestSkipped"] is False
    assert out["rows"] == 1
    assert "OPPORTUNITY_HISTORY_RECORDING_FAILED" in str(out.get("warningCode") or "")
    assert calls["provider"] == 1
    assert calls["history"] == 1


def test_opportunity_history_disappeared_opportunity_is_not_forced_into_current_board(tmp_path, monkeypatch) -> None:
    import app.services.opportunity_history as oh

    monkeypatch.setattr(oh, "_DB_PATH", tmp_path / "opp-history-disappeared.db")
    oh._ensure_schema()

    prior = {
        "eventId": "evt-400",
        "market": "spread",
        "side": "home",
        "sportsbook": "DraftKings",
        "point": 3.0,
        "price": -110,
        "qualificationStatus": "QUALIFIED",
        "productionEligible": True,
        "recommendation": "STRONG BET",
        "snapshotId": "snap-400-a",
    }
    prior_record = oh.record_history_snapshot(prior)
    disappear = {
        "eventId": "evt-400",
        "market": "spread",
        "side": "home",
        "sportsbook": "DraftKings",
        "point": None,
        "price": None,
        "qualificationStatus": "NOT_QUALIFIED",
        "productionEligible": False,
        "recommendation": "WATCH",
        "snapshotId": "snap-400-b",
    }
    disappear_record = oh.record_history_snapshot(disappear)

    assert prior_record["currentState"] == "QUALIFIED"
    assert disappear_record["previousHistoryId"] == prior_record["historyId"]
    assert disappear_record["currentState"] == "NO_LONGER_QUALIFIED"
    assert disappear_record["transitionReason"] == "QUALIFIED_TO_NO_LONGER_QUALIFIED"


def test_game_opportunity_history_endpoint_empty_history(tmp_path, monkeypatch) -> None:
    import app.services.opportunity_history as oh

    monkeypatch.setattr(oh, "_DB_PATH", tmp_path / "opp-history-endpoint-empty.db")
    oh._ensure_schema()

    response = client.get("/api/games/evt-empty/opportunity/history")
    assert response.status_code == 200
    payload = response.json()
    assert payload["eventId"] == "evt-empty"
    assert payload["count"] == 0
    assert payload["history"] == []
    assert payload["limit"] == 10
    assert payload["readOnly"] is True
    assert "executionRestriction" in payload


def test_game_opportunity_history_endpoint_multiple_rows_and_ordering(tmp_path, monkeypatch) -> None:
    import app.services.opportunity_history as oh

    monkeypatch.setattr(oh, "_DB_PATH", tmp_path / "opp-history-endpoint-order.db")
    oh._ensure_schema()

    base = {
        "eventId": "evt-hist-1",
        "market": "spread",
        "side": "home",
        "sportsbook": "DraftKings",
        "point": 2.5,
        "price": -110,
        "qualificationStatus": "WATCH",
        "recommendation": "WATCH",
        "productionEligible": False,
        "sourceSnapshotId": "snap-a",
        "observedAtUTC": "2026-09-07T00:00:00+00:00",
    }
    first = oh.record_history_snapshot(base)
    second_payload = dict(base)
    second_payload["sourceSnapshotId"] = "snap-b"
    second_payload["qualificationStatus"] = "QUALIFIED"
    second_payload["recommendation"] = "STRONG BET"
    second = oh.record_history_snapshot(second_payload)

    response = client.get("/api/games/evt-hist-1/opportunity/history?limit=10")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["history"][0]["historyId"] == second["historyId"]
    assert payload["history"][1]["historyId"] == first["historyId"]
    assert payload["history"][0]["transitionReason"] == "WATCH_TO_QUALIFIED"


def test_game_opportunity_history_endpoint_bounded_limit_and_event_isolation(tmp_path, monkeypatch) -> None:
    import app.services.opportunity_history as oh

    monkeypatch.setattr(oh, "_DB_PATH", tmp_path / "opp-history-endpoint-limit.db")
    oh._ensure_schema()

    for i in range(3):
        oh.record_history_snapshot(
            {
                "eventId": "evt-bounded",
                "market": "spread",
                "side": "away",
                "sportsbook": "DraftKings",
                "point": 3.5 - i,
                "price": -110,
                "qualificationStatus": "WATCH",
                "recommendation": "WATCH",
                "productionEligible": False,
                "sourceSnapshotId": f"snap-bound-{i}",
                "observedAtUTC": f"2026-09-07T00:00:0{i}+00:00",
            }
        )

    oh.record_history_snapshot(
        {
            "eventId": "evt-other",
            "market": "spread",
            "side": "away",
            "sportsbook": "DraftKings",
            "point": 1.0,
            "price": -110,
            "qualificationStatus": "WATCH",
            "recommendation": "WATCH",
            "productionEligible": False,
            "sourceSnapshotId": "snap-other",
            "observedAtUTC": "2026-09-07T00:00:10+00:00",
        }
    )

    response = client.get("/api/games/evt-bounded/opportunity/history?limit=2")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["limit"] == 2
    assert all(item["eventId"] == "evt-bounded" for item in payload["history"])


def test_game_opportunity_history_endpoint_response_contract_and_limit_guard(tmp_path, monkeypatch) -> None:
    import app.services.opportunity_history as oh

    monkeypatch.setattr(oh, "_DB_PATH", tmp_path / "opp-history-endpoint-contract.db")
    oh._ensure_schema()

    oh.record_history_snapshot(
        {
            "eventId": "evt-contract",
            "market": "spread",
            "side": "home",
            "sportsbook": "FanDuel",
            "point": -2.5,
            "price": -105,
            "qualificationStatus": "QUALIFIED",
            "recommendation": "STRONG BET",
            "productionEligible": True,
            "sourceSnapshotId": "snap-contract",
            "observedAtUTC": "2026-09-07T00:00:00+00:00",
        }
    )

    response = client.get("/api/games/evt-contract/opportunity/history?limit=26")
    assert response.status_code == 422

    ok = client.get("/api/games/evt-contract/opportunity/history?limit=1")
    assert ok.status_code == 200
    entry = ok.json()["history"][0]
    required = {
        "historyId",
        "eventId",
        "market",
        "side",
        "sportsbook",
        "point",
        "price",
        "qualificationStatus",
        "recommendation",
        "productionEligible",
        "currentState",
        "transitionReason",
        "observedAtUTC",
        "createdAtUTC",
        "previousSnapshotAvailable",
    }
    assert required.issubset(set(entry.keys()))


def test_game_opportunity_lifecycle_summary_contract_not_regressed_by_history_endpoint() -> None:
    games_response = client.get("/api/games")
    assert games_response.status_code == 200
    event_id = games_response.json()["games"][0]["eventId"]

    response = client.get(f"/api/games/{event_id}/opportunity")
    assert response.status_code == 200
    lifecycle = response.json()["lifecycle"]
    assert lifecycle["eventId"] == event_id
    assert lifecycle["readOnly"] is True
    assert "executionRestriction" in lifecycle
