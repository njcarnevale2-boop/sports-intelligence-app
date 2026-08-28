"""
Closing line capture and Closing Line Value (CLV) calculation.

Closing line = the final valid odds snapshot captured at least
CLOSING_LINE_CUTOFF_MINUTES (default 2) before scheduled kickoff.
Post-kickoff snapshots are never used.

CLV formulas by market
──────────────────────
SPREAD (away +7 → close +5.5): clv_points = rec_point − close_point = +1.5
SPREAD (home −7 → close −5.5): clv_points = rec_point − close_point = −1.5 (worse)
TOTAL OVER  (rec 47 → close 48.5): clv_points = close_point − rec_point = +1.5
TOTAL UNDER (rec 48.5 → close 47): clv_points = rec_point − close_point = +1.5
MONEYLINE: clv_probability = close_implied − rec_implied; clv_percent = × 100
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from app.runtime_paths import runtime_paths

_DB_PATH = runtime_paths.nfl_model_duckdb

_CUTOFF_MINUTES = int(os.getenv("CLOSING_LINE_CUTOFF_MINUTES", "2"))


# ── helpers ─────────────────────────────────────────────────────────────────

def _american_to_implied(price: float) -> float:
    if price >= 0:
        return 100.0 / (price + 100.0)
    return abs(price) / (abs(price) + 100.0)


def _open_db(read_only: bool = True):
    import duckdb  # type: ignore
    return duckdb.connect(str(_DB_PATH), read_only=read_only)


# ── result types ─────────────────────────────────────────────────────────────

@dataclass
class ClosingLineResult:
    event_id: str
    bookmaker_key: str
    market: str         # spreads | totals | h2h
    side: str           # home | away | over | under
    opening_point: Optional[float] = None
    opening_price: Optional[float] = None
    closing_point: Optional[float] = None
    closing_price: Optional[float] = None
    closing_timestamp: Optional[datetime] = None
    closing_status: str = "NOT_CAPTURED"   # AVAILABLE | NOT_CAPTURED | PENDING


@dataclass
class CLVResult:
    event_id: str
    bookmaker_key: str
    market: str
    side: str
    recommended_point: Optional[float]
    recommended_price: Optional[float]
    closing_point: Optional[float]
    closing_price: Optional[float]
    # Spread / total
    clv_points: Optional[float] = None
    # Moneyline
    clv_probability: Optional[float] = None
    clv_percent: Optional[float] = None
    closing_status: str = "NOT_CAPTURED"


# ── public API ───────────────────────────────────────────────────────────────

def get_closing_line(
    event_id: str,
    bookmaker_key: str,
    market_key: str,
    outcome_code: str,
    kickoff_utc: datetime,
) -> ClosingLineResult:
    """Return the closing snapshot for a specific event/book/market/side."""
    result = ClosingLineResult(
        event_id=event_id,
        bookmaker_key=bookmaker_key,
        market=market_key,
        side=outcome_code,
    )

    if not _DB_PATH.exists():
        return result

    cutoff = kickoff_utc - timedelta(minutes=_CUTOFF_MINUTES)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    # Convert to naive UTC for comparison with DuckDB timestamps
    cutoff_naive = cutoff.astimezone(timezone.utc).replace(tzinfo=None)

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    kickoff_naive = kickoff_utc.astimezone(timezone.utc).replace(tzinfo=None)

    # If game has not yet kicked off, status is PENDING
    if now_naive < kickoff_naive:
        result.closing_status = "PENDING"

    try:
        con = _open_db()
        rows = con.execute(
            """
            SELECT fetched_at, point, price
            FROM odds_snapshots
            WHERE api_event_id = ?
              AND bookmaker_key = ?
              AND market_key    = ?
              AND outcome_code  = ?
              AND fetched_at   <= ?
            ORDER BY fetched_at ASC
            """,
            [event_id, bookmaker_key, market_key, outcome_code, cutoff_naive],
        ).fetchall()
        con.close()
    except Exception:
        return result

    if not rows:
        return result

    first = rows[0]
    last  = rows[-1]

    result.opening_point    = float(first[1]) if first[1] is not None else None
    result.opening_price    = float(first[2]) if first[2] is not None else None
    result.closing_point    = float(last[1])  if last[1]  is not None else None
    result.closing_price    = float(last[2])  if last[2]  is not None else None
    result.closing_timestamp = last[0]
    result.closing_status   = "AVAILABLE"
    return result


def calculate_clv(
    recommended_point: Optional[float],
    recommended_price: Optional[float],
    closing_point: Optional[float],
    closing_price: Optional[float],
    market: str,
    side: str,
) -> CLVResult:
    """Calculate market-specific CLV.  Returns a CLVResult with no event context."""
    result = CLVResult(
        event_id="",
        bookmaker_key="",
        market=market,
        side=side,
        recommended_point=recommended_point,
        recommended_price=recommended_price,
        closing_point=closing_point,
        closing_price=closing_price,
        closing_status="AVAILABLE" if closing_point is not None or closing_price is not None else "NOT_CAPTURED",
    )

    mkt = market.lower().strip()
    sd  = side.lower().strip()

    if mkt in ("spreads", "spread"):
        if recommended_point is not None and closing_point is not None:
            # positive = bettor beat the closing spread
            result.clv_points = round(recommended_point - closing_point, 2)

    elif mkt in ("totals", "total"):
        if recommended_point is not None and closing_point is not None:
            if sd == "over":
                # lower open is better for over (clear lower bar)
                result.clv_points = round(closing_point - recommended_point, 2)
            else:
                # "under" – higher open is better
                result.clv_points = round(recommended_point - closing_point, 2)

    elif mkt in ("h2h", "moneyline"):
        if recommended_price is not None and closing_price is not None:
            rec_impl   = _american_to_implied(recommended_price)
            close_impl = _american_to_implied(closing_price)
            # positive = closing market now views our side as more likely (beat the close)
            clv_prob = round(close_impl - rec_impl, 6)
            result.clv_probability = clv_prob
            result.clv_percent     = round(clv_prob * 100, 2)

    return result


def get_closing_line_and_clv(
    event_id: str,
    bookmaker_key: str,
    market_key: str,
    outcome_code: str,
    kickoff_utc: datetime,
    recommended_point: Optional[float],
    recommended_price: Optional[float],
) -> CLVResult:
    """Convenience: fetch closing line then calculate CLV in one call."""
    closing = get_closing_line(event_id, bookmaker_key, market_key, outcome_code, kickoff_utc)
    clv = calculate_clv(
        recommended_point=recommended_point,
        recommended_price=recommended_price,
        closing_point=closing.closing_point,
        closing_price=closing.closing_price,
        market=market_key,
        side=outcome_code,
    )
    clv.event_id      = event_id
    clv.bookmaker_key = bookmaker_key
    clv.closing_status = closing.closing_status
    return clv
