"""Service for project membership (role-based access control)."""

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import audit_log
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
        """Return the user's role in the project, or None if they have no access.

        F-PROJ-02 / F-PROJ-14: `_accessible_filter` below calls itself the single source
        of truth for the access rule and states it as *owns OR is a member of*.
        `can_access` honoured that; this reader did not, so the same person could be
        admitted by one and refused by the other. Project creation writes the project
        and the owner's member row in separate commits, so a failure between them left
        `owner_id` pointing at somebody `require_role` then locked out of their own
        project — permanently, since there is no ownership-transfer path (F-PROJ-10).

        Where a member row disagrees with `owner_id`, the owner wins. Both mutation
        guards refuse to demote or remove an owner, so a non-owner row for the owner is
        unreachable by design; if one exists it is corruption, and the safe resolution
        of corruption is that the person named on the project can still reach it.
        """
        result = await db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        role = result.scalar_one_or_none()
        if role == "owner":
            return role
        owner_id = await db.scalar(select(Project.owner_id).where(Project.id == project_id))
        if owner_id is not None and owner_id == user_id:
            return "owner"
        return role

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

    async def update_member_role(
        self,
        db: AsyncSession,
        project_id: str,
        user_id: str,
        new_role: str,
    ) -> ProjectMember | None:
        """Change a non-owner member's role. Returns updated member or None."""
        result = await db.execute(
            select(ProjectMember)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
            .options(selectinload(ProjectMember.user))
        )
        member = result.scalar_one_or_none()
        if not member:
            return None
        if member.role == "owner":
            raise HTTPException(status_code=400, detail="Cannot change the owner's role")
        member.role = new_role
        await db.commit()
        await db.refresh(member, attribute_names=["user"])
        return member

    async def transfer_ownership(
        self,
        db: AsyncSession,
        project_id: str,
        *,
        new_owner_user_id: str,
        actor_user_id: str,
        actor_is_admin: bool = False,
    ) -> None:
        """Hand a project to another member (F-PROJ-10).

        Before this there was no path at all: ``update_member_role`` refuses to touch
        an owner and the route's schema accepts only ``editor``/``viewer``, so an
        owner could neither appoint a successor nor stop being one. Worse,
        ``Project.owner_id`` is ``ondelete="SET NULL"``, so deleting the account left
        a project with no owner and nobody able to appoint one — which is the
        stranded workspace the finding names, and why an admin may act here.

        Four things this does that a naive version would not:

        * **Both sources of truth move together.** ``get_role`` resolves owner from a
          member row *or* ``Project.owner_id``, so updating one leaves two owners —
          the new one by the column and the old one by the row — which is worse than
          having none.
        * **The receiving owner's quota is enforced.** Plan limits count projects by
          ``owner_id``, so a transfer that skips the check is a limit bypass wearing a
          feature's name. It runs *before* any write, so a refusal changes nothing.
        * **The target must already be a member.** Otherwise transfer doubles as a
          covert access grant; invite first, then transfer.
        * **The old owner is demoted, not removed.** Taking away someone's access is a
          different decision from taking away their ownership, and only one of them
          was asked for.
        """
        owner_id = await db.scalar(select(Project.owner_id).where(Project.id == project_id))
        member_owner = await db.scalar(
            select(ProjectMember.user_id).where(
                ProjectMember.project_id == project_id,
                ProjectMember.role == "owner",
            )
        )
        current_owner = owner_id or member_owner

        if not actor_is_admin and (current_owner is None or actor_user_id != current_owner):
            # An orphaned project reaches here with current_owner=None: nobody is the
            # owner, so nobody but an admin can appoint one. Claiming it yourself is
            # exactly the escalation this guard exists to refuse.
            raise HTTPException(
                status_code=403,
                detail="Only the project owner can transfer ownership",
            )

        if current_owner is not None and new_owner_user_id == current_owner:
            raise HTTPException(status_code=400, detail="That user already owns this project")

        target = await db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == new_owner_user_id,
            )
        )
        if target is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "The new owner must already be a member of this project — "
                    "invite them first, then transfer"
                ),
            )

        from app.services.entitlement_service import EntitlementService

        await EntitlementService().enforce_project_quota(db, new_owner_user_id)

        target.role = "owner"
        if current_owner is not None:
            existing = await db.scalar(
                select(ProjectMember).where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id == current_owner,
                )
            )
            if existing is not None:
                existing.role = "editor"
            else:
                db.add(
                    ProjectMember(
                        project_id=project_id,
                        user_id=current_owner,
                        role="editor",
                    )
                )
        await db.execute(
            update(Project).where(Project.id == project_id).values(owner_id=new_owner_user_id)
        )
        await db.commit()

        audit_log(
            "project.ownership_transferred",
            user_id=actor_user_id,
            project_id=project_id,
            resource_type="project",
            resource_id=project_id,
            detail="ownership transferred",
            previous_owner=current_owner or "none",
            new_owner=new_owner_user_id,
            by_admin=actor_is_admin,
        )

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

    @staticmethod
    def _accessible_filter(user_id: str):
        """Shared predicate: a project the user owns OR is a member of.

        Single source of truth for the access rule used by the HTTP API
        (``chat`` WebSocket gate) and the MCP tools so they cannot drift.
        """
        return or_(
            Project.owner_id == user_id,
            Project.id.in_(
                select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
            ),
        )

    async def can_access(
        self,
        db: AsyncSession,
        project_id: str,
        user_id: str,
    ) -> bool:
        """True when the user owns or is a member of the project."""
        if not user_id:
            return False
        result = await db.execute(
            select(Project.id).where(
                Project.id == project_id,
                self._accessible_filter(user_id),
            )
        )
        return result.scalar_one_or_none() is not None

    async def list_accessible(
        self,
        db: AsyncSession,
        user_id: str,
    ) -> list[Project]:
        """All projects the user owns or is a member of (owner-inclusive)."""
        if not user_id:
            return []
        result = await db.execute(
            select(Project)
            .where(self._accessible_filter(user_id))
            .order_by(Project.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_roles_bulk(
        self,
        db: AsyncSession,
        project_ids: list[str],
        user_id: str,
    ) -> dict[str, str]:
        """Return ``{project_id: role}`` for every project in *project_ids*.

        T17: single query that replaces the previous N+1 pattern of calling
        :meth:`get_role` in a loop (e.g. in ``GET /api/projects``).
        """
        if not project_ids:
            return {}
        result = await db.execute(
            select(ProjectMember.project_id, ProjectMember.role).where(
                ProjectMember.user_id == user_id,
                ProjectMember.project_id.in_(project_ids),
            )
        )
        roles = {row[0]: row[1] for row in result.all()}
        # Same rule as `get_role`, in one extra query rather than N (F-PROJ-02): a
        # bulk reader that disagreed with the single reader would put the divergence
        # on the project LIST, which is the first screen a locked-out owner sees.
        owned = await db.execute(
            select(Project.id).where(
                Project.id.in_(project_ids),
                Project.owner_id == user_id,
            )
        )
        for (pid,) in owned.all():
            roles[pid] = "owner"
        return roles
