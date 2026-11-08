from __future__ import annotations

import json
import urllib.parse
from dataclasses import replace
from datetime import datetime, timezone
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


def test_partial_response_duplicate_wrong_kickoff_and_stale_quotes_fail_before_write(tmp_path: Path):
    staging_root = tmp_path / "stage"
    candidate = _candidate(staging_root)
    env = _environment(candidate, staging_root)

    responses = []
    partial = _provider_response(candidate)
    partial.pop(1)
    responses.append((partial, "Partial provider response"))
    duplicate = _provider_response(candidate)
    duplicate.append(dict(duplicate[1]))
    responses.append((duplicate, "duplicate events"))
    wrong_kickoff = _provider_response(candidate)
    wrong_kickoff[1]["commence_time"] = "2026-11-08T15:00:00Z"
    responses.append((wrong_kickoff, "Partial provider response"))
    stale = _provider_response(candidate)
    stale[1]["bookmakers"][0]["markets"][0]["last_update"] = "2026-11-07T11:00:00Z"
    responses.append((stale, "Partial provider response"))

    for provider_events, reason in responses:
        transport = FakeTransport(_http_response(provider_events))
        with pytest.raises(LiveCaptureError, match=reason):
            execute_one_shot(candidate, live_authorized=True, environ=env, staging_root=staging_root, transport=transport)
        assert len(transport.calls) == 1
        assert not Path(env["SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR"]).exists()


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
    with pytest.raises(LiveCaptureError, match="Partial provider response"):
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