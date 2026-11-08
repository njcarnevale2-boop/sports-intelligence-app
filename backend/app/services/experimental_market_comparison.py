from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.experimental_power import ExperimentalPowerUnavailable, load_experimental_power
from app.services.result_engine.identity import build_canonical_event_identity
from app.services.result_engine.teams import normalize_team_id


STAGING_SERVICE_NAME = "sia-backend-staging"
STAGING_RUNTIME_ROOT = Path("/data/sia-backend-staging")
CAPTURE_ROOT_RELATIVE = Path("research/week9_odds_captures")
CAPTURE_VERSION = "week9_odds_live_capture_v1"
MAX_CAPTURE_AGE_SECONDS = 300


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _parse_utc(value: Any) -> datetime:
    text = str(value or "").strip()
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timezone required")
    return parsed.astimezone(timezone.utc)


def _finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite quote value")
    return number


def _reject_symlinks(path: Path) -> bool:
    current = path
    while True:
        if current.is_symlink():
            return True
        if current.parent == current:
            return False
        current = current.parent


def _no_market(power: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        **power,
        "marketDataStatus": "MARKET_DATA_UNAVAILABLE",
        "marketDataReason": reason,
        "marketDataCapturedAt": None,
        "games": [
            {**game, "marketStatus": "MARKET_DATA_UNAVAILABLE", "marketQuotes": []}
            for game in power.get("games", [])
        ],
    }


def _reject_symlinks(path: Path) -> bool:
    current = path
    while True:
        if current.is_symlink():
            return True
        if current.parent == current:
            return False
        current = current.parent


def _validate_capture(*, power: dict[str, Any], capture_dir: Path, now: datetime) -> dict[str, list[dict[str, Any]]]:
    manifest_path = capture_dir / "manifest.json"
    snapshot_path = capture_dir / "snapshot.json"
    manifest_bytes = manifest_path.read_bytes()
    snapshot_bytes = snapshot_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    snapshot = json.loads(snapshot_bytes)

    manifest_copy = dict(manifest)
    manifest_digest = str(manifest_copy.pop("manifest_sha256", ""))
    if not manifest_digest or _sha256_json(manifest_copy) != manifest_digest:
        raise ValueError("Capture manifest hash mismatch")
    if manifest.get("snapshot_file") != "snapshot.json" or manifest.get("snapshot_sha256") != _sha256_bytes(snapshot_bytes):
        raise ValueError("Capture snapshot file hash mismatch")
    if (
        manifest.get("capture_version") != CAPTURE_VERSION
        or manifest.get("environment") != "staging"
        or manifest.get("provider_requests") != 1
        or manifest.get("provider_credit_limit") != 1
        or manifest.get("database_writes") is not False
        or manifest.get("opportunity_history_writes") is not False
        or manifest.get("active_pointer_writes") is not False
        or manifest.get("official_publication") is not False
    ):
        raise ValueError("Capture manifest scope is invalid")

    snapshot_copy = dict(snapshot)
    snapshot_digest = str(snapshot_copy.pop("snapshot_sha256", ""))
    if not snapshot_digest or _sha256_json(snapshot_copy) != snapshot_digest:
        raise ValueError("Capture snapshot content hash mismatch")
    candidate = snapshot.get("candidate") or {}
    if (
        snapshot.get("status") != "CAPTURED_STAGING_ONLY"
        or snapshot.get("capture_version") != CAPTURE_VERSION
        or snapshot.get("mode") != "AUTHORIZED_ONE_SHOT_STAGING_CAPTURE"
        or snapshot.get("data_classification") != "LIVE_PROVIDER_RESPONSE"
        or snapshot.get("live_provider_data") is not True
        or snapshot.get("external_requests_made") != 1
        or snapshot.get("request_count") != 1
        or snapshot.get("production_writes_made") is not False
        or snapshot.get("database_writes_made") is not False
        or snapshot.get("opportunity_history_writes_made") is not False
        or snapshot.get("active_pointer_writes_made") is not False
        or snapshot.get("official_publication_made") is not False
    ):
        raise ValueError("Capture snapshot is not a one-request staging capture")
    validation = snapshot.get("validation") or {}
    if validation.get("allowlist_games") != 15:
        raise ValueError("Capture snapshot has invalid candidate coverage")
    if (
        candidate.get("candidate_id") != power.get("artifactId")
        or candidate.get("candidate_hash") != power.get("artifactHash")
        or candidate.get("schedule_version") != power.get("scheduleVersion")
        or candidate.get("schedule_hash") != power.get("scheduleHash")
    ):
        raise ValueError("Capture does not match the active experimental candidate identity")
    if (
        manifest.get("candidate_id") != candidate.get("candidate_id")
        or manifest.get("candidate_hash") != candidate.get("candidate_hash")
        or manifest.get("schedule_hash") != candidate.get("schedule_hash")
    ):
        raise ValueError("Capture manifest identity mismatch")
    authorization = snapshot.get("capture_authorization") or {}
    if (
        authorization.get("explicit_live_authorization_verified") is not True
        or authorization.get("environment") != "staging"
        or authorization.get("service_name") != STAGING_SERVICE_NAME
        or authorization.get("candidate_id") != candidate.get("candidate_id")
        or authorization.get("candidate_hash") != candidate.get("candidate_hash")
        or authorization.get("credit_limit") != 1
    ):
        raise ValueError("Capture authorization provenance is invalid")

    observed_at = _parse_utc(snapshot.get("observed_at"))
    max_age = int(snapshot.get("max_quote_age_seconds") or 0)
    if max_age != MAX_CAPTURE_AGE_SECONDS:
        raise ValueError("Capture freshness policy is invalid")
    if observed_at > now or (now - observed_at).total_seconds() > MAX_CAPTURE_AGE_SECONDS:
        raise ValueError("Capture observation is stale or in the future")

    games_by_id = {str(game["eventId"]): game for game in power.get("games", [])}
    if len(games_by_id) != len(power.get("games", [])):
        raise ValueError("Candidate contains duplicate event IDs")
    eligible_ids = {
        event_id for event_id, game in games_by_id.items()
        if _parse_utc(game["kickoffUtc"]) > observed_at
    }
    coverage = snapshot.get("coverage")
    if not isinstance(coverage, dict) or manifest.get("coverage") != coverage:
        raise ValueError("Capture manifest coverage mismatch")
    for field in ("eligible_candidate_event_ids", "covered_candidate_event_ids", "uncovered_candidate_event_ids", "rejection_reason_codes"):
        values = coverage.get(field)
        if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values) or values != sorted(set(values)):
            raise ValueError("Capture coverage contains invalid IDs or reason codes")
    covered_ids = set(coverage["covered_candidate_event_ids"])
    uncovered_ids = set(coverage["uncovered_candidate_event_ids"])
    quarantined = coverage.get("quarantined_candidate_event_ids", [])
    if not isinstance(quarantined, list) or not all(isinstance(value, str) and value for value in quarantined) or quarantined != sorted(set(quarantined)):
        raise ValueError("Capture quarantine contains invalid candidate IDs")
    quarantined_ids = set(quarantined)
    rejected_quarantine_ids = {
        item.get("candidate_event_id") for item in snapshot.get("rejected_events") or []
        if item.get("reason") == "KICKOFF_MISMATCH"
    }
    rejection_codes = set(coverage["rejection_reason_codes"])
    expected_rejection_codes = {
        item["reason"] for item in (snapshot.get("rejected_events") or []) + (snapshot.get("rejected_quotes") or [])
    }
    if uncovered_ids:
        expected_rejection_codes.add("NO_VALIDATED_SPREAD")
    allowed_rejection_codes = {"UNMATCHED_EVENT", "KICKOFF_ALREADY_OCCURRED", "NO_BOOKMAKERS", "STALE_QUOTE", "NO_MARKETS", "NO_VALIDATED_SPREAD", "KICKOFF_MISMATCH"}
    if (
        set(coverage["eligible_candidate_event_ids"]) != eligible_ids
        or snapshot.get("eligible_candidate_event_ids") != sorted(eligible_ids)
        or not covered_ids or covered_ids & uncovered_ids or covered_ids | uncovered_ids != eligible_ids
        or not quarantined_ids <= set(games_by_id) or quarantined_ids & covered_ids
        or quarantined_ids != rejected_quarantine_ids
        or snapshot.get("quarantined_candidate_event_ids", []) != quarantined
        or coverage.get("quarantined_game_count", 0) != len(quarantined_ids)
        or coverage.get("eligible_game_count") != len(eligible_ids)
        or coverage.get("covered_game_count") != len(covered_ids)
        or coverage.get("uncovered_game_count") != len(uncovered_ids)
        or coverage.get("status") != ("PARTIAL" if uncovered_ids else "COMPLETE")
        or rejection_codes != expected_rejection_codes or not rejection_codes <= allowed_rejection_codes
        or validation.get("pregame_eligible_games") != len(eligible_ids)
        or validation.get("eligible_games_with_spread_quotes") != len(covered_ids)
        or validation.get("eligible_games_missing_spread_quotes") != sorted(uncovered_ids)
    ):
        raise ValueError("Capture coverage does not match candidate eligibility")
    quotes_by_event: dict[str, list[dict[str, Any]]] = {event_id: [] for event_id in games_by_id}
    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    provider_events: dict[str, str] = {}
    for quote in snapshot.get("quotes") or []:
        event_id = str(quote.get("candidate_event_id") or "")
        game = games_by_id.get(event_id)
        if game is None or event_id not in covered_ids:
            raise ValueError("Capture contains an event outside the Week 9 candidate")
        if (
            normalize_team_id(quote.get("away_team")) != game["awayTeam"]
            or normalize_team_id(quote.get("home_team")) != game["homeTeam"]
            or _parse_utc(quote.get("kickoff_utc")) != _parse_utc(game["kickoffUtc"])
            or quote.get("market") != "spreads"
        ):
            raise ValueError("Capture event identity does not match the Week 9 candidate")
        event_identity = build_canonical_event_identity(
            season=2026,
            week=9,
            kickoff_utc=game["kickoffUtc"],
            away_team=game["awayTeam"],
            home_team=game["homeTeam"],
        )
        if quote.get("canonical_event_key") != event_identity.canonical_event_key:
            raise ValueError("Capture canonical event key mismatch")
        side = str(quote.get("outcome_side") or "")
        book = str(quote.get("sportsbook_key") or "")
        provider_event_id = str(quote.get("provider_event_id") or "")
        if side not in {"home", "away"} or not book or not provider_event_id:
            raise ValueError("Capture spread quote lacks sportsbook or side")
        if provider_event_id in provider_events and provider_events[provider_event_id] != event_id:
            raise ValueError("Capture provider event is mapped to multiple candidate games")
        provider_events[provider_event_id] = event_id
        quote_update = _parse_utc(quote.get("effective_quote_update"))
        quote_observed = _parse_utc(quote.get("observation_timestamp"))
        kickoff = _parse_utc(game["kickoffUtc"])
        if quote_observed != observed_at or quote_update > observed_at or quote_update > now or quote_update >= kickoff:
            raise ValueError("Capture quote timestamp is post-observation, future, or post-kickoff")
        quote_age = (now - quote_update).total_seconds()
        if quote_age < 0 or quote_age > max_age:
            raise ValueError("Capture quote is stale")
        point = _finite(quote.get("point"))
        price = _finite(quote.get("price"))
        if price == 0:
            raise ValueError("Capture quote price is invalid")
        group_key = (event_id, book)
        sides = grouped.setdefault(group_key, {})
        if side in sides:
            raise ValueError("Duplicate sportsbook spread outcome")
        sides[side] = {
            "point": point,
            "price": price,
            "sportsbookKey": book,
            "sportsbookTitle": str(quote.get("sportsbook_title") or book),
            "providerEventId": provider_event_id,
            "bookmakerLastUpdate": quote.get("bookmaker_last_update"),
            "marketLastUpdate": quote.get("market_last_update"),
            "quoteTimestamp": quote.get("effective_quote_update"),
        }

    for (event_id, _book), sides in grouped.items():
        if set(sides) != {"home", "away"}:
            raise ValueError("Capture is missing a paired home/away spread outcome")
        if sides["home"]["providerEventId"] != sides["away"]["providerEventId"]:
            raise ValueError("Capture spread outcomes have different provider event identities")
        if sides["home"]["quoteTimestamp"] != sides["away"]["quoteTimestamp"]:
            raise ValueError("Capture spread outcomes have different quote timestamps")
        if abs(sides["home"]["point"] + sides["away"]["point"]) > 0.01:
            raise ValueError("Capture home/away spread signs do not pair")
        quotes_by_event[event_id].append(
            {
                **sides["home"],
                "homeSpreadPoint": sides["home"]["point"],
                "awaySpreadPoint": sides["away"]["point"],
                "homePrice": sides["home"]["price"],
                "awayPrice": sides["away"]["price"],
                "marketImpliedHomeMargin": -sides["home"]["point"],
            }
        )
    for quotes in quotes_by_event.values():
        quotes.sort(key=lambda quote: (quote["sportsbookKey"], quote["quoteTimestamp"]))
        if len({quote["providerEventId"] for quote in quotes}) > 1:
            raise ValueError("Capture game has multiple provider event identities")
    if {event_id for event_id, quotes in quotes_by_event.items() if quotes} != covered_ids:
        raise ValueError("Capture validated game coverage does not match metadata")
    if validation.get("spread_pairs_validated") != len(grouped):
        raise ValueError("Capture validated sportsbook pair count does not match quotes")
    return quotes_by_event


def load_experimental_market_comparison(*, season: int, week: int) -> dict[str, Any]:
    if (
        str(os.getenv("RENDER") or "").strip().lower() != "true"
        or str(os.getenv("RENDER_SERVICE_NAME") or "").strip() != STAGING_SERVICE_NAME
        or str(os.getenv("NFL_ANALYTICS_OS_ROOT") or "").strip() != str(STAGING_RUNTIME_ROOT)
    ):
        raise ExperimentalPowerUnavailable("STAGING_ONLY_MARKET_VIEW")
    power = load_experimental_power(season=season, week=week)
    configured = str(os.getenv("SIA_WEEK9_ODDS_CAPTURE_OUTPUT_DIR") or "").strip()
    if not configured:
        return _no_market(power, "NO_VALIDATED_CAPTURE_CONFIGURED")
    capture_dir = Path(configured)
    allowed_root = STAGING_RUNTIME_ROOT / CAPTURE_ROOT_RELATIVE
    if not capture_dir.is_absolute() or ".." in capture_dir.parts or _reject_symlinks(capture_dir):
        return _no_market(power, "CAPTURE_PATH_INVALID")
    try:
        resolved = capture_dir.resolve(strict=True)
        if not resolved.is_relative_to(allowed_root) or resolved == allowed_root:
            return _no_market(power, "CAPTURE_PATH_OUTSIDE_STAGING_RESEARCH")
        if os.stat(resolved).st_dev != os.stat(STAGING_RUNTIME_ROOT).st_dev:
            return _no_market(power, "CAPTURE_PATH_DEVICE_MISMATCH")
        now = _utc_now()
        quotes_by_event = _validate_capture(power=power, capture_dir=resolved, now=now)
        snapshot = json.loads((resolved / "snapshot.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return _no_market(power, "NO_VALIDATED_CAPTURE_AVAILABLE")

    unavailable_ids = set(snapshot["coverage"].get("uncovered_candidate_event_ids", [])) | set(
        snapshot["coverage"].get("quarantined_candidate_event_ids", [])
    )
    games = []
    for game in power.get("games", []):
        started = _parse_utc(game["kickoffUtc"]) <= now
        unavailable = str(game["eventId"]) in unavailable_ids
        quotes = [] if started or unavailable else quotes_by_event.get(str(game["eventId"]), [])
        games.append(
            {
                **game,
                "marketStatus": "MARKET_DATA_UNAVAILABLE" if unavailable else "ALREADY_STARTED" if started else "AVAILABLE" if quotes else "MARKET_DATA_UNAVAILABLE",
                "marketQuotes": quotes,
            }
        )
    if not any(game["marketQuotes"] for game in games):
        return _no_market(power, "NO_FRESH_MATCHED_SPREAD_QUOTES")
    return {
        **power,
        "marketDataStatus": "AVAILABLE",
        "marketDataReason": None,
        "marketDataCapturedAt": snapshot["observed_at"],
        "games": games,
    }