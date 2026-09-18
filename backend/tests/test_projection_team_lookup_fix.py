from __future__ import annotations

import pandas as pd
import pytest

from app.services.power_engine.projection import (
    ProjectionLookupError,
    build_canonical_power_lookup,
    model_margin_home,
    resolve_team_power,
)
from app.services.power_engine.projection_generation import generate_projection_rows


def test_la_ratings_lar_market_resolves():
    ratings = pd.DataFrame(
        [
            {"team": "LA", "power_points": 3.158564291265},
            {"team": "SF", "power_points": -2.508807900018},
        ]
    )
    rp = build_canonical_power_lookup(ratings.to_dict(orient="records"))

    home_team, home_power = resolve_team_power(raw_team="LAR", power_lookup=rp, side="home", context_id="evt")
    away_team, away_power = resolve_team_power(raw_team="SF", power_lookup=rp, side="away", context_id="evt")

    assert home_team == "LAR"
    assert away_team == "SF"
    assert home_power == pytest.approx(3.158564291265)
    assert away_power == pytest.approx(-2.508807900018)


def test_lar_ratings_la_alias_resolves_when_supported():
    ratings = pd.DataFrame(
        [
            {"team": "LAR", "power_points": 3.158564291265},
        ]
    )
    rp = build_canonical_power_lookup(ratings.to_dict(orient="records"))

    normalized_team, power = resolve_team_power(raw_team="LA", power_lookup=rp, side="away", context_id="evt")

    assert normalized_team == "LAR"
    assert power == pytest.approx(3.158564291265)


def test_unknown_team_identifier_fails_closed():
    ratings = pd.DataFrame([{"team": "SEA", "power_points": 1.2}])
    rp = build_canonical_power_lookup(ratings.to_dict(orient="records"))

    with pytest.raises(ProjectionLookupError, match="Unknown team identifier: raw_team='XYZ'"):
        resolve_team_power(raw_team="XYZ", power_lookup=rp, side="home", context_id="evt-1")


def test_missing_known_team_rating_fails_closed():
    ratings = pd.DataFrame([{"team": "SEA", "power_points": 1.2}])
    rp = build_canonical_power_lookup(ratings.to_dict(orient="records"))

    with pytest.raises(ProjectionLookupError, match="raw_team='LAR'.*canonical_team='LAR'"):
        resolve_team_power(raw_team="LAR", power_lookup=rp, side="away", context_id="evt-2")


def test_no_implicit_zero_fallback_on_missing_lookup():
    ratings = pd.DataFrame([{"team": "NE", "power_points": 2.0}])
    rp = build_canonical_power_lookup(ratings.to_dict(orient="records"))

    with pytest.raises(ProjectionLookupError):
        resolve_team_power(raw_team="NYJ", power_lookup=rp, side="away", context_id="evt-3")


def test_projection_algebra_is_unchanged():
    ratings = pd.DataFrame(
        [
            {"team": "LA", "power_points": 3.158564291265},
            {"team": "NYG", "power_points": 2.149469924477},
        ]
    )
    rp = build_canonical_power_lookup(ratings.to_dict(orient="records"))

    home_team, home_power = resolve_team_power(raw_team="LAR", power_lookup=rp, side="home", context_id="evt-4")
    away_team, away_power = resolve_team_power(raw_team="NYG", power_lookup=rp, side="away", context_id="evt-4")
    projected_margin = model_margin_home(home_power=home_power, away_power=away_power)

    assert home_team == "LAR"
    assert away_team == "NYG"
    assert projected_margin == pytest.approx(2.509094366788)


def test_32_canonical_teams_can_be_represented_without_collision():
    canonical = [
        "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB",
        "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
        "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
    ]
    ratings = pd.DataFrame(
        [{"team": t, "power_points": float(i)} for i, t in enumerate(canonical)]
    )
    rp = build_canonical_power_lookup(ratings.to_dict(orient="records"))

    assert len(rp) == 32
    assert sorted(rp.keys()) == sorted(canonical)


def test_generation_path_normalizes_la_to_lar_and_computes_margin():
    ratings = [
        {"team": "LA", "power_points": 3.158564291265},
        {"team": "NYG", "power_points": 2.149469924477},
    ]
    games = [{"api_event_id": "evt-gen-1", "away_team": "NYG", "home_team": "LAR"}]

    rows = generate_projection_rows(ratings_records=ratings, games=games)

    assert len(rows) == 1
    assert rows[0]["home_team"] == "LAR"
    assert rows[0]["away_team"] == "NYG"
    assert rows[0]["home_power"] == pytest.approx(3.158564291265)
    assert rows[0]["away_power"] == pytest.approx(2.149469924477)
    assert rows[0]["model_margin_home"] == pytest.approx(2.509094366788)


def test_generation_fails_closed_on_unsupported_raw_team_identifier():
    ratings = [{"team": "SEA", "power_points": 1.2}]
    games = [{"api_event_id": "evt-gen-2", "away_team": "XYZ", "home_team": "SEA"}]

    with pytest.raises(ProjectionLookupError, match="Unknown team identifier: raw_team='XYZ'"):
        generate_projection_rows(ratings_records=ratings, games=games)


def test_generation_fails_closed_when_known_team_missing_from_ratings():
    ratings = [{"team": "SEA", "power_points": 1.2}]
    games = [{"api_event_id": "evt-gen-3", "away_team": "SEA", "home_team": "LAR"}]

    with pytest.raises(ProjectionLookupError, match="raw_team='LAR'.*canonical_team='LAR'"):
        generate_projection_rows(ratings_records=ratings, games=games)


def test_generation_fails_closed_on_duplicate_canonical_collision():
    ratings = [
        {"team": "LA", "power_points": 3.0},
        {"team": "LAR", "power_points": 4.0},
    ]
    games = [{"api_event_id": "evt-gen-4", "away_team": "SEA", "home_team": "LAR"}]

    with pytest.raises(ProjectionLookupError, match="Conflicting ratings for canonical team LAR"):
        generate_projection_rows(ratings_records=ratings, games=games)


def test_generation_no_implicit_zero_rating_fallback():
    ratings = [{"team": "NE", "power_points": 2.0}]
    games = [{"api_event_id": "evt-gen-5", "away_team": "NYJ", "home_team": "NE"}]

    with pytest.raises(ProjectionLookupError):
        generate_projection_rows(ratings_records=ratings, games=games)


def test_generation_stops_on_missing_rating_before_emitting_projection():
    ratings = [
        {"team": "SEA", "power_points": 1.2},
        {"team": "SF", "power_points": 1.0},
    ]
    games = [
        {"api_event_id": "evt-gen-6", "away_team": "SF", "home_team": "SEA"},
        {"api_event_id": "evt-gen-7", "away_team": "SEA", "home_team": "LAR"},
    ]

    with pytest.raises(ProjectionLookupError, match="context_id='evt-gen-7'"):
        generate_projection_rows(ratings_records=ratings, games=games)
