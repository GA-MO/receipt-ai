"""In-process pub/sub for document status events.

Used by the SSE endpoint to push extraction progress to the frontend without
polling. When running with the arq worker (separate process) we fall back to
Redis pub/sub via ``redis_publish`` so the API process can forward events to
clients.

The public surface is deliberately small:

* ``event_bus.publish(doc_id, payload)`` — called from processing code
* ``event_bus.subscribe(doc_id) -> AsyncIterator`` — called from SSE handler
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any

from .config import settings

logger = logging.getLogger(__name__)


class _EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._lock = asyncio.Lock()

    def publish(self, doc_id: str, payload: dict[str, Any]) -> None:
        """Fan out an event to local subscribers and to Redis if configured."""
        self._publish_local(doc_id, payload)
        if settings.use_arq:
            self._publish_redis(doc_id, payload)

    def _publish_local(self, doc_id: str, payload: dict[str, Any]) -> None:
        queues = self._subscribers.get(doc_id, [])
        for q in list(queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("Event queue full for %s; dropping event", doc_id)

    def _publish_redis(self, doc_id: str, payload: dict[str, Any]) -> None:
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url)
            client.publish(
                _redis_channel(doc_id),
                json.dumps(payload, ensure_ascii=False),
            )
        except Exception as exc:
            logger.warning("Failed to publish event to Redis: %s", exc)

    async def subscribe(self, doc_id: str) -> AsyncIterator[dict[str, Any]]:
        """Async iterator of events for a specific document."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=16)
        async with self._lock:
            self._subscribers[doc_id].append(queue)

        redis_task: asyncio.Task | None = None
        if settings.use_arq:
            redis_task = asyncio.create_task(_forward_redis(doc_id, queue))

        try:
            while True:
                payload = await queue.get()
                yield payload
        finally:
            async with self._lock:
                if queue in self._subscribers.get(doc_id, []):
                    self._subscribers[doc_id].remove(queue)
                if not self._subscribers[doc_id]:
                    self._subscribers.pop(doc_id, None)
            if redis_task:
                redis_task.cancel()


def _redis_channel(doc_id: str) -> str:
    return f"receipt-events:{doc_id}"


async def _forward_redis(doc_id: str, queue: asyncio.Queue) -> None:
    """Forward Redis pub/sub messages to a local asyncio queue."""
    try:
        import redis.asyncio as redis_async

        client = redis_async.from_url(settings.redis_url)
        pubsub = client.pubsub()
        await pubsub.subscribe(_redis_channel(doc_id))
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                payload = json.loads(message["data"])
            except (TypeError, json.JSONDecodeError):
                continue
            await queue.put(payload)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Redis subscriber for %s failed: %s", doc_id, exc)


event_bus = _EventBus()
