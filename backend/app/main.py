import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import SessionLocal, create_tables
from .routers import aliases, autocomplete, documents, inbox, products, stores, visits
from .scripts.seed_products import seed_if_empty

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs("data", exist_ok=True)
    create_tables()
    # Auto-seed the product catalog if the table is empty (e.g. fresh DB,
    # after a manual wipe, or after the first deploy). Idempotent no-op
    # when rows already exist.
    try:
        db = SessionLocal()
        try:
            seed_if_empty(db)
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Product auto-seed failed: %s", exc)
    # A previous process may have died mid-batch; pick that work back up.
    try:
        from .routers.documents import requeue_stuck_documents

        requeued = requeue_stuck_documents()
        if requeued:
            logger.info("Requeued %d document(s) stranded in processing", requeued)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Requeue of stuck documents failed: %s", exc)
    logger.info("Application started — upload_dir=%s", settings.upload_dir)
    yield
    # Drain in-flight extractions so we don't drop work on reload/SIGTERM.
    from .routers.documents import shutdown_extraction_pool

    shutdown_extraction_pool()
    logger.info("Application shutdown")


app = FastAPI(
    title="Thai Receipt Intelligence",
    description="AI-powered Thai receipt and sales document extraction",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health", tags=["ops"])
def health() -> dict:
    """Liveness/readiness probe: reports whether the DB answers, not just
    whether the process is up — a pod that cannot reach its volume is not
    ready, and restarting it is the right response."""
    from sqlalchemy import text

    from .database import engine

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}") from exc
    return {"status": "ok", "model": settings.openrouter_model}


app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(stores.router, prefix="/api/stores", tags=["stores"])
app.include_router(visits.router, prefix="/api/visits", tags=["visits"])
app.include_router(inbox.router, prefix="/api/inbox", tags=["inbox"])
app.include_router(aliases.router, prefix="/api/aliases", tags=["aliases"])
app.include_router(autocomplete.router, prefix="/api/autocomplete", tags=["autocomplete"])
app.include_router(products.router, prefix="/api/products", tags=["products"])
