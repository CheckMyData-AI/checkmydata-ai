"""Endpoint for querying currently running background tasks."""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.workflow_tracker import tracker

router = APIRouter()


@router.get("/active")
async def get_active_tasks(user: dict = Depends(get_current_user)):
    """Return all currently running background workflows (index_repo, db_index, code_db_sync)."""
    return tracker.get_active()
