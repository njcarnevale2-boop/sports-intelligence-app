from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.personnel_authority import load_personnel_authority_lookup
from app.services.personnel_ingestion import (
    PersonnelIngestionError,
    build_personnel_snapshot,
    load_latest_personnel_snapshot,
    normalize_team_id,
    write_personnel_snapshot,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "personnel"


def _fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_html_injury_fixture_parses_statuses_and_position_groups() -> None:
    snapshot = build_personnel_snapshot(
        season=2026,
        week=3,
        source_url="https://www.nfl.com/injuries/",
        source_payload=_fixture_text("nfl_injuries_week3.html"),
        source_timestamp="2026-09-25T17:05:00Z",
        retrieved_at="2026-09-25T17:06:00Z",
    )

    assert snapshot.source_timestamp == "2026-09-25T17:05:00Z"
    assert snapshot.records[0].retrieved_at == "2026-09-25T17:06:00Z"
    assert {record.team for record in snapshot.records} == {"WAS", "SEA", "DET"}
    assert {record.position_group for record in snapshot.records} == {"QB", "WR", "OL"}
    by_player = {record.player_name: record for record in snapshot.records}
    assert by_player["Jayden Daniels"].normalized_availability == "OUT"
    assert by_player["DK Metcalf"].normalized_availability == "QUESTIONABLE"
    assert by_player["Frank Ragnow"].normalized_availability == "DOUBTFUL"
    assert by_player["Jayden Daniels"].practice_status == "Dnp"
    assert by_player["Jayden Daniels"].injury_description == "Elbow"


def test_json_injury_fixture_team_normalization_and_provenance() -> None:
    snapshot = build_personnel_snapshot(
        season=2026,
        week=3,
        source_url="https://www.nfl.com/injuries/",
        source_payload=_fixture_text("nfl_injuries_week3.json"),
        source_timestamp="2026-09-25T17:05:00Z",
        retrieved_at="2026-09-25T17:06:00Z",
    )

    assert normalize_team_id("Washington Commanders") == "WAS"
    assert normalize_team_id("L.A. Rams") == "LAR"
    assert snapshot.personnel_snapshot_id.startswith("personnel-")
    assert snapshot.personnel_snapshot_hash
    assert snapshot.records[0].source_url == "https://www.nfl.com/injuries/"
    assert snapshot.records[0].source == "nfl.com/injuries"


def test_washington_out_does_not_auto_verify_replacement_starter(monkeypatch: pytest.MonkeyPatch) -> None:
    injuries = json.loads(_fixture_text("nfl_injuries_week3.json"))
    snapshot = build_personnel_snapshot(
        season=2026,
        week=3,
        source_url="https://www.nfl.com/injuries/",
        source_payload=injuries,
        source_timestamp="2026-09-25T17:05:00Z",
        retrieved_at="2026-09-25T17:06:00Z",
    )

    monkeypatch.setattr(
        "app.services.personnel_authority.load_latest_personnel_snapshot",
        lambda *, season, week, store_root=None: snapshot,
    )

    lookup = load_personnel_authority_lookup(
        season=2026,
        week=3,
        schedule_events=[SimpleNamespace(source_event_id="2026_03_WAS_SEA", canonical_event_key="2026_03_WAS_SEA", away_team="WAS", home_team="SEA")],
    )

    authority = lookup["2026_03_WAS_SEA"]
    assert authority["awayExpectedStartingQB"] is None
    assert authority["awayQBStatus"] == "UNVERIFIED"
    assert authority["qbResolutionStatus"] == "UNAVAILABLE"
    assert authority["personnelReadiness"] == "UNAVAILABLE"
    assert authority["personnelReadinessReason"] == "QB_RESOLUTION_UNVERIFIED"


def test_explicit_starter_evidence_can_verify_qb_resolution() -> None:
    injuries = json.loads(_fixture_text("nfl_injuries_week3.json"))
    starter_evidence = json.loads(_fixture_text("starter_evidence_week3.json"))["starter_evidence"]
    snapshot = build_personnel_snapshot(
        season=2026,
        week=3,
        source_url="https://www.nfl.com/injuries/",
        source_payload=injuries,
        source_timestamp="2026-09-25T17:05:00Z",
        retrieved_at="2026-09-25T17:06:00Z",
        starter_evidence=starter_evidence,
    )

    lookup = load_personnel_authority_lookup(
        season=2026,
        week=3,
        personnel_snapshot=snapshot,
        schedule_events=[SimpleNamespace(source_event_id="2026_03_WAS_SEA", canonical_event_key="2026_03_WAS_SEA", away_team="WAS", home_team="SEA")],
    )

    authority = lookup["2026_03_WAS_SEA"]
    assert authority["awayExpectedStartingQB"] == "Marcus Mariota"
    assert authority["homeExpectedStartingQB"] == "Geno Smith"
    assert authority["awayQBStatus"] == "VERIFIED"
    assert authority["homeQBStatus"] == "VERIFIED"
    assert authority["qbResolutionStatus"] == "CURRENT"
    assert authority["personnelReadiness"] == "CURRENT"
    assert authority["personnelReadinessReason"] == "QB_STATUS_CURRENT"


def test_duplicate_player_conflict_fails_closed() -> None:
    payload = json.loads(_fixture_text("nfl_injuries_week3.json"))
    payload["injuries"].append(
        {
            "team": "WAS",
            "player_name": "Jayden Daniels",
            "position": "QB",
            "injury_description": "Elbow",
            "practice_status": "Full",
            "game_status": "QUESTIONABLE",
        }
    )

    with pytest.raises(PersonnelIngestionError, match="Conflicting personnel status"):
        build_personnel_snapshot(
            season=2026,
            week=3,
            source_url="https://www.nfl.com/injuries/",
            source_payload=payload,
            source_timestamp="2026-09-25T17:05:00Z",
            retrieved_at="2026-09-25T17:06:00Z",
        )


def test_unknown_team_fails_closed() -> None:
    payload = json.loads(_fixture_text("nfl_injuries_week3.json"))
    payload["injuries"][0]["team"] = "Gotham City"

    with pytest.raises(PersonnelIngestionError, match="Unknown team"):
        build_personnel_snapshot(
            season=2026,
            week=3,
            source_url="https://www.nfl.com/injuries/",
            source_payload=payload,
            source_timestamp="2026-09-25T17:05:00Z",
            retrieved_at="2026-09-25T17:06:00Z",
        )


def test_snapshot_hash_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    payload = json.loads(_fixture_text("nfl_injuries_week3.json"))
    first = build_personnel_snapshot(
        season=2026,
        week=3,
        source_url="https://www.nfl.com/injuries/",
        source_payload=payload,
        source_timestamp="2026-09-25T17:05:00Z",
        retrieved_at="2026-09-25T17:06:00Z",
    )
    second = build_personnel_snapshot(
        season=2026,
        week=3,
        source_url="https://www.nfl.com/injuries/",
        source_payload=payload,
        source_timestamp="2026-09-25T17:05:00Z",
        retrieved_at="2026-09-25T17:06:00Z",
    )

    assert first.personnel_snapshot_id == second.personnel_snapshot_id
    assert first.personnel_snapshot_hash == second.personnel_snapshot_hash

    first_path = write_personnel_snapshot(first, store_root=tmp_path / "personnel")
    second_path = write_personnel_snapshot(second, store_root=tmp_path / "personnel")
    assert first_path == second_path
    assert first_path.exists()
    assert load_latest_personnel_snapshot(season=2026, week=3, store_root=tmp_path / "personnel").personnel_snapshot_hash == first.personnel_snapshot_hash


def test_malformed_source_fails_closed() -> None:
    with pytest.raises(PersonnelIngestionError, match="PERSONNEL_SOURCE_PARSE_FAILED"):
        build_personnel_snapshot(
            season=2026,
            week=3,
            source_url="https://www.nfl.com/injuries/",
            source_payload='{"injuries": [}',
            source_timestamp="2026-09-25T17:05:00Z",
            retrieved_at="2026-09-25T17:06:00Z",
        )
