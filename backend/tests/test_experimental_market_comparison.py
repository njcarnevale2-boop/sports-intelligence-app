from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.result_engine.identity import build_canonical_event_identity
from app.services.experimental_market_comparison import (
    CAPTURE_ROOT_RELATIVE,
    STAGING_RUNTIME_ROOT,
    _validate_capture,
    _sha256_bytes,
    _sha256_json,
    load_experimental_market_comparison,
)
from app.routes.experimental_power import router as experimental_power_router


NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
OBSERVED = "2026-11-07T11:59:00Z"


def _power_payload() -> dict:
    return {
        "season": 2026,
        "week": 9,
        "count": 1,
        "analysisType": "EXPERIMENTAL_POWER_ONLY",
        "projectionReadiness": "NOT_ACTIVE",
        "artifactId": "proj-test",
        "artifactHash": "artifact-hash",
        "scheduleVersion": "canonical-schedule-v2:2026:9:8b89dd5f8fbd",
        "scheduleHash": "8b89dd5f8fbd1c8834f7fdcc4c8577c07b487acbba6e5adeb14ace9005e3b9a0",
        "modelVersion": "sia_newbaseline_2018zero_reg_v1",
        "productionEligible": False,
        "officialEligible": False,
        "probabilitiesComputed": False,
        "evComputed": False,
        "games": [
            {
                "eventId": "2026_09_CIN_ATL",
                "awayTeam": "CIN",
                "homeTeam": "ATL",
                "kickoffUtc": "2026-11-08T14:30:00Z",
                "homeExpectedMargin": 1.5,
                "homeFairSpread": -1.5,
                "productionEligible": False,
                "officialEligible": False,
            }
        ],
    }


def _capture_fixture(tmp_path: Path, power: dict, *, observed: str = OBSERVED, quote_updated: str = OBSERVED) -> Path:
    capture_dir = tmp_path / "data/sia-backend-staging/research/week9_odds_captures/capture-test"
    capture_dir.mkdir(parents=True)
    game = power["games"][0]
    identity = build_canonical_event_identity(
        season=2026,
        week=9,
        kickoff_utc=game["kickoffUtc"],
        away_team=game["awayTeam"],
        home_team=game["homeTeam"],
    )
    snapshot = {
        "status": "CAPTURED_STAGING_ONLY",
        "capture_version": "week9_odds_live_capture_v1",
        "mode": "AUTHORIZED_ONE_SHOT_STAGING_CAPTURE",
        "data_classification": "LIVE_PROVIDER_RESPONSE",
        "live_provider_data": True,
        "external_requests_made": 1,
        "request_count": 1,
        "staging_writes_made": False,
        "production_writes_made": False,
        "database_writes_made": False,
        "opportunity_history_writes_made": False,
        "active_pointer_writes_made": False,
        "official_publication_made": False,
        "observed_at": observed,
        "max_quote_age_seconds": 300,
        "candidate": {
            "candidate_id": power["artifactId"],
            "candidate_hash": power["artifactHash"],
            "schedule_version": "canonical-schedule-v2:2026:9:8b89dd5f8fbd",
            "schedule_hash": "8b89dd5f8fbd1c8834f7fdcc4c8577c07b487acbba6e5adeb14ace9005e3b9a0",
        },
        "capture_authorization": {
            "explicit_live_authorization_verified": True,
            "environment": "staging",
            "service_name": "sia-backend-staging",
            "candidate_id": power["artifactId"],
            "candidate_hash": power["artifactHash"],
            "credit_limit": 1,
        },
        "quotes": [
            {
                "candidate_event_id": game["eventId"],
                "canonical_event_key": identity.canonical_event_key,
                "provider_event_id": "provider-event-1",
                "away_team": game["awayTeam"],
                "home_team": game["homeTeam"],
                "kickoff_utc": game["kickoffUtc"],
                "sportsbook_key": "fixture-book",
                "sportsbook_title": "Fixture Book",
                "market": "spreads",
                "outcome_side": "home",
                "point": -2.5,
                "price": -110,
                "bookmaker_last_update": quote_updated,
                "market_last_update": quote_updated,
                "effective_quote_update": quote_updated,
                "observation_timestamp": observed,
            },
            {
                "candidate_event_id": game["eventId"],
                "canonical_event_key": identity.canonical_event_key,
                "provider_event_id": "provider-event-1",
                "away_team": game["awayTeam"],
                "home_team": game["homeTeam"],
                "kickoff_utc": game["kickoffUtc"],
                "sportsbook_key": "fixture-book",
                "sportsbook_title": "Fixture Book",
                "market": "spreads",
                "outcome_side": "away",
                "point": 2.5,
                "price": -110,
                "bookmaker_last_update": quote_updated,
                "market_last_update": quote_updated,
                "effective_quote_update": quote_updated,
                "observation_timestamp": observed,
            },
        ],
        "validation": {
            "allowlist_games": 15,
            "pregame_eligible_games": 1,
            "eligible_games_missing_spread_quotes": [],
            "spread_pairs_validated": 1,
        },
    }
    snapshot["snapshot_sha256"] = _sha256_json(snapshot)
    snapshot_bytes = (json.dumps(snapshot, sort_keys=True, indent=2) + "\n").encode()
    (capture_dir / "snapshot.json").write_bytes(snapshot_bytes)
    manifest = {
        "capture_version": "week9_odds_live_capture_v1",
        "environment": "staging",
        "provider_requests": 1,
        "database_writes": False,
        "opportunity_history_writes": False,
        "active_pointer_writes": False,
        "official_publication": False,
        "snapshot_file": "snapshot.json",
        "snapshot_sha256": _sha256_bytes(snapshot_bytes),
        "candidate_id": power["artifactId"],
        "candidate_hash": power["artifactHash"],
        "schedule_hash": snapshot["candidate"]["schedule_hash"],
    }
    manifest["manifest_sha256"] = _sha256_json(manifest)
    (capture_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return capture_dir


def _staging_env(monkeypatch, tmp_path: Path, capture_dir: Path | None = None):
    runtime_root = tmp_path / "data/sia-backend-staging"
    runtime_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.services.experimental_market_comparison.STAGING_RUNTIME_ROOT", runtime_root)
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RENDER_SERVICE_NAME", "sia-backend-staging")
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(runtime_root))
    monkeypatch.setenv("SIA_EXPERIMENTAL_POWER_ENABLED", "true")
    if capture_dir is not None:
        monkeypatch.setenv("SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR", str(capture_dir))
    else:
        monkeypatch.delenv("SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR", raising=False)


def test_missing_capture_returns_explicit_market_data_unavailable(monkeypatch, tmp_path: Path):
    power = _power_payload()
    monkeypatch.setattr("app.services.experimental_market_comparison.load_experimental_power", lambda **_: power)
    _staging_env(monkeypatch, tmp_path)
    result = load_experimental_market_comparison(season=2026, week=9)
    assert result["marketDataStatus"] == "MARKET_DATA_UNAVAILABLE"
    assert result["marketDataReason"] == "NO_VALIDATED_CAPTURE_CONFIGURED"
    assert result["games"][0]["marketQuotes"] == []


def test_non_staging_identity_is_rejected_before_loading_candidate(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RENDER_SERVICE_NAME", "sia-backend-production")
    monkeypatch.setenv("NFL_ANALYTICS_OS_ROOT", str(tmp_path / "production-root"))
    monkeypatch.setattr(
        "app.services.experimental_market_comparison.load_experimental_power",
        lambda **_: (_ for _ in ()).throw(AssertionError("candidate loader must not run outside staging")),
    )
    import pytest
    from app.services.experimental_power import ExperimentalPowerUnavailable

    with pytest.raises(ExperimentalPowerUnavailable, match="STAGING_ONLY"):
        load_experimental_market_comparison(season=2026, week=9)


def test_market_comparison_route_is_registered_exactly_once():
    paths = [route.path for route in experimental_power_router.routes]
    assert paths.count("/api/experimental/power-market-comparison") == 1


def test_valid_capture_returns_sportsbook_spread_without_probability_or_ev(monkeypatch, tmp_path: Path):
    power = _power_payload()
    monkeypatch.setattr("app.services.experimental_market_comparison.load_experimental_power", lambda **_: power)
    capture_dir = _capture_fixture(tmp_path, power)
    _staging_env(monkeypatch, tmp_path, capture_dir)
    monkeypatch.setattr("app.services.experimental_market_comparison._utc_now", lambda: NOW)
    _validate_capture(power=power, capture_dir=capture_dir, now=NOW)
    result = load_experimental_market_comparison(season=2026, week=9)
    assert result["marketDataStatus"] == "AVAILABLE", result["marketDataReason"]
    quote = result["games"][0]["marketQuotes"][0]
    assert quote["sportsbookKey"] == "fixture-book"
    assert quote["homeSpreadPoint"] == -2.5
    assert quote["awaySpreadPoint"] == 2.5
    assert quote["homePrice"] == -110
    assert result["probabilitiesComputed"] is False
    assert result["evComputed"] is False


def test_stale_capture_and_identity_mismatch_return_unavailable(monkeypatch, tmp_path: Path):
    power = _power_payload()
    monkeypatch.setattr("app.services.experimental_market_comparison.load_experimental_power", lambda **_: power)
    capture_dir = _capture_fixture(tmp_path, power)
    _staging_env(monkeypatch, tmp_path, capture_dir)
    monkeypatch.setattr("app.services.experimental_market_comparison._utc_now", lambda: NOW + timedelta(minutes=10))
    stale = load_experimental_market_comparison(season=2026, week=9)
    assert stale["marketDataStatus"] == "MARKET_DATA_UNAVAILABLE"

    monkeypatch.setattr("app.services.experimental_market_comparison._utc_now", lambda: NOW)
    altered = {**power, "artifactHash": "wrong"}
    monkeypatch.setattr("app.services.experimental_market_comparison.load_experimental_power", lambda **_: altered)
    mismatch = load_experimental_market_comparison(season=2026, week=9)
    assert mismatch["marketDataStatus"] == "MARKET_DATA_UNAVAILABLE"


def test_quote_is_not_returned_after_its_game_kicks_off(monkeypatch, tmp_path: Path):
    power = _power_payload()
    monkeypatch.setattr("app.services.experimental_market_comparison.load_experimental_power", lambda **_: power)
    observed = "2026-11-08T14:29:00Z"
    quote_updated = "2026-11-08T14:28:00Z"
    capture_dir = _capture_fixture(tmp_path, power, observed=observed, quote_updated=quote_updated)
    _staging_env(monkeypatch, tmp_path, capture_dir)
    monkeypatch.setattr(
        "app.services.experimental_market_comparison._utc_now",
        lambda: datetime(2026, 11, 8, 14, 31, tzinfo=timezone.utc),
    )
    result = load_experimental_market_comparison(season=2026, week=9)
    assert result["marketDataStatus"] == "MARKET_DATA_UNAVAILABLE"
    assert result["games"][0]["marketQuotes"] == []