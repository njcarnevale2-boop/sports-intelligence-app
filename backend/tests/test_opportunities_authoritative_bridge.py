from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


@dataclass
class _BridgeFixture:
    schedule: SimpleNamespace
    projection_rows: list[dict]
    market_rows: list[dict]
    provider_event_ids: list[str]


def _readiness_current() -> dict:
    return {
        "projectionReadiness": "CURRENT",
        "projectionReadinessReason": "LINEAGE_CURRENT",
        "projectionSeason": 2026,
        "projectionWeek": 3,
        "projectionPowerThroughWeek": 2,
        "projectionArtifactId": "proj-bridge-test",
        "projectionArtifactHash": "hash-bridge-test",
        "projectionScheduleVersion": "schedule-v1:2026:3:test",
        "projectionScheduleHash": "schedule-hash-test",
        "projectionScheduleSourceVersion": "source-version-test",
        "projectionValidationStatus": "VALID",
        "projectionPowerSnapshotId": "snap-test",
        "projectionPowerSnapshotHash": "snap-hash-test",
        "projectionActivatedAt": "2026-09-27T03:13:22Z",
        "expectedPowerThroughWeek": 2,
    }


def _build_fixture(game_count: int = 16) -> _BridgeFixture:
    teams = [
        "ARI",
        "ATL",
        "BAL",
        "BUF",
        "CAR",
        "CHI",
        "CIN",
        "CLE",
        "DAL",
        "DEN",
        "DET",
        "GB",
        "HOU",
        "IND",
        "JAX",
        "KC",
        "LAC",
        "LAR",
        "LV",
        "MIA",
        "MIN",
        "NE",
        "NO",
        "NYG",
        "NYJ",
        "PHI",
        "PIT",
        "SEA",
        "SF",
        "TB",
        "TEN",
        "WAS",
    ]

    schedule_events = []
    projection_rows = []
    market_rows = []
    provider_event_ids = []

    for idx in range(game_count):
        away = teams[idx % len(teams)]
        home = teams[(idx + 16) % len(teams)]
        source_event_id = f"2026_03_{away}_{home}"
        provider_event_id = f"prov-{idx:02d}"
        kickoff = f"2026-09-2{(idx % 7) + 1}T17:00:00Z"
        canonical_key = f"cev-{idx:02d}"

        schedule_events.append(
            SimpleNamespace(
                source_event_id=source_event_id,
                canonical_event_key=canonical_key,
                season=2026,
                week=3,
                kickoff_utc=kickoff,
                away_team=away,
                home_team=home,
            )
        )

        projection_rows.append(
            {
                "event_id": source_event_id,
                "canonical_event_key": canonical_key,
                "season": 2026,
                "week": 3,
                "kickoff_utc": kickoff,
                "away_team": away,
                "home_team": home,
                "away_power": 0.0,
                "home_power": 0.0,
                "model_margin_home": float((idx % 7) - 3),
                "model_total_baseline": 44.0,
                "model_version": "model-v1",
                "probability_version": "prob-v1",
            }
        )

        market_rows.extend(
            [
                {
                    "eventId": provider_event_id,
                    "sportsbook": "DraftKings",
                    "market": "spread",
                    "side": "home",
                    "point": -3.5,
                    "americanOdds": -110,
                    "lastUpdated": "2026-09-27T03:19:00.620099+00:00",
                    "awayTeam": away,
                    "homeTeam": home,
                    "commenceTime": kickoff,
                },
                {
                    "eventId": provider_event_id,
                    "sportsbook": "DraftKings",
                    "market": "spread",
                    "side": "away",
                    "point": 3.5,
                    "americanOdds": -110,
                    "lastUpdated": "2026-09-27T03:19:00.620099+00:00",
                    "awayTeam": away,
                    "homeTeam": home,
                    "commenceTime": kickoff,
                },
            ]
        )
        provider_event_ids.append(provider_event_id)

    schedule = SimpleNamespace(
        schedule_version="schedule-v1:2026:3:test",
        schedule_hash="schedule-hash-test",
        source_version="source-version-test",
        season=2026,
        week=3,
        events=schedule_events,
    )
    return _BridgeFixture(
        schedule=schedule,
        projection_rows=projection_rows,
        market_rows=market_rows,
        provider_event_ids=provider_event_ids,
    )


def _patch_offline_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fx: _BridgeFixture) -> None:
    import app.routes.opportunities as route
    from app.services.games import service as games_service

    ranked_board = tmp_path / "ranked_bet_board.csv"
    pd.DataFrame([], columns=["api_event_id"]).to_csv(ranked_board, index=False)

    monkeypatch.setattr(route, "RANKED_BET_BOARD", ranked_board)
    monkeypatch.setattr(route, "resolve_canonical_week_metadata", lambda: {"season": 2026, "week": 3, "status": "ACTIVE"})
    monkeypatch.setattr(route, "build_week_readiness", lambda canonical=None: {"status": "READY"})
    monkeypatch.setattr(route, "resolve_projection_readiness", lambda season, week: _readiness_current())
    monkeypatch.setattr(route, "load_active_schedule", lambda season, week, store=None: fx.schedule)
    monkeypatch.setattr(
        route,
        "load_active_projection_artifact_by_identity",
        lambda season, week, artifact_id, artifact_hash: {"projection_rows": [dict(row) for row in fx.projection_rows]},
    )

    monkeypatch.setattr(route.market_data_service, "load_normalized_market_rows", lambda: [dict(row) for row in fx.market_rows])
    monkeypatch.setattr(
        route.market_data_service,
        "metadata",
        lambda: {"provider": "line_movement_board", "lastUpdated": "2026-09-27T03:19:00.620099+00:00", "dataStatus": "FILE"},
    )

    snapshots = {}
    for event_id in fx.provider_event_ids:
        snapshots[event_id] = {
            "provider": "line_movement_board",
            "lastUpdated": "2026-09-27T03:19:00.620099+00:00",
            "dataStatus": "FILE",
            "booksTracked": 1,
            "bestAwaySpread": {"sportsbook": "DraftKings", "line": 3.5, "price": -110, "lastUpdated": "2026-09-27T03:19:00.620099+00:00"},
            "bestHomeSpread": {"sportsbook": "DraftKings", "line": -3.5, "price": -110, "lastUpdated": "2026-09-27T03:19:00.620099+00:00"},
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
    monkeypatch.setattr(route.market_data_service, "all_event_snapshots", lambda: snapshots)

    monkeypatch.setattr(
        games_service,
        "list_games",
        lambda week=None, include_enrichment=False: {
            "availableWeeks": [3],
            "games": [
                {
                    "eventId": event_id,
                    "week": 3,
                    "season": 2026,
                }
                for event_id in fx.provider_event_ids
            ],
        },
    )

    monkeypatch.setattr(route, "get_market_intelligence", lambda *args, **kwargs: {"booksTracked": 1, "signal": "CONFIRMED"})

    class _FakeInjuryContext:
        def build_context(self, away_team: str, home_team: str) -> dict:
            return {"summary": "neutral", "severity": "neutral"}

    monkeypatch.setattr(route, "InjuryMatchupContext", _FakeInjuryContext)
    monkeypatch.setattr(route, "_record_history_for_snapshot", lambda *args, **kwargs: [])


def test_active_projection_schedule_authority_without_legacy_schedule(monkeypatch):
    import app.routes.opportunities as route

    fx = _build_fixture(game_count=1)
    readiness = _readiness_current()

    monkeypatch.setattr(route, "load_active_schedule", lambda season, week, store=None: fx.schedule)
    monkeypatch.setattr(
        route,
        "load_active_projection_artifact_by_identity",
        lambda season, week, artifact_id, artifact_hash: {"projection_rows": [dict(row) for row in fx.projection_rows]},
    )
    monkeypatch.setattr(route.market_data_service, "load_normalized_market_rows", lambda: [dict(row) for row in fx.market_rows])

    lookup = route._load_active_projection_lookup_for_week(
        resolved_season=2026,
        resolved_week=3,
        readiness=readiness,
        week_event_ids={fx.provider_event_ids[0]},
    )
    assert set(lookup.keys()) == {fx.provider_event_ids[0]}
    assert lookup[fx.provider_event_ids[0]].get("projection_source") == "ACTIVE_PROJECTION_ARTIFACT"


def test_event_id_namespace_bridge_maps_source_to_provider(monkeypatch):
    import app.routes.opportunities as route

    fx = _build_fixture(game_count=1)
    readiness = _readiness_current()

    monkeypatch.setattr(route, "load_active_schedule", lambda season, week, store=None: fx.schedule)
    monkeypatch.setattr(
        route,
        "load_active_projection_artifact_by_identity",
        lambda season, week, artifact_id, artifact_hash: {"projection_rows": [dict(row) for row in fx.projection_rows]},
    )
    monkeypatch.setattr(route.market_data_service, "load_normalized_market_rows", lambda: [dict(row) for row in fx.market_rows])

    lookup = route._load_active_projection_lookup_for_week(
        resolved_season=2026,
        resolved_week=3,
        readiness=readiness,
        week_event_ids={fx.provider_event_ids[0]},
    )
    row = lookup[fx.provider_event_ids[0]]
    assert str(row.get("source_event_id")) == "2026_03_ARI_LAC"
    assert str(row.get("provider_api_event_id")) == fx.provider_event_ids[0]


def test_wrong_matchup_fails_closed(monkeypatch):
    import app.routes.opportunities as route

    fx = _build_fixture(game_count=1)
    readiness = _readiness_current()
    bad_rows = [dict(fx.market_rows[0])]
    bad_rows[0]["awayTeam"] = "BAD"

    monkeypatch.setattr(route, "load_active_schedule", lambda season, week, store=None: fx.schedule)
    monkeypatch.setattr(
        route,
        "load_active_projection_artifact_by_identity",
        lambda season, week, artifact_id, artifact_hash: {"projection_rows": [dict(row) for row in fx.projection_rows]},
    )
    monkeypatch.setattr(route.market_data_service, "load_normalized_market_rows", lambda: bad_rows)

    with pytest.raises(ValueError, match="ACTIVE_PROJECTION_EVENT_BRIDGE_MISSING"):
        route._load_active_projection_lookup_for_week(
            resolved_season=2026,
            resolved_week=3,
            readiness=readiness,
            week_event_ids={fx.provider_event_ids[0]},
        )


def test_wrong_kickoff_fails_closed(monkeypatch):
    import app.routes.opportunities as route

    fx = _build_fixture(game_count=1)
    readiness = _readiness_current()
    bad_rows = [dict(fx.market_rows[0])]
    bad_rows[0]["commenceTime"] = "2026-10-01T00:00:00Z"

    monkeypatch.setattr(route, "load_active_schedule", lambda season, week, store=None: fx.schedule)
    monkeypatch.setattr(
        route,
        "load_active_projection_artifact_by_identity",
        lambda season, week, artifact_id, artifact_hash: {"projection_rows": [dict(row) for row in fx.projection_rows]},
    )
    monkeypatch.setattr(route.market_data_service, "load_normalized_market_rows", lambda: bad_rows)

    with pytest.raises(ValueError, match="ACTIVE_PROJECTION_EVENT_BRIDGE_MISSING"):
        route._load_active_projection_lookup_for_week(
            resolved_season=2026,
            resolved_week=3,
            readiness=readiness,
            week_event_ids={fx.provider_event_ids[0]},
        )


def test_ambiguous_mapping_fails_closed(monkeypatch):
    import app.routes.opportunities as route

    fx = _build_fixture(game_count=1)
    readiness = _readiness_current()
    bad_rows = [dict(fx.market_rows[0]), dict(fx.market_rows[1])]
    bad_rows[1]["eventId"] = "prov-alt"

    monkeypatch.setattr(route, "load_active_schedule", lambda season, week, store=None: fx.schedule)
    monkeypatch.setattr(
        route,
        "load_active_projection_artifact_by_identity",
        lambda season, week, artifact_id, artifact_hash: {"projection_rows": [dict(row) for row in fx.projection_rows]},
    )
    monkeypatch.setattr(route.market_data_service, "load_normalized_market_rows", lambda: bad_rows)

    with pytest.raises(ValueError, match="ACTIVE_PROJECTION_EVENT_ID_BRIDGE_AMBIGUOUS"):
        route._load_active_projection_lookup_for_week(
            resolved_season=2026,
            resolved_week=3,
            readiness=readiness,
            week_event_ids={fx.provider_event_ids[0]},
        )


def test_complete_spread_universe_evaluated_without_ranked_board(tmp_path: Path, monkeypatch):
    import app.routes.opportunities as route

    fx = _build_fixture(game_count=16)
    _patch_offline_runtime(monkeypatch, tmp_path, fx)

    payload = route._get_opportunities_payload(
        limit=500,
        best_lines_only=True,
        include_experimental=True,
        week=3,
        persist_history=False,
    )

    spread_rows = [item for item in payload.get("opportunities", []) if str(item.get("market") or "") == "spread"]
    spread_events = {str(item.get("eventId") or "") for item in spread_rows}

    assert payload["projectionReadiness"] == "CURRENT"
    assert len(spread_events) == 16
    assert len(spread_rows) == 32


def test_no_ranked_board_probability_fallback(tmp_path: Path, monkeypatch):
    import app.routes.opportunities as route

    fx = _build_fixture(game_count=2)
    _patch_offline_runtime(monkeypatch, tmp_path, fx)

    payload = route._get_opportunities_payload(
        limit=500,
        best_lines_only=True,
        include_experimental=True,
        week=3,
        persist_history=False,
    )

    spread_rows = [item for item in payload.get("opportunities", []) if str(item.get("market") or "") == "spread"]
    assert spread_rows
    assert all(str(item.get("projectionNumericsSource") or "") == "ACTIVE_PROJECTION_ARTIFACT" for item in spread_rows)
    assert all(item.get("currentWinProbability") is not None for item in spread_rows)


def test_invalid_authority_fails_closed_in_runtime(tmp_path: Path, monkeypatch):
    import app.routes.opportunities as route
    from app.services.games import service as games_service

    fx = _build_fixture(game_count=1)
    ranked_board = tmp_path / "ranked_bet_board.csv"
    pd.DataFrame([], columns=["api_event_id"]).to_csv(ranked_board, index=False)

    monkeypatch.setattr(route, "RANKED_BET_BOARD", ranked_board)
    monkeypatch.setattr(route, "resolve_canonical_week_metadata", lambda: {"season": 2026, "week": 3, "status": "ACTIVE"})
    monkeypatch.setattr(route, "build_week_readiness", lambda canonical=None: {"status": "READY"})
    monkeypatch.setattr(route, "resolve_projection_readiness", lambda season, week: _readiness_current())
    monkeypatch.setattr(route, "load_active_schedule", lambda season, week, store=None: None)
    monkeypatch.setattr(
        route,
        "load_active_projection_artifact_by_identity",
        lambda season, week, artifact_id, artifact_hash: {"projection_rows": [dict(row) for row in fx.projection_rows]},
    )
    monkeypatch.setattr(route.market_data_service, "load_normalized_market_rows", lambda: [dict(row) for row in fx.market_rows])
    monkeypatch.setattr(route.market_data_service, "metadata", lambda: {"provider": "line_movement_board", "lastUpdated": "2026-09-27T03:19:00.620099+00:00", "dataStatus": "FILE"})
    monkeypatch.setattr(games_service, "list_games", lambda week=None, include_enrichment=False: {"availableWeeks": [3], "games": [{"eventId": fx.provider_event_ids[0], "week": 3, "season": 2026}]})

    payload = route._get_opportunities_payload(
        limit=100,
        best_lines_only=True,
        include_experimental=True,
        week=3,
        persist_history=False,
    )
    assert payload["projectionReadiness"] == "INVALID"
    assert payload["projectionReadinessReason"] == "ACTIVE_PROJECTION_BINDING_FAILED"
