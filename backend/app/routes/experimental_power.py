from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.services.experimental_power import ExperimentalPowerUnavailable, load_experimental_power


router = APIRouter(prefix="/api/experimental", tags=["experimental-power"])


@router.get("/power-projections")
def experimental_power(season: int = Query(ge=2000, le=2100), week: int = Query(ge=1, le=18)):
    try:
        payload = load_experimental_power(season=season, week=week)
    except ExperimentalPowerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return JSONResponse(content=payload, headers={"Cache-Control": "no-store"})