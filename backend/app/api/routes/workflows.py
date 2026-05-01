"""SSE endpoint for real-time workflow progress events.

Tenancy: subscribers only receive events for workflows they own or for
workflows belonging to a project they're a member of. Admin users
(``settings.admin_emails``) see everything.
"""

import asyncio
import logging

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
    return StreamingResponse(
        _event_generator(queue, workflow_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
