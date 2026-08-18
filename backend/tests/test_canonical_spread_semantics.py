from __future__ import annotations

import sys
from pathlib import Path


RESEARCH_DIR = Path(__file__).resolve().parents[1] / "research"
if str(RESEARCH_DIR) not in sys.path:
    sys.path.append(str(RESEARCH_DIR))

from canonical_spread import ats_result_for_side, normalize_from_away_spread_row  # noqa: E402



def test_home_spread_is_negative_away_spread():
    game = normalize_from_away_spread_row(
        away_team="AWY",
        home_team="HME",
        away_spread=-7.5,
        away_price=-110,
        home_price=-110,
        actual_away_score=24,
        actual_home_score=14,
    )

    assert game.away_spread == -7.5
    assert game.home_spread == 7.5
    assert game.home_spread + game.away_spread == 0.0



def test_ats_result_away_favorite():
    game = normalize_from_away_spread_row(
        away_team="AWY",
        home_team="HME",
        away_spread=-3.5,
        away_price=-110,
        home_price=-110,
        actual_away_score=27,
        actual_home_score=20,
    )

    assert ats_result_for_side(game, "away") == "win"
    assert ats_result_for_side(game, "home") == "loss"



def test_ats_result_home_favorite():
    game = normalize_from_away_spread_row(
        away_team="AWY",
        home_team="HME",
        away_spread=4.0,
        away_price=-110,
        home_price=-110,
        actual_away_score=10,
        actual_home_score=20,
    )

    assert ats_result_for_side(game, "home") == "win"
    assert ats_result_for_side(game, "away") == "loss"



def test_ats_result_away_underdog():
    game = normalize_from_away_spread_row(
        away_team="AWY",
        home_team="HME",
        away_spread=6.5,
        away_price=-110,
        home_price=-110,
        actual_away_score=17,
        actual_home_score=20,
    )

    assert ats_result_for_side(game, "away") == "win"
    assert ats_result_for_side(game, "home") == "loss"



def test_ats_result_home_underdog():
    game = normalize_from_away_spread_row(
        away_team="AWY",
        home_team="HME",
        away_spread=-6.5,
        away_price=-110,
        home_price=-110,
        actual_away_score=24,
        actual_home_score=21,
    )

    assert ats_result_for_side(game, "home") == "win"
    assert ats_result_for_side(game, "away") == "loss"



def test_integer_push_for_selected_side():
    game = normalize_from_away_spread_row(
        away_team="AWY",
        home_team="HME",
        away_spread=-3.0,
        away_price=-110,
        home_price=-110,
        actual_away_score=24,
        actual_home_score=21,
    )

    assert ats_result_for_side(game, "away") == "push"
    assert ats_result_for_side(game, "home") == "push"
