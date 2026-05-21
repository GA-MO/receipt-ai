import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import SessionLocal, create_tables
from .routers import aliases, autocomplete, dashboard, documents, products, push, stores, visits
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
    logger.info("Application started — upload_dir=%s", settings.upload_dir)
    yield
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

app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(stores.router, prefix="/api/stores", tags=["stores"])
app.include_router(visits.router, prefix="/api/visits", tags=["visits"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(push.router, prefix="/api/push", tags=["push"])
app.include_router(aliases.router, prefix="/api/aliases", tags=["aliases"])
app.include_router(autocomplete.router, prefix="/api/autocomplete", tags=["autocomplete"])
app.include_router(products.router, prefix="/api/products", tags=["products"])
