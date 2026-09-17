from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import AcceptedFinalGameResult
from .identity import CanonicalEventIdentity
from .validation import ResultEngineValidationError, validate_accepted_result


@dataclass(frozen=True)
class WeekCompletenessResult:
    season: int
    week: int
    expected_count: int
    accepted_count: int
    missing_event_keys: tuple[str, ...]
    duplicate_event_keys: tuple[str, ...]
    unexpected_event_keys: tuple[str, ...]
    identity_mismatch_event_keys: tuple[str, ...]
    duplicate_team_appearances: tuple[str, ...]
    is_complete: bool


def validate_week_completeness(
    *,
    season: int,
    week: int,
    expected_events: Iterable[CanonicalEventIdentity],
    accepted_results: Iterable[AcceptedFinalGameResult],
    allow_zero_game_week: bool = False,
) -> WeekCompletenessResult:
    expected = list(expected_events)
    accepted = list(accepted_results)

    expected_keys: list[str] = []
    expected_by_key: dict[str, CanonicalEventIdentity] = {}
    expected_team_appearances: dict[str, int] = {}
    for event in expected:
        if event.season != season or event.week != week:
            raise ResultEngineValidationError("Expected events must all match the requested season/week")
        expected_keys.append(event.canonical_event_key)
        if event.canonical_event_key in expected_by_key:
            # Continue collecting; duplicate handling remains fail-closed in result payload.
            pass
        expected_by_key[event.canonical_event_key] = event
        expected_team_appearances[event.away_team] = expected_team_appearances.get(event.away_team, 0) + 1
        expected_team_appearances[event.home_team] = expected_team_appearances.get(event.home_team, 0) + 1

    duplicate_expected = sorted({k for k in expected_keys if expected_keys.count(k) > 1})

    accepted_keys: list[str] = []
    accepted_team_appearances: dict[str, int] = {}
    identity_mismatch_keys: set[str] = set()
    for result in accepted:
        validate_accepted_result(result)
        if result.season != season or result.week != week:
            raise ResultEngineValidationError("Accepted results must all match the requested season/week")
        accepted_keys.append(result.canonical_event_key)
        expected_identity = expected_by_key.get(result.canonical_event_key)
        if expected_identity is not None:
            if (
                expected_identity.away_team != result.away_team
                or expected_identity.home_team != result.home_team
                or expected_identity.kickoff_utc != result.kickoff_utc
            ):
                identity_mismatch_keys.add(result.canonical_event_key)
        accepted_team_appearances[result.away_team] = accepted_team_appearances.get(result.away_team, 0) + 1
        accepted_team_appearances[result.home_team] = accepted_team_appearances.get(result.home_team, 0) + 1

    duplicate_accepted = sorted({k for k in accepted_keys if accepted_keys.count(k) > 1})
    expected_key_set = set(expected_keys)
    accepted_key_set = set(accepted_keys)

    missing = sorted(expected_key_set - accepted_key_set)
    unexpected = sorted(accepted_key_set - expected_key_set)
    duplicate_expected_teams = {team for team, count in expected_team_appearances.items() if count > 1}
    duplicate_accepted_teams = {team for team, count in accepted_team_appearances.items() if count > 1}
    duplicate_teams = sorted(duplicate_expected_teams | duplicate_accepted_teams)

    is_complete = (
        (allow_zero_game_week or len(expected_keys) > 0)
        and
        len(duplicate_expected) == 0
        and len(duplicate_accepted) == 0
        and len(missing) == 0
        and len(unexpected) == 0
        and len(identity_mismatch_keys) == 0
        and len(duplicate_teams) == 0
        and len(expected_keys) == len(expected_key_set)
        and len(accepted_keys) == len(expected_key_set)
    )

    return WeekCompletenessResult(
        season=season,
        week=week,
        expected_count=len(expected_keys),
        accepted_count=len(accepted_keys),
        missing_event_keys=tuple(missing),
        duplicate_event_keys=tuple(sorted(set(duplicate_expected + duplicate_accepted))),
        unexpected_event_keys=tuple(unexpected),
        identity_mismatch_event_keys=tuple(sorted(identity_mismatch_keys)),
        duplicate_team_appearances=tuple(duplicate_teams),
        is_complete=is_complete,
    )
