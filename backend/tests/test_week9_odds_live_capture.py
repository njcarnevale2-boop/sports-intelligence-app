from __future__ import annotations

import json
import urllib.parse
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import research.week9_odds_live_capture as live_capture
from research.week9_odds_live_capture import (
    EXPECTED_LIVE_AUTHORIZATION,
    FIXED_QUERY,
    LiveCaptureError,
    HttpResponse,
    authorize_live_capture,
    build_dry_run_plan,
    execute_one_shot,
)
from research.week9_odds_snapshot_prepare import (
    DEFAULT_CANDIDATE_ROOT,
    build_synthetic_provider_response,
    load_candidate_allowlist,
)


OBSERVED_AT = "2026-11-07T12:00:00Z"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
FAKE_KEY = "synthetic-test-key-not-a-secret"


class FakeTransport:
    def __init__(self, response: HttpResponse | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def get(self, url: str, *, timeout_seconds: int) -> HttpResponse:
        self.calls.append((url, timeout_seconds))
        if self.error:
            raise self.error
        assert self.response is not None
        return self.response


def _candidate(staging_root: Path) -> dict:
    staging_root.mkdir(parents=True, exist_ok=True)
    candidate_root = staging_root.parent / live_capture.CANDIDATE_RELATIVE_PATH
    candidate_root.mkdir(parents=True, exist_ok=True)
    candidate = load_candidate_allowlist(DEFAULT_CANDIDATE_ROOT)
    candidate["bundle_root"] = str(candidate_root)
    return candidate


@pytest.fixture(autouse=True)
def load_immutable_local_candidate_for_fake_staging_paths(monkeypatch: pytest.MonkeyPatch):
    real_loader = live_capture.load_candidate_allowlist

    def load_for_test(path: Path):
        candidate = real_loader(DEFAULT_CANDIDATE_ROOT)
        candidate["bundle_root"] = str(Path(path).resolve())
        return candidate

    monkeypatch.setattr(live_capture, "load_candidate_allowlist", load_for_test)


@pytest.fixture(autouse=True)
def freeze_internal_utc_clock_for_synthetic_tests(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(live_capture, "_utc_now", lambda: NOW)


def _environment(candidate: dict, staging_root: Path, *, overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        "RENDER": "true",
        "RENDER_SERVICE_NAME": "sia-backend-staging",
        "NFL_ANALYTICS_OS_ROOT": str(staging_root.resolve()),
        "SIA_WEEK9_ODDS_CAPTURE_ENVIRONMENT": "staging",
        "SIA_WEEK9_ODDS_CAPTURE_LIVE_AUTHORIZED": EXPECTED_LIVE_AUTHORIZATION,
        "SIA_POWER_CANDIDATE_ROOT": candidate["bundle_root"],
        "SIA_WEEK9_ODDS_CAPTURE_CANDIDATE_ID": candidate["candidate_id"],
        "SIA_WEEK9_ODDS_CAPTURE_CANDIDATE_HASH": candidate["candidate_hash"],
        "SIA_WEEK9_ODDS_CAPTURE_OBSERVED_AT": OBSERVED_AT,
        "SIA_WEEK9_ODDS_CAPTURE_MAX_QUOTE_AGE_SECONDS": "300",
        "SIA_WEEK9_ODDS_CAPTURE_MAX_CREDITS": "1",
        "SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR": str(
            (staging_root / "research/week9_odds_captures/test-capture-001").resolve()
        ),
        "ODDS_API_KEY": FAKE_KEY,
    }
    env.update(overrides or {})
    Path(env["SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR"]).parent.mkdir(parents=True, exist_ok=True)
    return env


def _provider_response(candidate: dict, *, observed: datetime = NOW) -> list[dict]:
    return build_synthetic_provider_response(candidate["allowlist"], observed)


def _http_response(provider_events: list[dict], *, status: int = 200, headers: dict[str, str] | None = None) -> HttpResponse:
    return HttpResponse(
        status_code=status,
        headers=headers or {},
        body=json.dumps(provider_events, sort_keys=True, separators=(",", ":")).encode(),
    )


def test_default_dry_run_is_networkless_and_has_exact_fixed_request_shape():
    candidate = load_candidate_allowlist(DEFAULT_CANDIDATE_ROOT)
    transport = FakeTransport(_http_response([]))
    plan = execute_one_shot(
        candidate,
        environ={"SIA_WEEK9_ODDS_CAPTURE_OBSERVED_AT": OBSERVED_AT},
        transport=transport,
    )
    assert plan["mode"] == "DRY_RUN"
    assert plan["network_requests"] == 0
    assert plan["writes"] == 0
    assert plan["request"]["endpoint"] == "/v4/sports/americanfootball_nfl/odds"
    assert {key: plan["request"][key] for key in FIXED_QUERY} == FIXED_QUERY
    assert transport.calls == []


def test_default_dry_run_does_not_fall_back_to_process_environment(monkeypatch: pytest.MonkeyPatch):
    candidate = load_candidate_allowlist(DEFAULT_CANDIDATE_ROOT)
    monkeypatch.setenv("SIA_WEEK9_ODDS_CAPTURE_OBSERVED_AT", OBSERVED_AT)
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    transport = FakeTransport(_http_response([]))
    with pytest.raises(LiveCaptureError, match="Explicit observation timestamp"):
        execute_one_shot(candidate, transport=transport)
    assert transport.calls == []


def test_authorized_test_mode_makes_exactly_one_fake_request_and_writes_only_temp_staging_root(tmp_path: Path):
    staging_root = tmp_path / "isolated-stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root)
    response = _http_response(
        _provider_response(candidate),
        headers={"x-requests-remaining": "999", "x-requests-used": "1", "x-requests-last": "1", "set-cookie": FAKE_KEY},
    )
    transport = FakeTransport(response)

    snapshot = execute_one_shot(
        candidate,
        live_authorized=True,
        environ=env,
        staging_root=staging_root,
        transport=transport,
    )

    assert len(transport.calls) == 1
    request_url, timeout = transport.calls[0]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(request_url).query)
    assert {key: query[key][0] for key in FIXED_QUERY} == FIXED_QUERY
    assert query["apiKey"] == [FAKE_KEY]
    assert timeout == 10
    assert snapshot["external_requests_made"] == 1
    assert snapshot["status"] == "CAPTURED_STAGING_ONLY"
    assert snapshot["sanitized_quota_headers"] == {
        "x-requests-remaining": 999,
        "x-requests-used": 1,
        "x-requests-last": 1,
    }
    assert len(snapshot["quotes"]) == 28
    assert snapshot["live_provider_data"] is True
    assert snapshot["eligible_candidate_event_ids"]
    serialized = json.dumps(snapshot, sort_keys=True)
    assert FAKE_KEY not in serialized
    assert "apiKey" not in serialized
    assert "api.the-odds-api.com" not in serialized
    saved = env["SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR"]
    assert (Path(saved) / "snapshot.json").exists()
    assert (Path(saved) / "manifest.json").exists()
    assert Path(saved).is_relative_to(staging_root / "research/week9_odds_captures")


def test_authorized_mode_reloads_candidate_and_rejects_tampered_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    staging_root = tmp_path / "isolated-stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root)
    tampered = dict(candidate)
    tampered["candidate_hash"] = "tampered"
    monkeypatch.setattr("research.week9_odds_live_capture.load_candidate_allowlist", lambda _path: candidate)
    transport = FakeTransport(_http_response(_provider_response(candidate)))
    with pytest.raises(LiveCaptureError, match="candidate hash"):
        execute_one_shot(tampered, live_authorized=True, environ=env, staging_root=staging_root, transport=transport)
    assert transport.calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"RENDER_SERVICE_NAME": "sia-backend-production"},
        {"RENDER": "false"},
        {"SIA_WEEK9_ODDS_CAPTURE_ENVIRONMENT": "production"},
        {"SIA_WEEK9_ODDS_CAPTURE_LIVE_AUTHORIZED": "true"},
        {"SIA_WEEK9_ODDS_CAPTURE_MAX_CREDITS": "3"},
        {"SIA_WEEK9_ODDS_CAPTURE_CANDIDATE_HASH": "wrong"},
    ],
)
def test_wrong_or_missing_authorization_gate_makes_no_request(tmp_path: Path, overrides: dict[str, str]):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root, overrides=overrides)
    transport = FakeTransport(_http_response(_provider_response(candidate)))
    with pytest.raises(LiveCaptureError):
        execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=transport)
    assert transport.calls == []


def test_authorization_refuses_old_or_future_observation_time(tmp_path: Path):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root, overrides={"SIA_WEEK9_ODDS_CAPTURE_OBSERVED_AT": "2026-11-07T10:00:00Z"})
    with pytest.raises(LiveCaptureError, match="clock skew"):
        authorize_live_capture(candidate=candidate, environ=env, staging_root=staging_root)


def test_stale_observation_cannot_authorize_live_request(tmp_path: Path):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root, overrides={"SIA_WEEK9_ODDS_CAPTURE_OBSERVED_AT": "2026-11-06T12:00:00Z"})
    transport = FakeTransport(_http_response(_provider_response(candidate)))
    with pytest.raises(LiveCaptureError, match="clock skew"):
        execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=transport)
    assert transport.calls == []


def test_stale_observation_cannot_authorize_live_request(tmp_path: Path):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(
        candidate,
        staging_root,
        overrides={"SIA_WEEK9_ODDS_CAPTURE_OBSERVED_AT": "2026-11-06T12:00:00Z"},
    )
    transport = FakeTransport(_http_response(_provider_response(candidate)))
    with pytest.raises(LiveCaptureError, match="clock skew"):
        execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=transport)
    assert transport.calls == []


def test_candidate_path_uses_exact_verified_sia_power_candidate_root(tmp_path: Path):
    staging_root = tmp_path / "data/sia-backend-staging"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root)
    auth = authorize_live_capture(candidate=candidate, environ=env, staging_root=staging_root)
    assert env["SIA_POWER_CANDIDATE_ROOT"] == str(
        tmp_path / "data/sia-staging-candidate/canonical_week9_power_only_v1_validated"
    )
    assert auth.output_dir.is_relative_to(staging_root / "research/week9_odds_captures")


def test_candidate_path_rejects_alternate_and_traversal_paths(tmp_path: Path):
    staging_root = tmp_path / "data/sia-backend-staging"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root)

    env["SIA_POWER_CANDIDATE_ROOT"] = str(tmp_path / "data/other-candidate")
    with pytest.raises(LiveCaptureError, match="does not match the verified staging candidate path"):
        authorize_live_capture(candidate=candidate, environ=env, staging_root=staging_root)

    expected = Path(candidate["bundle_root"])
    env["SIA_POWER_CANDIDATE_ROOT"] = str(expected.parent / ".." / expected.name)
    with pytest.raises(LiveCaptureError, match="no traversal"):
        authorize_live_capture(candidate=candidate, environ=env, staging_root=staging_root)


def test_candidate_path_rejects_symlink_even_when_target_is_the_validated_bundle(tmp_path: Path):
    staging_root = tmp_path / "data/sia-backend-staging"
    candidate = _candidate(staging_root)
    expected = Path(candidate["bundle_root"])
    target = tmp_path / "data/another-location/candidate"
    target.mkdir(parents=True)
    expected.rmdir()
    expected.symlink_to(target, target_is_directory=True)
    env = _environment(candidate, staging_root)
    with pytest.raises(LiveCaptureError, match="Symlink"):
        authorize_live_capture(candidate=candidate, environ=env, staging_root=staging_root)


def test_candidate_and_runtime_roots_must_share_device(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    staging_root = tmp_path / "data/sia-backend-staging"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root)
    original_device_id = live_capture._device_id
    candidate_root = Path(candidate["bundle_root"])

    def split_device(path: Path) -> int:
        return original_device_id(path) + (1 if path == candidate_root else 0)

    monkeypatch.setattr(live_capture, "_device_id", split_device)
    with pytest.raises(LiveCaptureError, match="same filesystem device"):
        authorize_live_capture(candidate=candidate, environ=env, staging_root=staging_root)


@pytest.mark.parametrize(
    "response,error,expected",
    [
        (HttpResponse(503, {}, b"secret body"), None, "HTTP 503"),
        (None, TimeoutError("sensitive request url"), "timed out"),
        (HttpResponse(200, {}, b"not json"), None, "invalid JSON"),
    ],
)
def test_provider_failures_are_sanitized_and_do_not_write(tmp_path: Path, response, error, expected: str):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root)
    transport = FakeTransport(response, error)
    with pytest.raises(LiveCaptureError, match=expected):
        execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=transport)
    assert len(transport.calls) == 1
    assert not Path(env["SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR"]).exists()


def test_partial_response_writes_only_covered_games_with_hashed_coverage(tmp_path: Path):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root)
    response = _provider_response(candidate)
    response.pop(1)
    second_book = deepcopy(response[1]["bookmakers"][0])
    second_book["key"] = "second-fixture-book"
    response[1]["bookmakers"].append(second_book)
    snapshot = execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=FakeTransport(_http_response(response)))
    coverage = snapshot["coverage"]
    assert coverage["status"] == "PARTIAL"
    assert coverage["covered_game_count"] == 13
    assert coverage["uncovered_game_count"] == 1
    assert snapshot["validation"]["spread_pairs_validated"] == 14
    assert "NO_VALIDATED_SPREAD" in coverage["rejection_reason_codes"]
    assert set(coverage["covered_candidate_event_ids"]) == {quote["candidate_event_id"] for quote in snapshot["quotes"]}
    manifest = json.loads((Path(env["SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR"]) / "manifest.json").read_text())
    assert manifest["coverage"] == coverage

    from app.services.experimental_market_comparison import _validate_capture

    power = {
        "artifactId": candidate["candidate_id"],
        "artifactHash": candidate["candidate_hash"],
        "scheduleVersion": candidate["schedule_version"],
        "scheduleHash": candidate["schedule_hash"],
        "games": [
            {"eventId": event["candidate_event_id"], "awayTeam": event["away_team"], "homeTeam": event["home_team"], "kickoffUtc": event["kickoff_utc"]}
            for event in candidate["allowlist"]
        ],
    }
    quotes_by_event = _validate_capture(power=power, capture_dir=Path(env["SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR"]), now=NOW)
    assert {event_id for event_id, quotes in quotes_by_event.items() if quotes} == set(coverage["covered_candidate_event_ids"])
    assert all(not quotes_by_event[event_id] for event_id in coverage["uncovered_candidate_event_ids"])
    assert max(map(len, quotes_by_event.values())) == 2


def test_stale_quote_is_uncovered_and_only_sanitized_reason_is_recorded(tmp_path: Path):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root)
    response = _provider_response(candidate)
    response[1]["bookmakers"][0]["markets"][0]["last_update"] = "2026-11-07T11:00:00Z"
    snapshot = execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=FakeTransport(_http_response(response)))
    assert snapshot["coverage"]["uncovered_game_count"] == 1
    assert "STALE_QUOTE" in snapshot["coverage"]["rejection_reason_codes"]
    assert snapshot["rejected_quotes"] == [{"reason": "STALE_QUOTE"}]


def test_shorter_freshness_policy_is_rejected_before_request(tmp_path: Path):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root, overrides={"SIA_WEEK9_ODDS_CAPTURE_MAX_QUOTE_AGE_SECONDS": "60"})
    transport = FakeTransport(_http_response(_provider_response(candidate)))
    with pytest.raises(LiveCaptureError, match="exactly 300 seconds"):
        execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=transport)
    assert transport.calls == []


def test_kickoff_at_request_time_is_rejected_without_transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    kickoff = datetime(2026, 11, 8, 14, 30, tzinfo=timezone.utc)
    observed = "2026-11-08T14:29:59Z"
    env = _environment(candidate, staging_root, overrides={"SIA_WEEK9_ODDS_CAPTURE_OBSERVED_AT": observed})
    monkeypatch.setattr(live_capture, "_utc_now", lambda: kickoff)
    transport = FakeTransport(_http_response([]))
    with pytest.raises(LiveCaptureError, match="started before the request"):
        execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=transport)
    assert transport.calls == []


def test_kickoff_during_request_is_rejected_without_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    kickoff = datetime(2026, 11, 8, 14, 30, tzinfo=timezone.utc)
    observed = kickoff - timedelta(seconds=1)
    env = _environment(candidate, staging_root, overrides={"SIA_WEEK9_ODDS_CAPTURE_OBSERVED_AT": "2026-11-08T14:29:59Z"})
    clock_values = iter([observed, observed, kickoff])
    monkeypatch.setattr(live_capture, "_utc_now", lambda: next(clock_values))
    transport = FakeTransport(_http_response(_provider_response(candidate, observed=observed)))
    with pytest.raises(LiveCaptureError, match="started during the request"):
        execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=transport)
    assert len(transport.calls) == 1
    assert not Path(env["SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR"]).exists()


def test_quote_becoming_stale_during_request_is_not_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root)
    response = _provider_response(candidate)
    response[1]["bookmakers"][0]["markets"][0]["last_update"] = "2026-11-07T11:55:05Z"
    clock_values = iter([NOW, NOW, NOW + timedelta(seconds=10)])
    monkeypatch.setattr(live_capture, "_utc_now", lambda: next(clock_values))
    transport = FakeTransport(_http_response(response))
    with pytest.raises(LiveCaptureError, match="became stale during the request"):
        execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=transport)
    assert len(transport.calls) == 1
    assert not Path(env["SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR"]).exists()


def test_zero_coverage_duplicate_and_wrong_kickoff_fail_before_write(tmp_path: Path):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root)

    responses = []
    responses.append(([], "no valid pregame spread coverage"))
    duplicate = _provider_response(candidate)
    duplicate.append(dict(duplicate[1]))
    responses.append((duplicate, "duplicate events"))
    wrong_kickoff = _provider_response(candidate)
    wrong_kickoff[1]["commence_time"] = "2026-11-08T15:00:00Z"
    responses.append((wrong_kickoff, "invalid event identity"))

    for provider_events, reason in responses:
        transport = FakeTransport(_http_response(provider_events))
        with pytest.raises(LiveCaptureError, match=reason):
            execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=transport)
        assert len(transport.calls) == 1
        assert not Path(env["SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR"]).exists()


@pytest.mark.parametrize("case", ["kickoff", "team", "duplicate", "duplicate_candidate", "malformed", "missing_id", "invalid_kickoff", "wrong_sport"])
def test_identity_failures_return_sanitized_structured_diagnostics(tmp_path: Path, case: str):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root)
    response = _provider_response(candidate)
    target = response[1]
    target["id"] = FAKE_KEY
    if case == "kickoff":
        target["commence_time"] = "2026-11-08T15:00:00Z"
        expected = "KICKOFF_MISMATCH"
    elif case == "team":
        target["home_team"] = FAKE_KEY
        expected = "INVALID_TEAM_IDENTITY"
    elif case == "duplicate":
        response.append(deepcopy(target))
        expected = "DUPLICATE_PROVIDER_EVENT_ID"
    elif case == "duplicate_candidate":
        other = deepcopy(target)
        other["id"] = "different-event-id"
        response.append(other)
        expected = "DUPLICATE_CANDIDATE_MATCH"
    elif case == "malformed":
        response.append(None)
        expected = "EVENT_NOT_OBJECT"
    elif case == "missing_id":
        target.pop("id")
        expected = "MISSING_PROVIDER_EVENT_ID"
    elif case == "invalid_kickoff":
        target["commence_time"] = FAKE_KEY
        expected = "INVALID_KICKOFF"
    else:
        target["sport_key"] = "another-sport"
        expected = "WRONG_SPORT"
    transport = FakeTransport(_http_response(response))
    with pytest.raises(LiveCaptureError) as failure:
        execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=transport)
    diagnostics = failure.value.diagnostics
    assert diagnostics is not None
    entries = [entry for entry in diagnostics["events"] if entry["reason"] == expected]
    assert entries
    assert FAKE_KEY not in str(failure.value)
    assert FAKE_KEY not in json.dumps(diagnostics)
    assert len(transport.calls) == 1
    assert not Path(env["SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR"]).exists()
    if case == "kickoff":
        assert entries[0]["category"] == "KICKOFF_MISMATCH"
        assert entries[0]["possible_candidate_events"]
        assert entries[0]["provider_kickoff_utc"] == "2026-11-08T15:00:00Z"
    elif case == "team":
        assert entries[0]["category"] == "TEAM_IDENTITY_MISMATCH"
        assert "home_team_fingerprint" in entries[0]
    elif case == "duplicate":
        assert entries[0]["category"] == "DUPLICATE_PROVIDER_EVENT"
    elif case == "duplicate_candidate":
        assert entries[0]["category"] == "DUPLICATE_CANDIDATE_EVENT"
    else:
        assert entries[0]["category"] == "MALFORMED_EVENT_IDENTITY"


def test_non_list_provider_response_has_sanitized_diagnostic(tmp_path: Path):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root)
    response = HttpResponse(status_code=200, headers={}, body=json.dumps({"secret": FAKE_KEY}).encode())
    with pytest.raises(LiveCaptureError) as failure:
        execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=FakeTransport(response))
    assert failure.value.diagnostics["response_reason"] == "RESPONSE_NOT_LIST"
    assert FAKE_KEY not in str(failure.value)
    assert not Path(env["SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR"]).exists()


def test_extra_provider_event_is_diagnosed_without_weakening_candidate_matching(tmp_path: Path):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root)
    response = _provider_response(candidate)
    extra = deepcopy(response[1])
    extra.update(id=FAKE_KEY, away_team="Arizona Cardinals", home_team="Buffalo Bills")
    response.append(extra)
    snapshot = execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=FakeTransport(_http_response(response)))
    events = snapshot["event_identity_diagnostics"]["events"]
    assert any(event["reason"] == "UNMATCHED_EVENT" and event["category"] == "EXTRA_PROVIDER_EVENT" for event in events)
    assert FAKE_KEY not in json.dumps(snapshot)


def test_blocking_identity_diagnostics_precede_truncated_extra_events(tmp_path: Path):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root)
    response = _provider_response(candidate)
    response[1]["commence_time"] = "2026-11-08T15:00:00Z"
    for index in range(55):
        extra = deepcopy(response[1])
        extra.update(id=f"extra-{index}", away_team="Arizona Cardinals", home_team="Buffalo Bills")
        response.append(extra)
    with pytest.raises(LiveCaptureError) as failure:
        execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=FakeTransport(_http_response(response)))
    diagnostics = failure.value.diagnostics
    assert diagnostics["truncated"] is True
    assert len(diagnostics["events"]) == 50
    assert diagnostics["events"][0]["reason"] == "KICKOFF_MISMATCH"


def test_duplicate_bookmaker_market_fails_closed_even_when_another_copy_is_valid(tmp_path: Path):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root)
    response = _provider_response(candidate)
    duplicate_market = dict(response[1]["bookmakers"][0]["markets"][0])
    response[1]["bookmakers"][0]["markets"].append(duplicate_market)
    transport = FakeTransport(_http_response(response))
    with pytest.raises(LiveCaptureError, match="duplicate bookmaker markets"):
        execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=transport)
    assert len(transport.calls) == 1
    assert not Path(env["SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR"]).exists()


def test_invalid_spread_sign_or_malformed_outcome_fails_without_persisting(tmp_path: Path):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root)
    provider_events = _provider_response(candidate)
    provider_events[1]["bookmakers"][0]["markets"][0]["outcomes"][1]["point"] += 2
    transport = FakeTransport(_http_response(provider_events))
    with pytest.raises(LiveCaptureError, match="malformed quotes"):
        execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=transport)
    assert len(transport.calls) == 1
    assert not Path(env["SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR"]).exists()


def test_destination_outside_staging_is_rejected(tmp_path: Path):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root, overrides={"SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR": str(tmp_path / "outside")})
    transport = FakeTransport(_http_response(_provider_response(candidate)))
    with pytest.raises(LiveCaptureError, match="staging research directory"):
        execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=transport)
    assert transport.calls == []