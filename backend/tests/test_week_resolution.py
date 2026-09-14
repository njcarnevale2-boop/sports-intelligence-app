from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.services import week_resolution as wk


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _configure_artifact_paths(monkeypatch, tmp_path: Path) -> dict[str, Path]:
    schedule = tmp_path / "schedule_context_latest.csv"
    projections = tmp_path / "current_game_projections.csv"
    line_board = tmp_path / "line_movement_board.csv"
    ranked_board = tmp_path / "ranked_bet_board.csv"

    monkeypatch.setattr(wk, "SCHEDULE_CONTEXT", schedule)
    monkeypatch.setattr(wk, "GAME_PROJECTIONS", projections)
    monkeypatch.setattr(wk, "LINE_MOVEMENT_BOARD", line_board)
    monkeypatch.setattr(wk, "RANKED_BET_BOARD", ranked_board)
    monkeypatch.setenv("NFL_WEEK_COMPLETION_BUFFER_HOURS", "6")
    monkeypatch.setenv("NFL_WEEK_CONTEXT_STALE_HOURS", "1000")

    return {
        "schedule": schedule,
        "projections": projections,
        "line": line_board,
        "ranked": ranked_board,
    }


def _base_schedule_rows() -> list[dict]:
    return [
        {"season": 2026, "week": 1, "gameday": "2026-09-10", "away_team": "NE", "home_team": "SEA"},
        {"season": 2026, "week": 1, "gameday": "2026-09-13", "away_team": "BUF", "home_team": "MIA"},
        {"season": 2026, "week": 1, "gameday": "2026-09-14", "away_team": "DEN", "home_team": "KC"},
        {"season": 2026, "week": 2, "gameday": "2026-09-17", "away_team": "NYG", "home_team": "DAL"},
        {"season": 2026, "week": 2, "gameday": "2026-09-20", "away_team": "PHI", "home_team": "WAS"},
    ]


def _base_projection_rows() -> list[dict]:
    return [
        {"api_event_id": "2026_1_NE_SEA", "commence_time": "2026-09-11T00:20:00+00:00", "away_team": "NE", "home_team": "SEA"},
        {"api_event_id": "2026_1_BUF_MIA", "commence_time": "2026-09-13T17:00:00+00:00", "away_team": "BUF", "home_team": "MIA"},
        {"api_event_id": "2026_1_DEN_KC", "commence_time": "2026-09-15T00:20:00+00:00", "away_team": "DEN", "home_team": "KC"},
        {"api_event_id": "2026_2_NYG_DAL", "commence_time": "2026-09-18T00:20:00+00:00", "away_team": "NYG", "home_team": "DAL"},
        {"api_event_id": "2026_2_PHI_WAS", "commence_time": "2026-09-20T17:00:00+00:00", "away_team": "PHI", "home_team": "WAS"},
    ]


def _write_full_ready_week2_artifacts(paths: dict[str, Path]) -> None:
    schedule = [row for row in _base_schedule_rows() if row["week"] == 2]
    projections = [row for row in _base_projection_rows() if row["api_event_id"].startswith("2026_2_")]
    line_rows = [
        {"api_event_id": "2026_2_NYG_DAL", "commence_time": "2026-09-18T00:20:00+00:00", "away_team": "NYG", "home_team": "DAL"},
        {"api_event_id": "2026_2_PHI_WAS", "commence_time": "2026-09-20T17:00:00+00:00", "away_team": "PHI", "home_team": "WAS"},
    ]
    ranked_rows = [
        {"api_event_id": "2026_2_NYG_DAL", "commence_time": "2026-09-18T00:20:00+00:00", "away_team": "NYG", "home_team": "DAL"},
    ]
    _write_csv(paths["schedule"], schedule)
    _write_csv(paths["projections"], projections)
    _write_csv(paths["line"], line_rows)
    _write_csv(paths["ranked"], ranked_rows)


def test_sunday_with_games_remaining_resolves_current_week(monkeypatch, tmp_path):
    paths = _configure_artifact_paths(monkeypatch, tmp_path)
    _write_csv(paths["schedule"], _base_schedule_rows())
    _write_csv(paths["projections"], _base_projection_rows())

    out = wk.resolve_canonical_week_metadata(now_utc=datetime(2026, 9, 13, 16, 0, tzinfo=timezone.utc))

    assert out["season"] == 2026
    assert out["week"] == 1
    assert out["reason"] == "WEEK_HAS_UPCOMING_OR_IN_PROGRESS_GAMES"


def test_monday_before_mnf_resolves_current_week(monkeypatch, tmp_path):
    paths = _configure_artifact_paths(monkeypatch, tmp_path)
    _write_csv(paths["schedule"], _base_schedule_rows())
    _write_csv(paths["projections"], _base_projection_rows())

    out = wk.resolve_canonical_week_metadata(now_utc=datetime(2026, 9, 14, 20, 0, tzinfo=timezone.utc))

    assert out["week"] == 1


def test_monday_during_mnf_resolves_current_week(monkeypatch, tmp_path):
    paths = _configure_artifact_paths(monkeypatch, tmp_path)
    _write_csv(paths["schedule"], _base_schedule_rows())
    _write_csv(paths["projections"], _base_projection_rows())

    out = wk.resolve_canonical_week_metadata(now_utc=datetime(2026, 9, 15, 1, 0, tzinfo=timezone.utc))

    assert out["week"] == 1


def test_after_mnf_completion_rolls_to_next_week(monkeypatch, tmp_path):
    paths = _configure_artifact_paths(monkeypatch, tmp_path)
    _write_csv(paths["schedule"], _base_schedule_rows())
    _write_csv(paths["projections"], _base_projection_rows())

    out = wk.resolve_canonical_week_metadata(now_utc=datetime(2026, 9, 15, 8, 30, tzinfo=timezone.utc))

    assert out["week"] == 2
    assert out["nextKickoffUtc"] == "2026-09-18T00:20:00+00:00"


def test_tuesday_morning_resolves_next_week_and_includes_tnf(monkeypatch, tmp_path):
    paths = _configure_artifact_paths(monkeypatch, tmp_path)
    _write_csv(paths["schedule"], _base_schedule_rows())
    _write_csv(paths["projections"], _base_projection_rows())

    out = wk.resolve_canonical_week_metadata(now_utc=datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc))

    assert out["week"] == 2
    assert out["nextKickoffUtc"] == "2026-09-18T00:20:00+00:00"


def test_bye_week_pattern_with_fewer_games_is_supported(monkeypatch, tmp_path):
    paths = _configure_artifact_paths(monkeypatch, tmp_path)
    schedule = [
        {"season": 2026, "week": 6, "gameday": "2026-10-15", "away_team": "NE", "home_team": "NYJ"},
        {"season": 2026, "week": 6, "gameday": "2026-10-18", "away_team": "KC", "home_team": "DEN"},
        {"season": 2026, "week": 7, "gameday": "2026-10-22", "away_team": "BUF", "home_team": "MIA"},
    ]
    projections = [
        {"api_event_id": "2026_6_NE_NYJ", "commence_time": "2026-10-16T00:20:00+00:00", "away_team": "NE", "home_team": "NYJ"},
        {"api_event_id": "2026_6_KC_DEN", "commence_time": "2026-10-18T20:25:00+00:00", "away_team": "KC", "home_team": "DEN"},
        {"api_event_id": "2026_7_BUF_MIA", "commence_time": "2026-10-23T00:20:00+00:00", "away_team": "BUF", "home_team": "MIA"},
    ]
    _write_csv(paths["schedule"], schedule)
    _write_csv(paths["projections"], projections)

    out = wk.resolve_canonical_week_metadata(now_utc=datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc))

    assert out["week"] == 6


def test_final_regular_week_rolls_to_postseason_identifier(monkeypatch, tmp_path):
    paths = _configure_artifact_paths(monkeypatch, tmp_path)
    schedule = [
        {"season": 2026, "week": 18, "gameday": "2027-01-03", "away_team": "NE", "home_team": "MIA"},
        {"season": 2026, "week": 19, "gameday": "2027-01-09", "away_team": "KC", "home_team": "BUF"},
    ]
    projections = [
        {"api_event_id": "2026_18_NE_MIA", "commence_time": "2027-01-03T18:00:00+00:00", "away_team": "NE", "home_team": "MIA"},
        {"api_event_id": "2026_19_KC_BUF", "commence_time": "2027-01-09T21:30:00+00:00", "away_team": "KC", "home_team": "BUF"},
    ]
    _write_csv(paths["schedule"], schedule)
    _write_csv(paths["projections"], projections)

    out = wk.resolve_canonical_week_metadata(now_utc=datetime(2027, 1, 4, 8, 0, tzinfo=timezone.utc))

    assert out["week"] == 19


def test_missing_schedule_reports_not_ready(monkeypatch, tmp_path):
    _configure_artifact_paths(monkeypatch, tmp_path)

    out = wk.resolve_canonical_week_metadata(now_utc=datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc))

    assert out["status"] == "NOT_READY"
    assert out["week"] is None


def test_readiness_missing_projection_artifact(monkeypatch, tmp_path):
    paths = _configure_artifact_paths(monkeypatch, tmp_path)
    _write_full_ready_week2_artifacts(paths)
    paths["projections"].unlink()

    readiness = wk.build_week_readiness(canonical={"season": 2026, "week": 2})

    assert readiness["scheduleReady"] is True
    assert readiness["projectionsReady"] is False
    assert readiness["status"] == "NOT_READY"


def test_readiness_projection_only_prior_week_is_not_ready(monkeypatch, tmp_path):
    paths = _configure_artifact_paths(monkeypatch, tmp_path)
    _write_csv(paths["schedule"], [row for row in _base_schedule_rows() if row["week"] == 2])
    _write_csv(paths["projections"], [row for row in _base_projection_rows() if row["api_event_id"].startswith("2026_1_")])
    _write_csv(paths["line"], [{"api_event_id": "2026_2_NYG_DAL", "commence_time": "2026-09-18T00:20:00+00:00", "away_team": "NYG", "home_team": "DAL"}])
    _write_csv(paths["ranked"], [{"api_event_id": "2026_2_NYG_DAL", "commence_time": "2026-09-18T00:20:00+00:00", "away_team": "NYG", "home_team": "DAL"}])

    readiness = wk.build_week_readiness(canonical={"season": 2026, "week": 2})

    assert readiness["projectionsReady"] is False


def test_readiness_missing_ranked_board_is_false(monkeypatch, tmp_path):
    paths = _configure_artifact_paths(monkeypatch, tmp_path)
    _write_csv(paths["schedule"], [row for row in _base_schedule_rows() if row["week"] == 2])
    _write_csv(paths["projections"], [row for row in _base_projection_rows() if row["api_event_id"].startswith("2026_2_")])
    _write_csv(paths["line"], [{"api_event_id": "2026_2_NYG_DAL", "commence_time": "2026-09-18T00:20:00+00:00", "away_team": "NYG", "home_team": "DAL"}])

    readiness = wk.build_week_readiness(canonical={"season": 2026, "week": 2})

    assert readiness["rankingsReady"] is False


def test_readiness_ranked_only_prior_week_is_false(monkeypatch, tmp_path):
    paths = _configure_artifact_paths(monkeypatch, tmp_path)
    _write_csv(paths["schedule"], [row for row in _base_schedule_rows() if row["week"] == 2])
    _write_csv(paths["projections"], [row for row in _base_projection_rows() if row["api_event_id"].startswith("2026_2_")])
    _write_csv(paths["line"], [{"api_event_id": "2026_2_NYG_DAL", "commence_time": "2026-09-18T00:20:00+00:00", "away_team": "NYG", "home_team": "DAL"}])
    _write_csv(paths["ranked"], [{"api_event_id": "2026_1_DEN_KC", "commence_time": "2026-09-15T00:20:00+00:00", "away_team": "DEN", "home_team": "KC"}])

    readiness = wk.build_week_readiness(canonical={"season": 2026, "week": 2})

    assert readiness["rankingsReady"] is False


def test_readiness_markets_true_rankings_false(monkeypatch, tmp_path):
    paths = _configure_artifact_paths(monkeypatch, tmp_path)
    _write_csv(paths["schedule"], [row for row in _base_schedule_rows() if row["week"] == 2])
    _write_csv(paths["projections"], [row for row in _base_projection_rows() if row["api_event_id"].startswith("2026_2_")])
    _write_csv(
        paths["line"],
        [
            {"api_event_id": "2026_2_NYG_DAL", "commence_time": "2026-09-18T00:20:00+00:00", "away_team": "NYG", "home_team": "DAL"},
            {"api_event_id": "2026_2_PHI_WAS", "commence_time": "2026-09-20T17:00:00+00:00", "away_team": "PHI", "home_team": "WAS"},
        ],
    )

    readiness = wk.build_week_readiness(canonical={"season": 2026, "week": 2})

    assert readiness["marketsReady"] is True
    assert readiness["rankingsReady"] is False
