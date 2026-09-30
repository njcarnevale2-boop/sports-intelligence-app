from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from .contracts import PowerSnapshot, PowerTeamRating
from .hashing import canonical_json, sha256_hex, snapshot_hash
from .methodology import UPDATER_VERSION
from .validation import CANONICAL_NFL_TEAMS, validate_snapshot


PRESEASON_METHODOLOGY_VERSION = "sia_power_preseason_init_v2_regression_family"


@dataclass(frozen=True)
class PreseasonRegressionMethodology:
    target_season: int
    source_season: int
    source_snapshot_id: str
    source_snapshot_hash: str
    regression_factor: float
    methodology_version: str = PRESEASON_METHODOLOGY_VERSION

    def identity_payload(self) -> dict[str, object]:
        return {
            "methodologyVersion": str(self.methodology_version),
            "kind": "REGRESSION_TO_MEAN",
            "targetSeason": int(self.target_season),
            "sourceSeason": int(self.source_season),
            "sourceSnapshotId": str(self.source_snapshot_id),
            "sourceSnapshotHash": str(self.source_snapshot_hash),
            "regressionFactor": float(self.regression_factor),
        }

    def methodology_hash(self) -> str:
        return sha256_hex(canonical_json(self.identity_payload()))


def _require_positive_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _require_non_empty_str(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _require_iso_timestamp(value: str, field_name: str) -> str:
    text = _require_non_empty_str(value, field_name)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO timestamp") from exc
    return text


def _require_regression_factor(value: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("regression_factor must be numeric") from exc
    if numeric < 0.0 or numeric > 1.0:
        raise ValueError("regression_factor must be between 0.0 and 1.0")
    return numeric


def _validate_prior_terminal(prior_terminal_team_powers: Mapping[str, float]) -> dict[str, float]:
    if not isinstance(prior_terminal_team_powers, Mapping):
        raise ValueError("prior_terminal_team_powers must be a mapping")

    missing = [team for team in CANONICAL_NFL_TEAMS if team not in prior_terminal_team_powers]
    extra = [team for team in prior_terminal_team_powers.keys() if team not in CANONICAL_NFL_TEAMS]
    if missing or extra:
        raise ValueError(f"Team set mismatch in prior terminal powers: missing={sorted(missing)} extra={sorted(extra)}")

    normalized: dict[str, float] = {}
    for team in CANONICAL_NFL_TEAMS:
        value = prior_terminal_team_powers[team]
        try:
            normalized[team] = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid prior terminal power for team {team}") from exc
    return normalized


def build_preseason_regressed_root_snapshot(
    *,
    prior_terminal_team_powers: Mapping[str, float],
    target_season: int,
    source_season: int,
    source_snapshot_id: str,
    source_snapshot_hash: str,
    regression_factor: float,
    generated_at: str,
    updater_version: str = UPDATER_VERSION,
    methodology_version: str = PRESEASON_METHODOLOGY_VERSION,
) -> PowerSnapshot:
    normalized = _validate_prior_terminal(prior_terminal_team_powers)
    target_season_value = _require_positive_int(target_season, "target_season")
    source_season_value = _require_positive_int(source_season, "source_season")
    source_snapshot_id_value = _require_non_empty_str(source_snapshot_id, "source_snapshot_id")
    source_snapshot_hash_value = _require_non_empty_str(source_snapshot_hash, "source_snapshot_hash")
    generated_at_value = _require_iso_timestamp(generated_at, "generated_at")
    updater_version_value = _require_non_empty_str(updater_version, "updater_version")
    regression_factor_value = _require_regression_factor(regression_factor)

    league_mean = sum(normalized.values()) / float(len(CANONICAL_NFL_TEAMS))
    teams = tuple(
        PowerTeamRating(
            team_id=team,
            power=league_mean + (regression_factor_value * (normalized[team] - league_mean)),
        )
        for team in CANONICAL_NFL_TEAMS
    )

    methodology = PreseasonRegressionMethodology(
        target_season=target_season_value,
        source_season=source_season_value,
        source_snapshot_id=source_snapshot_id_value,
        source_snapshot_hash=source_snapshot_hash_value,
        regression_factor=regression_factor_value,
        methodology_version=methodology_version,
    )
    methodology_hash_value = methodology.methodology_hash()

    provisional = PowerSnapshot(
        snapshot_id="",
        snapshot_hash="",
        season=target_season_value,
        through_week=0,
        updater_version=updater_version_value,
        methodology_hash=methodology_hash_value,
        source_snapshot_id=source_snapshot_id_value,
        generated_at=generated_at_value,
        teams=teams,
    )
    provisional_hash = snapshot_hash(provisional)
    snapshot_id = f"power-root-{target_season_value}-v2-{provisional_hash[:12]}"

    snapshot = PowerSnapshot(
        snapshot_id=snapshot_id,
        snapshot_hash="",
        season=provisional.season,
        through_week=provisional.through_week,
        updater_version=provisional.updater_version,
        methodology_hash=provisional.methodology_hash,
        source_snapshot_id=provisional.source_snapshot_id,
        generated_at=provisional.generated_at,
        teams=provisional.teams,
    )
    final_hash = snapshot_hash(snapshot)
    snapshot_with_hash = PowerSnapshot(
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=final_hash,
        season=snapshot.season,
        through_week=snapshot.through_week,
        updater_version=snapshot.updater_version,
        methodology_hash=snapshot.methodology_hash,
        source_snapshot_id=snapshot.source_snapshot_id,
        generated_at=snapshot.generated_at,
        teams=snapshot.teams,
    )
    validate_snapshot(snapshot_with_hash)
    return snapshot_with_hash