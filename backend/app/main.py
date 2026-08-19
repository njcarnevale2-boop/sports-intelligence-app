import logging
import os
import json
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

from app.routes.opportunities import router as opportunities_router
from app.routes.context import router as context_router
from app.routes.injuries import router as injuries_router
from app.routes.admin import router as admin_router
from app.routes.admin_status import router as admin_status_router
from app.routes.auth import router as auth_router
from app.routes.performance import router as performance_router
from app.routes.analytics import router as analytics_router
from app.routes.games import router as games_router
from app.routes.recommendation_snapshot import router as recommendation_snapshot_router
from app.routes.decision_ledger import router as decision_ledger_router
from app.routes.social import router as social_router
from app.routes.ask_sia import router as ask_sia_router
from app.routes.move_the_line import router as move_the_line_router
from app.routes.shadow_markets import router as shadow_markets_router
from database.session import init_db

app = FastAPI(
    title="Sports Intelligence API",
    version="0.1.0",
)

_ = settings


def parse_cors_origins(raw: str | None) -> list[str]:
    default_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
    if not raw:
        return default_origins

    value = raw.strip()
    if not value:
        return default_origins

    # Support JSON array style env values in addition to comma-separated strings.
    if value.startswith("["):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                origins = [str(origin).strip() for origin in parsed if str(origin).strip()]
                return origins or default_origins
        except json.JSONDecodeError:
            pass

    origins = [origin.strip() for origin in value.split(",") if origin.strip()]
    return origins or default_origins


cors_origins = parse_cors_origins(os.getenv("CORS_ORIGINS"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
)

app.include_router(opportunities_router)
app.include_router(context_router)
app.include_router(injuries_router)
app.include_router(admin_router)
app.include_router(admin_status_router)
app.include_router(auth_router)
app.include_router(performance_router)
app.include_router(analytics_router)
app.include_router(games_router)
app.include_router(social_router)
app.include_router(recommendation_snapshot_router)
app.include_router(decision_ledger_router)
app.include_router(ask_sia_router)
app.include_router(move_the_line_router)
app.include_router(shadow_markets_router)


@app.on_event("startup")
def startup_event() -> None:
    try:
        init_db()
    except Exception:
        pass
    from app.services.refresh_orchestrator import start_scheduler
    from app.services.market_data import market_data_service

    logger = logging.getLogger("startup")
    logging.basicConfig(level=logging.INFO)

    logger.info("Market data warm-up: starting")
    t0 = time.perf_counter()
    try:
        rows = market_data_service.load_normalized_market_rows()
        snapshots = market_data_service.all_event_snapshots()
        elapsed_md = time.perf_counter() - t0

        from app.services.market_intelligence import build_market_intelligence_lookup
        t1 = time.perf_counter()
        build_market_intelligence_lookup()
        elapsed_mi = time.perf_counter() - t1

        elapsed = time.perf_counter() - t0
        logger.info(
            "Market data warm-up: complete in %.2fs (market_data=%.2fs, market_intelligence=%.2fs) — %d rows, %d events",
            elapsed,
            elapsed_md,
            elapsed_mi,
            len(rows),
            len(snapshots),
        )
    except Exception as exc:  # noqa: BLE001
        elapsed = time.perf_counter() - t0
        logger.warning(
            "Market data warm-up: failed after %.2fs (%s) — cold-start latency expected",
            elapsed,
            exc,
        )

    start_scheduler()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "sports-intelligence-api",
    }