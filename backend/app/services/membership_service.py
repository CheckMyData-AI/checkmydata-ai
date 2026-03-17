"""Service for project membership (role-based access control)."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project import Project
from app.models.project_member import ProjectMember

ROLE_HIERARCHY = {"owner": 3, "editor": 2, "viewer": 1}


class MembershipService:
    async def get_role(
        self,
        db: AsyncSession,
        project_id: str,
        user_id: str,
    ) -> str | None:
        """Return the user's role in the project, or None if not a member."""
        result = await db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def require_role(
        self,
        db: AsyncSession,
        project_id: str,
        user_id: str,
        min_role: str = "viewer",
    ) -> str:
        """Return the role if sufficient, otherwise raise 403."""
        role = await self.get_role(db, project_id, user_id)
        if role is None:
            raise HTTPException(status_code=403, detail="Not a member of this project")
        if ROLE_HIERARCHY.get(role, 0) < ROLE_HIERARCHY.get(min_role, 0):
            raise HTTPException(
                status_code=403,
                detail=f"Requires at least '{min_role}' role",
            )
        return role

    async def add_member(
        self,
        db: AsyncSession,
        project_id: str,
        user_id: str,
        role: str = "viewer",
    ) -> ProjectMember:
        existing = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        member = existing.scalar_one_or_none()
        if member:
            member.role = role
        else:
            member = ProjectMember(
                project_id=project_id,
                user_id=user_id,
                role=role,
            )
            db.add(member)
        await db.commit()
        await db.refresh(member)
        return member

    async def remove_member(
        self,
        db: AsyncSession,
        project_id: str,
        user_id: str,
    ) -> bool:
        result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            return False
        if member.role == "owner":
            raise HTTPException(status_code=400, detail="Cannot remove the project owner")
        await db.delete(member)
        await db.commit()
        return True

    async def list_members(
        self,
        db: AsyncSession,
        project_id: str,
    ) -> list[ProjectMember]:
        result = await db.execute(
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id)
            .options(selectinload(ProjectMember.user))
        )
        return list(result.scalars().all())

    async def get_accessible_projects(
        self,
        db: AsyncSession,
        user_id: str,
    ) -> list[Project]:
        result = await db.execute(
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
        )
        return list(result.scalars().all())
