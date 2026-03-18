"""CRUD service for ProjectRepository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import ProjectRepository


class RepositoryService:
    """Manage project repositories."""

    async def create(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        name: str,
        repo_url: str,
        branch: str = "main",
        provider: str = "git_ssh",
        ssh_key_id: str | None = None,
        auth_token_encrypted: str | None = None,
    ) -> ProjectRepository:
        repo = ProjectRepository(
            id=str(uuid.uuid4()),
            project_id=project_id,
            name=name,
            provider=provider,
            repo_url=repo_url,
            branch=branch,
            ssh_key_id=ssh_key_id,
            auth_token_encrypted=auth_token_encrypted,
        )
        session.add(repo)
        await session.commit()
        await session.refresh(repo)
        return repo

    async def list_by_project(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> Sequence[ProjectRepository]:
        result = await session.execute(
            select(ProjectRepository)
            .where(ProjectRepository.project_id == project_id)
            .order_by(ProjectRepository.created_at)
        )
        return result.scalars().all()

    async def get(self, session: AsyncSession, repo_id: str) -> ProjectRepository | None:
        result = await session.execute(
            select(ProjectRepository).where(ProjectRepository.id == repo_id)
        )
        return result.scalar_one_or_none()

    ALLOWED_UPDATE_FIELDS = {"repo_url", "branch", "name", "ssh_key_id"}

    async def update(
        self,
        session: AsyncSession,
        repo_id: str,
        **kwargs,
    ) -> ProjectRepository | None:
        repo = await self.get(session, repo_id)
        if not repo:
            return None
        for key, value in kwargs.items():
            if key in self.ALLOWED_UPDATE_FIELDS:
                setattr(repo, key, value)
        await session.commit()
        await session.refresh(repo)
        return repo

    async def delete(self, session: AsyncSession, repo_id: str) -> bool:
        repo = await self.get(session, repo_id)
        if not repo:
            return False
        await session.delete(repo)
        await session.commit()
        return True
