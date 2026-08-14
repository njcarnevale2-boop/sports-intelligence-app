from fastapi import APIRouter

from app.services.social_intelligence import social_intelligence_service


router = APIRouter(prefix="/api", tags=["social-intelligence"])


@router.get("/games/{event_id}/social-intelligence")
def get_game_social_intelligence(event_id: str):
    return social_intelligence_service.get_game_social_context(event_id)