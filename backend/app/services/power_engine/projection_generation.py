from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .projection import (
    ProjectionLookupError,
    build_canonical_power_lookup,
    model_margin_home,
    resolve_team_power,
)


def generate_projection_rows(
    *,
    ratings_records: Iterable[Mapping[str, Any]],
    games: Iterable[Mapping[str, Any]],
    team_field: str = "team",
    rating_field: str = "power_points",
    event_id_field: str = "api_event_id",
    away_team_field: str = "away_team",
    home_team_field: str = "home_team",
    hfa: float = 1.5,
) -> list[dict[str, Any]]:
    """Generate projection rows from in-memory ratings and game inputs.

    This function is orchestration-only: canonicalization, fail-closed lookups,
    and margin algebra are delegated to power_engine.projection.
    """

    power_lookup = build_canonical_power_lookup(
        ratings_records,
        team_field=team_field,
        rating_field=rating_field,
    )

    out: list[dict[str, Any]] = []
    for idx, game in enumerate(games):
        if not isinstance(game, Mapping):
            raise ProjectionLookupError("Game record must be a mapping")

        context_raw = game.get(event_id_field)
        context_id = str(context_raw) if context_raw not in (None, "") else f"row-{idx}"

        away_team, away_power = resolve_team_power(
            raw_team=game.get(away_team_field),
            power_lookup=power_lookup,
            side="away",
            context_id=context_id,
        )
        home_team, home_power = resolve_team_power(
            raw_team=game.get(home_team_field),
            power_lookup=power_lookup,
            side="home",
            context_id=context_id,
        )

        row = dict(game)
        row[away_team_field] = away_team
        row[home_team_field] = home_team
        row["away_power"] = away_power
        row["home_power"] = home_power
        row["model_margin_home"] = model_margin_home(
            home_power=home_power,
            away_power=away_power,
            hfa=hfa,
        )
        out.append(row)

    return out
