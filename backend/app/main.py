from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.opportunities import router as opportunities_router
from app.routes.context import router as context_router
from app.routes.injuries import router as injuries_router
from app.routes.admin import router as admin_router
from database.session import init_db

app = FastAPI(
    title="Sports Intelligence API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(opportunities_router)
app.include_router(context_router)
app.include_router(injuries_router)
app.include_router(admin_router)


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