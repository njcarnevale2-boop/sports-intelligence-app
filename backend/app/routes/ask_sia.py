from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.ask_sia import get_ask_sia_response


router = APIRouter(prefix="/api", tags=["ask-sia"])


class AskSiaRequest(BaseModel):
    eventId: str
    question: str
    snapshotId: Optional[str] = None


@router.post("/ask-sia")
def ask_sia(request: AskSiaRequest):
    event_id = str(request.eventId or "").strip()
    question = str(request.question or "").strip()
    if not event_id:
        raise HTTPException(status_code=400, detail="eventId is required")
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    return get_ask_sia_response(
        event_id=event_id,
        question=question,
        snapshot_id=request.snapshotId,
    )
