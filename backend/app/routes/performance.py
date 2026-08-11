from fastapi import APIRouter

from app.services.performance import get_performance_service


router = APIRouter(prefix="/api", tags=["performance"])


@router.post("/performance/track")
def track_recommendation(payload: dict):
    service = get_performance_service()
    record = service.track_recommendation(payload)
    return {
        "success": True,
        "recordId": record.id,
    }


@router.get("/performance")
def get_performance():
    service = get_performance_service()
    return service.get_performance_summary()
