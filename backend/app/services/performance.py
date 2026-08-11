from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import PerformanceRecord
from database.session import SessionLocal


class PerformanceService:
    def __init__(self, session: Session | None = None) -> None:
        self.session = session or SessionLocal()

    def track_recommendation(self, payload: Dict[str, Any]) -> PerformanceRecord:
        record = PerformanceRecord(
            game=payload.get("game"),
            sportsbook=payload.get("sportsbook"),
            market=payload.get("market"),
            recommendation=payload.get("recommendation"),
            sports_intelligence_score=payload.get("sportsIntelligenceScore"),
            market_intelligence=json.dumps(payload.get("marketIntelligence") or {}, sort_keys=True),
            injury_context=json.dumps(payload.get("injuryContext") or {}, sort_keys=True),
            weather_context=json.dumps(payload.get("weatherContext") or {}, sort_keys=True),
            model_probability=payload.get("modelProbability"),
            implied_probability=payload.get("impliedProbability"),
            edge=payload.get("edge"),
            expected_value=payload.get("expectedValue"),
            line_at_recommendation=payload.get("lineAtRecommendation"),
            closing_line=payload.get("closingLine"),
            final_score=payload.get("finalScore"),
            result=payload.get("result"),
            units_won_lost=payload.get("unitsWonLost"),
            timestamp=payload.get("timestamp") or datetime.now(timezone.utc),
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def get_performance_summary(self) -> Dict[str, Any]:
        records = self.session.query(PerformanceRecord).all()
        if not records:
            return self._empty_summary()

        total_units = sum(float(r.units_won_lost or 0) for r in records)
        wins = sum(1 for r in records if str(r.result or "").lower() == "win")
        losses = sum(1 for r in records if str(r.result or "").lower() == "loss")
        total = len(records)

        win_rate = round((wins / total) * 100, 1) if total else 0.0
        roi = round((total_units / max(total, 1)) * 100, 1) if total else 0.0

        market_profit = self._group_profit(records, "market")
        sportsbook_profit = self._group_profit(records, "sportsbook")
        si_profit = self._group_profit(records, "sports_intelligence_score")
        recommendation_profit = self._group_profit(records, "recommendation")

        closing_line_value = self._closing_line_value(records)

        return {
            "overallROI": roi,
            "winRate": win_rate,
            "closingLineValue": closing_line_value,
            "profitByMarket": market_profit,
            "profitBySportsbook": sportsbook_profit,
            "profitBySiScore": si_profit,
            "profitByRecommendation": recommendation_profit,
            "charts": {
                "roiTrend": [],
                "profitByMarket": market_profit,
                "profitBySportsbook": sportsbook_profit,
                "profitBySiScore": si_profit,
                "profitByRecommendation": recommendation_profit,
            },
        }

    def _empty_summary(self) -> Dict[str, Any]:
        return {
            "overallROI": 0.0,
            "winRate": 0.0,
            "closingLineValue": 0.0,
            "profitByMarket": [],
            "profitBySportsbook": [],
            "profitBySiScore": [],
            "profitByRecommendation": [],
            "charts": {
                "roiTrend": [],
                "profitByMarket": [],
                "profitBySportsbook": [],
                "profitBySiScore": [],
                "profitByRecommendation": [],
            },
        }

    def _group_profit(self, records: List[PerformanceRecord], key: str) -> List[Dict[str, Any]]:
        grouped: Dict[str, float] = {}
        for record in records:
            value = getattr(record, key) if hasattr(record, key) else None
            if value is None:
                value = "unknown"
            label = str(value)
            grouped[label] = grouped.get(label, 0.0) + float(record.units_won_lost or 0)

        return [{"label": label, "profit": round(total, 2)} for label, total in sorted(grouped.items())]

    def _closing_line_value(self, records: List[PerformanceRecord]) -> float:
        if not records:
            return 0.0

        values: List[float] = []
        for record in records:
            if record.line_at_recommendation is None or record.closing_line is None:
                continue
            values.append(float(record.closing_line) - float(record.line_at_recommendation))

        return round(sum(values) / len(values), 2) if values else 0.0


def get_performance_service() -> PerformanceService:
    return PerformanceService()
