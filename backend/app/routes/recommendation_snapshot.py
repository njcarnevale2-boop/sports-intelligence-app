from fastapi import APIRouter, HTTPException

from app.services.recommendation_snapshot import (
    capture_closing_lines,
    get_clv_for_event,
    get_clv_summary,
    store_snapshot,
)
from app.services.decision_ledger import record_my_card_decision_from_payload

router = APIRouter(prefix="/api/recommendation", tags=["recommendation"])


@router.post("/snapshot")
def create_snapshot(payload: dict):
    """Store an immutable recommendation snapshot when a bet is added to My Card."""
    snapshot_id = store_snapshot(payload)
    if not snapshot_id:
        return {"success": False, "reason": "database unavailable"}

    decision_payload = dict(payload)
    decision_payload["sourceSnapshotId"] = snapshot_id
    try:
        decision = record_my_card_decision_from_payload(decision_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "snapshotId": snapshot_id,
        "decisionId": decision["decisionId"],
        "decisionVersion": decision["decisionVersion"],
        "decisionCreated": decision["created"],
    }


@router.get("/clv/{event_id}")
def get_event_clv(event_id: str):
    """Return CLV records for a specific event."""
    records = get_clv_for_event(event_id)
    return {"eventId": event_id, "count": len(records), "records": records}


@router.get("/clv-summary")
def get_clv_summary_endpoint():
    """Return aggregate CLV stats."""
    return get_clv_summary()


@router.post("/capture-closing-lines")
def trigger_closing_capture():
    """Manually trigger closing line capture for all PENDING snapshots."""
    counts = capture_closing_lines()
    return {
        "success": True,
        "captured": counts["captured"],
        "pending": counts["pending"],
        "missing": counts["missing"],
    }
