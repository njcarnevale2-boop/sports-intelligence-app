from __future__ import annotations

from dataclasses import replace

from .contracts import (
    FinalGameResult,
    PowerSnapshot,
    PowerTeamRating,
    PowerUpdateResult,
    WeekUpdateResult,
)
from .hashing import methodology_hash, snapshot_hash
from .methodology import FROZEN_METHODOLOGY, FrozenMethodology, UPDATER_VERSION
from .validation import (
    canonical_team_sort_key,
    parse_kickoff_utc,
    validate_final_result,
    validate_snapshot,
)


def apply_single_game_update(
    *,
    home_power_before: float,
    away_power_before: float,
    result: FinalGameResult,
    methodology: FrozenMethodology = FROZEN_METHODOLOGY,
    updater_version: str = UPDATER_VERSION,
    methodology_hash_value: str | None = None,
) -> PowerUpdateResult:
    validate_final_result(result)

    hfa = float(methodology.hfa)
    k = float(methodology.k)
    cap = float(methodology.error_cap)
    game_shrink = float(methodology.game_shrink)
    mh = methodology_hash_value or methodology_hash(methodology, updater_version)

    expected_home_margin = float(home_power_before) - float(away_power_before) + hfa
    actual_home_margin = float(result.home_score - result.away_score)
    raw_error = actual_home_margin - expected_home_margin
    clipped_error = max(-cap, min(cap, raw_error))

    home_adjustment = k * clipped_error
    away_adjustment = -home_adjustment

    home_power_after = (float(home_power_before) + home_adjustment) * game_shrink
    away_power_after = (float(away_power_before) + away_adjustment) * game_shrink

    return PowerUpdateResult(
        game_id=result.game_id,
        home_team=result.home_team,
        away_team=result.away_team,
        home_score=result.home_score,
        away_score=result.away_score,
        actual_home_margin=actual_home_margin,
        home_power_before=float(home_power_before),
        away_power_before=float(away_power_before),
        expected_home_margin=expected_home_margin,
        raw_error=raw_error,
        clipped_error=clipped_error,
        home_adjustment=home_adjustment,
        away_adjustment=away_adjustment,
        home_power_after=home_power_after,
        away_power_after=away_power_after,
        k=k,
        cap=cap,
        game_shrink=game_shrink,
        hfa=hfa,
        updater_version=updater_version,
        methodology_hash=mh,
    )


def _sorted_results(results: tuple[FinalGameResult, ...]) -> tuple[FinalGameResult, ...]:
    return tuple(
        sorted(
            results,
            key=lambda r: (parse_kickoff_utc(r.kickoff_utc), r.game_id),
        )
    )


def apply_week_results(
    *,
    snapshot: PowerSnapshot,
    results: tuple[FinalGameResult, ...],
    generated_at: str,
    updater_version: str = UPDATER_VERSION,
    methodology: FrozenMethodology = FROZEN_METHODOLOGY,
) -> WeekUpdateResult:
    validate_snapshot(snapshot)
    if not results:
        raise ValueError("At least one final game result is required")

    for result in results:
        validate_final_result(result)

    ordered = _sorted_results(results)

    season_values = {r.season for r in ordered}
    week_values = {r.week for r in ordered}
    if len(season_values) != 1 or len(week_values) != 1:
        raise ValueError("All results must belong to one season and one completed week")
    if next(iter(season_values)) != snapshot.season:
        raise ValueError("Result season must match snapshot season")
    if next(iter(week_values)) <= snapshot.through_week:
        raise ValueError("Result week must be greater than snapshot through_week")

    seen_game_ids: set[str] = set()
    seen_teams: set[str] = set()
    for result in ordered:
        if result.game_id in seen_game_ids:
            raise ValueError(f"Duplicate game_id in results: {result.game_id}")
        seen_game_ids.add(result.game_id)

        if result.home_team in seen_teams or result.away_team in seen_teams:
            raise ValueError(
                f"Duplicate team appearance in week results: {result.home_team} vs {result.away_team}"
            )
        seen_teams.add(result.home_team)
        seen_teams.add(result.away_team)

    powers = {team.team_id: float(team.power) for team in snapshot.teams}
    updates: list[PowerUpdateResult] = []
    mh = methodology_hash(methodology, updater_version)

    for result in ordered:
        if result.home_team not in powers or result.away_team not in powers:
            raise ValueError(f"Result contains unknown team not in snapshot: {result.game_id}")

        update = apply_single_game_update(
            home_power_before=powers[result.home_team],
            away_power_before=powers[result.away_team],
            result=result,
            methodology=methodology,
            updater_version=updater_version,
            methodology_hash_value=mh,
        )

        powers[result.home_team] = update.home_power_after
        powers[result.away_team] = update.away_power_after
        updates.append(update)

    ordered_teams = tuple(
        PowerTeamRating(team_id=team_id, power=powers[team_id])
        for team_id in sorted(powers.keys(), key=canonical_team_sort_key)
    )

    # Snapshot hash intentionally excludes generated_at and snapshot_id for content identity.
    provisional = PowerSnapshot(
        snapshot_id="",
        snapshot_hash="",
        season=snapshot.season,
        through_week=next(iter(week_values)),
        updater_version=updater_version,
        methodology_hash=mh,
        source_snapshot_id=snapshot.snapshot_id,
        generated_at=generated_at,
        teams=ordered_teams,
    )

    new_hash = snapshot_hash(provisional)
    new_snapshot = replace(
        provisional,
        snapshot_id=f"power-{provisional.season}-wk{provisional.through_week}-{new_hash[:12]}",
        snapshot_hash=new_hash,
    )

    return WeekUpdateResult(
        snapshot_after=new_snapshot,
        updates=tuple(updates),
    )
