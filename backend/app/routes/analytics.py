from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.services.analytics import AnalyticsService
from database.session import SessionLocal

router = APIRouter(prefix="/api", tags=["analytics"])
service = AnalyticsService()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/analytics/events")
def record_event(payload: dict, db: Session = Depends(get_db)) -> dict:
    service.record_event(
        event_type=payload.get("eventType"),
        page=payload.get("page"),
        opportunity_id=payload.get("opportunityId"),
        user_id=payload.get("userId"),
        metadata=payload.get("metadata") or {},
    )
    return {"success": True}


@router.get("/admin/analytics")
def admin_analytics() -> dict:
    return service.get_admin_summary()
