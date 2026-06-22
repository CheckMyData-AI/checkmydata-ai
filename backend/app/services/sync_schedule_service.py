"""Effective per-project daily-sync schedule (project override → global default)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.project_service import ProjectService


class SyncScheduleService:
    def __init__(self) -> None:
        self._projects = ProjectService()

    async def effective(self, session: AsyncSession, project_id: str) -> dict[str, Any]:
        project = await self._projects.get(session, project_id)
        proj_enabled = getattr(project, "sync_schedule_enabled", None)
        proj_hour = getattr(project, "sync_schedule_hour", None)
        source = "project" if (proj_enabled is not None or proj_hour is not None) else "global"
        return {
            "enabled": (
                proj_enabled if proj_enabled is not None else settings.daily_knowledge_sync_enabled
            ),
            "hour": proj_hour if proj_hour is not None else settings.daily_knowledge_sync_hour,
            "timezone": settings.daily_knowledge_sync_timezone,
            "source": source,
        }

    async def set_override(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        enabled: bool | None,
        hour: int | None,
    ) -> dict[str, Any]:
        project = await self._projects.get(session, project_id)
        if project is None:
            raise KeyError(project_id)
        project.sync_schedule_enabled = enabled
        project.sync_schedule_hour = hour
        await session.commit()
        return await self.effective(session, project_id)
