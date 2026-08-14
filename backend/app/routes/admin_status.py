from fastapi import APIRouter

from app.services.admin_status import get_admin_status_service
from app.services.data_refresh import refresh_all_data
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
def trigger_refresh():
    # Trigger live odds + line movement via the orchestrator, then also
    # run the in-process data refresh for model-layer consistency.
    odds_result = trigger_now()
    model_result = refresh_all_data()
    return {
        "success": model_result["success"],
        "duration": model_result["duration"],
        "gamesUpdated": model_result["gamesUpdated"],
        "opportunitiesUpdated": model_result["opportunitiesUpdated"],
        "timestamp": model_result["timestamp"],
        "oddsRefresh": odds_result,
    }
