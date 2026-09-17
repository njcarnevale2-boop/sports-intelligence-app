from __future__ import annotations

import hashlib
import json

from .contracts import PowerSnapshot, PowerUpdateResult
from .methodology import FrozenMethodology
from .validation import canonical_team_sort_key, validate_snapshot


def canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def methodology_identity_payload(methodology: FrozenMethodology, updater_version: str) -> dict:
    return {
        "methodology": methodology.to_identity_payload(),
        "updaterVersion": str(updater_version),
    }


def methodology_hash(methodology: FrozenMethodology, updater_version: str) -> str:
    return sha256_hex(canonical_json(methodology_identity_payload(methodology, updater_version)))


def snapshot_identity_payload(snapshot: PowerSnapshot) -> dict:
    validate_snapshot(snapshot)
    ordered = sorted(snapshot.teams, key=lambda t: canonical_team_sort_key(t.team_id))
    return {
        "season": int(snapshot.season),
        "throughWeek": int(snapshot.through_week),
        "updaterVersion": str(snapshot.updater_version),
        "methodologyHash": str(snapshot.methodology_hash),
        "sourceSnapshotId": snapshot.source_snapshot_id,
        "teams": [
            {
                "teamId": t.team_id,
                "power": float(t.power),
            }
            for t in ordered
        ],
    }


def snapshot_hash(snapshot: PowerSnapshot) -> str:
    return sha256_hex(canonical_json(snapshot_identity_payload(snapshot)))


def update_identity_payload(update: PowerUpdateResult) -> dict:
    return {
        "gameId": update.game_id,
        "homeTeam": update.home_team,
        "awayTeam": update.away_team,
        "homeScore": int(update.home_score),
        "awayScore": int(update.away_score),
        "actualHomeMargin": float(update.actual_home_margin),
        "homePowerBefore": float(update.home_power_before),
        "awayPowerBefore": float(update.away_power_before),
        "expectedHomeMargin": float(update.expected_home_margin),
        "rawError": float(update.raw_error),
        "clippedError": float(update.clipped_error),
        "homeAdjustment": float(update.home_adjustment),
        "awayAdjustment": float(update.away_adjustment),
        "homePowerAfter": float(update.home_power_after),
        "awayPowerAfter": float(update.away_power_after),
        "k": float(update.k),
        "cap": float(update.cap),
        "gameShrink": float(update.game_shrink),
        "hfa": float(update.hfa),
        "updaterVersion": update.updater_version,
        "methodologyHash": update.methodology_hash,
    }


def update_payload_hash(update: PowerUpdateResult) -> str:
    return sha256_hex(canonical_json(update_identity_payload(update)))
