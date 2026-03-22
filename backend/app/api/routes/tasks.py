"""Endpoint for querying currently running background tasks."""

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_current_user
from app.core.rate_limit import limiter
from app.core.workflow_tracker import tracker

router = APIRouter()


@router.get("/active")
@limiter.limit("60/minute")
async def get_active_tasks(request: Request, user: dict = Depends(get_current_user)):
    """Return all currently running background workflows (index_repo, db_index, code_db_sync)."""
    return tracker.get_active()
