from fastapi import APIRouter

from app.services.recommendation_snapshot import (
    build_snapshot_id,
    capture_closing_lines,
    delete_snapshot,
    get_clv_for_event,
    get_clv_summary,
    link_snapshot_decision,
    snapshot_exists,
    store_snapshot,
)
from app.services.decision_ledger import record_my_card_decision_from_payload
from app.services.decision_ledger import get_personal_wager_dashboard, record_personal_wager_from_payload
from app.services.games import service as games_service

router = APIRouter(prefix="/api/recommendation", tags=["recommendation"])


def _is_actionable_qualified(payload: dict) -> bool:
    qualification = str(payload.get("qualificationStatus") or "").upper()
    if qualification == "QUALIFIED":
        return True
    current_qualification = payload.get("currentQualification")
    if isinstance(current_qualification, dict):
        return str(current_qualification.get("status") or "").upper() == "QUALIFIED" and bool(current_qualification.get("actionable"))
    return False


def _missing_actionable_fields(payload: dict) -> list[str]:
    execution = payload.get("currentExecution") if isinstance(payload.get("currentExecution"), dict) else {}
    sizing = payload.get("currentSizing") if isinstance(payload.get("currentSizing"), dict) else {}
    required = {
        "season": payload.get("season"),
        "week": payload.get("week"),
        "eventId": payload.get("eventId"),
        "market": payload.get("market"),
        "side": payload.get("side"),
        "sportsbook": execution.get("sportsbook"),
        "price": execution.get("price"),
        "quoteTimestamp": execution.get("quoteTimestamp"),
        "marketTimestamp": execution.get("currentMarketTimestamp") if execution.get("currentMarketTimestamp") is not None else payload.get("marketTimestamp"),
        "modelProbability": payload.get("modelProbability"),
        "calibratedProbability": payload.get("calibratedProbability"),
        "pushProbability": payload.get("pushProbability"),
        "lossProbability": payload.get("lossProbability"),
        "impliedProbability": payload.get("impliedProbability"),
        "edge": payload.get("edge"),
        "evPerDollar": payload.get("evPerDollar"),
        "fullKellyFraction": sizing.get("fullKellyFraction") if sizing else payload.get("fullKellyFraction"),
        "fractionalKellyFraction": sizing.get("fractionalKellyFraction") if sizing else payload.get("fractionalKellyFraction"),
        "bankrollPercent": sizing.get("bankrollPercent") if sizing else payload.get("bankrollPercent"),
        "recommendedAmount": sizing.get("recommendedAmount") if sizing else payload.get("recommendedAmount"),
        "recommendedUnits": sizing.get("recommendedUnits") if sizing else payload.get("recommendedUnits"),
        "unitSizeAtBet": sizing.get("unitSize") if sizing else payload.get("unitSizeAtBet"),
        "bankrollBasis": sizing.get("bankrollBasis") if sizing else payload.get("bankrollBasis"),
        "modelVersion": payload.get("modelVersion"),
        "probabilityEngineVersion": payload.get("probabilityEngineVersion"),
        "calibrationVersion": payload.get("calibrationVersion"),
        "rankingVersion": payload.get("rankingVersion"),
        "qualificationPolicyVersion": payload.get("qualificationPolicyVersion"),
        "modelTimestamp": payload.get("modelTimestamp"),
    }

    point_required = str(payload.get("market") or "").lower() not in {"moneyline", "h2h"}
    if point_required:
        required["point"] = execution.get("point")

    missing: list[str] = []
    for field, value in required.items():
        if value is None:
            missing.append(field)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(field)

    if execution:
        if str(execution.get("status") or "").upper() != "AVAILABLE":
            missing.append("currentExecution.status=AVAILABLE")
    else:
        missing.append("currentExecution")

    return missing


def _apply_current_execution_and_sizing(payload: dict) -> dict:
    normalized = dict(payload)
    current_execution = payload.get("currentExecution") if isinstance(payload.get("currentExecution"), dict) else {}
    current_sizing = payload.get("currentSizing") if isinstance(payload.get("currentSizing"), dict) else {}

    if current_execution:
        if current_execution.get("sportsbook") is not None:
            normalized["sportsbook"] = current_execution.get("sportsbook")
        if current_execution.get("point") is not None:
            normalized["point"] = current_execution.get("point")
        if current_execution.get("price") is not None:
            normalized["price"] = current_execution.get("price")
        if current_execution.get("quoteTimestamp") is not None:
            normalized["quoteTimestamp"] = current_execution.get("quoteTimestamp")
        if current_execution.get("currentMarketTimestamp") is not None:
            normalized["marketTimestamp"] = current_execution.get("currentMarketTimestamp")

    if current_sizing:
        if current_sizing.get("fullKellyFraction") is not None:
            normalized["fullKellyFraction"] = current_sizing.get("fullKellyFraction")
        if current_sizing.get("fractionalKellyFraction") is not None:
            normalized["fractionalKellyFraction"] = current_sizing.get("fractionalKellyFraction")
        if current_sizing.get("bankrollPercent") is not None:
            normalized["bankrollPercent"] = current_sizing.get("bankrollPercent")
        if current_sizing.get("recommendedAmount") is not None:
            normalized["recommendedAmount"] = current_sizing.get("recommendedAmount")
        if current_sizing.get("recommendedUnits") is not None:
            normalized["recommendedUnits"] = current_sizing.get("recommendedUnits")
        if current_sizing.get("unitSize") is not None:
            normalized["unitSizeAtBet"] = current_sizing.get("unitSize")
        if current_sizing.get("bankrollBasis") is not None:
            normalized["bankrollBasis"] = current_sizing.get("bankrollBasis")

    return normalized


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
    with_current_state = _apply_current_execution_and_sizing(payload)
    normalized = _resolve_identity(with_current_state)
    event_id = str(normalized.get("eventId") or "").strip()
    if not event_id or normalized.get("season") is None or normalized.get("week") is None:
        return {
            "success": False,
            "snapshotRecorded": False,
            "ledgerRecorded": False,
            "trackingStatus": "FAILED",
            "reason": "season, week, and eventId are required",
        }

    if _is_actionable_qualified(normalized):
        missing = _missing_actionable_fields(normalized)
        if missing:
            return {
                "success": False,
                "snapshotRecorded": False,
                "ledgerRecorded": False,
                "trackingStatus": "FAILED",
                "reason": "Missing required actionable evidence: " + ", ".join(missing),
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

    backlink_warning = None
    try:
        link_snapshot_decision(snapshot_id, str(decision.get("decisionId") or ""))
    except ValueError as exc:
        backlink_warning = str(exc)
    except Exception:
        backlink_warning = "Snapshot decision backlink could not be recorded."

    response = {
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
    if backlink_warning:
        response["warning"] = backlink_warning
    return response


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
