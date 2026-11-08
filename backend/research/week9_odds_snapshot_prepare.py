from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TOOL_VERSION = "week9_odds_snapshot_prepare_v1"
EXPECTED_BUNDLE_SHA256 = "5d10971844c1191c2f3e6ac117a77e2aa62728c82b7d77f430ccf35bcfca60c1"
EXPECTED_CANDIDATE_ID = "proj-a0ce3caf93d2f832"
EXPECTED_CANDIDATE_HASH = "cc47f974be2d5a5495b288bffef13c5a657ebd043fce5ed40cbfea023be6fc07"
EXPECTED_SCHEDULE_VERSION = "canonical-schedule-v2:2026:9:8b89dd5f8fbd"
EXPECTED_SCHEDULE_HASH = "8b89dd5f8fbd1c8834f7fdcc4c8577c07b487acbba6e5adeb14ace9005e3b9a0"
EXPECTED_LINEAGE_ID = "ln-2026-wk8-2380f2961d70"
EXPECTED_WEEK8_SNAPSHOT_ID = "power-2026-wk8-bbe73e1ea965"
EXPECTED_WEEK8_SNAPSHOT_HASH = "bbe73e1ea965b3c89584bd733b7e75bca51cfa8e1a026cd7e2fd23cff0f2117b"
EXPECTED_GAME_COUNT = 15
HOME_FIELD_ADVANTAGE = 1.5
DEFAULT_MAX_QUOTE_AGE_SECONDS = 300
DEFAULT_CANDIDATE_ROOT = (
    Path.home() / "Development/sia-week9-recovery-20261105/canonical_week9_power_only_v1_validated"
)
DEFAULT_RESEARCH_ROOT = Path.home() / "Development/sia-week9-recovery-20261105"
DEFAULT_OUTPUT_DIR = DEFAULT_RESEARCH_ROOT / "week9_odds_snapshot_preparation_v1"

CANONICAL_TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB",
    "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG", "NYJ",
    "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
}
TEAM_ALIASES = {
    "JAC": "JAX", "LA": "LAR", "L.A.": "LAR", "OAK": "LV", "WSH": "WAS",
    "ARIZONA CARDINALS": "ARI", "ATLANTA FALCONS": "ATL", "BALTIMORE RAVENS": "BAL",
    "BUFFALO BILLS": "BUF", "CAROLINA PANTHERS": "CAR", "CHICAGO BEARS": "CHI",
    "CINCINNATI BENGALS": "CIN", "CLEVELAND BROWNS": "CLE", "DALLAS COWBOYS": "DAL",
    "DENVER BRONCOS": "DEN", "DETROIT LIONS": "DET", "GREEN BAY PACKERS": "GB",
    "HOUSTON TEXANS": "HOU", "INDIANAPOLIS COLTS": "IND", "JACKSONVILLE JAGUARS": "JAX",
    "KANSAS CITY CHIEFS": "KC", "LAS VEGAS RAIDERS": "LV", "LOS ANGELES CHARGERS": "LAC",
    "LOS ANGELES RAMS": "LAR", "MIAMI DOLPHINS": "MIA", "MINNESOTA VIKINGS": "MIN",
    "NEW ENGLAND PATRIOTS": "NE", "NEW ORLEANS SAINTS": "NO", "NEW YORK GIANTS": "NYG",
    "NEW YORK JETS": "NYJ", "PHILADELPHIA EAGLES": "PHI", "PITTSBURGH STEELERS": "PIT",
    "SAN FRANCISCO 49ERS": "SF", "SEATTLE SEAHAWKS": "SEA", "TAMPA BAY BUCCANEERS": "TB",
    "TENNESSEE TITANS": "TEN", "WASHINGTON COMMANDERS": "WAS", "WASHINGTON REDSKINS": "WAS",
    "49ERS": "SF", "BEARS": "CHI", "BENGALS": "CIN", "BILLS": "BUF", "BRONCOS": "DEN",
    "BROWNS": "CLE", "BUCCANEERS": "TB", "CARDINALS": "ARI", "CHARGERS": "LAC",
    "CHIEFS": "KC", "COLTS": "IND", "COMMANDERS": "WAS", "COWBOYS": "DAL", "DOLPHINS": "MIA",
    "EAGLES": "PHI", "FALCONS": "ATL", "GIANTS": "NYG", "JAGUARS": "JAX", "JETS": "NYJ",
    "LIONS": "DET", "PACKERS": "GB", "PANTHERS": "CAR", "PATRIOTS": "NE", "RAIDERS": "LV",
    "RAMS": "LAR", "RAVENS": "BAL", "SAINTS": "NO", "SEAHAWKS": "SEA", "STEELERS": "PIT",
    "TEXANS": "HOU", "TITANS": "TEN", "VIKINGS": "MIN",
}
TEAM_NAMES = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs", "LAC": "Los Angeles Chargers", "LAR": "Los Angeles Rams",
    "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings",
    "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
}


class SnapshotPreparationError(ValueError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _safe_child(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise SnapshotPreparationError(f"Candidate path escapes bundle root: {relative}")
    return candidate


def _parse_utc(value: Any, *, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise SnapshotPreparationError(f"Missing {field}")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotPreparationError(f"Invalid {field}: {text}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SnapshotPreparationError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_team(value: Any) -> str | None:
    raw = " ".join(str(value or "").strip().upper().replace(".", "").split())
    if not raw:
        return None
    team = TEAM_ALIASES.get(raw, raw)
    return team if team in CANONICAL_TEAMS else None


def _schedule_identity_payload(schedule: dict[str, Any]) -> dict[str, Any]:
    events = sorted(
        schedule["events"],
        key=lambda row: (str(row["kickoff_utc"]), str(row["canonical_event_key"])),
    )
    return {
        "season": int(schedule["season"]),
        "week": int(schedule["week"]),
        "events": [
            {
                "source_event_id": str(row["source_event_id"]),
                "canonical_event_key": str(row["canonical_event_key"]),
                "game_type": str(row.get("game_type") or "REG"),
                "gameday": str(row["gameday"]),
                "kickoff_utc": str(row["kickoff_utc"]),
                "away_team": str(row["away_team"]),
                "home_team": str(row["home_team"]),
            }
            for row in events
        ],
    }


def _schedule_payload_hash(schedule: dict[str, Any]) -> str:
    return _sha256_json(
        {
            "schedule_version": schedule["schedule_version"],
            "schedule_hash": schedule["schedule_hash"],
            "season": int(schedule["season"]),
            "week": int(schedule["week"]),
            "event_count": int(schedule["event_count"]),
            "source": schedule["source"],
            "source_version": schedule.get("source_version"),
            "source_dataset_version": schedule.get("source_dataset_version"),
            "source_content_sha256": schedule.get("source_content_sha256"),
            "source_manifest_identity": schedule.get("source_manifest_identity"),
            "events": _schedule_identity_payload(schedule)["events"],
        }
    )


def load_candidate_allowlist(bundle_root: Path = DEFAULT_CANDIDATE_ROOT) -> dict[str, Any]:
    root = bundle_root.resolve()
    bundle_path = root / "bundle.json"
    bundle_bytes = bundle_path.read_bytes()
    bundle_sha = _sha256_bytes(bundle_bytes)
    if bundle_sha != EXPECTED_BUNDLE_SHA256:
        raise SnapshotPreparationError(f"Candidate bundle SHA-256 mismatch: {bundle_sha}")
    bundle = json.loads(bundle_bytes)

    if (
        bundle.get("status") != "PREPARED_NOT_ACTIVE"
        or bundle.get("candidateId") != EXPECTED_CANDIDATE_ID
        or bundle.get("candidateHash") != EXPECTED_CANDIDATE_HASH
        or bundle.get("scheduleVersion") != EXPECTED_SCHEDULE_VERSION
        or bundle.get("scheduleHash") != EXPECTED_SCHEDULE_HASH
        or bundle.get("lineageId") != EXPECTED_LINEAGE_ID
        or bundle.get("week8SnapshotId") != EXPECTED_WEEK8_SNAPSHOT_ID
        or bundle.get("week8SnapshotHash") != EXPECTED_WEEK8_SNAPSHOT_HASH
        or bundle.get("activePointersCreated") is not False
        or bundle.get("productionEligible") is not False
        or bundle.get("officialEligible") is not False
    ):
        raise SnapshotPreparationError("Candidate bundle identity or inactive-scope gate failed")

    files = bundle.get("files")
    if not isinstance(files, dict) or not files:
        raise SnapshotPreparationError("Candidate bundle file manifest is missing")
    for relative, expected_hash in files.items():
        if relative.startswith(("power_engine/meta/active/", "power_engine/projections/active/")):
            raise SnapshotPreparationError("Candidate manifest includes an active-pointer file")
        path = _safe_child(root, relative)
        if not path.is_file() or _sha256_bytes(path.read_bytes()) != expected_hash:
            raise SnapshotPreparationError(f"Candidate manifest file mismatch: {relative}")

    schedule_path = str(bundle["schedulePath"])
    if files.get(schedule_path) is None:
        raise SnapshotPreparationError("Schedule artifact is not manifest-pinned")
    schedule = json.loads(_safe_child(root, schedule_path).read_text(encoding="utf-8"))
    if int(schedule.get("season", 0)) != 2026 or int(schedule.get("week", 0)) != 9:
        raise SnapshotPreparationError("Candidate schedule is not 2026 Week 9")
    if len(schedule.get("events") or []) != EXPECTED_GAME_COUNT or int(schedule.get("event_count", 0)) != EXPECTED_GAME_COUNT:
        raise SnapshotPreparationError("Candidate schedule must contain exactly 15 events")
    if _sha256_json(_schedule_identity_payload(schedule)) != EXPECTED_SCHEDULE_HASH:
        raise SnapshotPreparationError("Canonical schedule hash does not recompute")
    if _schedule_payload_hash(schedule) != schedule.get("payload_hash"):
        raise SnapshotPreparationError("Schedule payload hash does not recompute")

    candidate_path = str(bundle["candidatePath"])
    candidate = json.loads(_safe_child(root, candidate_path).read_text(encoding="utf-8"))
    if (
        candidate.get("artifact_id") != EXPECTED_CANDIDATE_ID
        or candidate.get("artifact_hash") != EXPECTED_CANDIDATE_HASH
        or candidate.get("status") != "CANDIDATE"
        or candidate.get("season") != 2026
        or candidate.get("week") != 9
        or candidate.get("schedule_version") != EXPECTED_SCHEDULE_VERSION
        or candidate.get("schedule_hash") != EXPECTED_SCHEDULE_HASH
        or candidate.get("probability_version") != "NOT_COMPUTED_POWER_ONLY"
    ):
        raise SnapshotPreparationError("Candidate artifact identity/scope gate failed")

    lineage_path = f"power_engine/meta/lineages/{EXPECTED_LINEAGE_ID}.json"
    snapshot_path = f"power_engine/snapshots/{EXPECTED_WEEK8_SNAPSHOT_ID}.json"
    if lineage_path not in files or snapshot_path not in files:
        raise SnapshotPreparationError("Week 8 lineage or snapshot is not manifest-pinned")
    lineage = json.loads(_safe_child(root, lineage_path).read_text(encoding="utf-8"))
    snapshot = json.loads(_safe_child(root, snapshot_path).read_text(encoding="utf-8"))
    if (
        lineage.get("lineage_id") != EXPECTED_LINEAGE_ID
        or lineage.get("season") != 2026
        or lineage.get("through_week") != 8
        or lineage.get("active_snapshot_id") != EXPECTED_WEEK8_SNAPSHOT_ID
        or snapshot.get("snapshot_id") != EXPECTED_WEEK8_SNAPSHOT_ID
        or snapshot.get("snapshot_hash") != EXPECTED_WEEK8_SNAPSHOT_HASH
        or snapshot.get("through_week") != 8
        or candidate.get("power_snapshot_id") != EXPECTED_WEEK8_SNAPSHOT_ID
        or candidate.get("power_snapshot_hash") != EXPECTED_WEEK8_SNAPSHOT_HASH
    ):
        raise SnapshotPreparationError("Candidate lineage does not terminate at the pinned Week 8 snapshot")

    schedule_by_source_id = {str(event["source_event_id"]): event for event in schedule["events"]}
    projection_rows = candidate.get("projection_rows") or []
    if len(projection_rows) != EXPECTED_GAME_COUNT:
        raise SnapshotPreparationError("Candidate projection coverage is not 15 games")
    allowlist = []
    seen_source_ids: set[str] = set()
    seen_event_keys: set[str] = set()
    for row in projection_rows:
        event_id = str(row.get("event_id") or "")
        if event_id in seen_source_ids or event_id not in schedule_by_source_id:
            raise SnapshotPreparationError(f"Candidate projection event mismatch: {event_id}")
        seen_source_ids.add(event_id)
        event = schedule_by_source_id[event_id]
        canonical_key = str(event["canonical_event_key"])
        if canonical_key in seen_event_keys:
            raise SnapshotPreparationError(f"Duplicate canonical candidate event: {canonical_key}")
        seen_event_keys.add(canonical_key)
        away = normalize_team(event["away_team"])
        home = normalize_team(event["home_team"])
        if away is None or home is None or away == home:
            raise SnapshotPreparationError(f"Invalid candidate teams for {event_id}")
        kickoff = _parse_utc(event["kickoff_utc"], field="candidate kickoff")
        model_margin = float(row["model_margin_home"])
        expected_margin = float(row["home_power"]) - float(row["away_power"]) + HOME_FIELD_ADVANTAGE
        if not math.isfinite(model_margin) or abs(model_margin - expected_margin) > 0.01:
            raise SnapshotPreparationError(f"Candidate home-margin convention mismatch: {event_id}")
        allowlist.append(
            {
                "candidate_event_id": event_id,
                "canonical_event_key": canonical_key,
                "season": 2026,
                "week": 9,
                "away_team": away,
                "home_team": home,
                "kickoff_utc": _utc_text(kickoff),
                "model_margin_home": model_margin,
                "candidate_home_fair_spread": -model_margin,
            }
        )
    if seen_source_ids != set(schedule_by_source_id):
        raise SnapshotPreparationError("Candidate projections do not cover the full canonical schedule")
    allowlist.sort(key=lambda event: (event["kickoff_utc"], event["canonical_event_key"]))

    return {
        "bundle_root": str(root),
        "bundle_sha256": bundle_sha,
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "candidate_hash": EXPECTED_CANDIDATE_HASH,
        "candidate_path": candidate_path,
        "lineage_id": EXPECTED_LINEAGE_ID,
        "week8_snapshot_id": EXPECTED_WEEK8_SNAPSHOT_ID,
        "week8_snapshot_hash": EXPECTED_WEEK8_SNAPSHOT_HASH,
        "schedule_version": EXPECTED_SCHEDULE_VERSION,
        "schedule_hash": EXPECTED_SCHEDULE_HASH,
        "schedule_file_sha256": files[schedule_path],
        "manifest_file_count": len(files),
        "allowlist": allowlist,
    }


def _parse_utc(value: Any, *, field: str) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotPreparationError(f"Invalid {field}: {text}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SnapshotPreparationError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _team(value: Any) -> str | None:
    text = " ".join(str(value or "").strip().upper().replace(".", "").split())
    token = TEAM_ALIASES.get(text, text)
    return token if token in CANONICAL_TEAMS else None


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _event_key(event: dict[str, Any]) -> tuple[str, str, str]:
    return event["away_team"], event["home_team"], event["kickoff_utc"]


def _validate_allowlist(allowlist: list[dict[str, Any]]) -> None:
    if len(allowlist) != EXPECTED_GAME_COUNT:
        raise SnapshotPreparationError("Candidate allowlist must contain exactly 15 games")
    event_ids = [str(event.get("candidate_event_id") or "") for event in allowlist]
    event_keys = [str(event.get("canonical_event_key") or "") for event in allowlist]
    match_keys = [_event_key(event) for event in allowlist]
    if not all(event_ids) or len(set(event_ids)) != len(event_ids):
        raise SnapshotPreparationError("Candidate allowlist contains duplicate or missing event IDs")
    if not all(event_keys) or len(set(event_keys)) != len(event_keys):
        raise SnapshotPreparationError("Candidate allowlist contains duplicate or missing canonical event keys")
    if len(set(match_keys)) != len(match_keys):
        raise SnapshotPreparationError("Candidate allowlist contains ambiguous matchup/kickoff keys")


def build_synthetic_provider_response(allowlist: list[dict[str, Any]], observed_at: datetime) -> list[dict[str, Any]]:
    update_at = _utc_text(observed_at - timedelta(seconds=60))
    response = []
    for index, event in enumerate(allowlist):
        home_spread = -2.5 - (index % 4) * 0.5
        response.append(
            {
                "id": f"synthetic-oddsapi-{event['candidate_event_id']}",
                "sport_key": "americanfootball_nfl",
                "commence_time": event["kickoff_utc"],
                "home_team": TEAM_NAMES[event["home_team"]],
                "away_team": TEAM_NAMES[event["away_team"]],
                "bookmakers": [
                    {
                        "key": "synthetic-test-book",
                        "title": "Synthetic Fixture Book",
                        "last_update": update_at,
                        "markets": [
                            {
                                "key": "spreads",
                                "last_update": update_at,
                                "outcomes": [
                                    {"name": TEAM_NAMES[event["home_team"]], "price": -110, "point": home_spread},
                                    {"name": TEAM_NAMES[event["away_team"]], "price": -110, "point": -home_spread},
                                ],
                            }
                        ],
                    }
                ],
            }
        )
    return response


def prepare_snapshot(
    candidate: dict[str, Any],
    provider_response: Any,
    *,
    observed_at: str,
    max_quote_age_seconds: int = DEFAULT_MAX_QUOTE_AGE_SECONDS,
    response_kind: str,
    provider_response_sha256: str,
) -> dict[str, Any]:
    observation = _parse_utc(observed_at, field="observed_at")
    if isinstance(max_quote_age_seconds, bool) or max_quote_age_seconds <= 0:
        raise SnapshotPreparationError("max_quote_age_seconds must be positive")
    if not isinstance(provider_response, list):
        raise SnapshotPreparationError("Provider response fixture must be a JSON array")

    allowlist = candidate["allowlist"]
    _validate_allowlist(allowlist)
    exact_index: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    pair_index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    eligible = []
    excluded = []
    for event in allowlist:
        exact_index[_event_key(event)].append(event)
        pair_index[(event["away_team"], event["home_team"])].append(event)
        game_kickoff = _parse_utc(event["kickoff_utc"], field="candidate kickoff")
        if game_kickoff > observation:
            eligible.append(event)
        else:
            excluded.append({"candidate_event_id": event["candidate_event_id"], "reason": "KICKOFF_ALREADY_OCCURRED"})

    response_ids = [str(event.get("id") or "") for event in provider_response if isinstance(event, dict)]
    id_counts = Counter(response_ids)
    matched_by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rejected_events: list[dict[str, Any]] = []
    unmatched_count = 0

    for provider_event in provider_response:
        if not isinstance(provider_event, dict):
            rejected_events.append({"provider_event_id": None, "reason": "EVENT_NOT_OBJECT"})
            unmatched_count += 1
            continue
        provider_id = str(provider_event.get("id") or "")
        if not provider_id:
            rejected_events.append({"provider_event_id": None, "reason": "MISSING_PROVIDER_EVENT_ID"})
            unmatched_count += 1
            continue
        if id_counts[provider_id] > 1:
            rejected_events.append({"provider_event_id": provider_id, "reason": "DUPLICATE_PROVIDER_EVENT_ID"})
            unmatched_count += 1
            continue
        if provider_event.get("sport_key") not in (None, "americanfootball_nfl"):
            rejected_events.append({"provider_event_id": provider_id, "reason": "WRONG_SPORT"})
            unmatched_count += 1
            continue

        away = _team(provider_event.get("away_team"))
        home = _team(provider_event.get("home_team"))
        try:
            kickoff = _utc_text(_parse_utc(provider_event.get("commence_time"), field="provider commence_time"))
        except SnapshotPreparationError:
            rejected_events.append({"provider_event_id": provider_id, "reason": "INVALID_KICKOFF"})
            unmatched_count += 1
            continue
        if away is None or home is None or away == home:
            rejected_events.append({"provider_event_id": provider_id, "reason": "INVALID_TEAM_IDENTITY"})
            unmatched_count += 1
            continue

        candidates = exact_index.get((away, home, kickoff), [])
        if len(candidates) > 1:
            rejected_events.append({"provider_event_id": provider_id, "reason": "AMBIGUOUS_CANDIDATE_MATCH"})
            unmatched_count += 1
        elif not candidates:
            reason = "KICKOFF_MISMATCH" if pair_index.get((away, home)) else "UNMATCHED_EVENT"
            rejected_events.append({"provider_event_id": provider_id, "reason": reason})
            unmatched_count += 1
        elif _parse_utc(candidates[0]["kickoff_utc"], field="candidate kickoff") <= observation:
            rejected_events.append(
                {"provider_event_id": provider_id, "candidate_event_id": candidates[0]["candidate_event_id"], "reason": "KICKOFF_ALREADY_OCCURRED"}
            )
            unmatched_count += 1
        else:
            matched_by_candidate[candidates[0]["candidate_event_id"]].append(provider_event)

    duplicate_candidate_ids = {event_id for event_id, matches in matched_by_candidate.items() if len(matches) > 1}
    for event_id in sorted(duplicate_candidate_ids):
        for event in matched_by_candidate[event_id]:
            rejected_events.append(
                {"provider_event_id": str(event.get("id")), "candidate_event_id": event_id, "reason": "DUPLICATE_CANDIDATE_MATCH"}
            )
            unmatched_count += 1

    allowlist_by_id = {event["candidate_event_id"]: event for event in allowlist}
    accepted_quotes: list[dict[str, Any]] = []
    rejected_quotes: list[dict[str, Any]] = []
    spread_pair_checks: list[dict[str, Any]] = []
    matched_event_ids = sorted(set(matched_by_candidate) - duplicate_candidate_ids)

    for candidate_event_id in matched_event_ids:
        provider_event = matched_by_candidate[candidate_event_id][0]
        candidate_event = allowlist_by_id[candidate_event_id]
        bookmakers = provider_event.get("bookmakers")
        if not isinstance(bookmakers, list) or not bookmakers:
            rejected_events.append({"provider_event_id": provider_event["id"], "candidate_event_id": candidate_event_id, "reason": "NO_BOOKMAKERS"})
            continue
        seen_book_market: set[tuple[str, str]] = set()
        for bookmaker in bookmakers:
            if not isinstance(bookmaker, dict):
                rejected_quotes.append({"provider_event_id": provider_event["id"], "reason": "BOOKMAKER_NOT_OBJECT"})
                continue
            book_key = str(bookmaker.get("key") or "").strip()
            book_title = str(bookmaker.get("title") or "").strip()
            if not book_key or not book_title:
                rejected_quotes.append({"provider_event_id": provider_event["id"], "reason": "MISSING_SPORTSBOOK_IDENTITY"})
                continue
            bookmaker_update = bookmaker.get("last_update")
            markets = bookmaker.get("markets")
            if not isinstance(markets, list) or not markets:
                rejected_quotes.append({"provider_event_id": provider_event["id"], "sportsbook": book_key, "reason": "NO_MARKETS"})
                continue
            for market in markets:
                if not isinstance(market, dict):
                    rejected_quotes.append({"provider_event_id": provider_event["id"], "sportsbook": book_key, "reason": "MARKET_NOT_OBJECT"})
                    continue
                market_key = str(market.get("key") or "").strip()
                if not market_key:
                    rejected_quotes.append({"provider_event_id": provider_event["id"], "sportsbook": book_key, "reason": "MISSING_MARKET_KEY"})
                    continue
                pair_key = (book_key, market_key)
                if pair_key in seen_book_market:
                    rejected_quotes.append(
                        {"provider_event_id": provider_event["id"], "sportsbook": book_key, "market": market_key, "reason": "DUPLICATE_BOOKMAKER_MARKET"}
                    )
                    continue
                seen_book_market.add(pair_key)

                market_update = market.get("last_update")
                effective_update = market_update or bookmaker_update
                if not effective_update:
                    rejected_quotes.append(
                        {"provider_event_id": provider_event["id"], "sportsbook": book_key, "market": market_key, "reason": "MISSING_QUOTE_UPDATE_TIMESTAMP"}
                    )
                    continue
                try:
                    quote_updated_at = _parse_utc(effective_update, field="quote last_update")
                except SnapshotPreparationError:
                    rejected_quotes.append(
                        {"provider_event_id": provider_event["id"], "sportsbook": book_key, "market": market_key, "reason": "INVALID_QUOTE_UPDATE_TIMESTAMP"}
                    )
                    continue
                if quote_updated_at > observation:
                    rejected_quotes.append(
                        {"provider_event_id": provider_event["id"], "sportsbook": book_key, "market": market_key, "reason": "QUOTE_UPDATED_AFTER_OBSERVATION"}
                    )
                    continue
                age_seconds = int((observation - quote_updated_at).total_seconds())
                if age_seconds > max_quote_age_seconds:
                    rejected_quotes.append(
                        {
                            "provider_event_id": provider_event["id"],
                            "candidate_event_id": candidate_event_id,
                            "sportsbook": book_key,
                            "market": market_key,
                            "reason": "STALE_QUOTE",
                            "age_seconds": age_seconds,
                        }
                    )
                    continue

                outcomes = market.get("outcomes")
                if not isinstance(outcomes, list) or not outcomes:
                    rejected_quotes.append(
                        {"provider_event_id": provider_event["id"], "sportsbook": book_key, "market": market_key, "reason": "NO_OUTCOMES"}
                    )
                    continue
                parsed_outcomes = []
                invalid_reason = None
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        invalid_reason = "OUTCOME_NOT_OBJECT"
                        break
                    outcome_name = str(outcome.get("name") or "").strip()
                    price = _finite_number(outcome.get("price"))
                    point = _finite_number(outcome.get("point"))
                    if not outcome_name:
                        invalid_reason = "MISSING_OUTCOME_NAME"
                        break
                    if price is None or price == 0:
                        invalid_reason = "MISSING_OR_INVALID_PRICE"
                        break
                    if market_key in {"spreads", "totals"} and point is None:
                        invalid_reason = "MISSING_OR_INVALID_POINT"
                        break
                    outcome_team = _team(outcome_name)
                    if outcome_team == candidate_event["home_team"]:
                        outcome_side = "home"
                    elif outcome_team == candidate_event["away_team"]:
                        outcome_side = "away"
                    elif outcome_name.casefold() in {"over", "under"}:
                        outcome_side = outcome_name.casefold()
                    else:
                        outcome_side = "other"
                    parsed_outcomes.append(
                        {"outcome_name": outcome_name, "outcome_side": outcome_side, "point": point, "price": price}
                    )

                if invalid_reason:
                    rejected_quotes.append(
                        {"provider_event_id": provider_event["id"], "sportsbook": book_key, "market": market_key, "reason": invalid_reason}
                    )
                    continue

                spread_metadata = {}
                if market_key == "spreads":
                    home_outcomes = [item for item in parsed_outcomes if item["outcome_side"] == "home"]
                    away_outcomes = [item for item in parsed_outcomes if item["outcome_side"] == "away"]
                    if len(home_outcomes) != 1 or len(away_outcomes) != 1:
                        rejected_quotes.append(
                            {"provider_event_id": provider_event["id"], "sportsbook": book_key, "market": market_key, "reason": "SPREAD_OUTCOME_TEAM_AMBIGUITY"}
                        )
                        continue
                    home_point = float(home_outcomes[0]["point"])
                    away_point = float(away_outcomes[0]["point"])
                    if abs(home_point + away_point) > 0.01:
                        rejected_quotes.append(
                            {"provider_event_id": provider_event["id"], "sportsbook": book_key, "market": market_key, "reason": "SPREAD_SIGN_MISMATCH"}
                        )
                        continue
                    spread_metadata = {
                        "market_home_spread_point": home_point,
                        "market_away_spread_point": away_point,
                        "market_implied_home_margin": -home_point,
                        "candidate_home_fair_spread": candidate_event["candidate_home_fair_spread"],
                        "candidate_home_expected_margin": candidate_event["model_margin_home"],
                        "spread_sign_validated": abs(home_point + away_point) <= 0.01
                        and abs(candidate_event["candidate_home_fair_spread"] + candidate_event["model_margin_home"]) <= 0.01,
                    }
                    spread_pair_checks.append(
                        {
                            "candidate_event_id": candidate_event_id,
                            "sportsbook": book_key,
                            "home_spread_point": home_point,
                            "away_spread_point": away_point,
                            "market_implied_home_margin": -home_point,
                            "candidate_home_expected_margin": candidate_event["model_margin_home"],
                            "candidate_home_fair_spread": candidate_event["candidate_home_fair_spread"],
                            "valid": spread_metadata["spread_sign_validated"],
                        }
                    )

                for parsed in parsed_outcomes:
                    accepted_quotes.append(
                        {
                            "candidate_event_id": candidate_event_id,
                            "canonical_event_key": candidate_event["canonical_event_key"],
                            "provider_event_id": str(provider_event["id"]),
                            "away_team": candidate_event["away_team"],
                            "home_team": candidate_event["home_team"],
                            "kickoff_utc": candidate_event["kickoff_utc"],
                            "sportsbook_key": book_key,
                            "sportsbook_title": book_title,
                            "market": market_key,
                            "outcome": parsed["outcome_name"],
                            "outcome_side": parsed["outcome_side"],
                            "point": parsed["point"],
                            "price": parsed["price"],
                            "bookmaker_last_update": bookmaker_update,
                            "market_last_update": market_update,
                            "effective_quote_update": _utc_text(quote_updated_at),
                            "observation_timestamp": _utc_text(observation),
                            "quote_age_seconds": age_seconds,
                            **spread_metadata,
                        }
                    )

    accepted_quotes.sort(
        key=lambda row: (row["candidate_event_id"], row["sportsbook_key"], row["market"], row["outcome_side"])
    )
    eligible_ids = {event["candidate_event_id"] for event in eligible}
    spread_covered_ids = {
        check["candidate_event_id"] for check in spread_pair_checks if check["valid"]
    }
    missing_spread_ids = sorted(eligible_ids - spread_covered_ids)
    status = "PREPARED_LOCAL_ONLY" if not missing_spread_ids else "INCOMPLETE_LOCAL_ONLY"
    snapshot = {
        "schema_version": "sia_week9_odds_snapshot_v1",
        "status": status,
        "mode": "DRY_RUN_OFFLINE",
        "data_classification": "SYNTHETIC_FIXTURE_ONLY" if response_kind == "SYNTHETIC_FIXTURE" else "LOCAL_RESPONSE_FIXTURE_UNVERIFIED",
        "live_provider_data": False,
        "external_requests_made": 0,
        "staging_writes_made": False,
        "production_writes_made": False,
        "observed_at": _utc_text(observation),
        "max_quote_age_seconds": max_quote_age_seconds,
        "candidate": {
            "bundle_sha256": candidate["bundle_sha256"],
            "candidate_id": candidate["candidate_id"],
            "candidate_hash": candidate["candidate_hash"],
            "lineage_id": candidate["lineage_id"],
            "week8_snapshot_id": candidate["week8_snapshot_id"],
            "week8_snapshot_hash": candidate["week8_snapshot_hash"],
            "schedule_version": candidate["schedule_version"],
            "schedule_hash": candidate["schedule_hash"],
            "schedule_file_sha256": candidate["schedule_file_sha256"],
            "manifest_file_count": candidate["manifest_file_count"],
        },
        "allowlist": allowlist,
        "eligible_candidate_event_ids": sorted(eligible_ids),
        "excluded_games": excluded,
        "quotes": accepted_quotes,
        "rejected_events": rejected_events,
        "rejected_quotes": rejected_quotes,
        "spread_pair_checks": spread_pair_checks,
        "validation": {
            "allowlist_games": len(allowlist),
            "pregame_eligible_games": len(eligible),
            "kickoff_excluded_games": len(excluded),
            "provider_events_received": len(provider_response),
            "matched_provider_events": len(matched_event_ids),
            "unmatched_or_rejected_events": unmatched_count,
            "spread_pairs_validated": sum(bool(check["valid"]) for check in spread_pair_checks),
            "eligible_games_with_spread_quotes": len(spread_covered_ids),
            "eligible_games_missing_spread_quotes": missing_spread_ids,
            "accepted_quote_outcomes": len(accepted_quotes),
            "rejected_quote_groups": len(rejected_quotes),
        },
        "provider_response_sha256": provider_response_sha256,
    }
    snapshot["snapshot_sha256"] = _sha256_json(snapshot)
    return snapshot


def write_local_artifacts(
    *,
    output_dir: Path,
    candidate_root: Path,
    snapshot: dict[str, Any],
    provider_response: list[dict[str, Any]],
    research_root: Path = DEFAULT_RESEARCH_ROOT,
) -> dict[str, Any]:
    output_path = output_dir.resolve()
    allowed_root = research_root.resolve()
    if not output_path.is_relative_to(allowed_root):
        raise SnapshotPreparationError("Output must be inside the local research directory")
    if output_path.is_relative_to(candidate_root.resolve()):
        raise SnapshotPreparationError("Output must not be written inside the immutable candidate bundle")
    if output_path == Path("/data") or output_path.is_relative_to(Path("/data")):
        raise SnapshotPreparationError("Output must not target staging or production storage")
    if output_path.exists():
        raise SnapshotPreparationError(f"Refusing to overwrite existing output directory: {output_path}")

    output_path.mkdir(parents=True, exist_ok=False)
    fixture_bytes = (json.dumps(provider_response, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    snapshot_bytes = (json.dumps(snapshot, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    (output_path / "synthetic_provider_response.json").write_bytes(fixture_bytes)
    (output_path / "snapshot.json").write_bytes(snapshot_bytes)
    manifest = {
        "tool_version": TOOL_VERSION,
        "mode": "DRY_RUN_OFFLINE",
        "external_requests_made": 0,
        "staging_writes_made": False,
        "production_writes_made": False,
        "candidate_bundle_sha256": snapshot["candidate"]["bundle_sha256"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "files": {
            "synthetic_provider_response.json": _sha256_bytes(fixture_bytes),
            "snapshot.json": _sha256_bytes(snapshot_bytes),
        },
    }
    manifest["manifest_sha256"] = _sha256_json(manifest)
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    (output_path / "manifest.json").write_bytes(manifest_bytes)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a local-only Week 9 odds snapshot; network access is not implemented.")
    parser.add_argument("--candidate-bundle", type=Path, default=DEFAULT_CANDIDATE_ROOT)
    parser.add_argument("--observed-at", required=True, help="Explicit ISO-8601 timestamp with timezone; no current clock is read.")
    parser.add_argument("--max-quote-age-seconds", type=int, default=DEFAULT_MAX_QUOTE_AGE_SECONDS)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--provider-response", type=Path, help="Local JSON response fixture only; no request is made.")
    source_group.add_argument("--synthetic-fixture", action="store_true", help="Build a clearly synthetic fixture from the candidate allowlist.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--dry-run", action="store_true", required=True, help="Required. This tool has no live or staging-write mode.")
    args = parser.parse_args()

    candidate = load_candidate_allowlist(args.candidate_bundle)
    observed = _parse_utc(args.observed_at, field="observed_at")
    if args.synthetic_fixture:
        provider_response = build_synthetic_provider_response(candidate["allowlist"], observed)
        response_kind = "SYNTHETIC_FIXTURE"
        response_hash = _sha256_json(provider_response)
    else:
        fixture_bytes = args.provider_response.read_bytes()
        provider_response = json.loads(fixture_bytes)
        response_kind = "LOCAL_RESPONSE_FIXTURE"
        response_hash = _sha256_bytes(fixture_bytes)
    snapshot = prepare_snapshot(
        candidate,
        provider_response,
        observed_at=args.observed_at,
        max_quote_age_seconds=args.max_quote_age_seconds,
        response_kind=response_kind,
        provider_response_sha256=response_hash,
    )
    manifest = write_local_artifacts(
        output_dir=args.output_dir,
        candidate_root=args.candidate_bundle,
        snapshot=snapshot,
        provider_response=provider_response,
    )
    print(
        json.dumps(
            {
                "status": snapshot["status"],
                "output_dir": str(args.output_dir),
                "snapshot_sha256": snapshot["snapshot_sha256"],
                "candidate_games": snapshot["validation"]["allowlist_games"],
                "pregame_games": snapshot["validation"]["pregame_eligible_games"],
                "kickoff_excluded": snapshot["validation"]["kickoff_excluded_games"],
                "accepted_quote_outcomes": snapshot["validation"]["accepted_quote_outcomes"],
                "manifest_sha256": manifest["manifest_sha256"],
                "external_requests_made": 0,
                "staging_writes_made": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()