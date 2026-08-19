from __future__ import annotations

from dataclasses import dataclass
from typing import Any


NORMALIZATION_METHOD = "METHOD_C_ZSCORE_WITHIN_MARKET"
NORMALIZATION_VERSION = "cross_market_phase1_v1"


@dataclass(frozen=True)
class _MarketStats:
    mean_edge: float
    std_edge: float
    mean_ev: float
    std_ev: float


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _market_stats(rows: list[dict[str, Any]]) -> _MarketStats:
    edges = [_safe_float(r.get("calibratedEdge")) for r in rows]
    evs = [_safe_float(r.get("ev")) for r in rows]

    mean_edge = sum(edges) / len(edges) if edges else 0.0
    mean_ev = sum(evs) / len(evs) if evs else 0.0

    var_edge = sum((x - mean_edge) ** 2 for x in edges) / len(edges) if edges else 0.0
    var_ev = sum((x - mean_ev) ** 2 for x in evs) / len(evs) if evs else 0.0

    std_edge = var_edge ** 0.5
    std_ev = var_ev ** 0.5

    return _MarketStats(
        mean_edge=mean_edge,
        std_edge=std_edge if std_edge > 1e-12 else 1.0,
        mean_ev=mean_ev,
        std_ev=std_ev if std_ev > 1e-12 else 1.0,
    )


def attach_shadow_global_scores(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach research-only global score/rank fields to shadow candidates.

    This does not alter production eligibility, market eligibility, or publish behavior.
    """
    if not candidates:
        return candidates

    by_market: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        by_market.setdefault(str(row.get("marketFamily") or "UNKNOWN"), []).append(row)

    market_stats = {market: _market_stats(rows) for market, rows in by_market.items()}

    for row in candidates:
        market = str(row.get("marketFamily") or "UNKNOWN")
        stats = market_stats[market]
        edge = _safe_float(row.get("calibratedEdge"))
        ev = _safe_float(row.get("ev"))

        z_edge = (edge - stats.mean_edge) / stats.std_edge
        z_ev = (ev - stats.mean_ev) / stats.std_ev

        score = 0.5 * z_edge + 0.5 * z_ev

        row["globalResearchScore"] = float(score)
        row["globalResearchRank"] = None
        row["normalizationMethod"] = NORMALIZATION_METHOD
        row["normalizationVersion"] = NORMALIZATION_VERSION

    ranked = sorted(
        candidates,
        key=lambda x: (
            -_safe_float(x.get("globalResearchScore"), default=-999.0),
            0 if str(x.get("qualificationStatus") or "").upper() == "QUALIFIED" else 1,
            -_safe_float(x.get("calibratedEdge"), default=-999.0),
            -_safe_float(x.get("ev"), default=-999.0),
            str(x.get("eventId") or ""),
            str(x.get("side") or ""),
        ),
    )

    for idx, row in enumerate(ranked, start=1):
        row["globalResearchRank"] = idx

    return candidates
