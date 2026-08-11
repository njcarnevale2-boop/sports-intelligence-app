from fastapi import APIRouter

from app.services.data_refresh import refresh_all_data


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/refresh")
def refresh_endpoint():
    result = refresh_all_data()
    return {
        "success": result["success"],
        "duration": result["duration"],
        "gamesUpdated": result["gamesUpdated"],
        "opportunitiesUpdated": result["opportunitiesUpdated"],
        "timestamp": result["timestamp"],
    }
