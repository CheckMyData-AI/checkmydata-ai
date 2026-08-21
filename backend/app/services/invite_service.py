"""Service for email-based project invitations."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.project_invite import ProjectInvite
from app.models.project_member import ProjectMember
from app.models.user import User

logger = logging.getLogger(__name__)


def _aware_dt(value: datetime) -> datetime:
    """SQLite reads timestamps back naive; compare in UTC either way."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def invite_expires_at(invite: ProjectInvite) -> datetime:
    """When *invite* stops being acceptable (F-PROJ-04).

    A NULL ``expires_at`` is read as ``created_at + invite_expiry_days`` rather than as
    "never": rows predating the column are exactly the stale invites the finding is
    about, so the policy applies to their real creation time and no backfill is needed.
    """
    if invite.expires_at is not None:
        return _aware_dt(invite.expires_at)
    return _aware_dt(invite.created_at) + timedelta(days=settings.invite_expiry_days)


def invite_is_expired(invite: ProjectInvite, *, now: datetime | None = None) -> bool:
    """True when *invite* is past its window."""
    return (now or datetime.now(UTC)) >= invite_expires_at(invite)


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
            # F-PROJ-06: "already pending" reads as *already done*, which is exactly the
            # wrong conclusion for the person most likely to see it — somebody retrying
            # because they suspect the first email never arrived. Name the way out.
            raise HTTPException(
                status_code=409,
                detail=(
                    "An invite is already pending for this email. If it never arrived, "
                    "resend it from the project's members list rather than creating a "
                    "second one."
                ),
            )

        invite = ProjectInvite(
            project_id=project_id,
            email=email,
            invited_by=invited_by,
            role=role,
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(days=settings.invite_expiry_days),
        )
        db.add(invite)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=409, detail="Invite already pending for this email")

        result = await db.execute(
            select(ProjectInvite)
            .options(selectinload(ProjectInvite.inviter), selectinload(ProjectInvite.project))
            .where(ProjectInvite.id == invite.id)
        )
        return result.scalar_one()

    async def get_pending_invite(
        self,
        db: AsyncSession,
        invite_id: str,
        project_id: str,
    ) -> ProjectInvite | None:
        result = await db.execute(
            select(ProjectInvite)
            .options(selectinload(ProjectInvite.inviter), selectinload(ProjectInvite.project))
            .where(
                and_(
                    ProjectInvite.id == invite_id,
                    ProjectInvite.project_id == project_id,
                    ProjectInvite.status == "pending",
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_invites(
        self,
        db: AsyncSession,
        project_id: str,
    ) -> list[ProjectInvite]:
        result = await db.execute(
            select(ProjectInvite).where(ProjectInvite.project_id == project_id)
        )
        return list(result.scalars().all())

    async def revoke_invite(
        self,
        db: AsyncSession,
        invite_id: str,
        _user_id: str,
        project_id: str | None = None,
    ) -> bool:
        stmt = select(ProjectInvite).where(ProjectInvite.id == invite_id)
        if project_id:
            stmt = stmt.where(ProjectInvite.project_id == project_id)
        result = await db.execute(stmt)
        invite = result.scalar_one_or_none()
        if not invite:
            return False
        if invite.status != "pending":
            raise HTTPException(status_code=400, detail="Only pending invites can be revoked")
        invite.status = "revoked"
        await db.commit()
        return True

    async def decline_invite(
        self,
        db: AsyncSession,
        invite_id: str,
        user: dict,
    ) -> dict[str, bool]:
        """Decline (remove) a pending invite addressed to the authenticated user.

        Mirrors :meth:`accept_invite`'s security checks and error contract:
        ``404`` when the invite does not exist, ``400`` when it is no longer
        pending, and ``403`` when the caller's email does not match the
        invitee's (case-insensitive).

        The invite row is **deleted** rather than status-flipped: the
        ``uq_invite_project_email_status`` unique constraint on
        ``(project_id, email, status)`` means a persisted ``declined`` marker
        would collide the moment the owner re-invites the same address and the
        user declines again. Deleting keeps the invitee's pending list clean
        and re-invite safe.
        """
        result = await db.execute(select(ProjectInvite).where(ProjectInvite.id == invite_id))
        invite = result.scalar_one_or_none()
        if not invite:
            raise HTTPException(status_code=404, detail="Invite not found")
        if invite.status != "pending":
            raise HTTPException(status_code=400, detail="Invite is no longer pending")

        user_email = (user.get("email") or "").lower().strip()
        if not user_email or user_email != invite.email.lower().strip():
            raise HTTPException(
                status_code=403,
                detail="This invite is for a different email address",
            )

        await db.delete(invite)
        await db.commit()
        return {"ok": True}

    async def accept_invite(
        self,
        db: AsyncSession,
        invite_id: str,
        user_id: str,
        *,
        _skip_email_check: bool = False,
    ) -> tuple[ProjectMember, ProjectInvite]:
        """Accept a pending invite and return ``(member, invite)``.

        The returned *invite* has ``inviter`` and ``project`` eagerly loaded
        so callers can read e.g. ``invite.inviter.email`` for notifications.
        """
        result = await db.execute(
            select(ProjectInvite)
            .options(selectinload(ProjectInvite.inviter), selectinload(ProjectInvite.project))
            .where(ProjectInvite.id == invite_id)
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

        # F-PROJ-03. This block used to sit inside `async with db.begin_nested()`, and
        # the board recorded it as "500 on idempotent re-accept". Measured on SQLAlchemy
        # 2.0.51: it does not 500 — a `commit()` inside an open SAVEPOINT deactivates the
        # savepoint transaction, which then exits quietly, and
        # `test_does_not_duplicate_if_already_member` has always passed. The symptom was
        # wrong; the smell was not.
        #
        # The savepoint bought nothing. The early return committed inside it and the
        # normal path committed after it, so no rollback path existed for it to provide —
        # a savepoint that never rolls back reads as a guarantee and is decoration. Worse,
        # committing inside an open one works by accident of this library version, so a
        # SQLAlchemy that tightens the rule would turn a working path into the 500 the
        # board already believed was there.
        #
        # One transaction, committed once, with the IntegrityError retry that was always
        # the real concurrency guard.
        if invite_is_expired(invite):
            # F-PROJ-04: refuse rather than silently drop, so somebody clicking a
            # dead link is told why instead of watching nothing happen.
            raise HTTPException(
                status_code=410,
                detail=("This invitation has expired. Ask the project owner to send a new one."),
            )
        invite.status = "accepted"
        invite.accepted_at = datetime.now(UTC)

        existing = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == invite.project_id,
                ProjectMember.user_id == user_id,
            )
        )
        member = existing.scalar_one_or_none()
        if member:
            # Already a member: the invite is still marked accepted, so the same click
            # twice settles the same way both times.
            await db.commit()
            return member, invite

        member = ProjectMember(
            project_id=invite.project_id,
            user_id=user_id,
            role=invite.role,
        )
        db.add(member)

        try:
            await db.commit()
            await db.refresh(member)
        except IntegrityError:
            await db.rollback()
            existing = await db.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == invite.project_id,
                    ProjectMember.user_id == user_id,
                )
            )
            member = existing.scalar_one()
        return member, invite

    async def list_pending_for_email(
        self,
        db: AsyncSession,
        email: str,
    ) -> list[ProjectInvite]:
        result = await db.execute(
            select(ProjectInvite)
            .options(selectinload(ProjectInvite.project))
            .where(
                and_(
                    ProjectInvite.email == email.lower().strip(),
                    ProjectInvite.status == "pending",
                )
            )
        )
        return list(result.scalars().all())

    async def auto_accept_for_user(
        self,
        db: AsyncSession,
        user_id: str,
        email: str,
    ) -> list[ProjectMember]:
        """Auto-accept all pending invites for a newly registered email.

        Skips the email ownership check since the caller already verified identity.
        """
        pending = await self.list_pending_for_email(db, email)
        members = []
        for invite in pending:
            # F-PROJ-04: SKIP here rather than let `accept_invite` raise. This runs
            # inside registration, and a 410 would fail somebody's sign-up over a
            # stranger's forgotten invitation — a worse outcome than the bug. The
            # interactive path still explains itself; this one just declines.
            if invite_is_expired(invite):
                logger.info(
                    "Auto-accept skipped an expired invite %s for %s (created %s)",
                    invite.id[:8],
                    email,
                    invite.created_at,
                )
                continue
            member, _inv = await self.accept_invite(db, invite.id, user_id, _skip_email_check=True)
            members.append(member)
        return members
