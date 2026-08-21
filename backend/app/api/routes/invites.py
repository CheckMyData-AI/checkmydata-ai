"""REST routes for project invitations and membership management."""

import logging
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.config import settings
from app.core.audit import audit_log
from app.core.rate_limit import limiter
from app.services.email_service import EmailService
from app.services.invite_service import InviteService
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)

router = APIRouter()
_invite_svc = InviteService()
_membership_svc = MembershipService()
_email_svc = EmailService()


class InviteCreate(BaseModel):
    email: EmailStr
    role: Literal["owner", "editor", "viewer"] = "editor"


class InviteResponse(BaseModel):
    id: str
    project_id: str
    email: str
    role: str
    status: str
    invited_by: str
    created_at: str | None = None
    accepted_at: str | None = None
    project_name: str | None = None
    #: F-PROJ-06. The invite row is committed before the email is attempted and the sender
    #: never raises, so without this a failed delivery answered 200 and said nothing. `None`
    #: means "not attempted on this response" (listing an existing invite), which is
    #: deliberately different from `False`, "we tried and it did not go".
    email_sent: bool | None = None


class RoleUpdate(BaseModel):
    # "owner" is deliberately absent: ownership moves through
    # POST /{project_id}/transfer-ownership, which enforces the receiving owner's
    # plan quota and keeps `Project.owner_id` and the member row in step. Allowing
    # it here would create a second, unguarded path to the same state.
    role: Literal["editor", "viewer"]


class OwnershipTransfer(BaseModel):
    new_owner_user_id: str


class MemberResponse(BaseModel):
    id: str
    project_id: str
    user_id: str
    role: str
    email: str | None = None
    display_name: str | None = None


@router.post("/{project_id}/invites", response_model=InviteResponse)
@limiter.limit("20/minute")
async def create_invite(
    request: Request,
    project_id: str,
    body: InviteCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")
    if body.role not in ("editor", "viewer"):
        raise HTTPException(status_code=400, detail="Role must be 'editor' or 'viewer'")
    invite = await _invite_svc.create_invite(
        db,
        project_id,
        body.email,
        body.role,
        user["user_id"],
    )
    audit_log(
        "invite.create",
        user_id=user["user_id"],
        project_id=project_id,
        resource_type="invite",
        resource_id=invite.id,
        detail=body.email,
    )
    # F-PROJ-06: the invite row is committed before this runs, and `_send` never raises —
    # so a failed send used to answer 200 with an invitation the recipient never hears
    # about. Worse, retrying answers 409 "already pending", which reads as *already done*
    # and confirms the owner's wrong belief. Reporting it is the whole fix: the invite
    # exists either way, and the owner needs to know whether to resend or paste the link.
    email_sent = await _email_svc.send_invite_email(
        invite_id=invite.id,
        to_email=invite.email,
        project_name=invite.project.name if invite.project else project_id,
        inviter_name=(
            invite.inviter.display_name if invite.inviter else user.get("email", "Someone")
        ),
        role=invite.role,
    )
    if not email_sent:
        logger.warning(
            "invite %s created for %s but the email could not be sent",
            invite.id,
            invite.email,
        )
    return InviteResponse(
        email_sent=email_sent,
        id=invite.id,
        project_id=invite.project_id,
        email=invite.email,
        role=invite.role,
        status=invite.status,
        invited_by=invite.invited_by,
        created_at=invite.created_at.isoformat() if invite.created_at else None,
        accepted_at=invite.accepted_at.isoformat() if invite.accepted_at else None,
    )


@router.get("/{project_id}/invites", response_model=list[InviteResponse])
async def list_invites(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")
    invites = await _invite_svc.list_invites(db, project_id)
    return [
        InviteResponse(
            id=inv.id,
            project_id=inv.project_id,
            email=inv.email,
            role=inv.role,
            status=inv.status,
            invited_by=inv.invited_by,
            created_at=inv.created_at.isoformat() if inv.created_at else None,
            accepted_at=inv.accepted_at.isoformat() if inv.accepted_at else None,
        )
        for inv in invites
    ]


@router.delete("/{project_id}/invites/{invite_id}")
@limiter.limit("20/minute")
async def revoke_invite(
    request: Request,
    project_id: str,
    invite_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")
    revoked = await _invite_svc.revoke_invite(db, invite_id, user["user_id"], project_id=project_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="Invite not found")
    audit_log(
        "invite.revoke",
        user_id=user["user_id"],
        project_id=project_id,
        resource_type="invite",
        resource_id=invite_id,
    )
    return {"ok": True}


@router.post("/{project_id}/invites/{invite_id}/resend")
@limiter.limit("5/minute")
async def resend_invite(
    request: Request,
    project_id: str,
    invite_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")
    invite = await _invite_svc.get_pending_invite(db, invite_id, project_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Pending invite not found")
    audit_log(
        "invite.resend",
        user_id=user["user_id"],
        project_id=project_id,
        resource_type="invite",
        resource_id=invite_id,
        detail=invite.email,
    )
    email_sent = await _email_svc.send_invite_email(
        invite_id=f"{invite.id}/resend/{int(time.time())}",
        to_email=invite.email,
        project_name=invite.project.name if invite.project else project_id,
        inviter_name=(
            invite.inviter.display_name if invite.inviter else user.get("email", "Someone")
        ),
        role=invite.role,
    )
    # F-PROJ-06: `{"ok": True}` from a resend that did not send is the same lie as the
    # create path told, and worse here — resending is what somebody does *because* they
    # suspect the first one never arrived.
    if not email_sent:
        logger.warning(
            "invite %s resent to %s but the email could not be sent", invite.id, invite.email
        )
    return {"ok": True, "email_sent": email_sent}


@router.post("/accept/{invite_id}")
@limiter.limit("10/minute")
async def accept_invite(
    request: Request,
    invite_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    member, invite = await _invite_svc.accept_invite(db, invite_id, user["user_id"])
    audit_log(
        "invite.accept",
        user_id=user["user_id"],
        project_id=member.project_id,
        resource_type="invite",
        resource_id=invite_id,
    )
    if invite.inviter:
        await _email_svc.send_invite_accepted_email(
            invite_id=invite_id,
            inviter_email=invite.inviter.email,
            inviter_name=invite.inviter.display_name,
            accepted_user_email=user["email"],
            accepted_user_name="",
            project_name=invite.project.name if invite.project else member.project_id,
        )
    return {
        "ok": True,
        "project_id": member.project_id,
        "role": member.role,
    }


@router.post("/decline/{invite_id}")
@limiter.limit("10/minute")
async def decline_invite(
    request: Request,
    invite_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _invite_svc.decline_invite(db, invite_id, user)
    audit_log(
        "invite.decline",
        user_id=user["user_id"],
        resource_type="invite",
        resource_id=invite_id,
    )
    return {"ok": True}


@router.get("/pending", response_model=list[InviteResponse])
async def list_pending_invites(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    invites = await _invite_svc.list_pending_for_email(db, user["email"])
    return [
        InviteResponse(
            id=inv.id,
            project_id=inv.project_id,
            email=inv.email,
            role=inv.role,
            status=inv.status,
            invited_by=inv.invited_by,
            created_at=inv.created_at.isoformat() if inv.created_at else None,
            accepted_at=None,
            project_name=inv.project.name if inv.project else None,
        )
        for inv in invites
    ]


@router.get("/{project_id}/members", response_model=list[MemberResponse])
async def list_members(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    members = await _membership_svc.list_members(db, project_id)
    result = []
    for m in members:
        email = None
        display_name = None
        if m.user:
            email = m.user.email
            display_name = m.user.display_name
        result.append(
            MemberResponse(
                id=m.id,
                project_id=m.project_id,
                user_id=m.user_id,
                role=m.role,
                email=email,
                display_name=display_name,
            )
        )
    return result


@router.post("/{project_id}/transfer-ownership", status_code=204)
@limiter.limit("5/minute")
async def transfer_ownership(
    request: Request,
    project_id: str,
    body: OwnershipTransfer,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Hand a project to another member (F-PROJ-10).

    Authorization is **not** `require_role(..., "owner")`: an orphaned project —
    `Project.owner_id` is `ondelete="SET NULL"`, so a deleted account leaves one —
    has no owner, so that check would 403 everyone and the workspace would stay
    stranded, which is the finding. The service decides instead, and it lets an admin
    act precisely in that case. Rate limit is deliberately tighter than the
    role-change route's: this is the one action that can hand a workspace away.
    """
    await _membership_svc.transfer_ownership(
        db,
        project_id,
        new_owner_user_id=body.new_owner_user_id,
        actor_user_id=user["user_id"],
        actor_is_admin=settings.is_admin_email(user.get("email")),
    )
    return Response(status_code=204)


@router.patch("/{project_id}/members/{member_user_id}", response_model=MemberResponse)
@limiter.limit("20/minute")
async def update_member_role(
    request: Request,
    project_id: str,
    member_user_id: str,
    body: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")
    member = await _membership_svc.update_member_role(
        db,
        project_id,
        member_user_id,
        body.role,
    )
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    audit_log(
        "member.role_change",
        user_id=user["user_id"],
        project_id=project_id,
        resource_type="member",
        resource_id=member_user_id,
        detail=body.role,
    )
    return MemberResponse(
        id=member.id,
        project_id=member.project_id,
        user_id=member.user_id,
        role=member.role,
        email=member.user.email if member.user else None,
        display_name=member.user.display_name if member.user else None,
    )


@router.delete("/{project_id}/members/{member_user_id}")
@limiter.limit("10/minute")
async def remove_member(
    request: Request,
    project_id: str,
    member_user_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")
    removed = await _membership_svc.remove_member(db, project_id, member_user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Member not found")
    audit_log(
        "member.remove",
        user_id=user["user_id"],
        project_id=project_id,
        resource_type="member",
        resource_id=member_user_id,
    )
    return {"ok": True}
