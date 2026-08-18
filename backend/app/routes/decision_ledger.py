from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.services.decision_ledger import (
    append_outcome,
    get_admin_ledger_summary,
    get_decision,
    get_prospective_performance,
    list_decisions,
    list_publications,
    publish_sia3,
    record_decision,
    validate_decision_hash,
)


router = APIRouter(prefix="/api/admin/ledger", tags=["admin-ledger"])


def _require_admin_token(x_admin_token: str | None) -> None:
    if not x_admin_token or x_admin_token != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Admin token required")


class DecisionRecordRequest(BaseModel):
    publicationType: str = "OTHER"
    payload: Dict[str, Any]


class SlotRequest(BaseModel):
    slotLabel: Optional[str] = None
    qualificationStatus: Optional[str] = None
    decisionId: Optional[str] = None
    decision: Optional[Dict[str, Any]] = None


class PublicationRequest(BaseModel):
    publicationType: str = "SIA_3"
    publishedAtUTC: Optional[str] = None
    season: int
    week: int
    isOfficial: bool = False
    officialCadence: Optional[str] = None
    slots: List[SlotRequest] = Field(default_factory=list)


class OutcomeRequest(BaseModel):
    decisionId: str
    capturedAtUTC: Optional[str] = None
    closingLine: Optional[float] = None
    closingPrice: Optional[float] = None
    closingSportsbook: Optional[str] = None
    closingTimestamp: Optional[str] = None
    closingConsensusMethodology: Optional[str] = None
    clv: Optional[float] = None
    clvType: Optional[str] = None
    finalAwayScore: Optional[int] = None
    finalHomeScore: Optional[int] = None
    betResult: Optional[str] = None
    profitPerDollar: Optional[float] = None
    sourceSnapshotId: Optional[str] = None


@router.post("/decisions")
def create_decision(request: DecisionRecordRequest, x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    try:
        return record_decision(request.payload, publication_type=request.publicationType)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/decisions/{decision_id}")
def read_decision(decision_id: str):
    decision = get_decision(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    return decision


@router.get("/decisions")
def query_decisions(
    season: int | None = Query(default=None),
    week: int | None = Query(default=None),
    publicationType: str | None = Query(default=None),
    latestOnly: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=1000),
):
    items = list_decisions(
        season=season,
        week=week,
        publication_type=publicationType,
        latest_only=latestOnly,
        limit=limit,
    )
    return {
        "count": len(items),
        "items": items,
    }


@router.post("/publications/sia3")
def create_sia3_publication(request: PublicationRequest, x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    try:
        payload = request.model_dump()
        payload["slots"] = [slot.model_dump() for slot in request.slots]
        return publish_sia3(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/publications")
def query_publications(
    season: int | None = Query(default=None),
    week: int | None = Query(default=None),
):
    items = list_publications(season=season, week=week)
    return {"count": len(items), "items": items}


@router.post("/outcomes")
def capture_outcome(request: OutcomeRequest, x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    try:
        return append_outcome(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/hash/{decision_id}")
def validate_hash(decision_id: str):
    result = validate_decision_hash(decision_id)
    if not result.get("found"):
        raise HTTPException(status_code=404, detail="Decision not found")
    return result


@router.get("/audit")
def read_ledger_audit(limit: int = Query(default=200, ge=1, le=1000)):
    return get_admin_ledger_summary(limit=limit)


@router.get("/performance")
def read_prospective_performance():
    return get_prospective_performance()
