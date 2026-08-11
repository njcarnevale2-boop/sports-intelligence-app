from fastapi import APIRouter

from app.services.admin_status import get_admin_status_service
from app.services.data_refresh import refresh_all_data


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/status")
def get_admin_status():
    service = get_admin_status_service()
    return service.get_status()


@router.post("/refresh")
def trigger_refresh():
    result = refresh_all_data()
    return {
        "success": result["success"],
        "duration": result["duration"],
        "gamesUpdated": result["gamesUpdated"],
        "opportunitiesUpdated": result["opportunitiesUpdated"],
        "timestamp": result["timestamp"],
    }
