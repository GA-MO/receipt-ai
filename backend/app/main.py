import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import create_tables
from .routers import dashboard, documents

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
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
