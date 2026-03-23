import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.rate_limit import limiter
from app.models.notification import Notification

logger = logging.getLogger(__name__)

router = APIRouter()


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    project_id: str | None
    title: str
    body: str | None
    type: str
    is_read: bool
    created_at: datetime | None


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    unread_only: bool = True,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    q = select(Notification).where(Notification.user_id == user["user_id"])
    if unread_only:
        q = q.where(Notification.is_read == False)  # noqa: E712
    q = q.order_by(Notification.created_at.desc()).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/count")
async def unread_count(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user["user_id"],
            Notification.is_read == False,  # noqa: E712
        )
    )
    return {"count": result.scalar() or 0}


@router.patch("/{notification_id}/read")
@limiter.limit("60/minute")
async def mark_read(
    request: Request,
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user["user_id"],
        )
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.is_read = True
    await db.commit()
    return {"ok": True}


@router.post("/read-all")
@limiter.limit("30/minute")
async def mark_all_read(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    from sqlalchemy import update

    await db.execute(
        update(Notification)
        .where(
            Notification.user_id == user["user_id"],
            Notification.is_read == False,  # noqa: E712
        )
        .values(is_read=True)
    )
    await db.commit()
    return {"ok": True}
