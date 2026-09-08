from __future__ import annotations

from typing import Any

import pandas as pd


EXCLUDED_CURRENT_MARKET_SPORTSBOOKS = frozenset({"lowvig", "lowvigag"})


def normalize_current_market_sportsbook(value: Any) -> str:
    text = str(value or "").strip().lower()
    return "".join(character for character in text if character.isalnum())


def is_current_market_sportsbook_allowed(value: Any) -> bool:
    normalized = normalize_current_market_sportsbook(value)
    if not normalized:
        return True
    return normalized not in EXCLUDED_CURRENT_MARKET_SPORTSBOOKS


def filter_current_market_sportsbook_rows(df: pd.DataFrame, column: str = "sportsbook") -> pd.DataFrame:
    if df.empty or column not in df.columns:
        return df.copy()

    allowed = df[column].map(is_current_market_sportsbook_allowed)
    return df.loc[allowed].copy()