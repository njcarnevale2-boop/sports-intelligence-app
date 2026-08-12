from fastapi import APIRouter, HTTPException

from app.services.recommendation_snapshot import (
    capture_closing_lines,
    get_clv_for_event,
    get_clv_summary,
    store_snapshot,
)

router = APIRouter(prefix="/api/recommendation", tags=["recommendation"])


@router.post("/snapshot")
def create_snapshot(payload: dict):
    """Store an immutable recommendation snapshot when a bet is added to My Card."""
    snapshot_id = store_snapshot(payload)
    if not snapshot_id:
        return {"success": False, "reason": "database unavailable"}
    return {"success": True, "snapshotId": snapshot_id}


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
