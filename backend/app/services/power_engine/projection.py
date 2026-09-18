from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.services.result_engine.teams import normalize_team_id


class ProjectionLookupError(ValueError):
    pass


def _normalize_or_raise(raw_team: Any) -> str:
    try:
        return normalize_team_id(raw_team)
    except ValueError as exc:
        raise ProjectionLookupError(f"Unknown team identifier: raw_team={raw_team!r}") from exc


def build_canonical_power_lookup(
    records: Iterable[Mapping[str, Any]],
    *,
    team_field: str = "team",
    rating_field: str = "power_points",
) -> dict[str, float]:
    lookup: dict[str, float] = {}

    for record in records:
        if not isinstance(record, Mapping):
            raise ProjectionLookupError("Power record must be a mapping")

        raw_team = record.get(team_field)
        canonical_team = _normalize_or_raise(raw_team)

        try:
            power_value = float(record.get(rating_field))
        except (TypeError, ValueError) as exc:
            raise ProjectionLookupError(
                f"Invalid rating value for team: raw_team={raw_team!r} field={rating_field}"
            ) from exc

        existing = lookup.get(canonical_team)
        if existing is not None and abs(existing - power_value) > 1e-12:
            raise ProjectionLookupError(
                "Conflicting ratings for canonical team "
                f"{canonical_team}: existing={existing} incoming={power_value}"
            )
        lookup[canonical_team] = power_value

    return lookup


def resolve_team_power(
    *,
    raw_team: Any,
    power_lookup: Mapping[str, float],
    side: str,
    context_id: str,
) -> tuple[str, float]:
    canonical_team = _normalize_or_raise(raw_team)

    if canonical_team not in power_lookup:
        raise ProjectionLookupError(
            "Missing team rating for projection lookup: "
            f"context_id={context_id!r} side={side!r} raw_team={raw_team!r} canonical_team={canonical_team!r}"
        )

    return canonical_team, float(power_lookup[canonical_team])


def model_margin_home(*, home_power: float, away_power: float, hfa: float = 1.5) -> float:
    return float(home_power) - float(away_power) + float(hfa)
