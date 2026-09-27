from __future__ import annotations

import csv
import gzip
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
import app.services.schedule_engine.source_ingestion as ingest_module

from app.services.power_engine import (
    CANONICAL_NFL_TEAMS,
    PowerEngineStore,
    PowerLineageRecord,
    PowerSnapshot,
    PowerTeamRating,
    apply_frozen_weekly_power_transition,
    snapshot_hash,
)
from app.services.result_engine import ResultEngineStore, freeze_week_result_set
from app.services.schedule_engine import (
    ScheduleEngineStore,
    compare_candidate_to_legacy_seed,
    ingest_nflverse_schedule_source_bytes,
    load_active_schedule,
    load_active_schedule_by_identity,
)
from app.services.schedule_engine.source_ingestion import ScheduleSourceIngestionError
from result_engine_test_utils import make_accepted_result, make_identity


def _store(tmp_path: Path) -> ScheduleEngineStore:
    return ScheduleEngineStore(root_dir=tmp_path / "schedule-store")


def _result_store(tmp_path: Path) -> ResultEngineStore:
    return ResultEngineStore(root_dir=tmp_path / "result-store")


def _power_store(tmp_path: Path) -> PowerEngineStore:
    return PowerEngineStore(root_dir=tmp_path / "power-store")


def _build_csv_gz(rows: list[dict[str, str]]) -> bytes:
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
    for row in rows:
        payload = {key: "" for key in writer.fieldnames}
        payload.update(row)
        writer.writerow(payload)
    return gzip.compress(output.getvalue().encode("utf-8"))


def _rows_week3(kickoff_a: str = "20:20") -> list[dict[str, str]]:
    return [
        {
            "game_id": "2026_03_ARI_ATL",
            "season": "2026",
            "week": "3",
            "game_type": "REG",
            "gameday": "2026-09-24",
            "gametime": kickoff_a,
            "away_team": "ARI",
            "home_team": "ATL",
            "weekday": "Thursday",
        },
        {
            "game_id": "2026_03_BAL_BUF",
            "season": "2026",
            "week": "3",
            "game_type": "REG",
            "gameday": "2026-09-27",
            "gametime": "13:00",
            "away_team": "BAL",
            "home_team": "BUF",
            "weekday": "Sunday",
        },
    ]


def _rows_week18_and_wc() -> list[dict[str, str]]:
    return [
        {
            "game_id": "2026_18_MIA_NYJ",
            "season": "2026",
            "week": "18",
            "game_type": "REG",
            "gameday": "2027-01-10",
            "gametime": "13:00",
            "away_team": "MIA",
            "home_team": "NYJ",
        },
        {
            "game_id": "2026_19_BAL_KC",
            "season": "2026",
            "week": "19",
            "game_type": "WC",
            "gameday": "2027-01-16",
            "gametime": "20:15",
            "away_team": "BAL",
            "home_team": "KC",
        },
    ]


def _ingest(
    tmp_path: Path,
    payload: bytes,
    *,
    release_id: str = "251386473",
    asset_id: str = "591413177",
    asset_updated_at: str = "2026-09-26T20:37:02Z",
    asset_digest_reported: str | None = None,
):
    return ingest_nflverse_schedule_source_bytes(
        payload_bytes=payload,
        source_uri="https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv.gz",
        release_tag="schedules",
        release_id=release_id,
        release_published_at="2025-10-01T11:19:34Z",
        release_updated_at="2026-09-26T20:37:03Z",
        target_commitish="main",
        asset_name="games.csv.gz",
        asset_id=asset_id,
        asset_updated_at=asset_updated_at,
        asset_size_bytes_reported=len(payload),
        asset_digest_reported=asset_digest_reported,
        http_etag='"abc"',
        http_last_modified="Sat, 26 Sep 2026 20:37:02 GMT",
        store=_store(tmp_path),
        result_store=_result_store(tmp_path),
        power_store=_power_store(tmp_path),
    )


def _source_dir(tmp_path: Path, source_version: str) -> Path:
    return _store(tmp_path).root_dir / "sources" / "nflverse" / source_version


def _snapshot(*, season: int, through_week: int, snapshot_id: str) -> PowerSnapshot:
    teams = tuple(PowerTeamRating(team_id=team, power=float(idx) / 5.0) for idx, team in enumerate(CANONICAL_NFL_TEAMS))
    base = PowerSnapshot(
        snapshot_id=snapshot_id,
        snapshot_hash="",
        season=season,
        through_week=through_week,
        updater_version="power-updater-v1",
        methodology_hash="method-v1",
        source_snapshot_id=None,
        generated_at="2026-09-10T00:00:00Z",
        teams=teams,
    )
    return replace(base, snapshot_hash=snapshot_hash(base))


def _seed_active_lineage(power_store: PowerEngineStore, *, season: int, through_week: int, snapshot_id: str, lineage_id: str) -> PowerSnapshot:
    snap = power_store.persist_snapshot(_snapshot(season=season, through_week=through_week, snapshot_id=snapshot_id))
    lineage = PowerLineageRecord(
        lineage_id=lineage_id,
        parent_lineage_id=None,
        root_snapshot_id=snap.snapshot_id,
        active_snapshot_id=snap.snapshot_id,
        season=season,
        through_week=through_week,
        status="ACTIVE",
        created_at="2026-09-10T00:00:00Z",
        superseded_at=None,
        superseded_by=None,
    )
    power_store.create_lineage(lineage, set_active=True)
    return snap


def _freeze_week_result_set_for_rows(result_store: ResultEngineStore, *, season: int, week: int, rows: list[dict[str, str]]) -> None:
    expected = []
    accepted = []
    for idx, row in enumerate(rows):
        kickoff = "2026-09-25T00:20:00Z" if idx == 0 else "2026-09-27T17:00:00Z"
        expected.append(
            make_identity(
                season=season,
                week=week,
                away_team=row["away_team"],
                home_team=row["home_team"],
                kickoff_utc=kickoff,
            )
        )
        accepted.append(
            make_accepted_result(
                season=season,
                week=week,
                away_team=row["away_team"],
                home_team=row["home_team"],
                kickoff_utc=kickoff,
                source_event_id=f"evt-{week}-{idx}",
                away_score=17 + idx,
                home_score=20 + idx,
            )
        )
    out = freeze_week_result_set(
        store=result_store,
        season=season,
        week=week,
        expected_events=expected,
        accepted_results=accepted,
    )
    assert out["status"] == "FROZEN"


def test_source_version_determinism(tmp_path: Path):
    payload = _build_csv_gz(_rows_week3())
    first = _ingest(tmp_path / "a", payload)
    second = _ingest(tmp_path / "b", payload)
    assert first["sourceVersion"] == second["sourceVersion"]


def test_ingest_persists_raw_manifest_and_active_pointer(tmp_path: Path):
    payload = _build_csv_gz(_rows_week3())
    out = _ingest(tmp_path, payload)

    assert out["status"] == "INGESTED"
    assert out["manifest"]["parser_format"] == "csv.gz"
    assert out["manifest"]["row_count"] == 2

    active = load_active_schedule(season=2026, week=3, store=_store(tmp_path))
    assert active.event_count == 2
    assert all(event.game_type == "REG" for event in active.events)


def test_same_source_replay_idempotent(tmp_path: Path):
    payload = _build_csv_gz(_rows_week3())
    first = _ingest(tmp_path, payload)
    second = _ingest(tmp_path, payload)

    assert first["sourceVersion"] == second["sourceVersion"]
    assert second["sourcePersisted"] == "ALREADY_PERSISTED"
    assert second["weeks"][0]["status"] == "UNCHANGED_CANONICAL"


def test_same_canonical_new_source_version_keeps_active_pointer(tmp_path: Path):
    payload = _build_csv_gz(_rows_week3())
    first = _ingest(tmp_path, payload, release_id="r1", asset_id="a1", asset_updated_at="2026-09-26T20:37:02Z")
    active_before = load_active_schedule(season=2026, week=3, store=_store(tmp_path))

    second = _ingest(tmp_path, payload, release_id="r2", asset_id="a2", asset_updated_at="2026-09-26T20:40:00Z")
    active_after = load_active_schedule(season=2026, week=3, store=_store(tmp_path))

    assert first["sourceVersion"] != second["sourceVersion"]
    assert second["weeks"][0]["status"] == "UNCHANGED_CANONICAL"
    assert active_before.schedule_hash == active_after.schedule_hash
    assert active_before.schedule_version == active_after.schedule_version


def test_future_correction_promotes_new_active_version(tmp_path: Path):
    first = _ingest(tmp_path, _build_csv_gz(_rows_week3()))
    before = load_active_schedule(season=2026, week=3, store=_store(tmp_path))

    corrected_rows = _rows_week3(kickoff_a="20:25")
    second = _ingest(tmp_path, _build_csv_gz(corrected_rows), release_id="r2", asset_id="a2", asset_updated_at="2026-09-26T21:00:00Z")
    after = load_active_schedule(season=2026, week=3, store=_store(tmp_path))

    assert first["sourceVersion"] != second["sourceVersion"]
    assert second["weeks"][0]["status"] == "PROMOTED_UPDATED"
    assert before.schedule_hash != after.schedule_hash


def test_consumed_week_frozen_result_conflicts_without_pointer_move(tmp_path: Path):
    payload = _build_csv_gz(_rows_week3())
    _ingest(tmp_path, payload)
    baseline = load_active_schedule(season=2026, week=3, store=_store(tmp_path))

    _freeze_week_result_set_for_rows(_result_store(tmp_path), season=2026, week=3, rows=_rows_week3())

    out = _ingest(
        tmp_path,
        _build_csv_gz(_rows_week3(kickoff_a="20:25")),
        release_id="r2",
        asset_id="a2",
        asset_updated_at="2026-09-26T22:00:00Z",
    )
    current = load_active_schedule(season=2026, week=3, store=_store(tmp_path))

    assert out["weeks"][0]["status"] == "CONFLICT_CONSUMED_WEEK"
    assert current.schedule_hash == baseline.schedule_hash


def test_consumed_week_power_transition_conflicts_without_pointer_move(tmp_path: Path):
    rows = _rows_week3()
    _ingest(tmp_path, _build_csv_gz(rows))
    baseline = load_active_schedule(season=2026, week=3, store=_store(tmp_path))

    power_store = _power_store(tmp_path)
    result_store = _result_store(tmp_path)
    _seed_active_lineage(power_store, season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    _freeze_week_result_set_for_rows(result_store, season=2026, week=3, rows=rows)
    transition = apply_frozen_weekly_power_transition(season=2026, week=3, power_store=power_store, result_store=result_store)
    assert transition["status"] == "APPLIED"

    out = _ingest(
        tmp_path,
        _build_csv_gz(_rows_week3(kickoff_a="20:25")),
        release_id="r3",
        asset_id="a3",
        asset_updated_at="2026-09-26T23:00:00Z",
    )
    current = load_active_schedule(season=2026, week=3, store=_store(tmp_path))

    assert out["weeks"][0]["status"] == "CONFLICT_CONSUMED_WEEK"
    assert current.schedule_hash == baseline.schedule_hash


def test_active_pointer_hash_verification(tmp_path: Path):
    _ingest(tmp_path, _build_csv_gz(_rows_week3()))

    pointer_path = _store(tmp_path).root_dir / "active" / "2026" / "week-3.json"
    payload = json.loads(pointer_path.read_text(encoding="utf-8"))
    payload["schedule_hash"] = "deadbeef"
    pointer_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ScheduleSourceIngestionError, match="ACTIVE_SCHEDULE_HASH_MISMATCH"):
        load_active_schedule(season=2026, week=3, store=_store(tmp_path))


def test_active_identity_read_is_strict(tmp_path: Path):
    _ingest(tmp_path, _build_csv_gz(_rows_week3()))
    active_before = load_active_schedule(season=2026, week=3, store=_store(tmp_path))

    _ingest(
        tmp_path,
        _build_csv_gz(_rows_week3(kickoff_a="20:25")),
        release_id="r2",
        asset_id="a2",
        asset_updated_at="2026-09-26T21:00:00Z",
    )

    with pytest.raises(ScheduleSourceIngestionError, match="ACTIVE_SCHEDULE_POINTER_IDENTITY_MISMATCH"):
        load_active_schedule_by_identity(
            season=2026,
            week=3,
            schedule_version=active_before.schedule_version,
            schedule_hash=active_before.schedule_hash,
            store=_store(tmp_path),
        )


def test_required_validation_failures(tmp_path: Path):
    payload = b"<html>error</html>"
    with pytest.raises(ScheduleSourceIngestionError, match="SCHEDULE_SOURCE_HTML_RESPONSE"):
        _ingest(tmp_path / "html", payload)

    bad_gzip = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xffbad"
    with pytest.raises(ScheduleSourceIngestionError, match="SCHEDULE_SOURCE_GZIP_INVALID"):
        _ingest(tmp_path / "gzip", bad_gzip)

    with pytest.raises(ScheduleSourceIngestionError, match="SCHEDULE_SOURCE_DIGEST_MISMATCH"):
        _ingest(tmp_path / "digest", _build_csv_gz(_rows_week3()), asset_digest_reported="sha256:0000")


def test_schema_and_duplicate_validation_failures(tmp_path: Path):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["game_id", "season"])
    writer.writeheader()
    writer.writerow({"game_id": "x", "season": "2026"})
    with pytest.raises(ScheduleSourceIngestionError, match="SCHEDULE_SOURCE_SCHEMA_MISSING_FIELDS"):
        _ingest(tmp_path / "schema", gzip.compress(output.getvalue().encode("utf-8")))

    dup = _rows_week3()
    dup[1]["game_id"] = dup[0]["game_id"]
    with pytest.raises(ScheduleSourceIngestionError, match="SCHEDULE_SOURCE_DUPLICATE_GAME_ID"):
        _ingest(tmp_path / "dup", _build_csv_gz(dup))


def test_game_type_preserved_for_postseason(tmp_path: Path):
    out = _ingest(tmp_path, _build_csv_gz(_rows_week18_and_wc()))
    assert {item["week"] for item in out["weeks"]} == {18, 19}

    reg = load_active_schedule(season=2026, week=18, store=_store(tmp_path))
    wc = load_active_schedule(season=2026, week=19, store=_store(tmp_path))
    assert reg.events[0].game_type == "REG"
    assert wc.events[0].game_type == "WC"


def test_legacy_parity_report(tmp_path: Path):
    # Seed legacy canonical artifact through existing legacy path.
    from app.services.schedule_engine import materialize_canonical_weekly_schedule
    import duckdb

    db_path = tmp_path / "legacy.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE schedules (
            game_id VARCHAR,
            season INTEGER,
            week INTEGER,
            gameday VARCHAR,
            gametime VARCHAR,
            away_team VARCHAR,
            home_team VARCHAR
        )
        """
    )
    for row in _rows_week3():
        con.execute(
            "INSERT INTO schedules VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                row["game_id"],
                int(row["season"]),
                int(row["week"]),
                row["gameday"],
                row["gametime"],
                row["away_team"],
                row["home_team"],
            ],
        )
    con.close()

    materialize_canonical_weekly_schedule(season=2026, week=3, store=_store(tmp_path), duckdb_path=db_path)
    out = _ingest(tmp_path, _build_csv_gz(_rows_week3()))
    statuses = [item["status"] for item in out["legacyParity"]]
    assert "PARITY" in statuses


def test_concurrent_identical_ingestion(tmp_path: Path):
    payload = _build_csv_gz(_rows_week3())
    barrier = threading.Barrier(2)

    def _run() -> str:
        barrier.wait()
        out = _ingest(tmp_path, payload)
        return out["weeks"][0]["status"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(list(pool.map(lambda _: _run(), range(2))))

    assert statuses == ["PROMOTED_INITIAL", "UNCHANGED_CANONICAL"]


def test_concurrent_conflicting_ingestion(tmp_path: Path):
    left = _build_csv_gz(_rows_week3())
    right = _build_csv_gz(_rows_week3(kickoff_a="20:25"))
    barrier = threading.Barrier(2)

    def _run(payload: bytes) -> str:
        barrier.wait()
        return _ingest(tmp_path, payload)["weeks"][0]["status"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(_run, [left, right]))

    assert {a, b} <= {"PROMOTED_INITIAL", "PROMOTED_UPDATED", "UNCHANGED_CANONICAL"}


def test_raw_tamper_fails_closed(tmp_path: Path):
    payload = _build_csv_gz(_rows_week3())
    out = _ingest(tmp_path, payload)
    source_version = out["sourceVersion"]
    bytes_path = _source_dir(tmp_path, source_version) / "games.csv.gz"
    bytes_path.write_bytes(b"corrupt")

    with pytest.raises(ScheduleSourceIngestionError, match="SCHEDULE_SOURCE_IMMUTABLE_CONFLICT"):
        _ingest(tmp_path, payload)


def test_manifest_tamper_fails_closed(tmp_path: Path):
    payload = _build_csv_gz(_rows_week3())
    out = _ingest(tmp_path, payload)
    source_version = out["sourceVersion"]
    manifest_path = _source_dir(tmp_path, source_version) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["asset_id"] = "tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ScheduleSourceIngestionError, match="SCHEDULE_SOURCE_MANIFEST_CONFLICT"):
        _ingest(tmp_path, payload)


def test_missing_artifact_fails_closed(tmp_path: Path):
    _ingest(tmp_path, _build_csv_gz(_rows_week3()))
    active = load_active_schedule(season=2026, week=3, store=_store(tmp_path))
    artifact_path = _store(tmp_path).root_dir / "weeks" / "2026" / "week-3" / f"{active.schedule_version}.json"
    artifact_path.unlink()

    with pytest.raises(ScheduleSourceIngestionError, match="ACTIVE_SCHEDULE_ARTIFACT_MISSING"):
        load_active_schedule(season=2026, week=3, store=_store(tmp_path))


def test_tampered_artifact_fails_closed(tmp_path: Path):
    _ingest(tmp_path, _build_csv_gz(_rows_week3()))
    active = load_active_schedule(season=2026, week=3, store=_store(tmp_path))
    artifact_path = _store(tmp_path).root_dir / "weeks" / "2026" / "week-3" / f"{active.schedule_version}.json"
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["events"][0]["away_team"] = "NYJ"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(Exception):
        load_active_schedule(season=2026, week=3, store=_store(tmp_path))


def test_pointer_source_lineage_mismatch_fails_closed(tmp_path: Path):
    _ingest(tmp_path, _build_csv_gz(_rows_week3()))
    pointer_path = _store(tmp_path).root_dir / "active" / "2026" / "week-3.json"
    payload = json.loads(pointer_path.read_text(encoding="utf-8"))
    payload["source_version"] = "different"
    pointer_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ScheduleSourceIngestionError, match="ACTIVE_SCHEDULE_SOURCE_VERSION_MISMATCH"):
        load_active_schedule(season=2026, week=3, store=_store(tmp_path))


def test_duplicate_canonical_event_key_fails_closed(tmp_path: Path):
    dup_key_rows = [
        {
            "game_id": "2026_03_AAA_BBB_1",
            "season": "2026",
            "week": "3",
            "game_type": "REG",
            "gameday": "2026-09-24",
            "gametime": "20:20",
            "away_team": "ARI",
            "home_team": "ATL",
        },
        {
            "game_id": "2026_03_AAA_BBB_2",
            "season": "2026",
            "week": "3",
            "game_type": "REG",
            "gameday": "2026-09-24",
            "gametime": "20:20",
            "away_team": "ARI",
            "home_team": "ATL",
        },
    ]
    with pytest.raises(Exception, match="SCHEDULE_DUPLICATE_CANONICAL_EVENT_KEY"):
        _ingest(tmp_path, _build_csv_gz(dup_key_rows))


def test_invalid_kickoff_and_team_validation_fails_closed(tmp_path: Path):
    bad_kickoff = _rows_week3()
    bad_kickoff[0]["gametime"] = "8:15 PM"
    with pytest.raises(Exception, match="SCHEDULE_GAMETIME_INVALID"):
        _ingest(tmp_path / "kickoff", _build_csv_gz(bad_kickoff))

    missing_away = _rows_week3()
    missing_away[0]["away_team"] = ""
    with pytest.raises(Exception):
        _ingest(tmp_path / "away", _build_csv_gz(missing_away))

    missing_home = _rows_week3()
    missing_home[0]["home_team"] = ""
    with pytest.raises(Exception):
        _ingest(tmp_path / "home", _build_csv_gz(missing_home))

    same_team = _rows_week3()
    same_team[0]["away_team"] = "ATL"
    same_team[0]["home_team"] = "ATL"
    with pytest.raises(ScheduleSourceIngestionError, match="SCHEDULE_SOURCE_IDENTITY_INVALID"):
        _ingest(tmp_path / "identity", _build_csv_gz(same_team))


def test_incomplete_week_is_allowed_structurally(tmp_path: Path):
    one_game = [_rows_week3()[0]]
    out = _ingest(tmp_path, _build_csv_gz(one_game))
    assert out["weeks"][0]["status"] == "PROMOTED_INITIAL"
    active = load_active_schedule(season=2026, week=3, store=_store(tmp_path))
    assert active.event_count == 1


def test_game_types_reg_wc_div_con_sb_preserved(tmp_path: Path):
    rows = [
        {"game_id": "2026_18_REG", "season": "2026", "week": "18", "game_type": "REG", "gameday": "2027-01-10", "gametime": "13:00", "away_team": "MIA", "home_team": "NYJ"},
        {"game_id": "2026_19_WC", "season": "2026", "week": "19", "game_type": "WC", "gameday": "2027-01-16", "gametime": "13:00", "away_team": "BAL", "home_team": "KC"},
        {"game_id": "2026_20_DIV", "season": "2026", "week": "20", "game_type": "DIV", "gameday": "2027-01-23", "gametime": "13:00", "away_team": "BUF", "home_team": "CIN"},
        {"game_id": "2026_21_CON", "season": "2026", "week": "21", "game_type": "CON", "gameday": "2027-01-30", "gametime": "13:00", "away_team": "DAL", "home_team": "PHI"},
        {"game_id": "2026_22_SB", "season": "2026", "week": "22", "game_type": "SB", "gameday": "2027-02-06", "gametime": "18:30", "away_team": "SF", "home_team": "KC"},
    ]
    _ingest(tmp_path, _build_csv_gz(rows))
    assert load_active_schedule(season=2026, week=18, store=_store(tmp_path)).events[0].game_type == "REG"
    assert load_active_schedule(season=2026, week=19, store=_store(tmp_path)).events[0].game_type == "WC"
    assert load_active_schedule(season=2026, week=20, store=_store(tmp_path)).events[0].game_type == "DIV"
    assert load_active_schedule(season=2026, week=21, store=_store(tmp_path)).events[0].game_type == "CON"
    assert load_active_schedule(season=2026, week=22, store=_store(tmp_path)).events[0].game_type == "SB"


def test_game_type_changes_affect_schedule_hash(tmp_path: Path):
    rows_reg = [
        {
            "game_id": "2026_19_BAL_KC",
            "season": "2026",
            "week": "19",
            "game_type": "REG",
            "gameday": "2027-01-16",
            "gametime": "20:15",
            "away_team": "BAL",
            "home_team": "KC",
        }
    ]
    _ingest(tmp_path, _build_csv_gz(rows_reg))
    reg = load_active_schedule(season=2026, week=19, store=_store(tmp_path))

    rows_wc = [dict(rows_reg[0], game_type="WC")]
    _ingest(tmp_path, _build_csv_gz(rows_wc), release_id="r2", asset_id="a2", asset_updated_at="2026-09-26T21:00:00Z")
    wc = load_active_schedule(season=2026, week=19, store=_store(tmp_path))

    assert reg.schedule_hash != wc.schedule_hash


def test_game_type_collision_same_identity_fails_closed(tmp_path: Path):
    rows = [
        {
            "game_id": "2026_19_BAL_KC_A",
            "season": "2026",
            "week": "19",
            "game_type": "REG",
            "gameday": "2027-01-16",
            "gametime": "20:15",
            "away_team": "BAL",
            "home_team": "KC",
        },
        {
            "game_id": "2026_19_BAL_KC_B",
            "season": "2026",
            "week": "19",
            "game_type": "WC",
            "gameday": "2027-01-16",
            "gametime": "20:15",
            "away_team": "BAL",
            "home_team": "KC",
        },
    ]
    with pytest.raises(Exception, match="SCHEDULE_DUPLICATE_CANONICAL_EVENT_KEY"):
        _ingest(tmp_path, _build_csv_gz(rows))


def test_malformed_consumed_state_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _ingest(tmp_path, _build_csv_gz(_rows_week3()))
    _seed_active_lineage(_power_store(tmp_path), season=2026, through_week=2, snapshot_id="power-2026-wk2", lineage_id="ln-2026-wk2")
    monkeypatch.setattr(ingest_module, "active_power_transition_observability", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    out = _ingest(
        tmp_path,
        _build_csv_gz(_rows_week3(kickoff_a="20:25")),
        release_id="r2",
        asset_id="a2",
        asset_updated_at="2026-09-26T21:00:00Z",
    )
    assert out["weeks"][0]["status"] == "CONFLICT_CONSUMED_WEEK"
    assert out["weeks"][0]["reason"] == "CONSUMED_STATE_UNVERIFIED"


def test_raw_write_failure_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ingest_module, "_atomic_write_bytes", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("raw boom")))
    with pytest.raises(OSError, match="raw boom"):
        _ingest(tmp_path, _build_csv_gz(_rows_week3()))
    pointer = _store(tmp_path).root_dir / "active" / "2026" / "week-3.json"
    assert not pointer.exists()


def test_restart_after_raw_persistence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    original = ingest_module._persist_canonical_version

    def _boom(*args, **kwargs):
        raise OSError("canonical boom")

    monkeypatch.setattr(ingest_module, "_persist_canonical_version", _boom)
    with pytest.raises(OSError, match="canonical boom"):
        _ingest(tmp_path, _build_csv_gz(_rows_week3()))

    monkeypatch.setattr(ingest_module, "_persist_canonical_version", original)
    out = _ingest(tmp_path, _build_csv_gz(_rows_week3()))
    assert out["weeks"][0]["status"] == "PROMOTED_INITIAL"


def test_pointer_write_failure_and_restart_after_canonical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    original = ingest_module._publish_active_pointer

    def _boom(*args, **kwargs):
        raise OSError("pointer boom")

    monkeypatch.setattr(ingest_module, "_publish_active_pointer", _boom)
    with pytest.raises(OSError, match="pointer boom"):
        _ingest(tmp_path, _build_csv_gz(_rows_week3()))

    monkeypatch.setattr(ingest_module, "_publish_active_pointer", original)
    out = _ingest(tmp_path, _build_csv_gz(_rows_week3()))
    assert out["weeks"][0]["status"] == "PROMOTED_INITIAL"


def test_legacy_diff_read_only(tmp_path: Path):
    from app.services.schedule_engine import materialize_canonical_weekly_schedule
    import duckdb

    db_path = tmp_path / "legacy.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE schedules (
            game_id VARCHAR,
            season INTEGER,
            week INTEGER,
            gameday VARCHAR,
            gametime VARCHAR,
            away_team VARCHAR,
            home_team VARCHAR
        )
        """
    )
    for row in _rows_week3():
        con.execute(
            "INSERT INTO schedules VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                row["game_id"],
                int(row["season"]),
                int(row["week"]),
                row["gameday"],
                row["gametime"],
                row["away_team"],
                row["home_team"],
            ],
        )
    con.close()

    materialize_canonical_weekly_schedule(season=2026, week=3, store=_store(tmp_path), duckdb_path=db_path)
    legacy_path = _store(tmp_path).root_dir / "weeks" / "canonical-weekly-schedule-2026-3.json"
    legacy_before = legacy_path.read_text(encoding="utf-8")

    changed = _rows_week3(kickoff_a="20:25")
    out = _ingest(tmp_path, _build_csv_gz(changed))

    statuses = [item["status"] for item in out["legacyParity"]]
    assert "DIFF" in statuses
    assert legacy_path.read_text(encoding="utf-8") == legacy_before
