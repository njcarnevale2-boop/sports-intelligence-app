from fastapi import APIRouter, Query

from app.services.admin_status import get_admin_status_service
from app.services.data_refresh import refresh_all_data
from app.services.odds_status import (
    evaluate_optional_provider_request,
    get_core_request_cost_verification,
    perform_core_cost_bootstrap,
)
from app.services.refresh_orchestrator import trigger_now, get_refresh_status
from app.services.social_sources import get_social_source_coverage_report


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/status")
def get_admin_status():
    service = get_admin_status_service()
    return service.get_status()


@router.get("/refresh-status")
def get_odds_refresh_status():
    return get_refresh_status()


@router.get("/social-sources/coverage")
def get_social_sources_coverage():
    return get_social_source_coverage_report()


@router.post("/refresh")
def trigger_refresh(
    sportsbook_refresh: bool = Query(default=False, alias="sportsbookRefresh"),
    bootstrap_core_cost: bool = Query(default=False, alias="bootstrapCoreCost"),
    bootstrap_shape_id: str = Query(default="", alias="bootstrapShapeId"),
    allow_unknown_credit_cost: bool = Query(default=False, alias="allowUnknownCreditCost"),
    allow_unknown_weekly_usage: bool = Query(default=False, alias="allowUnknownWeeklyUsage"),
    override_quota_guards: bool = Query(default=False, alias="overrideQuotaGuards"),
):
    # Default path is local-only model refresh to avoid accidental credit spend.
    odds_result = {
        "triggered": False,
        "reason": "SPORTSBOOK_REFRESH_NOT_REQUESTED",
    }

    if bootstrap_core_cost and not sportsbook_refresh:
        odds_result = {
            "triggered": False,
            "reason": "BOOTSTRAP_REQUIRES_SPORTSBOOK_REFRESH",
        }
    elif sportsbook_refresh and bootstrap_core_cost:
        odds_result = perform_core_cost_bootstrap(requested_shape_id=bootstrap_shape_id)
    elif sportsbook_refresh:
        core_cost = get_core_request_cost_verification()
        guard = evaluate_optional_provider_request(
            estimated_credits=core_cost.get("coreOddsVerifiedRequestCost"),
            allow_unknown_credit_cost=bool(allow_unknown_credit_cost),
            allow_unknown_weekly_usage=bool(allow_unknown_weekly_usage),
            override_quota_guards=bool(override_quota_guards),
        )
        if not bool(guard.get("allowed")):
            odds_result = {
                "triggered": False,
                "reason": guard.get("reason"),
                "warnings": guard.get("warnings") or [],
                "quotaSafety": guard.get("quotaSafety"),
                "coreOddsRequestShapeId": core_cost.get("coreOddsRequestShapeId"),
                "coreOddsVerifiedRequestCost": core_cost.get("coreOddsVerifiedRequestCost"),
                "coreOddsCostVerificationStatus": core_cost.get("coreOddsCostVerificationStatus"),
            }
        else:
            odds_result = trigger_now()
            odds_result["warnings"] = guard.get("warnings") or []
            odds_result["quotaSafety"] = guard.get("quotaSafety")
            odds_result["coreOddsRequestShapeId"] = core_cost.get("coreOddsRequestShapeId")
            odds_result["coreOddsVerifiedRequestCost"] = core_cost.get("coreOddsVerifiedRequestCost")
            odds_result["coreOddsCostVerificationStatus"] = core_cost.get("coreOddsCostVerificationStatus")

    model_result = refresh_all_data()
    return {
        "success": model_result["success"],
        "duration": model_result["duration"],
        "gamesUpdated": model_result["gamesUpdated"],
        "opportunitiesUpdated": model_result["opportunitiesUpdated"],
        "timestamp": model_result["timestamp"],
        "oddsRefresh": odds_result,
    }
