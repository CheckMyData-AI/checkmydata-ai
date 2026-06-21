"""Read access to scheduled daily-sync run history."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_sync_run import KnowledgeSyncRun


class KnowledgeSyncRunService:
    """Query service for :class:`~app.models.knowledge_sync_run.KnowledgeSyncRun` records."""

    async def list_for_project(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        limit: int = 20,
    ) -> list[KnowledgeSyncRun]:
        """Return up to *limit* (clamped to 1–50) sync runs for *project_id*, newest first."""
        capped = max(1, min(limit, 50))
        result = await session.execute(
            select(KnowledgeSyncRun)
            .where(KnowledgeSyncRun.project_id == project_id)
            .order_by(KnowledgeSyncRun.created_at.desc())
            .limit(capped)
        )
        return list(result.scalars().all())
