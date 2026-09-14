from fastapi import APIRouter

from app.services.recommendation_snapshot import (
    capture_closing_lines,
    get_clv_for_event,
    get_clv_summary,
    store_snapshot,
)
from app.services.decision_ledger import record_my_card_decision_from_payload
from app.services.decision_ledger import get_personal_wager_dashboard, record_personal_wager_from_payload

router = APIRouter(prefix="/api/recommendation", tags=["recommendation"])


@router.post("/snapshot")
def create_snapshot(payload: dict):
    """Store an immutable recommendation snapshot when a bet is added to My Card."""
    snapshot_id = store_snapshot(payload)
    if not snapshot_id:
        return {
            "success": False,
            "snapshotRecorded": False,
            "ledgerRecorded": False,
            "trackingStatus": "FAILED",
            "reason": "database unavailable",
        }

    decision_payload = dict(payload)
    decision_payload["sourceSnapshotId"] = snapshot_id
    wager_payload = dict(payload)
    wager_payload["sourceSnapshotId"] = snapshot_id

    decision = None
    try:
        decision = record_my_card_decision_from_payload(decision_payload)
    except ValueError as exc:
        wager = None
        try:
            wager = record_personal_wager_from_payload(
                wager_payload,
                decision_id=None,
                source_snapshot_id=snapshot_id,
            )
        except ValueError:
            wager = None
        return {
            "success": True,
            "snapshotRecorded": True,
            "ledgerRecorded": False,
            "trackingStatus": "PARTIAL",
            "snapshotId": snapshot_id,
            "wagerId": None if wager is None else wager.get("wagerId"),
            "warning": "Added to My Card. Performance tracking could not be fully started.",
            "trackingDetail": str(exc),
        }

    wager = None
    try:
        wager = record_personal_wager_from_payload(
            wager_payload,
            decision_id=decision.get("decisionId"),
            source_snapshot_id=snapshot_id,
        )
    except ValueError:
        wager = None

    return {
        "success": True,
        "snapshotRecorded": True,
        "ledgerRecorded": True,
        "trackingStatus": "COMPLETE",
        "snapshotId": snapshot_id,
        "wagerId": None if wager is None else wager.get("wagerId"),
        "decisionId": decision["decisionId"],
        "decisionVersion": decision["decisionVersion"],
        "decisionCreated": decision["created"],
    }


@router.get("/my-card-ledger")
def get_my_card_ledger(limit: int = 500):
    return get_personal_wager_dashboard(limit=limit)


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
