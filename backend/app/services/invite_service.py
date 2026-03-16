"""Service for email-based project invitations."""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project_invite import ProjectInvite
from app.models.project_member import ProjectMember
from app.models.user import User


class InviteService:
    async def create_invite(
        self,
        db: AsyncSession,
        project_id: str,
        email: str,
        role: str,
        invited_by: str,
    ) -> ProjectInvite:
        email = email.lower().strip()

        existing_member = await db.execute(
            select(ProjectMember)
            .join(User, ProjectMember.user_id == User.id)
            .where(
                and_(
                    ProjectMember.project_id == project_id,
                    User.email == email,
                )
            )
        )
        if existing_member.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="User is already a member")

        existing_invite = await db.execute(
            select(ProjectInvite).where(
                and_(
                    ProjectInvite.project_id == project_id,
                    ProjectInvite.email == email,
                    ProjectInvite.status == "pending",
                )
            )
        )
        if existing_invite.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Invite already pending for this email")

        invite = ProjectInvite(
            project_id=project_id,
            email=email,
            invited_by=invited_by,
            role=role,
            status="pending",
        )
        db.add(invite)
        await db.commit()
        await db.refresh(invite)
        return invite

    async def list_invites(
        self, db: AsyncSession, project_id: str,
    ) -> list[ProjectInvite]:
        result = await db.execute(
            select(ProjectInvite).where(ProjectInvite.project_id == project_id)
        )
        return list(result.scalars().all())

    async def revoke_invite(
        self, db: AsyncSession, invite_id: str, _user_id: str,
    ) -> bool:
        result = await db.execute(
            select(ProjectInvite).where(ProjectInvite.id == invite_id)
        )
        invite = result.scalar_one_or_none()
        if not invite:
            return False
        if invite.status != "pending":
            raise HTTPException(status_code=400, detail="Only pending invites can be revoked")
        invite.status = "revoked"
        await db.commit()
        return True

    async def accept_invite(
        self, db: AsyncSession, invite_id: str, user_id: str,
        *, _skip_email_check: bool = False,
    ) -> ProjectMember:
        result = await db.execute(
            select(ProjectInvite).where(ProjectInvite.id == invite_id)
        )
        invite = result.scalar_one_or_none()
        if not invite:
            raise HTTPException(status_code=404, detail="Invite not found")
        if invite.status != "pending":
            raise HTTPException(status_code=400, detail="Invite is no longer pending")

        if not _skip_email_check:
            user_result = await db.execute(select(User).where(User.id == user_id))
            user_obj = user_result.scalar_one_or_none()
            if not user_obj or user_obj.email.lower().strip() != invite.email.lower().strip():
                raise HTTPException(
                    status_code=403,
                    detail="This invite is for a different email address",
                )

        invite.status = "accepted"
        invite.accepted_at = datetime.now(timezone.utc)

        existing = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == invite.project_id,
                ProjectMember.user_id == user_id,
            )
        )
        member = existing.scalar_one_or_none()
        if member:
            await db.commit()
            return member

        member = ProjectMember(
            project_id=invite.project_id,
            user_id=user_id,
            role=invite.role,
        )
        db.add(member)
        await db.commit()
        await db.refresh(member)
        return member

    async def list_pending_for_email(
        self, db: AsyncSession, email: str,
    ) -> list[ProjectInvite]:
        result = await db.execute(
            select(ProjectInvite).where(
                and_(
                    ProjectInvite.email == email.lower().strip(),
                    ProjectInvite.status == "pending",
                )
            )
        )
        return list(result.scalars().all())

    async def auto_accept_for_user(
        self, db: AsyncSession, user_id: str, email: str,
    ) -> list[ProjectMember]:
        """Auto-accept all pending invites for a newly registered email.

        Skips the email ownership check since the caller already verified identity.
        """
        pending = await self.list_pending_for_email(db, email)
        members = []
        for invite in pending:
            member = await self.accept_invite(db, invite.id, user_id, _skip_email_check=True)
            members.append(member)
        return members
