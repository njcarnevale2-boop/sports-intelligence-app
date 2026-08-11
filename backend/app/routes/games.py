from fastapi import APIRouter, Query

from app.services.games import service

router = APIRouter(prefix="/api", tags=["games"])


@router.get("/games")
def list_games(
    week: int | None = Query(default=None),
    date: str | None = Query(default=None),
) -> dict:
    games = service.list_games(week=week, date=date)
    return {
        "count": len(games),
        "week": week,
        "date": date,
        "games": games,
    }
