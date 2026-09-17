from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PowerTeamRating:
    team_id: str
    power: float


@dataclass(frozen=True)
class PowerSnapshot:
    snapshot_id: str
    snapshot_hash: str
    season: int
    through_week: int
    updater_version: str
    methodology_hash: str
    source_snapshot_id: str | None
    generated_at: str
    teams: tuple[PowerTeamRating, ...]


@dataclass(frozen=True)
class FinalGameResult:
    season: int
    week: int
    game_id: str
    kickoff_utc: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    source_result_version: str


@dataclass(frozen=True)
class PowerUpdateResult:
    game_id: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    actual_home_margin: float
    home_power_before: float
    away_power_before: float
    expected_home_margin: float
    raw_error: float
    clipped_error: float
    home_adjustment: float
    away_adjustment: float
    home_power_after: float
    away_power_after: float
    k: float
    cap: float
    game_shrink: float
    hfa: float
    updater_version: str
    methodology_hash: str


@dataclass(frozen=True)
class WeekUpdateResult:
    snapshot_after: PowerSnapshot
    updates: tuple[PowerUpdateResult, ...]


@dataclass(frozen=True)
class PowerUpdateLedgerRecord:
    update_id: str
    lineage_id: str
    snapshot_id_before: str
    snapshot_id_after: str
    season: int
    week: int
    game_id: str
    kickoff_utc: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    actual_home_margin: float
    home_power_before: float
    away_power_before: float
    expected_home_margin: float
    raw_error: float
    clipped_error: float
    k: float
    cap: float
    game_shrink: float
    hfa: float
    home_adjustment: float
    away_adjustment: float
    home_power_after: float
    away_power_after: float
    updater_version: str
    methodology_hash: str
    source_result_version: str
    generated_at: str
    idempotency_key: str
    payload_hash: str


@dataclass(frozen=True)
class PowerLineageRecord:
    lineage_id: str
    parent_lineage_id: str | None
    root_snapshot_id: str
    active_snapshot_id: str
    season: int
    through_week: int
    status: str
    created_at: str
    superseded_at: str | None
    superseded_by: str | None
