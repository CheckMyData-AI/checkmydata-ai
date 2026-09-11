"""SSE endpoint for real-time workflow progress events.

Tenancy: subscribers only receive events for workflows they own or for
workflows belonging to a project they're a member of. Admin users
(``settings.admin_emails``) see everything.
"""

import asyncio
import logging
import time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.config import settings
from app.core.workflow_tracker import WorkflowEvent, tracker
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)

router = APIRouter()
_membership_svc = MembershipService()


async def _event_generator(
    queue: asyncio.Queue[WorkflowEvent],
    workflow_id_filter: str | None,
    *,
    max_seconds: float,
):
    """Yield SSE-formatted events from the queue, for at most *max_seconds*.

    The ceiling is not tidiness. FastAPI closes a yield dependency's exit stack
    only after the response is sent, and for a ``StreamingResponse`` that means
    after this generator finishes — so before API-02 an open tab held one pooled
    database connection for as long as it stayed open, on a route with no rate
    limit. The connection is returned before the loop starts now, and this bounds
    everything else the stream holds; EventSource reconnects on its own, so a
    client sees a reconnect rather than an end.
    """
    deadline = time.monotonic() + max_seconds
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                yield ": stream-max-duration reached, reconnect\n\n"
                return
            try:
                event = await asyncio.wait_for(queue.get(), timeout=min(30.0, remaining))
            except TimeoutError:
                yield ": keepalive\n\n"
                continue

            if workflow_id_filter and event.workflow_id != workflow_id_filter:
                continue

            yield f"event: step\ndata: {event.to_json()}\n\n"
    except asyncio.CancelledError:
        return
    except Exception:
        logger.warning("SSE event stream error", exc_info=True)
    finally:
        await tracker.unsubscribe(queue)


@router.get("/events")
async def workflow_events(
    workflow_id: str | None = Query(None, description="Filter to a specific workflow"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    is_admin = settings.is_admin_email(user.get("email"))
    if is_admin:
        queue = await tracker.subscribe()
    else:
        projects = await _membership_svc.get_accessible_projects(db, user["user_id"])
        accessible = frozenset(p.id for p in projects)
        queue = await tracker.subscribe(
            user_id=user["user_id"],
            accessible_project_ids=accessible,
        )
    # API-02: that SELECT autobegan a transaction and checked a connection out of
    # the pool, and the dependency's exit stack does not close until the generator
    # below finishes. Commit here and the connection goes back now, rather than
    # when the user closes the tab.
    await db.commit()
    return StreamingResponse(
        _event_generator(queue, workflow_id, max_seconds=settings.sse_max_stream_seconds),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
