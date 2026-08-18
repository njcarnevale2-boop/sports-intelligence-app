from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.services.decision_ledger import (
    build_official_sia3_preview,
    append_outcome,
    get_admin_ledger_summary,
    get_decision,
    get_prospective_performance,
    list_decisions,
    list_publications,
    publish_sia3,
    publish_official_sia3_from_preview,
    record_decision,
    record_my_card_decision_from_payload,
    validate_decision_hash,
)
from app.routes.opportunities import get_opportunities
from app.services.games import service as games_service


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


class OfficialPublishRequest(BaseModel):
    week: Optional[int] = None
    snapshotId: str
    overrideStaleOdds: bool = False
    overrideMissingSnapshotLinkage: bool = False


@router.post("/decisions")
def create_decision(request: DecisionRecordRequest, x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    try:
        return record_decision(request.payload, publication_type=request.publicationType)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/decisions/my-card")
def create_my_card_decision(payload: Dict[str, Any], x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    try:
        return record_my_card_decision_from_payload(payload)
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


def _resolve_week_and_season(week: Optional[int]) -> tuple[int, int]:
    games = games_service.list_games(week=week)
    selected_week = week
    if selected_week is None:
        available = games.get("availableWeeks") or []
        selected_week = int(available[0]) if available else 1
        games = games_service.list_games(week=selected_week)

    rows = games.get("games") or []
    if rows:
        first = rows[0]
        season = int(first.get("season") or datetime.now(timezone.utc).year)
    else:
        season = datetime.now(timezone.utc).year
    return season, int(selected_week)


@router.get("/official-sia3/preview")
def preview_official_sia3(
    week: int | None = Query(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _require_admin_token(x_admin_token)
    season, resolved_week = _resolve_week_and_season(week)
    opps_payload = get_opportunities(limit=100, best_lines_only=True, week=resolved_week)
    opportunities = opps_payload.get("opportunities") or []
    preview = build_official_sia3_preview(opportunities, season=season, week=resolved_week)
    preview["snapshotId"] = opps_payload.get("snapshotId")
    preview["dataTimestamp"] = opps_payload.get("lastUpdated")
    preview["dataStatus"] = opps_payload.get("dataStatus")
    return preview


@router.post("/official-sia3/publish")
def publish_official_sia3(request: OfficialPublishRequest, x_admin_token: str | None = Header(default=None)):
    _require_admin_token(x_admin_token)
    season, resolved_week = _resolve_week_and_season(request.week)
    opps_payload = get_opportunities(limit=100, best_lines_only=True, week=resolved_week)
    live_snapshot_id = opps_payload.get("snapshotId")
    if not live_snapshot_id:
        raise HTTPException(status_code=400, detail="No opportunity snapshot available; refresh preview and retry")
    if str(request.snapshotId) != str(live_snapshot_id):
        raise HTTPException(status_code=400, detail="Snapshot is stale; refresh preview and publish again")

    opportunities = opps_payload.get("opportunities") or []
    preview = build_official_sia3_preview(
        opportunities,
        season=season,
        week=resolved_week,
        source_snapshot_id=str(live_snapshot_id),
    )
    try:
        publication = publish_official_sia3_from_preview(
            preview,
            override_stale=request.overrideStaleOdds,
            override_missing_linkage=request.overrideMissingSnapshotLinkage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "preview": preview,
        "publication": publication,
    }


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
