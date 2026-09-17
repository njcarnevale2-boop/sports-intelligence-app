from __future__ import annotations

import multiprocessing as mp
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.services.result_engine import (
    ResultAcceptanceEngine,
    ResultEnginePersistenceError,
    ResultEngineStore,
    build_canonical_event_identity,
)
from app.services.result_engine.contracts import SourceEventBridgeRecord
from app.services.result_engine.identity import CANONICAL_EVENT_KEY_POLICY_VERSION, canonical_event_identity_payload
from app.services.result_engine.validation import deterministic_bridge_id
from result_engine_test_utils import make_accepted_result, make_engine, make_identity, make_observation, make_policy, make_store


def _mp_bridge(source: str, source_event_id: str, canonical_event_key: str, first_observation_id: str) -> SourceEventBridgeRecord:
    draft = SourceEventBridgeRecord(
        bridge_id="",
        source=source,
        source_event_id=source_event_id,
        canonical_event_key=canonical_event_key,
        created_at_utc="2026-09-10T05:00:00Z",
        first_observation_id=first_observation_id,
    )
    return replace(draft, bridge_id=deterministic_bridge_id(draft))


def _mp_worker(task: dict[str, str]) -> tuple[str, str]:
    root_dir = Path(task["root_dir"])
    case = task["case"]
    variant = task["variant"]
    store = ResultEngineStore(root_dir=root_dir)

    try:
        if case.startswith("obs"):
            if variant == "base":
                observation = make_observation(
                    source="provider_mp",
                    source_event_id="evt-mp",
                    source_observation_id="source-obs-mp-1",
                    source_result_version="v1",
                    observed_at_utc="2026-09-10T05:00:00Z",
                    provider_published_at_utc="2026-09-10T04:59:50Z",
                )
            else:
                observation = make_observation(
                    source="provider_mp",
                    source_event_id="evt-mp",
                    source_observation_id="source-obs-mp-1",
                    source_result_version="v2",
                    observed_at_utc="2026-09-10T05:00:00Z",
                    provider_published_at_utc="2026-09-10T04:59:50Z",
                )
            persisted = store.persist_observation(observation)
            return "success", persisted.observation_id

        if case.startswith("accepted"):
            if variant == "base":
                accepted = make_accepted_result(
                    source="provider_mp_a",
                    source_event_id="evt-mp-a",
                    source_result_version="v1",
                )
            else:
                accepted = make_accepted_result(
                    source="provider_mp_b",
                    source_event_id="evt-mp-b",
                    source_result_version="v1",
                )
            persisted = store.persist_accepted_result(accepted)
            return "success", persisted.result_id

        if case.startswith("bridge"):
            if variant == "base":
                bridge = _mp_bridge(
                    source="provider_mp",
                    source_event_id="evt-mp",
                    canonical_event_key=make_identity().canonical_event_key,
                    first_observation_id="obs-a",
                )
            else:
                bridge = _mp_bridge(
                    source="provider_mp",
                    source_event_id="evt-mp",
                    canonical_event_key=make_identity(away_team="BUF", home_team="MIA").canonical_event_key,
                    first_observation_id="obs-b",
                )
            persisted = store.persist_source_event_bridge(bridge)
            return "success", persisted.bridge_id

        return "unexpected_failure", f"Unsupported case: {case}"
    except ResultEnginePersistenceError as exc:
        return "intentional_failure", str(exc)
    except Exception as exc:  # pragma: no cover
        return "unexpected_failure", repr(exc)


def _run_20_process_case(root_dir: Path, *, case: str, conflict: bool) -> dict[str, Any]:
    root_dir.mkdir(parents=True, exist_ok=True)
    variants = (["base"] * 20) if not conflict else (["base"] * 10 + ["conflict"] * 10)
    tasks = [{"root_dir": str(root_dir), "case": case, "variant": variant} for variant in variants]

    ctx = mp.get_context("fork")
    with ctx.Pool(processes=20) as pool:
        outcomes = pool.map(_mp_worker, tasks)

    success_count = sum(1 for status, _ in outcomes if status == "success")
    intentional_failure_count = sum(1 for status, _ in outcomes if status == "intentional_failure")
    unexpected_failures = [detail for status, detail in outcomes if status == "unexpected_failure"]
    if unexpected_failures:
        raise AssertionError(f"Unexpected multiprocess failures for {case}: {unexpected_failures}")

    store = ResultEngineStore(root_dir=root_dir)
    if case.startswith("obs"):
        authoritative = store.list_observations()
        final_state = {
            "observation_id": authoritative[0].observation_id,
            "source": authoritative[0].source,
            "source_event_id": authoritative[0].source_event_id,
            "source_observation_id": authoritative[0].source_observation_id,
            "source_result_version": authoritative[0].source_result_version,
            "source_evidence_hash": authoritative[0].source_evidence_hash,
            "observed_at_utc": authoritative[0].observed_at_utc,
        }
        artifact_count = len(list((root_dir / "observations").glob("*.json")))
    elif case.startswith("accepted"):
        authoritative = store.list_accepted_results()
        final_state = {
            "result_id": authoritative[0].result_id,
            "canonical_event_key": authoritative[0].canonical_event_key,
            "source": authoritative[0].source,
            "source_event_id": authoritative[0].source_event_id,
            "away_score": authoritative[0].away_score,
            "home_score": authoritative[0].home_score,
        }
        artifact_count = len(list((root_dir / "accepted").glob("*.json")))
    else:
        authoritative = store.list_source_event_bridges()
        final_state = {
            "bridge_id": authoritative[0].bridge_id,
            "source": authoritative[0].source,
            "source_event_id": authoritative[0].source_event_id,
            "canonical_event_key": authoritative[0].canonical_event_key,
        }
        artifact_count = len(list((root_dir / "identity" / "source_event").glob("*.json")))

    resolved_root = root_dir.resolve()
    return {
        "case": case,
        "success_count": success_count,
        "intentional_failure_count": intentional_failure_count,
        "artifact_count": artifact_count,
        "final_authoritative_state": final_state,
        "artifact_root": str(resolved_root),
        "all_paths_under_root": all(path.resolve().is_relative_to(resolved_root) for path in root_dir.rglob("*")),
        "writes_to_data": any(str(path.resolve()).startswith("/data") for path in root_dir.rglob("*")),
    }


def build_final_gate_multiprocess_reports(root_dir: Path) -> dict[str, dict[str, Any]]:
    case_map = {
        "A": _run_20_process_case(root_dir / "case_a_identical_observation", case="obs_identical", conflict=False),
        "B": _run_20_process_case(root_dir / "case_b_conflicting_observation", case="obs_conflicting", conflict=True),
        "C": _run_20_process_case(root_dir / "case_c_identical_accepted", case="accepted_identical", conflict=False),
        "D": _run_20_process_case(root_dir / "case_d_conflicting_accepted", case="accepted_conflicting", conflict=True),
        "E": _run_20_process_case(root_dir / "case_e_identical_bridge", case="bridge_identical", conflict=False),
        "F": _run_20_process_case(root_dir / "case_f_conflicting_bridge", case="bridge_conflicting", conflict=True),
    }
    return case_map


def test_multiprocess_final_gate_20_process_matrix(tmp_path):
    reports = build_final_gate_multiprocess_reports(tmp_path / "final-gate-multiprocess")

    for case in ["A", "C", "E"]:
        report = reports[case]
        assert report["success_count"] == 20
        assert report["intentional_failure_count"] == 0
        assert report["artifact_count"] == 1
        assert report["all_paths_under_root"] is True
        assert report["writes_to_data"] is False

    for case in ["B", "D", "F"]:
        report = reports[case]
        assert report["success_count"] >= 1
        assert report["intentional_failure_count"] >= 1
        assert report["artifact_count"] == 1
        assert report["all_paths_under_root"] is True
        assert report["writes_to_data"] is False


def test_replay_different_local_observed_at_does_not_confirm(tmp_path):
    engine = make_engine(tmp_path, min_seconds=60)
    first = make_observation(
        source="provider_a",
        source_event_id="evt-replay",
        source_observation_id="prov-obs-1",
        source_result_version="scores-v1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )
    replay = make_observation(
        source="provider_a",
        source_event_id="evt-replay",
        source_observation_id="prov-obs-1",
        source_result_version="scores-v1",
        observed_at_utc="2026-09-10T05:03:00Z",
        provider_published_at_utc="2026-09-10T04:59:50Z",
    )

    first_outcome = engine.ingest_raw_observation(first)
    replay_outcome = engine.ingest_raw_observation(replay)

    assert first_outcome["status"] == "PENDING_CONFIRMATION"
    assert replay_outcome["status"] == "PENDING_CONFIRMATION"
    assert replay_outcome["accepted"] is None
    assert len(engine.store.list_observations()) == 1


def test_independent_source_observations_with_interval_do_confirm(tmp_path):
    engine = make_engine(tmp_path, min_seconds=60)
    first = make_observation(
        source="provider_a",
        source_event_id="evt-independent",
        source_observation_id="prov-obs-1",
        source_result_version="scores-v1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:00Z",
    )
    second = make_observation(
        source="provider_a",
        source_event_id="evt-independent",
        source_observation_id="prov-obs-2",
        source_result_version="scores-v1",
        observed_at_utc="2026-09-10T05:02:30Z",
        provider_published_at_utc="2026-09-10T05:00:10Z",
    )

    engine.ingest_raw_observation(first)
    outcome = engine.ingest_raw_observation(second)

    assert first.source_observation_id != second.source_observation_id
    assert first.provider_published_at_utc != second.provider_published_at_utc
    assert first.source_evidence_hash != second.source_evidence_hash
    assert outcome["status"] == "ACCEPTED"
    assert outcome["accepted"] is not None


def test_reschedule_keeps_identity_and_kickoff_remains_auditable():
    original = build_canonical_event_identity(
        season=2026,
        week=1,
        kickoff_utc="2026-09-10T00:15:00Z",
        away_team="NE",
        home_team="SEA",
    )
    rescheduled = build_canonical_event_identity(
        season=2026,
        week=1,
        kickoff_utc="2026-09-11T00:15:00Z",
        away_team="NE",
        home_team="SEA",
    )

    assert CANONICAL_EVENT_KEY_POLICY_VERSION == "stable_matchup_week_v1"
    assert original.canonical_event_key == rescheduled.canonical_event_key
    assert original.kickoff_utc != rescheduled.kickoff_utc


def test_home_away_reversal_is_different_identity():
    base = build_canonical_event_identity(
        season=2026,
        week=1,
        kickoff_utc="2026-09-10T00:15:00Z",
        away_team="NE",
        home_team="SEA",
    )
    reversed_identity = build_canonical_event_identity(
        season=2026,
        week=1,
        kickoff_utc="2026-09-10T00:15:00Z",
        away_team="SEA",
        home_team="NE",
    )

    assert base.canonical_event_key != reversed_identity.canonical_event_key


def test_canonical_event_key_formula_is_stable_matchup_week_only():
    payload = canonical_event_identity_payload(
        season=2026,
        week=1,
        kickoff_utc="2026-09-10T00:15:00Z",
        away_team="NE",
        home_team="SEA",
    )

    assert payload == {
        "season": 2026,
        "week": 1,
        "away_team": "NE",
        "home_team": "SEA",
        "canonical_event_key_policy": "stable_matchup_week_v1",
    }


def test_single_accepted_authority_lineage_for_one_canonical_event(tmp_path):
    engine = ResultAcceptanceEngine(store=make_store(tmp_path), policy=make_policy(min_seconds=60))

    first = make_observation(
        source="provider_a",
        source_event_id="evt-a",
        source_observation_id="provider-a-1",
        source_result_version="scores-v1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:00Z",
    )
    second = make_observation(
        source="provider_a",
        source_event_id="evt-a",
        source_observation_id="provider-a-2",
        source_result_version="scores-v1",
        observed_at_utc="2026-09-10T05:02:00Z",
        provider_published_at_utc="2026-09-10T05:00:10Z",
    )

    engine.ingest_raw_observation(first)
    accepted_outcome = engine.ingest_raw_observation(second)
    assert accepted_outcome["status"] == "ACCEPTED"
    assert len(engine.store.list_accepted_results()) == 1

    corroborating_provider = make_observation(
        source="provider_b",
        source_event_id="evt-b",
        source_observation_id="provider-b-1",
        source_result_version="scores-v1",
        observed_at_utc="2026-09-10T05:05:00Z",
        provider_published_at_utc="2026-09-10T05:04:50Z",
    )
    corroborating_outcome = engine.ingest_raw_observation(corroborating_provider)

    assert corroborating_outcome["status"] == "CORRECTION_CANDIDATE"
    assert corroborating_outcome["correctionCandidateId"] is not None
    assert len(engine.store.list_accepted_results()) == 1


def test_conflicting_provider_score_becomes_correction_not_second_authority(tmp_path):
    engine = ResultAcceptanceEngine(store=make_store(tmp_path), policy=make_policy(min_seconds=60))

    first = make_observation(
        source="provider_a",
        source_event_id="evt-a",
        source_observation_id="provider-a-1",
        source_result_version="scores-v1",
        observed_at_utc="2026-09-10T05:00:00Z",
        provider_published_at_utc="2026-09-10T04:59:00Z",
    )
    second = make_observation(
        source="provider_a",
        source_event_id="evt-a",
        source_observation_id="provider-a-2",
        source_result_version="scores-v1",
        observed_at_utc="2026-09-10T05:02:00Z",
        provider_published_at_utc="2026-09-10T05:00:10Z",
    )

    engine.ingest_raw_observation(first)
    engine.ingest_raw_observation(second)

    conflicting = make_observation(
        source="provider_c",
        source_event_id="evt-c",
        source_observation_id="provider-c-1",
        source_result_version="scores-v1",
        observed_at_utc="2026-09-10T05:06:00Z",
        provider_published_at_utc="2026-09-10T05:05:50Z",
        home_score=31,
    )
    conflict_outcome = engine.ingest_raw_observation(conflicting)

    assert conflict_outcome["status"] == "CORRECTION_CANDIDATE"
    assert conflict_outcome["correctionCandidateId"] is not None
    assert len(engine.store.list_accepted_results()) == 1
    assert len(engine.store.list_correction_candidates()) >= 1


def test_all_final_gate_artifacts_stay_under_temp_root(tmp_path):
    reports = build_final_gate_multiprocess_reports(tmp_path / "final-gate-root-isolation")

    for report in reports.values():
        artifact_root = Path(report["artifact_root"]).resolve()
        assert str(artifact_root).startswith(str(tmp_path.resolve()))
        assert report["all_paths_under_root"] is True
        assert report["writes_to_data"] is False
