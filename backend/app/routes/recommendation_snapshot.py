from fastapi import APIRouter

from app.services.recommendation_snapshot import (
    build_snapshot_id,
    capture_closing_lines,
    delete_snapshot,
    get_clv_for_event,
    get_clv_summary,
    snapshot_exists,
    store_snapshot,
)
from app.services.decision_ledger import record_my_card_decision_from_payload
from app.services.decision_ledger import get_personal_wager_dashboard, record_personal_wager_from_payload
from app.services.games import service as games_service

router = APIRouter(prefix="/api/recommendation", tags=["recommendation"])


def _resolve_identity(payload: dict) -> dict:
    resolved = dict(payload)
    event_id = str(resolved.get("eventId") or "").strip()
    if not event_id:
        return resolved

    if resolved.get("season") is not None and resolved.get("week") is not None:
        return resolved

    try:
        available = games_service.list_games()
        for week in available.get("availableWeeks", []):
            weekly = games_service.list_games(week=week)
            for game in weekly.get("games", []):
                if str(game.get("eventId") or "") == event_id:
                    if resolved.get("season") is None and game.get("season") is not None:
                        resolved["season"] = game.get("season")
                    if resolved.get("week") is None and game.get("week") is not None:
                        resolved["week"] = game.get("week")
                    return resolved
    except Exception:
        return resolved

    return resolved


@router.post("/snapshot")
def create_snapshot(payload: dict):
    """Store an immutable recommendation snapshot when a bet is added to My Card."""
    normalized = _resolve_identity(payload)
    event_id = str(normalized.get("eventId") or "").strip()
    if not event_id or normalized.get("season") is None or normalized.get("week") is None:
        return {
            "success": False,
            "snapshotRecorded": False,
            "ledgerRecorded": False,
            "trackingStatus": "FAILED",
            "reason": "season, week, and eventId are required",
        }

    snapshot_id = build_snapshot_id(normalized)
    existed_before = snapshot_exists(snapshot_id)
    if not existed_before:
        stored_snapshot_id = store_snapshot(normalized)
        if not stored_snapshot_id:
            return {
                "success": False,
                "snapshotRecorded": False,
                "ledgerRecorded": False,
                "trackingStatus": "FAILED",
                "reason": "database unavailable",
            }
        snapshot_id = stored_snapshot_id

    if not snapshot_id:
        return {
            "success": False,
            "snapshotRecorded": False,
            "ledgerRecorded": False,
            "trackingStatus": "FAILED",
            "reason": "database unavailable",
        }

    decision_payload = dict(normalized)
    decision_payload["sourceSnapshotId"] = snapshot_id
    wager_payload = dict(normalized)
    wager_payload["sourceSnapshotId"] = snapshot_id

    decision = None
    try:
        decision = record_my_card_decision_from_payload(decision_payload)
    except ValueError as exc:
        if not existed_before:
            delete_snapshot(snapshot_id)
        return {
            "success": False,
            "snapshotRecorded": False,
            "ledgerRecorded": False,
            "trackingStatus": "FAILED",
            "reason": str(exc),
        }
    except Exception:
        if not existed_before:
            delete_snapshot(snapshot_id)
        return {
            "success": False,
            "snapshotRecorded": False,
            "ledgerRecorded": False,
            "trackingStatus": "FAILED",
            "reason": "Performance tracking could not be fully started.",
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
