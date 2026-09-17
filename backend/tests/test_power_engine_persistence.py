from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from app.services.power_engine import (
    CANONICAL_NFL_TEAMS,
    FinalGameResult,
    PowerLineageRecord,
    PowerSnapshot,
    PowerTeamRating,
    PowerUpdateLedgerRecord,
    PowerEnginePersistenceError,
    PowerEngineStore,
    apply_single_game_update,
    build_ledger_record,
    snapshot_hash,
)


def _build_snapshot(
    *,
    snapshot_id: str = "snap-2026-wk0",
    generated_at: str = "2026-09-16T00:00:00+00:00",
    through_week: int = 0,
) -> PowerSnapshot:
    teams = tuple(
        PowerTeamRating(team_id=team, power=float(index) / 10.0)
        for index, team in enumerate(CANONICAL_NFL_TEAMS)
    )
    base = PowerSnapshot(
        snapshot_id=snapshot_id,
        snapshot_hash="",
        season=2026,
        through_week=through_week,
        updater_version="sia_power_engine_2e4a_v1",
        methodology_hash="a" * 64,
        source_snapshot_id=None,
        generated_at=generated_at,
        teams=teams,
    )
    return replace(base, snapshot_hash=snapshot_hash(base))


def _result(
    *,
    game_id: str = "2026_01_ARI_ATL",
    kickoff: str = "2026-09-10T20:20:00+00:00",
    home_team: str = "ATL",
    away_team: str = "ARI",
    home_score: int = 24,
    away_score: int = 17,
) -> FinalGameResult:
    return FinalGameResult(
        season=2026,
        week=1,
        game_id=game_id,
        kickoff_utc=kickoff,
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
        source_result_version="scores-v1",
    )


def _build_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PowerEngineStore:
    root = tmp_path / "power-engine-root"
    monkeypatch.setenv("POWER_ENGINE_ROOT", str(root))
    return PowerEngineStore()


def _build_ledger_record(
    *,
    snapshot_before: PowerSnapshot,
    snapshot_after: PowerSnapshot,
    lineage_id: str = "ln-2026-main",
) -> PowerUpdateLedgerRecord:
    result = _result()
    update = apply_single_game_update(
        home_power_before=0.1,
        away_power_before=0.0,
        result=result,
    )
    return build_ledger_record(
        lineage_id=lineage_id,
        snapshot_before=snapshot_before,
        snapshot_after=snapshot_after,
        result=result,
        update=update,
        generated_at="2026-09-16T01:00:00+00:00",
    )


def _write_snapshot_artifact(store: PowerEngineStore, snapshot: PowerSnapshot, *, file_name: str | None = None) -> None:
    store._ensure_dirs()
    payload = {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_hash": snapshot.snapshot_hash,
        "season": snapshot.season,
        "through_week": snapshot.through_week,
        "updater_version": snapshot.updater_version,
        "methodology_hash": snapshot.methodology_hash,
        "source_snapshot_id": snapshot.source_snapshot_id,
        "generated_at": snapshot.generated_at,
        "teams": [asdict(team) for team in snapshot.teams],
    }
    path = store._snapshots_dir / (file_name or f"{snapshot.snapshot_id}.json")
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _write_ledger_artifact(
    store: PowerEngineStore,
    record: PowerUpdateLedgerRecord,
    *,
    file_name: str | None = None,
) -> None:
    store._ensure_dirs()
    path = store._ledger_dir / (file_name or f"{record.update_id}.json")
    path.write_text(json.dumps(asdict(record), sort_keys=True), encoding="utf-8")


def _write_lineage_artifact(store: PowerEngineStore, lineage: PowerLineageRecord, *, file_name: str | None = None) -> None:
    store._ensure_dirs()
    path = store._lineages_dir / (file_name or f"{lineage.lineage_id}.json")
    path.write_text(json.dumps(asdict(lineage), sort_keys=True), encoding="utf-8")


def _write_active_pointer(store: PowerEngineStore, *, season: int, lineage_id: str, updated_at: str = "2026-09-17T00:00:00+00:00") -> None:
    store._ensure_dirs()
    path = store._active_lineage_pointer_path(season)
    path.write_text(
        json.dumps({"season": season, "lineage_id": lineage_id, "updated_at": updated_at}, sort_keys=True),
        encoding="utf-8",
    )


def test_snapshot_write_read_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    snap = _build_snapshot()

    persisted = store.persist_snapshot(snap)
    loaded = store.get_snapshot(snap.snapshot_id)

    assert persisted == snap
    assert loaded == snap


def test_snapshot_preserves_32_team_invariant(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    bad = _build_snapshot()
    bad = replace(bad, teams=bad.teams[:-1])

    with pytest.raises(PowerEnginePersistenceError):
        store.persist_snapshot(bad)


def test_snapshot_hash_verification(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    bad = replace(_build_snapshot(), snapshot_hash="b" * 64)

    with pytest.raises(PowerEnginePersistenceError, match="Snapshot hash mismatch"):
        store.persist_snapshot(bad)


def test_generated_at_does_not_change_snapshot_content_hash():
    a = _build_snapshot(snapshot_id="snap-a", generated_at="2026-09-16T00:00:00+00:00")
    b = _build_snapshot(snapshot_id="snap-b", generated_at="2026-09-17T00:00:00+00:00")
    assert a.snapshot_hash == b.snapshot_hash


def test_identical_snapshot_write_is_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    snap = _build_snapshot()

    one = store.persist_snapshot(snap)
    two = store.persist_snapshot(snap)

    assert one == two
    assert len(store.list_snapshots(season=2026)) == 1


def test_same_snapshot_id_different_content_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    snap = _build_snapshot(snapshot_id="snap-collision")
    store.persist_snapshot(snap)

    changed_team = list(snap.teams)
    changed_team[0] = PowerTeamRating(team_id=changed_team[0].team_id, power=99.0)
    changed = replace(
        snap,
        teams=tuple(changed_team),
        snapshot_hash=snapshot_hash(replace(snap, teams=tuple(changed_team), snapshot_hash="")),
    )

    with pytest.raises(PowerEnginePersistenceError, match="snapshot_id collision"):
        store.persist_snapshot(changed)


def test_corrupt_snapshot_hard_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    snap = _build_snapshot(snapshot_id="snap-corrupt")
    store.persist_snapshot(snap)

    snapshot_file = store.root_dir / "snapshots" / "snap-corrupt.json"
    snapshot_file.write_text('{"not":"valid"}', encoding="utf-8")

    with pytest.raises(PowerEnginePersistenceError):
        store.get_snapshot("snap-corrupt")


def test_truncated_snapshot_hard_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    snap = _build_snapshot(snapshot_id="snap-truncated")
    store.persist_snapshot(snap)

    snapshot_file = store.root_dir / "snapshots" / "snap-truncated.json"
    snapshot_file.write_text("{", encoding="utf-8")

    with pytest.raises(PowerEnginePersistenceError):
        store.get_snapshot("snap-truncated")


def test_ledger_write_read_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    before = store.persist_snapshot(_build_snapshot(snapshot_id="snap-before"))
    after = store.persist_snapshot(_build_snapshot(snapshot_id="snap-after", through_week=1))

    rec = _build_ledger_record(snapshot_before=before, snapshot_after=after)
    persisted = store.persist_ledger_record(rec)
    loaded = store.get_ledger_record(rec.update_id)

    assert persisted == rec
    assert loaded == rec


def test_ledger_idempotency_and_payload_hash_are_deterministic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    before = store.persist_snapshot(_build_snapshot(snapshot_id="snap-before-det"))
    after = store.persist_snapshot(_build_snapshot(snapshot_id="snap-after-det", through_week=1))

    a = _build_ledger_record(snapshot_before=before, snapshot_after=after)
    b = _build_ledger_record(snapshot_before=before, snapshot_after=after)

    assert a.idempotency_key == b.idempotency_key
    assert a.payload_hash == b.payload_hash
    assert a.update_id == b.update_id


def test_identical_ledger_replay_does_not_duplicate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    before = store.persist_snapshot(_build_snapshot(snapshot_id="snap-before-idem"))
    after = store.persist_snapshot(_build_snapshot(snapshot_id="snap-after-idem", through_week=1))
    rec = _build_ledger_record(snapshot_before=before, snapshot_after=after)

    one = store.persist_ledger_record(rec)
    two = store.persist_ledger_record(rec)

    assert one == two
    assert len(store.list_ledger(season=2026, week=1, lineage_id="ln-2026-main")) == 1


def test_same_ledger_idempotency_key_different_payload_hard_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    before = store.persist_snapshot(_build_snapshot(snapshot_id="snap-before-collision"))
    after = store.persist_snapshot(_build_snapshot(snapshot_id="snap-after-collision", through_week=1))
    rec = _build_ledger_record(snapshot_before=before, snapshot_after=after)
    store.persist_ledger_record(rec)

    changed = replace(rec, raw_error=rec.raw_error + 1.0, payload_hash=rec.payload_hash)
    with pytest.raises(PowerEnginePersistenceError, match="Ledger payload hash mismatch"):
        store.persist_ledger_record(changed)


def test_corrupt_ledger_hard_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    before = store.persist_snapshot(_build_snapshot(snapshot_id="snap-before-corrupt"))
    after = store.persist_snapshot(_build_snapshot(snapshot_id="snap-after-corrupt", through_week=1))
    rec = _build_ledger_record(snapshot_before=before, snapshot_after=after)
    store.persist_ledger_record(rec)

    ledger_file = store.root_dir / "ledger" / f"{rec.update_id}.json"
    ledger_file.write_text("{", encoding="utf-8")

    with pytest.raises(PowerEnginePersistenceError):
        store.get_ledger_record(rec.update_id)


def test_create_and_read_active_lineage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    snap = store.persist_snapshot(_build_snapshot(snapshot_id="snap-root"))
    lineage = PowerLineageRecord(
        lineage_id="ln-2026-a",
        parent_lineage_id=None,
        root_snapshot_id=snap.snapshot_id,
        active_snapshot_id=snap.snapshot_id,
        season=2026,
        through_week=0,
        status="ACTIVE",
        created_at="2026-09-16T00:00:00+00:00",
        superseded_at=None,
        superseded_by=None,
    )

    store.create_lineage(lineage, set_active=True)
    active = store.get_active_lineage(2026)

    assert active.lineage_id == "ln-2026-a"


def test_reject_two_active_lineages_same_season(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    snap = store.persist_snapshot(_build_snapshot(snapshot_id="snap-ln"))
    a = PowerLineageRecord(
        lineage_id="ln-2026-first",
        parent_lineage_id=None,
        root_snapshot_id=snap.snapshot_id,
        active_snapshot_id=snap.snapshot_id,
        season=2026,
        through_week=0,
        status="ACTIVE",
        created_at="2026-09-16T00:00:00+00:00",
        superseded_at=None,
        superseded_by=None,
    )
    b = PowerLineageRecord(
        lineage_id="ln-2026-second",
        parent_lineage_id=None,
        root_snapshot_id=snap.snapshot_id,
        active_snapshot_id=snap.snapshot_id,
        season=2026,
        through_week=0,
        status="ACTIVE",
        created_at="2026-09-17T00:00:00+00:00",
        superseded_at=None,
        superseded_by=None,
    )

    store.create_lineage(a, set_active=False)
    with pytest.raises(PowerEnginePersistenceError, match="Only one ACTIVE lineage"):
        store.create_lineage(b, set_active=False)


def test_superseded_lineage_remains_readable_and_active_pointer_switches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    root = store.persist_snapshot(_build_snapshot(snapshot_id="snap-root-ln"))
    wk1 = store.persist_snapshot(_build_snapshot(snapshot_id="snap-wk1-ln", through_week=1))

    l1 = PowerLineageRecord(
        lineage_id="ln-2026-old",
        parent_lineage_id=None,
        root_snapshot_id=root.snapshot_id,
        active_snapshot_id=root.snapshot_id,
        season=2026,
        through_week=0,
        status="ACTIVE",
        created_at="2026-09-16T00:00:00+00:00",
        superseded_at=None,
        superseded_by=None,
    )
    l2 = PowerLineageRecord(
        lineage_id="ln-2026-new",
        parent_lineage_id="ln-2026-old",
        root_snapshot_id=root.snapshot_id,
        active_snapshot_id=wk1.snapshot_id,
        season=2026,
        through_week=1,
        status="ACTIVE",
        created_at="2026-09-17T00:00:00+00:00",
        superseded_at=None,
        superseded_by=None,
    )

    store.create_lineage(l1, set_active=True)
    store.create_lineage(l2, set_active=True)

    active = store.get_active_lineage(2026)
    old = store.get_lineage("ln-2026-old")
    new = store.get_lineage("ln-2026-new")

    assert active.lineage_id == "ln-2026-new"
    assert old.status == "SUPERSEDED"
    assert old.superseded_by == "ln-2026-new"
    assert new.status == "ACTIVE"

    assert (store.root_dir / "meta" / "lineages" / "ln-2026-old.json").exists()
    assert (store.root_dir / "meta" / "lineages" / "ln-2026-new.json").exists()


def test_concurrent_duplicate_snapshot_writes_are_safe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    snap = _build_snapshot(snapshot_id="snap-concurrent")

    def worker() -> PowerSnapshot:
        return store.persist_snapshot(snap)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: worker(), range(16)))

    assert all(result.snapshot_id == "snap-concurrent" for result in results)
    assert len(list((store.root_dir / "snapshots").glob("*.json"))) == 1


def test_concurrent_duplicate_ledger_writes_are_safe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    before = store.persist_snapshot(_build_snapshot(snapshot_id="snap-before-concurrent"))
    after = store.persist_snapshot(_build_snapshot(snapshot_id="snap-after-concurrent", through_week=1))
    rec = _build_ledger_record(snapshot_before=before, snapshot_after=after)

    def worker() -> PowerUpdateLedgerRecord:
        return store.persist_ledger_record(rec)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: worker(), range(16)))

    assert all(result.update_id == rec.update_id for result in results)
    assert len(list((store.root_dir / "ledger").glob("*.json"))) == 1


def test_temporary_test_root_never_touches_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    snap = _build_snapshot(snapshot_id="snap-temp-root")
    store.persist_snapshot(snap)

    assert str(store.root_dir).startswith(str(tmp_path.resolve()))
    assert str(store.root_dir).startswith("/data") is False
    assert (store.root_dir / "snapshots" / "snap-temp-root.json").exists()


def test_root_dir_argument_is_sufficient_without_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("POWER_ENGINE_ROOT", raising=False)
    root = tmp_path / "explicit-root"
    store = PowerEngineStore(root_dir=root)
    snap = _build_snapshot(snapshot_id="snap-root-arg")

    store.persist_snapshot(snap)

    assert store.root_dir == root.resolve()
    assert store._snapshots_dir == (root / "snapshots").resolve()
    assert store._ledger_dir == (root / "ledger").resolve()
    assert store._meta_dir == (root / "meta").resolve()
    assert (root / "snapshots" / "snap-root-arg.json").exists()
    assert not (tmp_path / "power-engine-root").exists()


@pytest.mark.parametrize("bad_identifier", [".", "..", "../escape", "/abs", "a/b", "a\\b"])
def test_filename_bearing_identifiers_reject_special_and_traversal_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    bad_identifier: str,
):
    store = _build_store(tmp_path, monkeypatch)

    with pytest.raises(PowerEnginePersistenceError, match="unsupported characters"):
        store._snapshot_path(bad_identifier)
    with pytest.raises(PowerEnginePersistenceError, match="unsupported characters"):
        store._ledger_path(bad_identifier)
    with pytest.raises(PowerEnginePersistenceError, match="unsupported characters"):
        store._lineage_path(bad_identifier)


def test_missing_snapshot_index_is_rebuilt_and_duplicate_content_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    store = _build_store(tmp_path, monkeypatch)
    original = _build_snapshot(snapshot_id="snap-index-a")
    alternate = _build_snapshot(snapshot_id="snap-index-b")
    store.persist_snapshot(original)
    store._snapshot_hash_index.unlink()

    assert store.persist_snapshot(original) == original
    with pytest.raises(PowerEnginePersistenceError, match="Duplicate snapshot authority is not allowed"):
        store.persist_snapshot(alternate)

    assert sorted(path.name for path in store._snapshots_dir.glob("*.json")) == ["snap-index-a.json"]
    assert json.loads(store._snapshot_hash_index.read_text(encoding="utf-8")) == {
        original.snapshot_hash: original.snapshot_id
    }


def test_stale_snapshot_index_is_rebuilt_from_authoritative_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    store = _build_store(tmp_path, monkeypatch)
    snapshot = _build_snapshot(snapshot_id="snap-stale-index")
    store.persist_snapshot(snapshot)
    store._snapshot_hash_index.write_text(json.dumps({"stale": "value"}, sort_keys=True), encoding="utf-8")

    assert store.list_snapshots(season=2026) == [snapshot]
    assert json.loads(store._snapshot_hash_index.read_text(encoding="utf-8")) == {
        snapshot.snapshot_hash: snapshot.snapshot_id
    }


def test_duplicate_snapshot_authority_on_disk_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    a = _build_snapshot(snapshot_id="snap-dup-a")
    b = _build_snapshot(snapshot_id="snap-dup-b")
    _write_snapshot_artifact(store, a)
    _write_snapshot_artifact(store, b)

    with pytest.raises(PowerEnginePersistenceError, match="Duplicate snapshot authority"):
        store.list_snapshots()
    with pytest.raises(PowerEnginePersistenceError, match="Duplicate snapshot authority"):
        store.get_snapshot("snap-dup-a")
    with pytest.raises(PowerEnginePersistenceError, match="Duplicate snapshot authority"):
        store.persist_snapshot(a)


def test_missing_ledger_index_is_rebuilt_and_alternate_update_id_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    store = _build_store(tmp_path, monkeypatch)
    before = store.persist_snapshot(_build_snapshot(snapshot_id="snap-ledger-index-before"))
    after = store.persist_snapshot(_build_snapshot(snapshot_id="snap-ledger-index-after", through_week=1))
    record = _build_ledger_record(snapshot_before=before, snapshot_after=after)
    store.persist_ledger_record(record)
    store._ledger_idempotency_index.unlink()
    alternate = replace(record, update_id="upd-alt-duplicate", payload_hash=record.payload_hash)

    assert store.persist_ledger_record(record) == record
    with pytest.raises(PowerEnginePersistenceError, match="Ledger update_id mismatch"):
        store.persist_ledger_record(alternate)

    assert sorted(path.name for path in store._ledger_dir.glob("*.json")) == [f"{record.update_id}.json"]
    assert json.loads(store._ledger_idempotency_index.read_text(encoding="utf-8")) == {
        record.idempotency_key: record.update_id
    }


def test_stale_ledger_index_is_rebuilt_from_authoritative_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    store = _build_store(tmp_path, monkeypatch)
    before = store.persist_snapshot(_build_snapshot(snapshot_id="snap-ledger-stale-before"))
    after = store.persist_snapshot(_build_snapshot(snapshot_id="snap-ledger-stale-after", through_week=1))
    record = _build_ledger_record(snapshot_before=before, snapshot_after=after)
    store.persist_ledger_record(record)
    store._ledger_idempotency_index.write_text(json.dumps({"stale": "value"}, sort_keys=True), encoding="utf-8")

    assert store.list_ledger(season=2026, week=1, lineage_id="ln-2026-main") == [record]
    assert json.loads(store._ledger_idempotency_index.read_text(encoding="utf-8")) == {
        record.idempotency_key: record.update_id
    }


def test_duplicate_ledger_authority_on_disk_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    before = store.persist_snapshot(_build_snapshot(snapshot_id="snap-ledger-dup-before"))
    after = store.persist_snapshot(_build_snapshot(snapshot_id="snap-ledger-dup-after", through_week=1))
    record = _build_ledger_record(snapshot_before=before, snapshot_after=after)
    duplicate = replace(record, update_id="upd-duplicate-record", payload_hash=record.payload_hash)
    _write_ledger_artifact(store, record)
    _write_ledger_artifact(store, duplicate)

    with pytest.raises(PowerEnginePersistenceError, match="Ledger update_id mismatch"):
        store.list_ledger()
    with pytest.raises(PowerEnginePersistenceError, match="Ledger update_id mismatch"):
        store.get_ledger_record(record.update_id)
    with pytest.raises(PowerEnginePersistenceError, match="Ledger update_id mismatch"):
        store.persist_ledger_record(record)


def test_manual_multiple_active_lineages_without_pointer_fail_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    a = PowerLineageRecord("ln-a", None, "snap-root", "snap-root", 2026, 0, "ACTIVE", "2026-09-16T00:00:00+00:00", None, None)
    b = PowerLineageRecord("ln-b", "ln-a", "snap-root", "snap-wk1", 2026, 1, "ACTIVE", "2026-09-17T00:00:00+00:00", None, None)
    _write_lineage_artifact(store, a)
    _write_lineage_artifact(store, b)

    with pytest.raises(PowerEnginePersistenceError, match="Multiple ACTIVE lineage artifacts"):
        store.list_lineages(2026)


def test_pointer_authority_reconciles_multiple_active_lineage_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    a = PowerLineageRecord("ln-a", None, "snap-root", "snap-root", 2026, 0, "ACTIVE", "2026-09-16T00:00:00+00:00", None, None)
    b = PowerLineageRecord("ln-b", "ln-a", "snap-root", "snap-wk1", 2026, 1, "ACTIVE", "2026-09-17T00:00:00+00:00", None, None)
    _write_lineage_artifact(store, a)
    _write_lineage_artifact(store, b)
    _write_active_pointer(store, season=2026, lineage_id="ln-b")

    active = store.get_active_lineage(2026)
    lineages = {record.lineage_id: record for record in store.list_lineages(2026)}

    assert active.lineage_id == "ln-b"
    assert lineages["ln-b"].status == "ACTIVE"
    assert lineages["ln-a"].status == "SUPERSEDED"
    assert lineages["ln-a"].superseded_by == "ln-b"


def test_active_pointer_to_missing_lineage_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    _write_active_pointer(store, season=2026, lineage_id="ln-missing")

    with pytest.raises(PowerEnginePersistenceError, match="references missing lineage"):
        store.get_active_lineage(2026)


def test_active_pointer_season_mismatch_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    lineage = PowerLineageRecord(
        "ln-2027",
        None,
        "snap-root",
        "snap-root",
        2027,
        0,
        "ACTIVE",
        "2026-09-16T00:00:00+00:00",
        None,
        None,
    )
    _write_lineage_artifact(store, lineage)
    _write_active_pointer(store, season=2026, lineage_id="ln-2027")

    with pytest.raises(PowerEnginePersistenceError, match="season mismatch"):
        store.get_active_lineage(2026)


def test_active_pointer_to_malformed_lineage_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    store._ensure_dirs()
    bad = store._lineages_dir / "ln-bad.json"
    bad.write_text(
        json.dumps(
            {
                "lineage_id": "ln-bad",
                "parent_lineage_id": None,
                "root_snapshot_id": "snap-root",
                "active_snapshot_id": "snap-root",
                "season": 2026,
                "through_week": 0,
                "status": "BROKEN",
                "created_at": "2026-09-16T00:00:00+00:00",
                "superseded_at": None,
                "superseded_by": None,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    _write_active_pointer(store, season=2026, lineage_id="ln-bad")

    with pytest.raises(PowerEnginePersistenceError, match="Invalid lineage status"):
        store.get_active_lineage(2026)


def test_old_active_remains_authoritative_before_pointer_commit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    old = PowerLineageRecord("ln-old", None, "snap-root", "snap-root", 2026, 0, "ACTIVE", "2026-09-16T00:00:00+00:00", None, None)
    new = PowerLineageRecord("ln-new", "ln-old", "snap-root", "snap-wk1", 2026, 1, "ACTIVE", "2026-09-17T00:00:00+00:00", None, None)
    _write_lineage_artifact(store, old)
    _write_lineage_artifact(store, new)
    _write_active_pointer(store, season=2026, lineage_id="ln-old", updated_at="2026-09-16T00:00:00+00:00")

    active = store.get_active_lineage(2026)
    lineages = {record.lineage_id: record for record in store.list_lineages(2026)}

    assert active.lineage_id == "ln-old"
    assert lineages["ln-old"].status == "ACTIVE"
    assert lineages["ln-new"].status == "SUPERSEDED"


def test_new_active_resolves_after_pointer_commit_before_status_reconcile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = _build_store(tmp_path, monkeypatch)
    old = PowerLineageRecord("ln-old", None, "snap-root", "snap-root", 2026, 0, "ACTIVE", "2026-09-16T00:00:00+00:00", None, None)
    new = PowerLineageRecord("ln-new", "ln-old", "snap-root", "snap-wk1", 2026, 1, "ACTIVE", "2026-09-17T00:00:00+00:00", None, None)
    _write_lineage_artifact(store, old)
    _write_lineage_artifact(store, new)
    _write_active_pointer(store, season=2026, lineage_id="ln-new", updated_at="2026-09-17T00:00:00+00:00")

    active = store.get_active_lineage(2026)
    lineages = {record.lineage_id: record for record in store.list_lineages(2026)}

    assert active.lineage_id == "ln-new"
    assert lineages["ln-new"].status == "ACTIVE"
    assert lineages["ln-old"].status == "SUPERSEDED"
    assert lineages["ln-old"].superseded_by == "ln-new"
