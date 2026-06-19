"""Cross-process workflow event bridge via Redis pub/sub (ARQ worker → API SSE)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.workflow_tracker import WorkflowEvent

logger = logging.getLogger(__name__)

WORKFLOW_EVENTS_CHANNEL = "cmd:workflow_events"

_subscriber_task: asyncio.Task[None] | None = None


async def publish_workflow_event(event: WorkflowEvent) -> None:
    """Publish a workflow event to Redis for API-process SSE subscribers."""
    from app.core import redis_client

    client = redis_client.get_redis()
    if client is None:
        return
    try:
        await client.publish(WORKFLOW_EVENTS_CHANNEL, event.to_json())
    except Exception:
        logger.debug("Failed to publish workflow event to Redis", exc_info=True)


async def _subscribe_loop() -> None:
    from app.core import redis_client
    from app.core.workflow_tracker import WorkflowEvent, tracker

    client = redis_client.get_redis()
    if client is None:
        return

    pubsub = client.pubsub()
    await pubsub.subscribe(WORKFLOW_EVENTS_CHANNEL)
    logger.info("Subscribed to workflow events channel: %s", WORKFLOW_EVENTS_CHANNEL)

    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            raw = message.get("data")
            if not raw:
                continue
            try:
                payload = json.loads(raw)
                event = WorkflowEvent(**payload)
            except Exception:
                logger.debug("Invalid workflow event payload from Redis", exc_info=True)
                continue
            await tracker.broadcast_external(event)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("Workflow events subscribe loop failed", exc_info=True)
    finally:
        try:
            await pubsub.unsubscribe(WORKFLOW_EVENTS_CHANNEL)
            await pubsub.aclose()
        except Exception:
            logger.debug("Error closing workflow pubsub", exc_info=True)


async def start_workflow_event_subscriber() -> None:
    """Start the API-process Redis subscriber (no-op without Redis)."""
    global _subscriber_task  # noqa: PLW0603

    from app.core import redis_client

    if redis_client.get_redis() is None:
        return
    if _subscriber_task is not None and not _subscriber_task.done():
        return
    _subscriber_task = asyncio.create_task(_subscribe_loop(), name="workflow_events_sub")


async def stop_workflow_event_subscriber() -> None:
    global _subscriber_task  # noqa: PLW0603

    if _subscriber_task is None:
        return
    if not _subscriber_task.done():
        _subscriber_task.cancel()
        try:
            await _subscriber_task
        except asyncio.CancelledError:
            pass
    _subscriber_task = None
