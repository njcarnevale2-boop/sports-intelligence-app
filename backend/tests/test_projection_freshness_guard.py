from __future__ import annotations

import json
import csv
import gzip
import io
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from app.services.power_engine import CANONICAL_NFL_TEAMS
from app.services.power_engine.persistence import PowerEngineStore
from app.services.power_engine.projection_publication import resolve_projection_readiness
from app.services.result_engine import ResultEngineStore
from app.services.schedule_engine import ScheduleEngineStore, ingest_nflverse_schedule_source_bytes, load_active_schedule


@dataclass
class _FakeFairPriceResult:
    fair_price: float | None = -118.0
    fair_line: float | None = -118.0
    true_playable_to: float | None = -112.0
    true_playable_to_status: str = "AVAILABLE"
    true_playable_to_reason: str = "TEST"
    worst_observed_playable_price: float | None = -112.0
    worst_observed_playable_price_status: str = "AVAILABLE"
    worst_observed_playable_price_reason: str = "TEST"
    playable_to: float | None = -112.0
    playable_to_status: str = "AVAILABLE"
    playable_to_reason: str = "TEST"
    current_win_probability: float | None = 0.62
    current_push_probability: float | None = 0.02
    current_loss_probability: float | None = 0.36
    current_ev: float | None = 0.123
    minimum_playable_ev: float | None = 0.0
    best_available_price: float | None = -110.0
    best_available_line: float | None = 3.0


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _base_readiness(*, status: str, reason: str) -> dict:
    return {
        "projectionReadiness": status,
        "projectionReadinessReason": reason,
        "projectionSeason": 2026,
        "projectionWeek": 3,
        "projectionPowerThroughWeek": 2 if status == "CURRENT" else 0,
        "projectionArtifactId": "proj-test",
        "projectionArtifactHash": "hash-test",
        "projectionScheduleVersion": "schedule-v1:2026:3:test",
        "projectionScheduleHash": "schedule-hash-test",
        "projectionValidationStatus": "VALID" if status == "CURRENT" else "VALID",
        "projectionPowerSnapshotId": "snap-test",
        "projectionPowerSnapshotHash": "snap-hash-test",
        "projectionActivatedAt": _iso_now(),
        "expectedPowerThroughWeek": 2,
    }


def _write_ranked_board(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_game_projections(path: Path, event_ids: list[str]) -> None:
    rows = []
    for eid in event_ids:
        rows.append(
            {
                "api_event_id": eid,
                "season": 2026,
                "week": 3,
                "commence_time": "2026-09-20T17:00:00+00:00",
                "away_team": "NO",
                "home_team": "ATL",
                "away_power": 0.0,
                "home_power": 0.0,
                "model_margin_home": -1.0,
                "market_margin_home": -2.5,
                "market_home_spread": -2.5,
                "spread_edge_points": 0.0,
                "home_cover_prob_est": 0.5,
                "home_cover_fair_odds": -100.0,
                "model_total_baseline": 45.0,
                "market_total": 44.0,
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)


def _patch_opportunities_dependencies(monkeypatch, tmp_path: Path, *, readiness: dict, quote_last_updated: str | None = None):
    import app.routes.opportunities as opportunities_route
    from app.services.games import service as games_service

    ranked_board = tmp_path / "ranked_bet_board.csv"
    projections = tmp_path / "current_game_projections.csv"

    rows = [
        {
            "api_event_id": "evt-guard-1",
            "commence_time": "2026-09-20T17:00:00+00:00",
            "away_team": "NO",
            "home_team": "ATL",
            "market": "spread",
            "side": "away",
            "point": 3.0,
            "sportsbook": "DraftKings",
            "price": -110,
            "model_prob": 0.58,
            "implied_prob_raw": 0.55,
            "fair_odds": -120,
            "edge_pp": 0.03,
            "ev_per_dollar": 0.04,
            "kelly_full": 0.03,
            "kelly_20pct": 0.006,
            "recommendation": "BET",
            "confidence_score": 70,
            "data_completeness": 0.95,
            "market_confidence": 0.8,
            "model_confidence": 0.7,
            "rank": 1,
            "qualification_status": "QUALIFIED",
            "qualification_reasons": ["edge", "ev"],
        }
    ]

    _write_ranked_board(ranked_board, rows)
    _write_game_projections(projections, ["evt-guard-1"])

    monkeypatch.setattr(opportunities_route, "RANKED_BET_BOARD", ranked_board)
    monkeypatch.setattr(opportunities_route, "GAME_PROJECTIONS", projections)

    monkeypatch.setattr(
        opportunities_route,
        "resolve_canonical_week_metadata",
        lambda: {
            "season": 2026,
            "week": 3,
            "status": "ACTIVE",
            "source": "test",
            "reason": "TEST",
        },
    )
    monkeypatch.setattr(opportunities_route, "build_week_readiness", lambda canonical=None: {"status": "READY"})

    monkeypatch.setattr(
        opportunities_route,
        "resolve_projection_readiness",
        lambda season, week: readiness,
    )
    monkeypatch.setattr(
        opportunities_route,
        "load_active_projection_artifact_by_identity",
        lambda season, week, artifact_id, artifact_hash: {
            "projection_rows": [
                {
                    "event_id": "evt-guard-1",
                    "season": 2026,
                    "week": 3,
                    "kickoff_utc": "2026-09-20T17:00:00Z",
                    "away_team": "NO",
                    "home_team": "ATL",
                    "away_power": 0.0,
                    "home_power": 0.0,
                    "model_margin_home": -1.0,
                    "model_total_baseline": 45.0,
                    "canonical_event_key": "cev-guard-1",
                    "model_version": "model-v1",
                    "probability_version": "prob-v1",
                }
            ]
        },
    )
    monkeypatch.setattr(
        opportunities_route,
        "load_canonical_weekly_schedule",
        lambda season, week, store=None: SimpleNamespace(
            schedule_version=str(readiness.get("projectionScheduleVersion") or "schedule-v1:2026:3:test"),
            schedule_hash=str(readiness.get("projectionScheduleHash") or "schedule-hash-test"),
            season=season,
            week=week,
            events=[
                SimpleNamespace(
                    source_event_id="evt-guard-1",
                    canonical_event_key="cev-guard-1",
                    season=season,
                    week=week,
                    kickoff_utc="2026-09-20T17:00:00Z",
                    away_team="NO",
                    home_team="ATL",
                )
            ],
        ),
    )

    monkeypatch.setattr(
        opportunities_route,
        "get_market_intelligence",
        lambda event_id, market, side: {
            "score": 7.0,
            "signal": "CONFIRMED",
            "steamBooks": 1,
            "booksMoving": 3,
            "booksTracked": 8,
            "consensus": 70,
        },
    )

    class _FakeInjuryContext:
        def build_context(self, away_team: str, home_team: str):
            return {"severity": "neutral", "summary": "neutral"}

    monkeypatch.setattr(opportunities_route, "InjuryMatchupContext", _FakeInjuryContext)

    monkeypatch.setattr(
        opportunities_route,
        "build_fair_price_result",
        lambda row, group_rows, game_projection_row, minimum_playable_ev: _FakeFairPriceResult(),
    )

    now_iso = quote_last_updated or datetime.now(timezone.utc).isoformat()

    monkeypatch.setattr(
        opportunities_route.market_data_service,
        "metadata",
        lambda: {
            "provider": "line_movement_board",
            "lastUpdated": now_iso,
            "dataStatus": "FILE",
        },
    )
    monkeypatch.setattr(
        opportunities_route.market_data_service,
        "all_event_snapshots",
        lambda: {
            "evt-guard-1": {
                "provider": "line_movement_board",
                "lastUpdated": now_iso,
                "dataStatus": "FILE",
                "booksTracked": 8,
                "bestAwaySpread": None,
                "bestHomeSpread": None,
                "bestAwayMoneyline": None,
                "bestHomeMoneyline": None,
                "bestOver": None,
                "bestUnder": None,
                "bestPriceAwaySpread": None,
                "bestPriceHomeSpread": None,
                "bestPriceAwayMoneyline": None,
                "bestPriceHomeMoneyline": None,
                "bestPriceOver": None,
                "bestPriceUnder": None,
            }
        },
    )
    monkeypatch.setattr(
        opportunities_route.market_data_service,
        "records_for_event",
        lambda event_id: [
            {
                "eventId": "evt-guard-1",
                "market": "spread",
                "side": "away",
                "point": 3.0,
                "americanOdds": -110,
                "sportsbook": "DraftKings",
                "lastUpdated": now_iso,
            }
        ]
        if str(event_id) == "evt-guard-1"
        else [],
    )

    monkeypatch.setattr(
        games_service,
        "list_games",
        lambda week=None, include_enrichment=True: {
            "availableWeeks": [3],
            "games": [
                {
                    "eventId": "evt-guard-1",
                    "season": 2026,
                    "week": 3,
                }
            ],
        },
    )

    monkeypatch.setattr(opportunities_route, "_record_history_for_snapshot", lambda *args, **kwargs: [])
    return opportunities_route


def _seed_projection_authority(
    *,
    store: PowerEngineStore,
    season: int = 2026,
    week: int = 3,
    artifact_season: int = 2026,
    artifact_week: int = 3,
    power_through_week: int = 2,
    pointer_hash: str = "artifact-hash-1",
    artifact_hash: str = "artifact-hash-1",
    artifact_id: str = "proj-artifact-1",
    validation_status: str = "VALID",
    schedule_version: str = "schedule-v1:2026:3:test",
    schedule_hash: str = "schedule-hash-1",
    schedule_source_version: str = "source-v1",
) -> None:
    projections_root = store.root_dir / "projections"
    artifacts_dir = projections_root / "artifacts"
    validations_dir = projections_root / "validations"
    active_dir = projections_root / "active"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    validations_dir.mkdir(parents=True, exist_ok=True)
    active_dir.mkdir(parents=True, exist_ok=True)

    artifact = {
        "artifact_id": artifact_id,
        "artifact_hash": artifact_hash,
        "season": artifact_season,
        "week": artifact_week,
        "power_through_week": power_through_week,
        "power_snapshot_id": "snap-1",
        "power_snapshot_hash": "snap-hash-1",
        "schedule_version": schedule_version,
        "schedule_hash": schedule_hash,
        "schedule_source_version": schedule_source_version,
        "model_version": "model-v1",
        "probability_version": "prob-v1",
        "methodology_hash": "methodology-hash",
        "updater_version": "updater-v1",
        "expected_game_count": 16,
        "projected_game_count": 16,
        "coverage_hash": "coverage-hash-1",
        "validation_report_id": "val-1",
        "projection_rows": [
            {
                "event_id": f"evt-{idx}",
                "season": artifact_season,
                "week": artifact_week,
                "kickoff_utc": "2026-09-20T17:00:00Z",
                "away_team": "NO",
                "home_team": "ATL",
                "away_power": 0.0,
                "home_power": 0.0,
                "model_margin_home": -1.0,
                "canonical_event_key": f"cev-{idx}",
                "model_version": "model-v1",
                "probability_version": "prob-v1",
            }
            for idx in range(16)
        ],
    }
    validation = {
        "validation_id": "val-1",
        "artifact_id": artifact_id,
        "status": validation_status,
    }
    pointer = {
        "season": season,
        "week": week,
        "artifact_id": artifact_id,
        "artifact_hash": pointer_hash,
        "power_snapshot_id": "snap-1",
        "power_snapshot_hash": "snap-hash-1",
        "schedule_hash": schedule_hash,
        "activated_at": _iso_now(),
    }

    (artifacts_dir / f"{artifact_id}.json").write_text(json.dumps(artifact), encoding="utf-8")
    (validations_dir / "val-1.json").write_text(json.dumps(validation), encoding="utf-8")
    (active_dir / f"active-{season}-{week}.json").write_text(json.dumps(pointer), encoding="utf-8")


def _seed_active_schedule_authority(tmp_path: Path, *, season: int = 2026, week: int = 3):
    schedule_store = ScheduleEngineStore(root_dir=tmp_path / "schedule")
    result_store = ResultEngineStore(root_dir=tmp_path / "result")
    power_store = PowerEngineStore(root_dir=tmp_path / "power")

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "game_id",
            "season",
            "week",
            "game_type",
            "gameday",
            "gametime",
            "away_team",
            "home_team",
            "weekday",
            "location",
            "result",
            "total",
            "overtime",
            "old_game_id",
            "gsis",
            "nfl_detail_id",
            "pfr",
            "pff",
            "espn",
        ],
    )
    writer.writeheader()
    for idx in range(16):
        away = CANONICAL_NFL_TEAMS[idx * 2]
        home = CANONICAL_NFL_TEAMS[idx * 2 + 1]
        writer.writerow(
            {
                "game_id": f"{season}_{week:02d}_{away}_{home}",
                "season": str(season),
                "week": str(week),
                "game_type": "REG",
                "gameday": "2026-09-27",
                "gametime": f"{13 + (idx % 6):02d}:00",
                "away_team": away,
                "home_team": home,
                "weekday": "Sunday",
            }
        )

    payload = gzip.compress(output.getvalue().encode("utf-8"), mtime=0)
    ingest_nflverse_schedule_source_bytes(
        payload_bytes=payload,
        source_uri="https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv.gz",
        release_tag="schedules",
        release_id="freshness-r1",
        release_published_at="2025-10-01T11:19:34Z",
        release_updated_at="2026-09-26T20:37:03Z",
        target_commitish="main",
        asset_name="games.csv.gz",
        asset_id="freshness-a1",
        asset_updated_at="2026-09-26T20:37:02Z",
        asset_size_bytes_reported=len(payload),
        asset_digest_reported=None,
        http_etag='"abc"',
        http_last_modified="Sat, 26 Sep 2026 20:37:02 GMT",
        store=schedule_store,
        result_store=result_store,
        power_store=power_store,
    )
    return schedule_store, load_active_schedule(season=season, week=week, store=schedule_store)


def test_projection_readiness_current_exact_lineage(tmp_path):
    store = PowerEngineStore(root_dir=tmp_path / "power")
    schedule_store, active = _seed_active_schedule_authority(tmp_path)
    _seed_projection_authority(
        store=store,
        schedule_version=active.schedule_version,
        schedule_hash=active.schedule_hash,
        schedule_source_version=active.source_version,
    )

    readiness = resolve_projection_readiness(season=2026, week=3, power_store=store, schedule_store=schedule_store)

    assert readiness["projectionReadiness"] == "CURRENT"
    assert readiness["projectionPowerThroughWeek"] == 2


def test_projection_readiness_stale_power_wrong_week_and_wrong_season(tmp_path):
    store = PowerEngineStore(root_dir=tmp_path / "power")
    schedule_store, active = _seed_active_schedule_authority(tmp_path)

    _seed_projection_authority(
        store=store,
        power_through_week=0,
        schedule_version=active.schedule_version,
        schedule_hash=active.schedule_hash,
        schedule_source_version=active.source_version,
    )
    assert resolve_projection_readiness(season=2026, week=3, power_store=store, schedule_store=schedule_store)["projectionReadiness"] == "STALE"

    _seed_projection_authority(
        store=store,
        artifact_id="proj-artifact-2",
        artifact_week=2,
        schedule_version=active.schedule_version,
        schedule_hash=active.schedule_hash,
        schedule_source_version=active.source_version,
    )
    assert resolve_projection_readiness(season=2026, week=3, power_store=store, schedule_store=schedule_store)["projectionReadiness"] == "STALE"

    _seed_projection_authority(
        store=store,
        artifact_id="proj-artifact-3",
        artifact_week=4,
        schedule_version=active.schedule_version,
        schedule_hash=active.schedule_hash,
        schedule_source_version=active.source_version,
    )
    assert resolve_projection_readiness(season=2026, week=3, power_store=store, schedule_store=schedule_store)["projectionReadiness"] == "STALE"

    _seed_projection_authority(
        store=store,
        artifact_id="proj-artifact-4",
        artifact_season=2025,
        schedule_version=active.schedule_version,
        schedule_hash=active.schedule_hash,
        schedule_source_version=active.source_version,
    )
    assert resolve_projection_readiness(season=2026, week=3, power_store=store, schedule_store=schedule_store)["projectionReadiness"] == "STALE"


def test_projection_readiness_missing_and_invalid_pointer_artifact_states(tmp_path):
    store = PowerEngineStore(root_dir=tmp_path / "power")

    missing = resolve_projection_readiness(season=2026, week=3, power_store=store)
    assert missing["projectionReadiness"] == "MISSING"

    _seed_projection_authority(store=store, artifact_id="proj-missing-artifact")
    artifact_path = store.root_dir / "projections" / "artifacts" / "proj-missing-artifact.json"
    artifact_path.unlink()
    invalid_missing_artifact = resolve_projection_readiness(season=2026, week=3, power_store=store)
    assert invalid_missing_artifact["projectionReadiness"] == "INVALID"

    _seed_projection_authority(
        store=store,
        artifact_id="proj-hash-mismatch",
        pointer_hash="pointer-hash",
        artifact_hash="artifact-hash",
    )
    invalid_hash = resolve_projection_readiness(season=2026, week=3, power_store=store)
    assert invalid_hash["projectionReadiness"] == "INVALID"
    assert invalid_hash["projectionReadinessReason"] == "POINTER_ARTIFACT_HASH_MISMATCH"

    active_pointer = store.root_dir / "projections" / "active" / "active-2026-3.json"
    active_pointer.write_text("{malformed", encoding="utf-8")
    invalid_pointer = resolve_projection_readiness(season=2026, week=3, power_store=store)
    assert invalid_pointer["projectionReadiness"] == "INVALID"


def test_opportunities_current_lineage_preserves_numerical_outputs(tmp_path, monkeypatch):
    readiness = _base_readiness(status="CURRENT", reason="LINEAGE_CURRENT")
    opportunities_route = _patch_opportunities_dependencies(monkeypatch, tmp_path, readiness=readiness)

    payload = opportunities_route.get_opportunities(limit=10, best_lines_only=True, week=3)
    opp = payload["opportunities"][0]

    assert payload["projectionReadiness"] == "CURRENT"
    assert opp["projectionReadiness"] == "CURRENT"
    assert opp["currentWinProbability"] == 0.62
    assert opp["currentEV"] == 0.123
    assert opp["currentQualification"]["actionable"] is True


def test_opportunities_stale_lineage_fails_closed_and_blocks_decision_board(tmp_path, monkeypatch):
    readiness = _base_readiness(status="STALE", reason="POWER_THROUGH_WEEK_MISMATCH")
    opportunities_route = _patch_opportunities_dependencies(monkeypatch, tmp_path, readiness=readiness)

    payload = opportunities_route.get_opportunities(limit=10, best_lines_only=True, include_experimental=True, week=3)
    opp = payload["opportunities"][0]

    assert payload["projectionReadiness"] == "STALE"
    assert opp["currentWinProbability"] is None
    assert opp["currentEV"] is None
    assert opp["edge"] is None
    assert opp["evPerDollar"] is None
    assert opp["currentQualification"]["actionable"] is False
    assert opp["currentSizing"]["status"] == "UNAVAILABLE"
    assert opp["qualificationStatus"] == "NOT_QUALIFIED"

    board = opportunities_route.get_decision_board(limit=3, week=3)
    assert board["projectionReadiness"] == "STALE"
    assert board["count"] == 0


def test_stale_projection_with_fresh_market_stays_non_actionable(tmp_path, monkeypatch):
    readiness = _base_readiness(status="STALE", reason="WEEK_MISMATCH")
    opportunities_route = _patch_opportunities_dependencies(monkeypatch, tmp_path, readiness=readiness)

    payload = opportunities_route.get_opportunities(limit=10, best_lines_only=True, include_experimental=True, week=3)
    opp = payload["opportunities"][0]

    assert opp["projectionReadiness"] == "STALE"
    assert opp["currentExecution"]["status"] == "AVAILABLE"
    assert opp["currentQualification"]["actionable"] is False
    assert opp["currentSizing"]["status"] == "UNAVAILABLE"


def test_current_projection_with_stale_market_keeps_projection_current(tmp_path, monkeypatch):
    readiness = _base_readiness(status="CURRENT", reason="LINEAGE_CURRENT")
    stale_quote = (datetime.now(timezone.utc) - timedelta(minutes=240)).isoformat()
    opportunities_route = _patch_opportunities_dependencies(
        monkeypatch,
        tmp_path,
        readiness=readiness,
        quote_last_updated=stale_quote,
    )

    payload = opportunities_route.get_opportunities(limit=10, best_lines_only=True, week=3)
    opp = payload["opportunities"][0]

    assert payload["projectionReadiness"] == "CURRENT"
    assert opp["projectionReadiness"] == "CURRENT"
    assert opp["currentExecution"]["status"] == "STALE_APPROVED_MARKET"
    assert opp["currentQualification"]["actionable"] is False


def test_missing_projection_authority_has_no_legacy_csv_fallback(tmp_path, monkeypatch):
    readiness = _base_readiness(status="MISSING", reason="ACTIVE_POINTER_MISSING")
    opportunities_route = _patch_opportunities_dependencies(monkeypatch, tmp_path, readiness=readiness)

    payload = opportunities_route.get_opportunities(limit=10, best_lines_only=True, include_experimental=True, week=3)
    opp = payload["opportunities"][0]

    assert payload["projectionReadiness"] == "MISSING"
    assert opp["projectionReadiness"] == "MISSING"
    assert opp["currentWinProbability"] is None
    assert opp["currentEV"] is None
    assert opp["currentQualification"]["actionable"] is False


def test_official_preview_fails_closed_when_projection_not_current(tmp_path, monkeypatch):
    import app.services.decision_ledger as decision_ledger_service

    readiness = _base_readiness(status="INVALID", reason="ACTIVE_ARTIFACT_UNREADABLE")
    opportunities_route = _patch_opportunities_dependencies(monkeypatch, tmp_path, readiness=readiness)

    opp_payload = opportunities_route.get_opportunities(limit=100, best_lines_only=True, week=3)
    preview = decision_ledger_service.build_official_sia3_preview(
        opp_payload.get("opportunities") or [],
        season=2026,
        week=3,
    )

    assert all((slot.get("decision") is None) for slot in preview.get("slots", []))


def test_projection_guard_exposes_readiness_diagnostics_on_payload_and_rows(tmp_path, monkeypatch):
    readiness = _base_readiness(status="STALE", reason="SEASON_MISMATCH")
    opportunities_route = _patch_opportunities_dependencies(monkeypatch, tmp_path, readiness=readiness)

    payload = opportunities_route.get_opportunities(limit=10, best_lines_only=True, include_experimental=True, week=3)
    opp = payload["opportunities"][0]

    for key in [
        "projectionReadiness",
        "projectionReadinessReason",
        "projectionSeason",
        "projectionWeek",
        "projectionPowerThroughWeek",
        "projectionArtifactId",
        "projectionArtifactHash",
        "projectionScheduleVersion",
        "projectionScheduleHash",
    ]:
        assert key in payload
        assert key in opp


def _canonical_schedule_for_identity_tests(events: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        schedule_version="schedule-v1:2026:3:test",
        schedule_hash="schedule-hash-test",
        season=2026,
        week=3,
        events=[SimpleNamespace(**event) for event in events],
    )


def _active_projection_row(
    *,
    event_id: str = "evt-guard-1",
    canonical_event_key: str = "cev-guard-1",
    season: int = 2026,
    week: int = 3,
    kickoff_utc: str = "2026-09-20T17:00:00Z",
    away_team: str = "NO",
    home_team: str = "ATL",
) -> dict:
    return {
        "event_id": event_id,
        "canonical_event_key": canonical_event_key,
        "season": season,
        "week": week,
        "kickoff_utc": kickoff_utc,
        "away_team": away_team,
        "home_team": home_team,
        "away_power": 0.0,
        "home_power": 0.0,
        "model_margin_home": -1.0,
        "model_version": "model-v1",
        "probability_version": "prob-v1",
    }


def test_active_projection_identity_exact_canonical_match_is_accepted(monkeypatch):
    import app.routes.opportunities as opportunities_route

    readiness = _base_readiness(status="CURRENT", reason="LINEAGE_CURRENT")
    schedule = _canonical_schedule_for_identity_tests(
        [
            {
                "source_event_id": "evt-guard-1",
                "canonical_event_key": "cev-guard-1",
                "season": 2026,
                "week": 3,
                "kickoff_utc": "2026-09-20T17:00:00Z",
                "away_team": "NO",
                "home_team": "ATL",
            }
        ]
    )
    monkeypatch.setattr(opportunities_route, "load_canonical_weekly_schedule", lambda season, week, store=None: schedule)
    monkeypatch.setattr(
        opportunities_route,
        "load_active_projection_artifact_by_identity",
        lambda season, week, artifact_id, artifact_hash: {"projection_rows": [_active_projection_row()]},
    )

    lookup = opportunities_route._load_active_projection_lookup_for_week(
        resolved_season=2026,
        resolved_week=3,
        readiness=readiness,
        week_event_ids={"evt-guard-1"},
    )
    assert set(lookup.keys()) == {"evt-guard-1"}


def test_active_projection_identity_missing_canonical_event_fails_closed(monkeypatch):
    import app.routes.opportunities as opportunities_route

    readiness = _base_readiness(status="CURRENT", reason="LINEAGE_CURRENT")
    schedule = _canonical_schedule_for_identity_tests(
        [
            {
                "source_event_id": "evt-guard-1",
                "canonical_event_key": "cev-guard-1",
                "season": 2026,
                "week": 3,
                "kickoff_utc": "2026-09-20T17:00:00Z",
                "away_team": "NO",
                "home_team": "ATL",
            },
            {
                "source_event_id": "evt-guard-2",
                "canonical_event_key": "cev-guard-2",
                "season": 2026,
                "week": 3,
                "kickoff_utc": "2026-09-20T20:25:00Z",
                "away_team": "BAL",
                "home_team": "BUF",
            },
        ]
    )
    monkeypatch.setattr(opportunities_route, "load_canonical_weekly_schedule", lambda season, week, store=None: schedule)
    monkeypatch.setattr(
        opportunities_route,
        "load_active_projection_artifact_by_identity",
        lambda season, week, artifact_id, artifact_hash: {"projection_rows": [_active_projection_row()]},
    )

    with pytest.raises(ValueError, match="ACTIVE_PROJECTION_EVENT_COVERAGE_MISMATCH"):
        opportunities_route._load_active_projection_lookup_for_week(
            resolved_season=2026,
            resolved_week=3,
            readiness=readiness,
            week_event_ids={"evt-guard-1", "evt-guard-2"},
        )


@pytest.mark.parametrize(
    ("rows", "error"),
    [
        (
            [
                _active_projection_row(event_id="evt-guard-1", canonical_event_key="cev-guard-1"),
                _active_projection_row(event_id="evt-guard-1", canonical_event_key="cev-guard-2"),
            ],
            "ACTIVE_PROJECTION_DUPLICATE_EVENT_ID",
        ),
        (
            [
                _active_projection_row(event_id="evt-guard-1", canonical_event_key="cev-guard-1"),
                _active_projection_row(event_id="evt-guard-2", canonical_event_key="cev-guard-1"),
            ],
            "ACTIVE_PROJECTION_DUPLICATE_CANONICAL_EVENT_KEY",
        ),
        (
            [_active_projection_row(kickoff_utc="2035-01-01T00:00:00Z")],
            "ACTIVE_PROJECTION_ROW_KICKOFF_MISMATCH",
        ),
        (
            [_active_projection_row(canonical_event_key="cev-wrong")],
            "ACTIVE_PROJECTION_CANONICAL_EVENT_KEY_MISMATCH",
        ),
        (
            [_active_projection_row(away_team="NYJ")],
            "ACTIVE_PROJECTION_ROW_AWAY_TEAM_MISMATCH",
        ),
        (
            [_active_projection_row(home_team="NE")],
            "ACTIVE_PROJECTION_ROW_HOME_TEAM_MISMATCH",
        ),
        (
            [_active_projection_row(season=2025)],
            "ACTIVE_PROJECTION_ROW_SEASON_MISMATCH",
        ),
        (
            [_active_projection_row(week=2)],
            "ACTIVE_PROJECTION_ROW_WEEK_MISMATCH",
        ),
        (
            [_active_projection_row(event_id="evt-extra", canonical_event_key="cev-extra")],
            "ACTIVE_PROJECTION_EVENT_ID_MISMATCH",
        ),
        (
            [_active_projection_row(event_id="evt-wrong", canonical_event_key="cev-guard-1")],
            "ACTIVE_PROJECTION_EVENT_ID_MISMATCH",
        ),
    ],
)
def test_active_projection_identity_fail_closed_matrix(monkeypatch, rows, error):
    import app.routes.opportunities as opportunities_route

    readiness = _base_readiness(status="CURRENT", reason="LINEAGE_CURRENT")
    schedule = _canonical_schedule_for_identity_tests(
        [
            {
                "source_event_id": "evt-guard-1",
                "canonical_event_key": "cev-guard-1",
                "season": 2026,
                "week": 3,
                "kickoff_utc": "2026-09-20T17:00:00Z",
                "away_team": "NO",
                "home_team": "ATL",
            }
        ]
    )
    monkeypatch.setattr(opportunities_route, "load_canonical_weekly_schedule", lambda season, week, store=None: schedule)
    monkeypatch.setattr(
        opportunities_route,
        "load_active_projection_artifact_by_identity",
        lambda season, week, artifact_id, artifact_hash: {"projection_rows": rows},
    )

    with pytest.raises(ValueError, match=error):
        opportunities_route._load_active_projection_lookup_for_week(
            resolved_season=2026,
            resolved_week=3,
            readiness=readiness,
            week_event_ids={"evt-guard-1"},
        )


def test_active_projection_identity_reordered_rows_are_accepted(monkeypatch):
    import app.routes.opportunities as opportunities_route

    readiness = _base_readiness(status="CURRENT", reason="LINEAGE_CURRENT")
    schedule = _canonical_schedule_for_identity_tests(
        [
            {
                "source_event_id": "evt-guard-1",
                "canonical_event_key": "cev-guard-1",
                "season": 2026,
                "week": 3,
                "kickoff_utc": "2026-09-20T17:00:00Z",
                "away_team": "NO",
                "home_team": "ATL",
            },
            {
                "source_event_id": "evt-guard-2",
                "canonical_event_key": "cev-guard-2",
                "season": 2026,
                "week": 3,
                "kickoff_utc": "2026-09-20T20:25:00Z",
                "away_team": "BAL",
                "home_team": "BUF",
            },
        ]
    )
    monkeypatch.setattr(opportunities_route, "load_canonical_weekly_schedule", lambda season, week, store=None: schedule)

    rows_a = [
        _active_projection_row(event_id="evt-guard-1", canonical_event_key="cev-guard-1"),
        _active_projection_row(
            event_id="evt-guard-2",
            canonical_event_key="cev-guard-2",
            kickoff_utc="2026-09-20T20:25:00Z",
            away_team="BAL",
            home_team="BUF",
        ),
    ]
    rows_b = list(reversed(rows_a))

    monkeypatch.setattr(
        opportunities_route,
        "load_active_projection_artifact_by_identity",
        lambda season, week, artifact_id, artifact_hash: {"projection_rows": rows_a},
    )
    lookup_a = opportunities_route._load_active_projection_lookup_for_week(
        resolved_season=2026,
        resolved_week=3,
        readiness=readiness,
        week_event_ids={"evt-guard-1", "evt-guard-2"},
    )

    monkeypatch.setattr(
        opportunities_route,
        "load_active_projection_artifact_by_identity",
        lambda season, week, artifact_id, artifact_hash: {"projection_rows": rows_b},
    )
    lookup_b = opportunities_route._load_active_projection_lookup_for_week(
        resolved_season=2026,
        resolved_week=3,
        readiness=readiness,
        week_event_ids={"evt-guard-1", "evt-guard-2"},
    )

    assert set(lookup_a.keys()) == {"evt-guard-1", "evt-guard-2"}
    assert set(lookup_b.keys()) == {"evt-guard-1", "evt-guard-2"}
    assert float(lookup_a["evt-guard-1"]["model_margin_home"]) == float(lookup_b["evt-guard-1"]["model_margin_home"])
    assert float(lookup_a["evt-guard-2"]["model_margin_home"]) == float(lookup_b["evt-guard-2"]["model_margin_home"])


def test_identity_failure_does_not_fallback_to_legacy_projection_csv(tmp_path, monkeypatch):
    readiness = _base_readiness(status="CURRENT", reason="LINEAGE_CURRENT")
    opportunities_route = _patch_opportunities_dependencies(monkeypatch, tmp_path, readiness=readiness)

    monkeypatch.setattr(
        opportunities_route,
        "load_active_projection_artifact_by_identity",
        lambda season, week, artifact_id, artifact_hash: {
            "projection_rows": [
                {
                    "event_id": "evt-guard-1",
                    "season": 2026,
                    "week": 3,
                    "kickoff_utc": "2035-01-01T00:00:00Z",
                    "away_team": "NO",
                    "home_team": "ATL",
                    "away_power": 0.0,
                    "home_power": 0.0,
                    "model_margin_home": -1.0,
                    "canonical_event_key": "cev-guard-1",
                    "model_version": "model-v1",
                    "probability_version": "prob-v1",
                }
            ]
        },
    )

    payload = opportunities_route.get_opportunities(limit=10, best_lines_only=True, include_experimental=True, week=3)
    opp = payload["opportunities"][0]

    assert payload["projectionReadiness"] == "INVALID"
    assert payload["projectionReadinessReason"] == "ACTIVE_PROJECTION_BINDING_FAILED"
    assert opp["currentWinProbability"] is None
    assert opp["currentEV"] is None
    assert opp["currentQualification"]["actionable"] is False
