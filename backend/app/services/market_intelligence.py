from pathlib import Path

import pandas as pd
import numpy as np


MODEL_ROOT = (
    Path.home()
    / "Downloads"
    / "NFL_Analytics_OS_v1_9"
)

LINE_MOVEMENT_BOARD = (
    MODEL_ROOT
    / "outputs"
    / "line_movement_board.csv"
)


_cached_modified_time = None
_cached_lookups = {}


def safe_float(value):
    if pd.isna(value):
        return None

    return float(value)


def american_implied_probability(odds):
    if odds is None:
        return None

    odds = float(odds)

    if odds == 0:
        return None

    if odds > 0:
        return 100 / (odds + 100)

    return abs(odds) / (
        abs(odds) + 100
    )


def normalize_market(market):
    market = str(market).lower()

    mapping = {
        "spread": "spreads",
        "spreads": "spreads",
        "total": "totals",
        "totals": "totals",
        "moneyline": "h2h",
        "h2h": "h2h",
    }

    return mapping.get(
        market,
        market,
    )


def empty_intelligence():
    return {
        "score": 0.0,
        "grade": "N/A",
        "signal": "Insufficient Market History",
        "booksTracked": 0,
        "booksMoving": 0,
        "steamBooks": 0,
        "supportingBooks": 0,
        "opposingBooks": 0,
        "consensus": 0.0,
        "largestPointMove": 0.0,
        "largestPriceMove": 0.0,
        "marketSupport": False,
        "snapshots": 0,
    }


def grade_score(score):
    if score >= 9:
        return "A+"

    if score >= 8:
        return "A"

    if score >= 7:
        return "B+"

    if score >= 6:
        return "B"

    if score >= 5:
        return "C+"

    if score >= 4:
        return "C"

    return "D"


def signal_label(
    score,
    consensus,
):
    if (
        score >= 8
        and consensus >= 70
    ):
        return "Strong Market Support"

    if (
        score >= 6
        and consensus >= 60
    ):
        return "Market Support"

    if consensus <= 35:
        return "Market Resistance"

    return "Mixed Market"


def movement_supports_side(row):
    market = normalize_market(
        row["market"]
    )

    side = str(
        row["side"]
    ).lower()

    point_move = safe_float(
        row["point_move"]
    )

    opening_price = safe_float(
        row["opening_price_observed"]
    )

    latest_price = safe_float(
        row["latest_price"]
    )

    if market == "spreads":
        if (
            point_move is None
            or point_move == 0
        ):
            return None

        return point_move < 0

    if market == "totals":
        if (
            point_move is None
            or point_move == 0
        ):
            return None

        if side == "over":
            return point_move > 0

        if side == "under":
            return point_move < 0

        return None

    if market == "h2h":
        opening_probability = (
            american_implied_probability(
                opening_price
            )
        )

        latest_probability = (
            american_implied_probability(
                latest_price
            )
        )

        if (
            opening_probability is None
            or latest_probability is None
        ):
            return None

        difference = (
            latest_probability
            - opening_probability
        )

        if abs(difference) < 0.001:
            return None

        return difference > 0

    return None


def _implied_probability_series(odds_series: pd.Series) -> pd.Series:
    odds = pd.to_numeric(odds_series, errors="coerce")
    output = pd.Series(np.nan, index=odds.index, dtype="float64")

    positive_mask = odds > 0
    negative_mask = odds < 0

    output.loc[positive_mask] = 100.0 / (odds.loc[positive_mask] + 100.0)
    output.loc[negative_mask] = odds.loc[negative_mask].abs() / (odds.loc[negative_mask].abs() + 100.0)
    return output


def _compute_supports_side(df: pd.DataFrame) -> pd.Series:
    supports = pd.Series([None] * len(df), index=df.index, dtype="object")

    market = df["normalized_market"]
    side = df["normalized_side"]
    point_move = df["point_move"]

    spread_mask = market.eq("spreads") & point_move.notna() & point_move.ne(0)
    supports.loc[spread_mask] = point_move.loc[spread_mask] < 0

    totals_base_mask = market.eq("totals") & point_move.notna() & point_move.ne(0)
    totals_over_mask = totals_base_mask & side.eq("over")
    totals_under_mask = totals_base_mask & side.eq("under")
    supports.loc[totals_over_mask] = point_move.loc[totals_over_mask] > 0
    supports.loc[totals_under_mask] = point_move.loc[totals_under_mask] < 0

    h2h_mask = market.eq("h2h")
    if h2h_mask.any():
        opening_probability = _implied_probability_series(df["opening_price_observed"])
        latest_probability = _implied_probability_series(df["latest_price"])
        difference = latest_probability - opening_probability
        valid_h2h = h2h_mask & difference.notna() & difference.abs().ge(0.001)
        supports.loc[valid_h2h] = difference.loc[valid_h2h] > 0

    return supports


def calculate_group_intelligence(group):
    books_tracked = int(
        group[
            "sportsbook"
        ].nunique()
    )

    moving_rows = group[
        (
            group[
                "point_move"
            ]
            .fillna(0)
            .abs()
            > 0
        )
        | (
            group[
                "price_move"
            ]
            .fillna(0)
            .abs()
            > 0
        )
    ]

    books_moving = int(
        moving_rows[
            "sportsbook"
        ].nunique()
    )

    steam_rows = group[
        group[
            "steam_flag"
        ]
        == True
    ]

    steam_books = int(
        steam_rows[
            "sportsbook"
        ].nunique()
    )

    supporting_rows = group[
        group[
            "supports_side"
        ]
        == True
    ]

    opposing_rows = group[
        group[
            "supports_side"
        ]
        == False
    ]

    supporting_books = int(
        supporting_rows[
            "sportsbook"
        ].nunique()
    )

    opposing_books = int(
        opposing_rows[
            "sportsbook"
        ].nunique()
    )

    directional_books = (
        supporting_books
        + opposing_books
    )

    consensus = (
        (
            supporting_books
            / directional_books
        )
        * 100
        if directional_books > 0
        else 50.0
    )

    point_moves = (
        group[
            "point_move"
        ]
        .dropna()
        .abs()
        .tolist()
    )

    largest_point_move = (
        max(point_moves)
        if point_moves
        else 0.0
    )

    price_moves = (
        group[
            "price_move"
        ]
        .dropna()
        .abs()
        .tolist()
    )

    largest_price_move = (
        max(price_moves)
        if price_moves
        else 0.0
    )

    snapshots = int(
        group[
            "snapshots"
        ]
        .fillna(0)
        .max()
    )

    score = 0.0

    # Consensus — max 3
    if consensus >= 90:
        score += 3.0

    elif consensus >= 75:
        score += 2.5

    elif consensus >= 65:
        score += 2.0

    elif consensus >= 55:
        score += 1.0

    # Steam participation — max 2.5
    if books_tracked > 0:
        steam_ratio = (
            steam_books
            / books_tracked
        )

        score += min(
            steam_ratio * 2.5,
            2.5,
        )

    # Books moving — max 2
    if books_tracked > 0:
        movement_ratio = (
            books_moving
            / books_tracked
        )

        score += min(
            movement_ratio * 2.0,
            2.0,
        )

    # Largest point move — max 1.5
    score += min(
        largest_point_move / 2.0,
        1.5,
    )

    # Snapshot depth — max 1
    if snapshots >= 5:
        score += 1.0

    elif snapshots >= 3:
        score += 0.7

    elif snapshots >= 2:
        score += 0.4

    score = round(
        min(score, 10.0),
        1,
    )

    market_support = (
        consensus >= 60
        and supporting_books > 0
    )

    return {
        "score": score,

        "grade": grade_score(
            score
        ),

        "signal": signal_label(
            score,
            consensus,
        ),

        "booksTracked": books_tracked,

        "booksMoving": books_moving,

        "steamBooks": steam_books,

        "supportingBooks": (
            supporting_books
        ),

        "opposingBooks": (
            opposing_books
        ),

        "consensus": round(
            consensus,
            1,
        ),

        "largestPointMove": round(
            largest_point_move,
            1,
        ),

        "largestPriceMove": round(
            largest_price_move,
            1,
        ),

        "marketSupport": (
            market_support
        ),

        "snapshots": snapshots,
    }


def build_market_intelligence_lookup(event_ids=None):
    global _cached_lookups
    global _cached_modified_time

    if not LINE_MOVEMENT_BOARD.exists():
        _cached_lookups = {}
        _cached_modified_time = None
        return {}

    try:
        modified_time = LINE_MOVEMENT_BOARD.stat().st_mtime
    except OSError:
        return {}

    normalized_ids = None
    if event_ids is not None:
        normalized_ids = tuple(sorted(str(event_id) for event_id in event_ids if str(event_id).strip()))
    if _cached_modified_time != modified_time:
        _cached_lookups = {}
        _cached_modified_time = modified_time

    cache_key = normalized_ids

    cached_lookup = _cached_lookups.get(cache_key)
    if cached_lookup is not None:
        return cached_lookup

    try:
        df = pd.read_csv(LINE_MOVEMENT_BOARD)
    except (pd.errors.EmptyDataError, OSError):
        _cached_lookups[cache_key] = {}
        return {}

    if df.empty:
        _cached_lookups[cache_key] = {}
        return {}

    df = df.copy()
    df["api_event_id"] = df["api_event_id"].astype(str)
    if normalized_ids is not None:
        df = df[df["api_event_id"].isin(normalized_ids)]
    if df.empty:
        _cached_lookups[cache_key] = {}
        return {}

    df["normalized_market"] = df["market"].apply(normalize_market)
    df["normalized_side"] = df["side"].astype(str).str.lower()
    df["point_move"] = pd.to_numeric(df["point_move"], errors="coerce")
    df["price_move"] = pd.to_numeric(df["price_move"], errors="coerce")
    df["snapshots"] = pd.to_numeric(df["snapshots"], errors="coerce")
    df["steam_flag"] = df["steam_flag"].fillna(False) == True
    df["supports_side"] = _compute_supports_side(df)

    lookup = {}
    grouped = df.groupby(["api_event_id", "normalized_market", "normalized_side"], dropna=False, sort=False)
    for (event_id, market, side), group in grouped:
        lookup[(str(event_id), str(market), str(side).lower())] = calculate_group_intelligence(group)

    _cached_lookups[cache_key] = lookup
    return lookup


def get_market_intelligence(
    event_id,
    market,
    side,
):
    lookup = (
        build_market_intelligence_lookup()
    )

    key = (
        str(event_id),
        normalize_market(market),
        str(side).lower(),
    )

    return lookup.get(
        key,
        empty_intelligence(),
    )