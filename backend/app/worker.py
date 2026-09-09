"""arq worker: durable background processing for document extraction.

Run with:

    cd backend && .venv/bin/arq app.worker.WorkerSettings

or ``make worker``. Requires Redis.

When ``settings.use_arq`` is true, the upload/re-extract endpoints enqueue a
job here via :func:`enqueue_process_document`. Otherwise they fall back to
FastAPI BackgroundTasks (good for local dev with zero infra).
"""

from __future__ import annotations

import logging
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings

from .config import settings

logger = logging.getLogger(__name__)


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url)


async def process_document_task(ctx: dict[str, Any], doc_id: str, file_path: str) -> None:
    """arq job that wraps the shared processing logic."""
    # Import lazily to avoid circular imports at module load time.
    from .routers.documents import _run_processing

    logger.info("arq: processing doc %s (attempt %s)", doc_id, ctx.get("job_try"))
    _run_processing(doc_id, file_path)


class WorkerSettings:
    """arq discovers this class via ``arq app.worker.WorkerSettings``."""

    functions = [process_document_task]
    redis_settings = _redis_settings()
    max_jobs = settings.extraction_concurrency  # EXTRACTION_CONCURRENCY
    job_timeout = 300  # 5 min hard cap per document
    keep_result = 3600  # keep results for 1 hour for debugging


# ---------------------------------------------------------------------------
# Producer side (called from the FastAPI app)
# ---------------------------------------------------------------------------

_pool = None


async def _get_pool():
    global _pool
    if _pool is None:
        _pool = await create_pool(_redis_settings())
    return _pool


def enqueue_process_document(doc_id: str, file_path: str) -> None:
    """Enqueue a process_document_task job from sync code."""
    import asyncio

    async def _enqueue() -> None:
        pool = await _get_pool()
        await pool.enqueue_job("process_document_task", doc_id, file_path)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(_enqueue(), loop).result(timeout=5)
    else:
        asyncio.run(_enqueue())
