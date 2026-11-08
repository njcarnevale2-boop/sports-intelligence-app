from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from research.week9_odds_snapshot_prepare import (
    DEFAULT_CANDIDATE_ROOT,
    DEFAULT_MAX_QUOTE_AGE_SECONDS,
    SnapshotPreparationError,
    build_synthetic_provider_response,
    load_candidate_allowlist,
    prepare_snapshot,
    write_local_artifacts,
)


OBSERVED_AT = "2026-11-07T12:00:00Z"


def _loaded_candidate():
    return load_candidate_allowlist(DEFAULT_CANDIDATE_ROOT)


def _fixture(candidate, observed_at=OBSERVED_AT):
    observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    return build_synthetic_provider_response(candidate["allowlist"], observed)


def _prepare(candidate, response, *, observed_at=OBSERVED_AT, max_age=DEFAULT_MAX_QUOTE_AGE_SECONDS):
    return prepare_snapshot(
        candidate,
        response,
        observed_at=observed_at,
        max_quote_age_seconds=max_age,
        response_kind="SYNTHETIC_FIXTURE",
        provider_response_sha256="synthetic-fixture-hash",
    )


def test_candidate_bundle_hash_schedule_and_week8_lineage_are_verified():
    candidate = _loaded_candidate()
    assert candidate["candidate_id"] == "proj-a0ce3caf93d2f832"
    assert candidate["lineage_id"] == "ln-2026-wk8-2380f2961d70"
    assert candidate["week8_snapshot_id"] == "power-2026-wk8-bbe73e1ea965"
    assert candidate["schedule_version"] == "canonical-schedule-v2:2026:9:8b89dd5f8fbd"
    assert len(candidate["allowlist"]) == 15


def test_explicit_observation_time_excludes_started_game_and_respects_boundary():
    candidate = _loaded_candidate()
    at_start = _prepare(candidate, _fixture(candidate), observed_at="2026-11-06T01:15:00Z")
    before_start = _prepare(candidate, _fixture(candidate), observed_at="2026-11-06T01:14:59Z")
    saturday = _prepare(candidate, _fixture(candidate), observed_at=OBSERVED_AT)
    assert at_start["validation"]["pregame_eligible_games"] == 14
    assert before_start["validation"]["pregame_eligible_games"] == 15
    assert saturday["validation"]["pregame_eligible_games"] == 14
    assert saturday["excluded_games"][0]["candidate_event_id"] == "2026_09_JAX_BAL"


def test_synthetic_snapshot_preserves_quote_fields_and_spread_sign():
    candidate = _loaded_candidate()
    snapshot = _prepare(candidate, _fixture(candidate))
    assert snapshot["data_classification"] == "SYNTHETIC_FIXTURE_ONLY"
    assert snapshot["external_requests_made"] == 0
    assert snapshot["staging_writes_made"] is False
    assert snapshot["validation"]["allowlist_games"] == 15
    assert snapshot["validation"]["pregame_eligible_games"] == 14
    assert snapshot["validation"]["eligible_games_with_spread_quotes"] == 14
    assert snapshot["validation"]["accepted_quote_outcomes"] == 28
    quote = snapshot["quotes"][0]
    assert {"provider_event_id", "sportsbook_key", "market", "outcome", "point", "price"} <= set(quote)
    assert "bookmaker_last_update" in quote and "market_last_update" in quote
    assert quote["observation_timestamp"] == OBSERVED_AT
    assert quote["spread_sign_validated"] is True
    assert quote["market_implied_home_margin"] == pytest.approx(-quote["market_home_spread_point"])
    assert quote["candidate_home_fair_spread"] == pytest.approx(-quote["candidate_home_expected_margin"])


def test_unmatched_and_incorrectly_timed_events_are_rejected():
    candidate = _loaded_candidate()
    response = _fixture(candidate)
    response[0]["commence_time"] = "2026-11-06T02:15:00Z"
    response[1]["home_team"] = "Houston Texans"
    snapshot = _prepare(candidate, response)
    reasons = {row["reason"] for row in snapshot["rejected_events"]}
    assert "KICKOFF_MISMATCH" in reasons
    assert "UNMATCHED_EVENT" in reasons


def test_observed_kickoff_mismatches_quarantine_games_without_affecting_other_quotes():
    candidate = _loaded_candidate()
    observed_at = "2026-11-08T16:04:19Z"
    response = _fixture(candidate, observed_at=observed_at)
    events = {event["id"]: event for event in response}
    cin = events["synthetic-oddsapi-2026_09_CIN_ATL"]
    lv = events["synthetic-oddsapi-2026_09_LV_SF"]
    exact_lv = json.loads(json.dumps(lv))
    exact_lv["id"] = "conflicting-exact-lv"
    response.append(exact_lv)
    cin["commence_time"] = "2026-11-08T13:05:00Z"
    lv["commence_time"] = "2026-11-08T21:25:00Z"
    for index in range(11):
        unrelated = json.loads(json.dumps(lv))
        unrelated.update(id=f"future-{index}", away_team="Arizona Cardinals", home_team="Buffalo Bills", commence_time="2026-11-15T18:00:00Z")
        response.append(unrelated)

    snapshot = _prepare(candidate, response, observed_at=observed_at)
    assert snapshot["quarantined_candidate_event_ids"] == ["2026_09_CIN_ATL", "2026_09_LV_SF"]
    mismatches = [event for event in snapshot["rejected_events"] if event["reason"] == "KICKOFF_MISMATCH"]
    assert {event["candidate_event_id"] for event in mismatches} == {"2026_09_CIN_ATL", "2026_09_LV_SF"}
    assert sum(event["reason"] == "UNMATCHED_EVENT" for event in snapshot["rejected_events"]) == 11
    quoted_ids = {quote["candidate_event_id"] for quote in snapshot["quotes"]}
    assert "2026_09_CIN_ATL" not in quoted_ids and "2026_09_LV_SF" not in quoted_ids
    assert quoted_ids
    assert "2026_09_LV_SF" in snapshot["validation"]["eligible_games_missing_spread_quotes"]


def test_subsecond_kickoff_difference_does_not_match_candidate():
    candidate = _loaded_candidate()
    response = _fixture(candidate)
    target = response[1]
    candidate_id = target["id"].removeprefix("synthetic-oddsapi-")
    target["commence_time"] = target["commence_time"].replace("Z", ".500Z")
    snapshot = _prepare(candidate, response)
    assert candidate_id in snapshot["quarantined_candidate_event_ids"]
    assert not any(quote["candidate_event_id"] == candidate_id for quote in snapshot["quotes"])


def test_duplicate_provider_events_reject_the_candidate_match():
    candidate = _loaded_candidate()
    response = _fixture(candidate)
    response.append(json.loads(json.dumps(response[1])))
    snapshot = _prepare(candidate, response)
    reasons = {row["reason"] for row in snapshot["rejected_events"]}
    assert "DUPLICATE_PROVIDER_EVENT_ID" in reasons
    assert snapshot["validation"]["eligible_games_with_spread_quotes"] == 13


def test_stale_and_missing_timestamps_are_rejected():
    candidate = _loaded_candidate()
    response = _fixture(candidate)
    response[1]["bookmakers"][0]["markets"][0]["last_update"] = "2026-11-07T11:54:59Z"
    stale = _prepare(candidate, response, max_age=300)
    assert any(row["reason"] == "STALE_QUOTE" for row in stale["rejected_quotes"])
    assert stale["validation"]["eligible_games_with_spread_quotes"] == 13

    response = _fixture(candidate)
    response[1]["bookmakers"][0].pop("last_update")
    response[1]["bookmakers"][0]["markets"][0].pop("last_update")
    missing = _prepare(candidate, response)
    assert any(row["reason"] == "MISSING_QUOTE_UPDATE_TIMESTAMP" for row in missing["rejected_quotes"])


def test_missing_price_and_inconsistent_spread_points_are_rejected():
    candidate = _loaded_candidate()
    response = _fixture(candidate)
    response[1]["bookmakers"][0]["markets"][0]["outcomes"][0].pop("price")
    missing = _prepare(candidate, response)
    assert any(row["reason"] == "MISSING_OR_INVALID_PRICE" for row in missing["rejected_quotes"])

    response = _fixture(candidate)
    response[1]["bookmakers"][0]["markets"][0]["outcomes"][1]["point"] += 1.0
    mismatched = _prepare(candidate, response)
    assert any(row["reason"] == "SPREAD_SIGN_MISMATCH" for row in mismatched["rejected_quotes"])


def test_ambiguous_candidate_allowlist_fails_closed():
    candidate = _loaded_candidate()
    candidate["allowlist"].append(dict(candidate["allowlist"][1]))
    with pytest.raises(SnapshotPreparationError, match="exactly 15"):
        _prepare(candidate, _fixture(candidate))


def test_deterministic_snapshot_hash_and_local_write_guard(tmp_path: Path):
    candidate = _loaded_candidate()
    response = _fixture(candidate)
    first = _prepare(candidate, response)
    second = _prepare(candidate, response)
    assert first["snapshot_sha256"] == second["snapshot_sha256"]

    output = tmp_path / "local-research" / "snapshot"
    manifest = write_local_artifacts(
        output_dir=output,
        candidate_root=DEFAULT_CANDIDATE_ROOT,
        snapshot=first,
        provider_response=response,
        research_root=tmp_path,
    )
    assert (output / "snapshot.json").exists()
    assert manifest["staging_writes_made"] is False
    with pytest.raises(SnapshotPreparationError, match="Refusing to overwrite"):
        write_local_artifacts(
            output_dir=output,
            candidate_root=DEFAULT_CANDIDATE_ROOT,
            snapshot=first,
            provider_response=response,
            research_root=tmp_path,
        )