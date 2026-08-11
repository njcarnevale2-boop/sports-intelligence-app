from pathlib import Path

import pandas as pd


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
_cached_lookup = {}


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


def build_market_intelligence_lookup():
    global _cached_lookup
    global _cached_modified_time

    if not LINE_MOVEMENT_BOARD.exists():
        _cached_lookup = {}
        _cached_modified_time = None
        return _cached_lookup

    try:
        modified_time = (
            LINE_MOVEMENT_BOARD
            .stat()
            .st_mtime
        )
    except OSError:
        return {}

    if (
        _cached_lookup
        and _cached_modified_time
        == modified_time
    ):
        return _cached_lookup

    try:
        df = pd.read_csv(
            LINE_MOVEMENT_BOARD
        )

    except (
        pd.errors.EmptyDataError,
        OSError,
    ):
        _cached_lookup = {}
        _cached_modified_time = (
            modified_time
        )

        return _cached_lookup

    if df.empty:
        _cached_lookup = {}
        _cached_modified_time = (
            modified_time
        )

        return _cached_lookup

    df = df.copy()

    df[
        "api_event_id"
    ] = (
        df[
            "api_event_id"
        ]
        .astype(str)
    )

    df[
        "normalized_market"
    ] = (
        df[
            "market"
        ]
        .apply(
            normalize_market
        )
    )

    df[
        "normalized_side"
    ] = (
        df[
            "side"
        ]
        .astype(str)
        .str.lower()
    )

    df[
        "supports_side"
    ] = df.apply(
        movement_supports_side,
        axis=1,
    )

    lookup = {}

    grouped = df.groupby(
        [
            "api_event_id",
            "normalized_market",
            "normalized_side",
        ],
        dropna=False,
        sort=False,
    )

    for (
        event_id,
        market,
        side,
    ), group in grouped:

        key = (
            str(event_id),
            str(market),
            str(side).lower(),
        )

        lookup[key] = (
            calculate_group_intelligence(
                group
            )
        )

    _cached_lookup = lookup

    _cached_modified_time = (
        modified_time
    )

    return _cached_lookup


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