from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from app.providers.provider_manager import ProviderManager


MODEL_ROOT = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9"
OUTPUTS_ROOT = MODEL_ROOT / "outputs"
LINE_MOVEMENT_BOARD = OUTPUTS_ROOT / "line_movement_board.csv"
RANKED_BET_BOARD = OUTPUTS_ROOT / "ranked_bet_board.csv"


def _safe_float(value: Any) -> Optional[float]:
    if pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_iso_timestamp(value: Any) -> Optional[str]:
    if value is None or pd.isna(value):
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        parsed = pd.to_datetime(text, utc=True, errors="coerce")
    except Exception:
        return None

    if parsed is None or pd.isna(parsed):
        return None

    return parsed.to_pydatetime().isoformat()


def american_implied_probability(odds: Optional[float]) -> Optional[float]:
    if odds is None:
        return None

    try:
        value = float(odds)
    except (TypeError, ValueError):
        return None

    if value == 0:
        return None

    if value > 0:
        return round(100 / (value + 100), 6)

    return round(abs(value) / (abs(value) + 100), 6)


def normalize_market(market: Any) -> str:
    text = str(market or "").strip().lower()
    mapping = {
        "spreads": "spread",
        "spread": "spread",
        "totals": "total",
        "total": "total",
        "h2h": "moneyline",
        "moneyline": "moneyline",
    }
    return mapping.get(text, text)


def normalize_side(side: Any) -> str:
    return str(side or "").strip().lower()


def normalize_event_id(event_id: Any) -> str:
    return str(event_id or "").strip()


def select_best_line_row(group: pd.DataFrame) -> pd.Series:
    market = normalize_market(group.iloc[0].get("market"))
    side = normalize_side(group.iloc[0].get("side"))

    if market == "spread":
        best_point = group["point"].max()
        candidates = group[group["point"] == best_point]
        best_price = candidates["price"].max()
        return candidates[candidates["price"] == best_price].iloc[0]

    if market == "total":
        if side == "over":
            best_point = group["point"].min()
            candidates = group[group["point"] == best_point]
            best_price = candidates["price"].max()
            return candidates[candidates["price"] == best_price].iloc[0]

        if side == "under":
            best_point = group["point"].max()
            candidates = group[group["point"] == best_point]
            best_price = candidates["price"].max()
            return candidates[candidates["price"] == best_price].iloc[0]

    return group.sort_values(["price"], ascending=[False]).iloc[0]


@dataclass
class BestLine:
    sportsbook: str
    line: Optional[float]
    price: Optional[float]
    lastUpdated: Optional[str]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "sportsbook": self.sportsbook,
            "line": self.line,
            "price": self.price,
            "lastUpdated": self.lastUpdated,
        }


class MarketDataService:
    def __init__(self) -> None:
        self.provider_manager = ProviderManager()
        self._normalized_rows_cache: Optional[List[Dict[str, Any]]] = None
        self._normalized_rows_cache_mtime: Optional[float] = None
        self._event_snapshots_cache: Optional[Dict[str, Dict[str, Any]]] = None
        self._event_snapshots_cache_mtime: Optional[float] = None

    def metadata(self) -> Dict[str, Any]:
        odds_metadata = self.provider_manager.get_odds_provider().get_metadata()

        if not LINE_MOVEMENT_BOARD.exists():
            return {
                "provider": "line_movement_board",
                "lastUpdated": None,
                "dataStatus": "UNAVAILABLE",
                "source": str(LINE_MOVEMENT_BOARD),
                "upstreamProvider": odds_metadata,
            }

        last_updated = datetime.fromtimestamp(LINE_MOVEMENT_BOARD.stat().st_mtime, tz=timezone.utc).isoformat()
        try:
            df = pd.read_csv(LINE_MOVEMENT_BOARD)
            if not df.empty and "last_seen" in df.columns:
                series = df["last_seen"].dropna()
                if not series.empty:
                    parsed = pd.to_datetime(series, utc=True, errors="coerce").dropna()
                    if not parsed.empty:
                        last_updated = parsed.max().to_pydatetime().isoformat()
        except Exception:
            pass

        return {
            "provider": "line_movement_board",
            "lastUpdated": last_updated,
            "dataStatus": "FILE",
            "source": str(LINE_MOVEMENT_BOARD),
            "upstreamProvider": odds_metadata,
        }

    def load_normalized_market_rows(self) -> List[Dict[str, Any]]:
        meta = self.metadata()
        if meta["dataStatus"] == "UNAVAILABLE":
            return []

        try:
            modified_time = LINE_MOVEMENT_BOARD.stat().st_mtime
        except OSError:
            modified_time = None

        if (
            self._normalized_rows_cache is not None
            and self._normalized_rows_cache_mtime == modified_time
        ):
            return self._normalized_rows_cache

        try:
            df = pd.read_csv(LINE_MOVEMENT_BOARD)
        except (OSError, pd.errors.EmptyDataError):
            self._normalized_rows_cache = []
            self._normalized_rows_cache_mtime = modified_time
            return []

        if df.empty:
            self._normalized_rows_cache = []
            self._normalized_rows_cache_mtime = modified_time
            return []

        df = df.copy()
        df["api_event_id"] = df["api_event_id"].fillna("").astype(str)
        df["sportsbook"] = df["sportsbook"].fillna("").astype(str)
        df["market"] = df["market"].apply(normalize_market)
        df["side"] = df["side"].fillna("").astype(str).str.lower()
        df["away_team"] = df["away_team"].fillna("").astype(str)
        df["home_team"] = df["home_team"].fillna("").astype(str)

        last_seen = pd.to_datetime(df["last_seen"], utc=True, errors="coerce")
        first_seen = pd.to_datetime(df["first_seen"], utc=True, errors="coerce")
        commence_time = pd.to_datetime(df["commence_time"], utc=True, errors="coerce")

        rows: List[Dict[str, Any]] = []
        for row_index, row in df.iterrows():
            event_id = normalize_event_id(row.get("api_event_id"))
            market = normalize_market(row.get("market"))
            side = normalize_side(row.get("side"))

            latest_point = _safe_float(row.get("latest_point"))
            opening_point = _safe_float(row.get("opening_point_observed"))
            latest_price = _safe_float(row.get("latest_price"))
            opening_price = _safe_float(row.get("opening_price_observed"))

            point = latest_point if latest_point is not None else opening_point
            american_odds = latest_price if latest_price is not None else opening_price

            rows.append(
                {
                    "eventId": event_id,
                    "sportsbook": str(row.get("sportsbook", "")).strip(),
                    "market": market,
                    "side": side,
                    "point": point,
                    "americanOdds": american_odds,
                    "impliedProbability": american_implied_probability(american_odds),
                    "lastUpdated": last_seen.iloc[row_index].to_pydatetime().isoformat() if pd.notna(last_seen.iloc[row_index]) else meta["lastUpdated"],
                    "provider": meta["provider"],
                    "dataStatus": meta["dataStatus"],
                    "openingPoint": opening_point,
                    "openingOdds": opening_price,
                    "latestPoint": latest_point,
                    "latestOdds": latest_price,
                    "snapshots": int(row.get("snapshots", 0)) if not pd.isna(row.get("snapshots")) else 0,
                    "firstSeen": first_seen.iloc[row_index].to_pydatetime().isoformat() if pd.notna(first_seen.iloc[row_index]) else None,
                    "lastSeen": last_seen.iloc[row_index].to_pydatetime().isoformat() if pd.notna(last_seen.iloc[row_index]) else None,
                    "steamFlag": bool(row.get("steam_flag", False)),
                    "commenceTime": commence_time.iloc[row_index].to_pydatetime().isoformat() if pd.notna(commence_time.iloc[row_index]) else None,
                    "awayTeam": str(row.get("away_team", "")).strip(),
                    "homeTeam": str(row.get("home_team", "")).strip(),
                }
            )

        self._normalized_rows_cache = rows
        self._normalized_rows_cache_mtime = modified_time
        return rows

    def records_for_event(self, event_id: str) -> List[Dict[str, Any]]:
        normalized = self.load_normalized_market_rows()
        event_key = normalize_event_id(event_id)
        return [row for row in normalized if row["eventId"] == event_key]

    def best_line(self, records: List[Dict[str, Any]], market: str, side: str) -> Optional[BestLine]:
        market_key = normalize_market(market)
        side_key = normalize_side(side)

        candidates = [
            row
            for row in records
            if row["market"] == market_key and row["side"] == side_key and row.get("sportsbook")
        ]
        if not candidates:
            return None

        def sort_key(row: Dict[str, Any]) -> tuple:
            point = row.get("point")
            odds = row.get("americanOdds")
            point_value = float(point) if point is not None else float("-inf")
            odds_value = float(odds) if odds is not None else float("-inf")

            if market_key == "total" and side_key == "over":
                return (-point_value, odds_value)

            if market_key == "total" and side_key == "under":
                return (point_value, odds_value)

            return (point_value, odds_value)

        selected = sorted(candidates, key=sort_key, reverse=True)[0]
        return BestLine(
            sportsbook=selected.get("sportsbook", ""),
            line=selected.get("point"),
            price=selected.get("americanOdds"),
            lastUpdated=selected.get("lastUpdated"),
        )

    def best_price(self, records: List[Dict[str, Any]], market: str, side: str) -> Optional[BestLine]:
        market_key = normalize_market(market)
        side_key = normalize_side(side)

        candidates = [
            row
            for row in records
            if row["market"] == market_key and row["side"] == side_key and row.get("sportsbook")
        ]
        if not candidates:
            return None

        selected = sorted(
            candidates,
            key=lambda row: float(row.get("americanOdds") if row.get("americanOdds") is not None else float("-inf")),
            reverse=True,
        )[0]

        return BestLine(
            sportsbook=selected.get("sportsbook", ""),
            line=selected.get("point"),
            price=selected.get("americanOdds"),
            lastUpdated=selected.get("lastUpdated"),
        )

    def consensus(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        spreads_home = [row["point"] for row in records if row["market"] == "spread" and row["side"] == "home" and row["point"] is not None]
        totals_over = [row["point"] for row in records if row["market"] == "total" and row["side"] == "over" and row["point"] is not None]
        moneyline_home = [row["americanOdds"] for row in records if row["market"] == "moneyline" and row["side"] == "home" and row["americanOdds"] is not None]
        moneyline_away = [row["americanOdds"] for row in records if row["market"] == "moneyline" and row["side"] == "away" and row["americanOdds"] is not None]

        consensus_spread = round(sum(spreads_home) / len(spreads_home), 2) if len(spreads_home) >= 2 else None
        consensus_total = round(sum(totals_over) / len(totals_over), 2) if len(totals_over) >= 2 else None

        consensus_moneyline: Optional[Dict[str, float]] = None
        if len(moneyline_home) >= 2 and len(moneyline_away) >= 2:
            consensus_moneyline = {
                "home": round(sum(moneyline_home) / len(moneyline_home), 2),
                "away": round(sum(moneyline_away) / len(moneyline_away), 2),
            }

        return {
            "consensusSpread": consensus_spread,
            "consensusTotal": consensus_total,
            "consensusMoneyline": consensus_moneyline,
            "booksTracked": len({row["sportsbook"] for row in records if row.get("sportsbook")}),
        }

    def event_market_snapshot(self, event_id: str) -> Dict[str, Any]:
        meta = self.metadata()
        records = self.records_for_event(event_id)
        return self._build_event_snapshot(normalize_event_id(event_id), records, meta)

    def _build_event_snapshot(self, event_id: str, records: List[Dict[str, Any]], meta: Dict[str, Any]) -> Dict[str, Any]:

        best_away_spread = self.best_line(records, "spread", "away")
        best_home_spread = self.best_line(records, "spread", "home")
        best_away_moneyline = self.best_line(records, "moneyline", "away")
        best_home_moneyline = self.best_line(records, "moneyline", "home")
        best_over = self.best_line(records, "total", "over")
        best_under = self.best_line(records, "total", "under")

        best_price_away_spread = self.best_price(records, "spread", "away")
        best_price_home_spread = self.best_price(records, "spread", "home")
        best_price_away_moneyline = self.best_price(records, "moneyline", "away")
        best_price_home_moneyline = self.best_price(records, "moneyline", "home")
        best_price_over = self.best_price(records, "total", "over")
        best_price_under = self.best_price(records, "total", "under")

        consensus = self.consensus(records)
        books_tracked = consensus["booksTracked"]

        snapshots = [row.get("snapshots", 0) for row in records if isinstance(row.get("snapshots"), int)]
        opening_available = any(row.get("openingPoint") is not None or row.get("openingOdds") is not None for row in records)

        return {
            "eventId": event_id,
            "provider": meta["provider"],
            "lastUpdated": meta["lastUpdated"],
            "dataStatus": "FILE" if records else "UNAVAILABLE",
            "booksTracked": books_tracked,
            "consensusSpread": consensus["consensusSpread"],
            "consensusTotal": consensus["consensusTotal"],
            "consensusMoneyline": consensus["consensusMoneyline"],
            "bestAwaySpread": best_away_spread.as_dict() if best_away_spread else None,
            "bestHomeSpread": best_home_spread.as_dict() if best_home_spread else None,
            "bestAwayMoneyline": best_away_moneyline.as_dict() if best_away_moneyline else None,
            "bestHomeMoneyline": best_home_moneyline.as_dict() if best_home_moneyline else None,
            "bestOver": best_over.as_dict() if best_over else None,
            "bestUnder": best_under.as_dict() if best_under else None,
            "bestPriceAwaySpread": best_price_away_spread.as_dict() if best_price_away_spread else None,
            "bestPriceHomeSpread": best_price_home_spread.as_dict() if best_price_home_spread else None,
            "bestPriceAwayMoneyline": best_price_away_moneyline.as_dict() if best_price_away_moneyline else None,
            "bestPriceHomeMoneyline": best_price_home_moneyline.as_dict() if best_price_home_moneyline else None,
            "bestPriceOver": best_price_over.as_dict() if best_price_over else None,
            "bestPriceUnder": best_price_under.as_dict() if best_price_under else None,
            "lineHistory": {
                "openingLineAvailable": opening_available,
                "currentLineAvailable": bool(records),
                "closingLineAvailable": False,
                "historicalSnapshots": max(snapshots) if snapshots else 0,
                "message": (
                    "Opening and current snapshots are file-based; closing lines are not yet captured."
                    if records
                    else "Market data is currently unavailable."
                ),
            },
            "records": records,
        }

    def all_event_snapshots(self) -> Dict[str, Dict[str, Any]]:
        try:
            modified_time = LINE_MOVEMENT_BOARD.stat().st_mtime
        except OSError:
            modified_time = None

        if (
            self._event_snapshots_cache is not None
            and self._event_snapshots_cache_mtime == modified_time
        ):
            return self._event_snapshots_cache

        meta = self.metadata()
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in self.load_normalized_market_rows():
            grouped.setdefault(row["eventId"], []).append(row)

        snapshots: Dict[str, Dict[str, Any]] = {}
        for event_id, records in grouped.items():
            snapshots[event_id] = self._build_event_snapshot(event_id, records, meta)

        self._event_snapshots_cache = snapshots
        self._event_snapshots_cache_mtime = modified_time
        return snapshots


market_data_service = MarketDataService()
