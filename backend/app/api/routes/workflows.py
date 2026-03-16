"""SSE endpoint for real-time workflow progress events."""

import asyncio
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user
from app.core.workflow_tracker import WorkflowEvent, tracker

logger = logging.getLogger(__name__)

router = APIRouter()


async def _event_generator(
    queue: asyncio.Queue[WorkflowEvent],
    workflow_id_filter: str | None,
):
    """Yield SSE-formatted events from the queue."""
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue

            if workflow_id_filter and event.workflow_id != workflow_id_filter:
                continue

            yield f"event: step\ndata: {event.to_json()}\n\n"
    except asyncio.CancelledError:
        return
    finally:
        tracker.unsubscribe(queue)


@router.get("/events")
async def workflow_events(
    workflow_id: str | None = Query(None, description="Filter to a specific workflow"),
    user: dict = Depends(get_current_user),
):
    queue = tracker.subscribe()
    return StreamingResponse(
        _event_generator(queue, workflow_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
