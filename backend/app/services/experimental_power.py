from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from app.services.power_engine.persistence import _snapshot_from_dict
from app.services.power_engine.projection_publication import CanonicalScheduleEvent, _validation_for_candidate


class ExperimentalPowerUnavailable(ValueError):
    pass


def load_experimental_power(*, season: int, week: int) -> dict:
    if os.getenv("SIA_EXPERIMENTAL_POWER_ENABLED", "").lower() != "true":
        raise ExperimentalPowerUnavailable("EXPERIMENTAL_POWER_DISABLED")
    configured = os.getenv("SIA_POWER_CANDIDATE_ROOT", "").strip()
    manifest_hash = os.getenv("SIA_POWER_CANDIDATE_MANIFEST_SHA256", "").strip()
    if not configured or not manifest_hash:
        raise ExperimentalPowerUnavailable("EXPERIMENTAL_BUNDLE_NOT_CONFIGURED")
    root = Path(configured).resolve()

    def content(relative: str) -> bytes:
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ExperimentalPowerUnavailable("EXPERIMENTAL_BUNDLE_PATH_INVALID")
        return path.read_bytes()

    try:
        manifest_bytes = content("bundle.json")
        if hashlib.sha256(manifest_bytes).hexdigest() != manifest_hash:
            raise ExperimentalPowerUnavailable("EXPERIMENTAL_MANIFEST_HASH_MISMATCH")
        manifest = json.loads(manifest_bytes)
        if manifest["status"] != "PREPARED_NOT_ACTIVE" or manifest["productionEligible"] is not False or manifest["officialEligible"] is not False:
            raise ExperimentalPowerUnavailable("EXPERIMENTAL_BUNDLE_SCOPE_INVALID")
        for relative, expected in manifest["files"].items():
            if hashlib.sha256(content(relative)).hexdigest() != expected:
                raise ExperimentalPowerUnavailable("EXPERIMENTAL_BUNDLE_HASH_MISMATCH")
        for directory in (root / "power_engine/meta/active", root / "power_engine/projections/active"):
            if directory.exists() and any(directory.glob("*.json")):
                raise ExperimentalPowerUnavailable("EXPERIMENTAL_BUNDLE_HAS_ACTIVE_POINTERS")
        artifact = json.loads(content(manifest["candidatePath"]))
        validation = json.loads(content(manifest["validationPath"]))
        schedule = json.loads(content(manifest["schedulePath"]))
        if artifact["season"] != season or artifact["week"] != week:
            raise ExperimentalPowerUnavailable("EXPERIMENTAL_WEEK_UNAVAILABLE")
        if artifact["status"] != "CANDIDATE" or artifact["probability_version"] != "NOT_COMPUTED_POWER_ONLY":
            raise ExperimentalPowerUnavailable("EXPERIMENTAL_ARTIFACT_SCOPE_INVALID")
        if artifact["artifact_id"] != manifest["candidateId"] or artifact["artifact_hash"] != manifest["candidateHash"]:
            raise ExperimentalPowerUnavailable("EXPERIMENTAL_ARTIFACT_IDENTITY_MISMATCH")
        if artifact["schedule_version"] != schedule["schedule_version"] or artifact["schedule_hash"] != schedule["schedule_hash"]:
            raise ExperimentalPowerUnavailable("EXPERIMENTAL_SCHEDULE_MISMATCH")
        events = [CanonicalScheduleEvent(
            event_id=row["source_event_id"], canonical_event_key=row["canonical_event_key"],
            season=season, week=week, kickoff_utc=row["kickoff_utc"], away_team=row["away_team"], home_team=row["home_team"],
        ) for row in schedule["events"]]
        checked = _validation_for_candidate(artifact=artifact, schedule_events=events)
        if checked["status"] != "VALID" or validation["status"] != "VALID" or validation["artifact_id"] != artifact["artifact_id"]:
            raise ExperimentalPowerUnavailable("EXPERIMENTAL_ARTIFACT_INVALID")
        snapshot = _snapshot_from_dict(json.loads(content("power_engine/snapshots/" + artifact["power_snapshot_id"] + ".json")))
        if snapshot.snapshot_hash != artifact["power_snapshot_hash"] or snapshot.through_week != week - 1:
            raise ExperimentalPowerUnavailable("EXPERIMENTAL_POWER_LINEAGE_MISMATCH")
        ratings = {row.team_id: row.power for row in snapshot.teams}
        games = []
        for row in artifact["projection_rows"]:
            margin = float(row["model_margin_home"])
            expected_margin = ratings[row["home_team"]] - ratings[row["away_team"]] + 1.5
            if not math.isfinite(margin) or abs(margin - expected_margin) > 1e-10:
                raise ExperimentalPowerUnavailable("EXPERIMENTAL_MARGIN_MISMATCH")
            games.append({
                "eventId": row["event_id"], "awayTeam": row["away_team"], "homeTeam": row["home_team"],
                "kickoffUtc": row["kickoff_utc"], "awayPower": row["away_power"], "homePower": row["home_power"],
                "homeExpectedMargin": margin, "homeFairSpread": -margin,
                "analysisType": "EXPERIMENTAL_POWER_ONLY", "personnelApproval": "NOT_EVALUATED",
                "productionEligible": False, "officialEligible": False,
            })
        return {
            "season": season, "week": week, "count": len(games), "games": games,
            "analysisType": "EXPERIMENTAL_POWER_ONLY", "projectionReadiness": "NOT_ACTIVE",
            "artifactId": artifact["artifact_id"], "artifactHash": artifact["artifact_hash"],
            "modelVersion": artifact["model_version"], "powerThroughWeek": snapshot.through_week,
            "scheduleVersion": artifact["schedule_version"], "scheduleHash": artifact["schedule_hash"],
            "personnelApproval": "NOT_EVALUATED",
            "probabilitiesComputed": False, "evComputed": False,
            "productionEligible": False, "officialEligible": False,
        }
    except ExperimentalPowerUnavailable:
        raise
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        raise ExperimentalPowerUnavailable("EXPERIMENTAL_BUNDLE_UNREADABLE_OR_INVALID") from exc