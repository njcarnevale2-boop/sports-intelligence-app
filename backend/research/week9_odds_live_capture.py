from __future__ import annotations

import argparse
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from research.week9_odds_snapshot_prepare import (
    DEFAULT_CANDIDATE_ROOT,
    DEFAULT_MAX_QUOTE_AGE_SECONDS,
    SnapshotPreparationError,
    _parse_utc,
    _sha256_bytes,
    _sha256_json,
    load_candidate_allowlist,
    prepare_snapshot,
)


CAPTURE_VERSION = "week9_odds_live_capture_v1"
STAGING_SERVICE_NAME = "sia-backend-staging"
STAGING_ROOT = Path("/data/sia-backend-staging")
CANDIDATE_RELATIVE_PATH = Path("sia-staging-candidate/canonical_week9_power_only_v1_validated")
OUTPUT_RELATIVE_ROOT = Path("research/week9_odds_captures")
EXPECTED_LIVE_AUTHORIZATION = "I_AUTHORIZE_ONE_STAGING_REQUEST"
MAX_PROVIDER_REQUESTS = 1
MAX_PROVIDER_CREDITS = 1
MAX_REQUEST_TIMEOUT_SECONDS = 10
MAX_OBSERVATION_CLOCK_SKEW_SECONDS = 60
ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
FIXED_QUERY = {
    "regions": "us",
    "markets": "spreads",
    "oddsFormat": "american",
    "dateFormat": "iso",
}
QUOTA_HEADER_NAMES = (
    "x-requests-remaining",
    "x-requests-used",
    "x-requests-last",
)


class LiveCaptureError(ValueError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, repr=False)
class LiveAuthorization:
    api_key: str = field(repr=False)
    observation_timestamp: str
    max_quote_age_seconds: int
    output_dir: Path
    staging_root: Path
    estimated_credit_limit: int
    service_name: str


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


class ProviderTransport(Protocol):
    def get(self, url: str, *, timeout_seconds: int) -> HttpResponse: ...


class UrllibProviderTransport:
    """One direct HTTP request; no retry, discovery, pagination, or logging."""

    class _DenyRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, new_url):
            return None

    def get(self, url: str, *, timeout_seconds: int) -> HttpResponse:
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "SIA-Week9-Staging-Capture/1.0"},
            method="GET",
        )
        try:
            opener = urllib.request.build_opener(self._DenyRedirect())
            with opener.open(request, timeout=timeout_seconds) as response:
                headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
                return HttpResponse(int(response.status), headers, response.read())
        except urllib.error.HTTPError as error:
            headers = {str(key).lower(): str(value) for key, value in error.headers.items()}
            return HttpResponse(int(error.code), headers, b"")


def build_request_url(api_key: str) -> str:
    if not api_key:
        raise LiveCaptureError("ODDS_API_KEY is missing")
    query = {**FIXED_QUERY, "apiKey": api_key}
    return f"{ODDS_API_BASE_URL}?{urllib.parse.urlencode(query)}"


def _require_env(environ: dict[str, str], name: str) -> str:
    value = str(environ.get(name) or "").strip()
    if not value:
        raise LiveCaptureError(f"Required capture gate is missing: {name}")
    return value


def _reject_symlink_components(path: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise LiveCaptureError(f"Symlink path component is forbidden: {current}")
        if current.parent == current:
            return
        current = current.parent


def _device_id(path: Path) -> int:
    return int(os.stat(path).st_dev)


def _verified_candidate_root(environ: dict[str, str], staging_root: Path) -> Path:
    root = Path(staging_root)
    if not root.is_absolute() or ".." in root.parts:
        raise LiveCaptureError("Staging runtime root must be a canonical absolute path")
    _reject_symlink_components(root)
    if not root.is_dir() or root.resolve(strict=True) != root:
        raise LiveCaptureError("Staging runtime root is missing or resolves through a symlink")

    expected = root.parent / CANDIDATE_RELATIVE_PATH
    raw_candidate = _require_env(environ, "SIA_POWER_CANDIDATE_ROOT")
    candidate = Path(raw_candidate)
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise LiveCaptureError("SIA_POWER_CANDIDATE_ROOT must be canonical and contain no traversal")
    if raw_candidate != str(expected):
        raise LiveCaptureError("SIA_POWER_CANDIDATE_ROOT does not match the verified staging candidate path")
    _reject_symlink_components(candidate)
    if not candidate.is_dir() or candidate.resolve(strict=True) != expected:
        raise LiveCaptureError("Candidate root is missing, symlinked, or resolves to a different path")
    if _device_id(candidate) != _device_id(root):
        raise LiveCaptureError("Candidate and staging runtime roots are not on the same filesystem device")
    return candidate


def _verify_candidate_identity(supplied: dict[str, Any], verified: dict[str, Any]) -> None:
    fields = (
        "bundle_sha256",
        "candidate_id",
        "candidate_hash",
        "schedule_version",
        "schedule_hash",
        "lineage_id",
        "week8_snapshot_id",
        "week8_snapshot_hash",
    )
    if any(supplied.get(field) != verified.get(field) for field in fields):
        raise LiveCaptureError("Supplied candidate identity differs from the verified staging bundle")
    if _sha256_json(supplied.get("allowlist")) != _sha256_json(verified.get("allowlist")):
        raise LiveCaptureError("Supplied candidate allowlist differs from the verified staging bundle")


def authorize_live_capture(
    *,
    candidate: dict[str, Any],
    environ: dict[str, str] | None = None,
    staging_root: Path = STAGING_ROOT,
) -> LiveAuthorization:
    """Validate all staging and operator gates before credentials reach transport."""
    env = dict(os.environ if environ is None else environ)
    root = Path(staging_root)

    if str(env.get("RENDER") or "").strip().lower() != "true":
        raise LiveCaptureError("Render runtime identity is not verified")
    service_name = _require_env(env, "RENDER_SERVICE_NAME")
    if service_name != STAGING_SERVICE_NAME:
        raise LiveCaptureError("Render service is not the approved staging service")
    if _require_env(env, "SIA_WEEK9_ODDS_CAPTURE_ENVIRONMENT") != "staging":
        raise LiveCaptureError("Explicit capture environment must be staging")
    if _require_env(env, "NFL_ANALYTICS_OS_ROOT") != str(root):
        raise LiveCaptureError("Runtime data root does not match the staging disk")
    if _require_env(env, "SIA_WEEK9_ODDS_CAPTURE_LIVE_AUTHORIZED") != EXPECTED_LIVE_AUTHORIZATION:
        raise LiveCaptureError("Explicit one-request authorization is missing")
    if _require_env(env, "SIA_WEEK9_ODDS_CAPTURE_CANDIDATE_ID") != candidate["candidate_id"]:
        raise LiveCaptureError("Explicit candidate ID does not match the pinned candidate")
    if _require_env(env, "SIA_WEEK9_ODDS_CAPTURE_CANDIDATE_HASH") != candidate["candidate_hash"]:
        raise LiveCaptureError("Explicit candidate hash does not match the pinned candidate")

    candidate_root = _verified_candidate_root(env, root)
    if Path(str(candidate.get("bundle_root") or "")) != candidate_root:
        raise LiveCaptureError("Loaded candidate root does not match the authorized staging bundle path")

    output_raw = _require_env(env, "SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR")
    output_dir = Path(output_raw)
    output_root = root / OUTPUT_RELATIVE_ROOT
    if not output_dir.is_absolute() or ".." in output_dir.parts:
        raise LiveCaptureError("Capture output path must be canonical and absolute")
    if not output_dir.is_relative_to(output_root) or output_dir == output_root:
        raise LiveCaptureError("Capture output must be a unique child of the staging research directory")
    _reject_symlink_components(output_dir.parent)
    if not output_dir.parent.is_dir() or output_dir.parent.resolve(strict=True) != output_dir.parent:
        raise LiveCaptureError("Capture output parent must exist and must not resolve through a symlink")
    if _device_id(output_dir.parent) != _device_id(root):
        raise LiveCaptureError("Capture output and staging runtime root are not on the same filesystem device")
    if output_dir.exists():
        raise LiveCaptureError("Capture destination already exists; refusing overwrite")

    observation = _require_env(env, "SIA_WEEK9_ODDS_CAPTURE_OBSERVED_AT")
    observed_at = _parse_utc(observation, field="SIA_WEEK9_ODDS_CAPTURE_OBSERVED_AT")
    clock = _utc_now()
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise LiveCaptureError("System clock must be timezone-aware")
    skew = abs((clock.astimezone(timezone.utc) - observed_at).total_seconds())
    if skew > MAX_OBSERVATION_CLOCK_SKEW_SECONDS:
        raise LiveCaptureError("Explicit observation timestamp is not current within the permitted clock skew")

    try:
        max_age = int(_require_env(env, "SIA_WEEK9_ODDS_CAPTURE_MAX_QUOTE_AGE_SECONDS"))
        credit_limit = int(_require_env(env, "SIA_WEEK9_ODDS_CAPTURE_MAX_CREDITS"))
    except ValueError as exc:
        raise LiveCaptureError("Quote-age and credit limits must be integers") from exc
    if max_age <= 0 or max_age > 3600:
        raise LiveCaptureError("Maximum quote age must be between 1 and 3600 seconds")
    if credit_limit != MAX_PROVIDER_CREDITS:
        raise LiveCaptureError("This adapter requires an explicit one-credit maximum")

    api_key = _require_env(env, "ODDS_API_KEY")
    return LiveAuthorization(
        api_key=api_key,
        observation_timestamp=observation,
        max_quote_age_seconds=max_age,
        output_dir=output_dir,
        staging_root=root,
        estimated_credit_limit=credit_limit,
        service_name=service_name,
    )


def build_dry_run_plan(candidate: dict[str, Any], *, observed_at: str, max_quote_age_seconds: int) -> dict[str, Any]:
    observation = _parse_utc(observed_at, field="observed_at")
    if max_quote_age_seconds <= 0:
        raise LiveCaptureError("max_quote_age_seconds must be positive")
    eligible = [
        event for event in candidate["allowlist"]
        if _parse_utc(event["kickoff_utc"], field="candidate kickoff") > observation
    ]
    excluded = [
        {"candidate_event_id": event["candidate_event_id"], "reason": "KICKOFF_ALREADY_OCCURRED"}
        for event in candidate["allowlist"]
        if _parse_utc(event["kickoff_utc"], field="candidate kickoff") <= observation
    ]
    return {
        "mode": "DRY_RUN",
        "network_requests": 0,
        "writes": 0,
        "candidate_id": candidate["candidate_id"],
        "candidate_hash": candidate["candidate_hash"],
        "schedule_version": candidate["schedule_version"],
        "schedule_hash": candidate["schedule_hash"],
        "observed_at": observation.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "max_quote_age_seconds": max_quote_age_seconds,
        "pregame_candidate_event_ids": sorted(event["candidate_event_id"] for event in eligible),
        "excluded_games": excluded,
        "request": {
            "method": "GET",
            "endpoint": "/v4/sports/americanfootball_nfl/odds",
            "regions": FIXED_QUERY["regions"],
            "markets": FIXED_QUERY["markets"],
            "oddsFormat": FIXED_QUERY["oddsFormat"],
            "dateFormat": FIXED_QUERY["dateFormat"],
            "timeout_seconds": MAX_REQUEST_TIMEOUT_SECONDS,
            "max_provider_requests": MAX_PROVIDER_REQUESTS,
            "estimated_credits": 1,
            "credit_estimate_status": "UNVERIFIED_PROVIDER_BILLING_ESTIMATE",
        },
    }


def _quota_headers(headers: dict[str, str]) -> dict[str, int | float]:
    import re

    sanitized: dict[str, int | float] = {}
    for name in QUOTA_HEADER_NAMES:
        value = headers.get(name)
        if value is None or re.fullmatch(r"\d+(?:\.\d+)?", str(value).strip()) is None:
            continue
        number = float(str(value).strip())
        sanitized[name] = int(number) if number.is_integer() else number
    return sanitized


def write_staging_snapshot(snapshot: dict[str, Any], *, output_dir: Path, staging_root: Path = STAGING_ROOT) -> dict[str, Any]:
    root = staging_root.resolve()
    target = output_dir.resolve()
    allowed_root = (root / OUTPUT_RELATIVE_ROOT).resolve()
    if not target.is_relative_to(allowed_root) or target == allowed_root:
        raise LiveCaptureError("Output path is not isolated under staging research storage")
    if target.exists():
        raise LiveCaptureError("Capture destination already exists; refusing overwrite")
    target.mkdir(parents=True, exist_ok=False)
    snapshot_bytes = (json.dumps(snapshot, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    snapshot_path = target / "snapshot.json"
    snapshot_path.write_bytes(snapshot_bytes)
    manifest = {
        "capture_version": CAPTURE_VERSION,
        "environment": "staging",
        "provider_requests": 1,
        "provider_credit_limit": MAX_PROVIDER_CREDITS,
        "database_writes": False,
        "opportunity_history_writes": False,
        "active_pointer_writes": False,
        "official_publication": False,
        "snapshot_file": "snapshot.json",
        "snapshot_sha256": _sha256_bytes(snapshot_bytes),
        "candidate_id": snapshot["candidate"]["candidate_id"],
        "candidate_hash": snapshot["candidate"]["candidate_hash"],
        "schedule_hash": snapshot["candidate"]["schedule_hash"],
    }
    manifest["manifest_sha256"] = _sha256_json(manifest)
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    (target / "manifest.json").write_bytes(manifest_bytes)
    return manifest


def execute_one_shot(
    candidate: dict[str, Any],
    *,
    live_authorized: bool = False,
    environ: dict[str, str] | None = None,
    staging_root: Path = STAGING_ROOT,
    transport: ProviderTransport | None = None,
) -> dict[str, Any]:
    """Return a no-network plan by default; live mode revalidates every gate internally."""
    if not live_authorized:
        env = {} if environ is None else dict(environ)
        observed_value = str(env.get("SIA_WEEK9_ODDS_CAPTURE_OBSERVED_AT") or "").strip()
        if not observed_value:
            raise LiveCaptureError("Explicit observation timestamp is required for dry-run")
        return build_dry_run_plan(
            candidate,
            observed_at=observed_value,
            max_quote_age_seconds=int(env.get("SIA_WEEK9_ODDS_CAPTURE_MAX_QUOTE_AGE_SECONDS", DEFAULT_MAX_QUOTE_AGE_SECONDS)),
        )

    env = dict(os.environ if environ is None else environ)
    authorization = authorize_live_capture(candidate=candidate, environ=env, staging_root=staging_root)
    candidate_root = _verified_candidate_root(env, staging_root)
    verified_candidate = load_candidate_allowlist(candidate_root)
    if any(
        candidate.get(field) != verified_candidate.get(field)
        for field in ("candidate_id", "candidate_hash", "schedule_version", "schedule_hash", "lineage_id", "week8_snapshot_id", "week8_snapshot_hash")
    ):
        raise LiveCaptureError("Supplied candidate identity differs from the verified staging bundle")
    candidate = verified_candidate
    observed_at = _parse_utc(authorization.observation_timestamp, field="observation_timestamp")
    started_at = _utc_now()
    skew = abs((started_at.astimezone(timezone.utc) - observed_at).total_seconds())
    if skew > MAX_OBSERVATION_CLOCK_SKEW_SECONDS:
        raise LiveCaptureError("Observation timestamp expired before request")
    eligible = [
        event for event in candidate["allowlist"]
        if _parse_utc(event["kickoff_utc"], field="candidate kickoff") > observed_at
    ]
    if not eligible:
        raise LiveCaptureError("No pregame candidate events remain")

    url = build_request_url(authorization.api_key)
    try:
        response = (transport or UrllibProviderTransport()).get(url, timeout_seconds=MAX_REQUEST_TIMEOUT_SECONDS)
    except (TimeoutError, socket.timeout) as exc:
        raise LiveCaptureError("Provider request timed out; no retry attempted") from exc
    except Exception as exc:
        raise LiveCaptureError(f"Provider transport failed ({type(exc).__name__}); no retry attempted") from None
    if response.status_code != 200:
        raise LiveCaptureError(f"Provider returned HTTP {response.status_code}; response body and request URL were discarded")

    try:
        provider_events = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveCaptureError("Provider returned invalid JSON; no data was written") from exc

    provider_body_sha = _sha256_bytes(response.body)
    try:
        snapshot = prepare_snapshot(
            candidate,
            provider_events,
            observed_at=authorization.observation_timestamp,
            max_quote_age_seconds=authorization.max_quote_age_seconds,
            response_kind="LOCAL_RESPONSE_FIXTURE",
            provider_response_sha256=provider_body_sha,
        )
    except SnapshotPreparationError as exc:
        raise LiveCaptureError(f"Provider response validation failed: {exc}") from exc

    validation = snapshot["validation"]
    duplicate_event_reasons = {"DUPLICATE_PROVIDER_EVENT_ID", "DUPLICATE_CANDIDATE_MATCH"}
    if any(item.get("reason") in duplicate_event_reasons for item in snapshot["rejected_events"]):
        raise LiveCaptureError("Provider response contains duplicate events; no data was written")
    if any(item.get("reason") == "DUPLICATE_BOOKMAKER_MARKET" for item in snapshot["rejected_quotes"]):
        raise LiveCaptureError("Provider response contains duplicate bookmaker markets; no data was written")
    if validation["eligible_games_missing_spread_quotes"]:
        raise LiveCaptureError(
            "Partial provider response: missing valid spreads for "
            f"{len(validation['eligible_games_missing_spread_quotes'])} eligible candidate games; no data was written"
        )

    snapshot.update(
        {
            "status": "CAPTURED_STAGING_ONLY",
            "capture_version": CAPTURE_VERSION,
            "mode": "AUTHORIZED_ONE_SHOT_STAGING_CAPTURE",
            "data_classification": "LIVE_PROVIDER_RESPONSE",
            "live_provider_data": True,
            "external_requests_made": 1,
            "request_count": 1,
            "staging_writes_made": False,
            "production_writes_made": False,
            "database_writes_made": False,
            "opportunity_history_writes_made": False,
            "active_pointer_writes_made": False,
            "official_publication_made": False,
            "request_shape": {
                "endpoint": "/v4/sports/americanfootball_nfl/odds",
                **FIXED_QUERY,
                "timeout_seconds": MAX_REQUEST_TIMEOUT_SECONDS,
                "retries": 0,
                "estimated_credits": 1,
                "credit_estimate_status": "UNVERIFIED_PROVIDER_BILLING_ESTIMATE",
            },
            "sanitized_quota_headers": _quota_headers(response.headers),
            "capture_authorization": {
                "explicit_live_authorization_verified": True,
                "environment": "staging",
                "service_name": authorization.service_name,
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
                "credit_limit": authorization.estimated_credit_limit,
            },
        }
    )
    snapshot.pop("snapshot_sha256", None)
    snapshot["snapshot_sha256"] = _sha256_json(snapshot)
    write_staging_snapshot(snapshot, output_dir=authorization.output_dir, staging_root=authorization.staging_root)
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="One-shot staging-only NFL odds capture; default is offline dry-run.")
    parser.add_argument("--dry-run", action="store_true", help="Build a request plan only; this is the default mode.")
    parser.add_argument("--authorize-live", action="store_true", help="Explicitly authorize one staging request after all environment gates pass.")
    parser.add_argument("--candidate-bundle", type=Path, default=None)
    parser.add_argument("--observed-at", default=None)
    parser.add_argument("--max-quote-age-seconds", type=int, default=None)
    args = parser.parse_args()
    if args.authorize_live and args.dry_run:
        parser.error("--authorize-live and --dry-run are mutually exclusive")

    if args.authorize_live:
        env = dict(os.environ)
        candidate_root = _verified_candidate_root(env, STAGING_ROOT)
        candidate = load_candidate_allowlist(candidate_root)
        if args.observed_at != env.get("SIA_WEEK9_ODDS_CAPTURE_OBSERVED_AT"):
            parser.error("--observed-at must exactly match SIA_WEEK9_ODDS_CAPTURE_OBSERVED_AT")
        snapshot = execute_one_shot(candidate, live_authorized=True, environ=env)
        summary = {
            "status": snapshot["status"],
            "capture_id": snapshot["snapshot_sha256"],
            "accepted_quotes": snapshot["validation"]["accepted_quote_outcomes"],
            "provider_requests": 1,
            "staging_only": True,
        }
        print(json.dumps(summary, indent=2))
        return

    observed_at = args.observed_at
    if not observed_at:
        parser.error("--observed-at is required for a dry-run plan")
    candidate = load_candidate_allowlist(args.candidate_bundle or DEFAULT_CANDIDATE_ROOT)
    max_age = args.max_quote_age_seconds or DEFAULT_MAX_QUOTE_AGE_SECONDS
    print(json.dumps(build_dry_run_plan(candidate, observed_at=observed_at, max_quote_age_seconds=max_age), indent=2))


if __name__ == "__main__":
    main()