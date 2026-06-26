"""Owner-attributed budget gate + usage sink for the code↔DB sync pipeline (H5)."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm.usage_sink import DbUsageSink
from app.models.project import Project
from app.services.usage_service import UsageService

logger = logging.getLogger(__name__)
_usage_svc = UsageService()


async def resolve_owner_user_id(session: AsyncSession, project_id: str) -> str | None:
    """Resolve a project's owner user ID.

    Returns None on any DB error so callers degrade gracefully instead of crashing.
    """
    try:
        row = await session.execute(select(Project.owner_id).where(Project.id == project_id))
        return row.scalar_one_or_none()
    except Exception:
        logger.debug(
            "sync budget: could not resolve owner for project %s — unenforced",
            project_id[:8],
            exc_info=True,
        )
        return None


def build_sink(owner_user_id: str, project_id: str) -> DbUsageSink:
    """Build a usage sink attributed to the owner."""
    return DbUsageSink(user_id=owner_user_id, project_id=project_id)


async def preflight_owner_budget(
    session: AsyncSession, project_id: str
) -> tuple[bool, str | None, str | None]:
    """Pre-flight budget check for sync operations (C1: graceful degradation when owner missing).

    Returns (ok, reason, owner_user_id):
    - ok=True, reason=None: proceed (enforced pass or unenforced)
    - ok=False, reason=msg: blocked (budget exceeded)
    """
    owner_id = await resolve_owner_user_id(session, project_id)
    if not owner_id:
        logger.warning("sync budget unenforced: project %s has no owner", project_id[:8])
        return True, None, None  # C1: degrade (unenforced), do NOT block
    if not settings.sync_budget_enforcement_enabled:
        return True, None, owner_id
    msg = await _usage_svc.check_token_budget(session, owner_id)
    return (False, msg, owner_id) if msg else (True, None, owner_id)
