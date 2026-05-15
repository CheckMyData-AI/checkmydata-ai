import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project import Project

logger = logging.getLogger(__name__)


class ProjectService:
    # Fields that callers are allowed to change via :meth:`update`.
    # Everything else (``id``, ``owner_id``, timestamps, relationship-backed
    # columns) must be changed through an explicit, purpose-built method —
    # never through a kwargs-driven ``update``.
    UPDATABLE_FIELDS: frozenset[str] = frozenset(
        {
            "name",
            "description",
            "repo_url",
            "repo_branch",
            "ssh_key_id",
            "indexing_llm_provider",
            "indexing_llm_model",
            "agent_llm_provider",
            "agent_llm_model",
            "sql_llm_provider",
            "sql_llm_model",
            "max_orchestrator_steps",
            "default_rule_initialized",
        }
    )

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
        """Update whitelisted fields only.

        Unknown keys or attempts to set protected columns (``id``,
        ``owner_id``, timestamps, …) are silently ignored — they do not
        mutate the row. Pass value ``None`` to leave the field untouched.
        """
        project = await self.get(session, project_id)
        if not project:
            return None

        rejected: list[str] = []
        for key, value in kwargs.items():
            if value is None:
                continue
            if key not in self.UPDATABLE_FIELDS:
                rejected.append(key)
                continue
            setattr(project, key, value)

        if rejected:
            logger.warning(
                "ProjectService.update rejected non-whitelisted fields for project %s: %s",
                project_id,
                sorted(rejected),
            )

        await session.commit()
        await session.refresh(project)
        return project

    async def delete(self, session: AsyncSession, project_id: str) -> bool:
        project = await self.get(session, project_id)
        if not project:
            return False
        # Collect connection ids before cascade fires so we can wipe per-connection
        # schema BM25 snapshots after the row is gone.
        connection_ids = [c.id for c in (project.connections or [])]
        try:
            await session.delete(project)
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.error("Cannot delete project %s: still referenced by child rows", project_id)
            raise
        # Best-effort cleanup of on-disk + Chroma artifacts. The DB cascade has
        # already wiped tables (FK ON DELETE CASCADE); the artifacts below are
        # not cascaded by Postgres and would otherwise leak across re-creates.
        try:
            from app.services.indexing_artifacts import (
                cleanup_connection_artifacts,
                cleanup_project_artifacts,
            )

            cleanup_project_artifacts(project_id)
            for cid in connection_ids:
                cleanup_connection_artifacts(cid)
        except Exception:
            logger.warning(
                "ProjectService.delete: artifact cleanup failed for project %s",
                project_id,
                exc_info=True,
            )
        return True
