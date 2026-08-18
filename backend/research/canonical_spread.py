from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Side = Literal["home", "away"]
Result = Literal["win", "loss", "push"]


@dataclass(frozen=True)
class CanonicalGameSpread:
    away_team: str
    home_team: str
    away_spread: float
    home_spread: float
    away_price: float | None
    home_price: float | None
    actual_away_score: float
    actual_home_score: float

    @property
    def actual_away_margin(self) -> float:
        return self.actual_away_score - self.actual_home_score

    @property
    def actual_home_margin(self) -> float:
        return self.actual_home_score - self.actual_away_score



def normalize_from_away_spread_row(
    *,
    away_team: str,
    home_team: str,
    away_spread: float,
    away_price: float | None,
    home_price: float | None,
    actual_away_score: float,
    actual_home_score: float,
) -> CanonicalGameSpread:
    home_spread = -float(away_spread)

    game = CanonicalGameSpread(
        away_team=str(away_team),
        home_team=str(home_team),
        away_spread=float(away_spread),
        home_spread=home_spread,
        away_price=away_price,
        home_price=home_price,
        actual_away_score=float(actual_away_score),
        actual_home_score=float(actual_home_score),
    )

    # Canonical invariant used by all research scripts.
    assert abs((game.home_spread + game.away_spread)) < 1e-12
    return game



def spread_for_side(game: CanonicalGameSpread, side: Side) -> float:
    return game.home_spread if side == "home" else game.away_spread



def price_for_side(game: CanonicalGameSpread, side: Side) -> float | None:
    return game.home_price if side == "home" else game.away_price



def ats_result_for_side(game: CanonicalGameSpread, side: Side) -> Result:
    if side == "home":
        adjusted_margin = game.actual_home_score + game.home_spread - game.actual_away_score
    else:
        adjusted_margin = game.actual_away_score + game.away_spread - game.actual_home_score

    if adjusted_margin > 0:
        return "win"
    if adjusted_margin < 0:
        return "loss"
    return "push"
