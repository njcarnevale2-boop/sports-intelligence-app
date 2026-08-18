from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.move_the_line import evaluate_move_the_line


router = APIRouter(prefix="/api", tags=["move-the-line"])


class MoveTheLineRequest(BaseModel):
    eventId: str
    hypotheticalSpread: float
    assumedOdds: float
    snapshotId: Optional[str] = None


@router.post("/move-the-line")
def move_the_line(request: MoveTheLineRequest):
    event_id = str(request.eventId or "").strip()
    if not event_id:
        raise HTTPException(status_code=400, detail="eventId is required")

    try:
        return evaluate_move_the_line(
            event_id=event_id,
            hypothetical_spread=float(request.hypotheticalSpread),
            assumed_odds=float(request.assumedOdds),
            snapshot_id=request.snapshotId,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
