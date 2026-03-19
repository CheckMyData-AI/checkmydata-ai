"""Load and save ProjectKnowledge + ProjectProfile between index runs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.project_cache import ProjectCache

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.knowledge.entity_extractor import ProjectKnowledge
    from app.knowledge.project_profiler import ProjectProfile

logger = logging.getLogger(__name__)


class ProjectCacheService:
    async def load_knowledge(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> ProjectKnowledge | None:
        from app.knowledge.entity_extractor import ProjectKnowledge as PKnow

        cache = await self._get_row(session, project_id)
        if not cache or cache.knowledge_json in ("{}", ""):
            return None
        try:
            return PKnow.from_json(cache.knowledge_json)
        except Exception:
            logger.warning("Failed to deserialize cached knowledge", exc_info=True)
            return None

    async def load_profile(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> ProjectProfile | None:
        from app.knowledge.project_profiler import ProjectProfile as PProf

        cache = await self._get_row(session, project_id)
        if not cache or cache.profile_json in ("{}", ""):
            return None
        try:
            return PProf.from_json(cache.profile_json)
        except Exception:
            logger.warning("Failed to deserialize cached profile", exc_info=True)
            return None

    async def save(
        self,
        session: AsyncSession,
        project_id: str,
        knowledge: ProjectKnowledge | None = None,
        profile: ProjectProfile | None = None,
    ) -> None:
        existing = await self._get_row(session, project_id)

        if existing:
            if knowledge is not None:
                existing.knowledge_json = knowledge.to_json()
            if profile is not None:
                existing.profile_json = profile.to_json()
        else:
            row = ProjectCache(
                project_id=project_id,
                knowledge_json=knowledge.to_json() if knowledge else "{}",
                profile_json=profile.to_json() if profile else "{}",
            )
            session.add(row)

        await session.commit()

    async def _get_row(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> ProjectCache | None:
        result = await session.execute(
            select(ProjectCache).where(ProjectCache.project_id == project_id)
        )
        return result.scalar_one_or_none()
