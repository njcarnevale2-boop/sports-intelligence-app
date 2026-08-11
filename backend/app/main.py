import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.opportunities import router as opportunities_router
from app.routes.context import router as context_router
from app.routes.injuries import router as injuries_router
from app.routes.admin import router as admin_router
from app.routes.admin_status import router as admin_status_router
from app.routes.auth import router as auth_router
from app.routes.performance import router as performance_router
from app.routes.analytics import router as analytics_router
from database.session import init_db

app = FastAPI(
    title="Sports Intelligence API",
    version="0.1.0",
)

cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(opportunities_router)
app.include_router(context_router)
app.include_router(injuries_router)
app.include_router(admin_router)
app.include_router(admin_status_router)
app.include_router(auth_router)
app.include_router(performance_router)
app.include_router(analytics_router)


@app.on_event("startup")
def startup_event() -> None:
    try:
        init_db()
    except Exception:
        pass


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "sports-intelligence-api",
    }