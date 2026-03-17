import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project import Project

logger = logging.getLogger(__name__)


class ProjectService:
    async def create(self, session: AsyncSession, **kwargs) -> Project:
        project = Project(**kwargs)
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return project

    async def get(self, session: AsyncSession, project_id: str) -> Project | None:
        result = await session.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.connections))
        )
        return result.scalar_one_or_none()

    async def list_all(self, session: AsyncSession) -> list[Project]:
        result = await session.execute(select(Project).order_by(Project.created_at.desc()))
        return list(result.scalars().all())

    async def update(self, session: AsyncSession, project_id: str, **kwargs) -> Project | None:
        project = await self.get(session, project_id)
        if not project:
            return None
        for key, value in kwargs.items():
            if hasattr(project, key) and value is not None:
                setattr(project, key, value)
        await session.commit()
        await session.refresh(project)
        return project

    async def delete(self, session: AsyncSession, project_id: str) -> bool:
        project = await self.get(session, project_id)
        if not project:
            return False
        try:
            await session.delete(project)
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.error("Cannot delete project %s: still referenced by child rows", project_id)
            raise
        return True
