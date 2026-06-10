"""Chat session CRUD + message history endpoints.

Extracted from the ``chat.py`` god-file (T-ARCH-1). The conversational
transports (HTTP /ask, SSE /ask/stream, WebSocket) stay in ``chat.py``.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.rate_limit import limiter
from app.core.workflow_tracker import tracker
from app.services.chat_service import ChatService
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)

router = APIRouter()
_chat_svc = ChatService()
_membership_svc = MembershipService()


class SessionCreate(BaseModel):
    project_id: str
    title: str = "New Chat"
    connection_id: str | None = None


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    title: str
    connection_id: str | None = None
    status: str = "idle"
    created_at: datetime | None = None


@router.post("/sessions", response_model=SessionResponse)
@limiter.limit("10/minute")
async def create_session(
    request: Request,
    body: SessionCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "viewer")
    session = await _chat_svc.create_session(
        db,
        body.project_id,
        body.title,
        user_id=user["user_id"],
        connection_id=body.connection_id,
    )
    return session


class EnsureWelcomeRequest(BaseModel):
    project_id: str
    connection_id: str | None = None


class EnsureWelcomeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    title: str
    connection_id: str | None = None
    created_at: datetime | None = None
    created: bool = False


@router.post("/sessions/ensure-welcome", response_model=EnsureWelcomeResponse)
@limiter.limit("10/minute")
async def ensure_welcome_session(
    request: Request,
    body: EnsureWelcomeRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "viewer")
    session, created = await _chat_svc.ensure_welcome_session(
        db,
        body.project_id,
        user_id=user["user_id"],
        connection_id=body.connection_id,
    )
    return EnsureWelcomeResponse(
        id=session.id,
        project_id=session.project_id,
        title=session.title,
        connection_id=session.connection_id,
        created_at=session.created_at,
        created=created,
    )


@router.get("/sessions/{project_id}", response_model=list[SessionResponse])
async def list_sessions(
    project_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    return await _chat_svc.list_sessions(
        db,
        project_id,
        user_id=user["user_id"],
        skip=skip,
        limit=limit,
    )


class SessionUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


async def _require_session_owner(db: AsyncSession, session_id: str, user_id: str):
    """Return the session if the user owns it, else raise 403/404."""
    session_obj = await _chat_svc.get_session(db, session_id)
    if not session_obj:
        raise HTTPException(status_code=404, detail="Session not found")
    if session_obj.user_id and session_obj.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your session")
    return session_obj


@router.patch("/sessions/{session_id}", response_model=SessionResponse)
@limiter.limit("30/minute")
async def update_session(
    request: Request,
    session_id: str,
    body: SessionUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _require_session_owner(db, session_id, user["user_id"])
    updated = await _chat_svc.update_session_title(db, session_id, body.title)
    if not updated:
        raise HTTPException(status_code=404, detail="Session not found")
    return updated


@router.post("/sessions/{session_id}/generate-title", response_model=SessionResponse)
@limiter.limit("10/minute")
async def generate_session_title(
    request: Request,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Auto-generate a session title from the first user message."""
    from app.llm.base import Message as LLMMessage
    from app.llm.router import LLMRouter

    await _require_session_owner(db, session_id, user["user_id"])

    from sqlalchemy import select as sa_select

    from app.models.chat_session import ChatMessage as ChatMessageModel

    msg_result = await db.execute(
        sa_select(ChatMessageModel.content)
        .where(
            ChatMessageModel.session_id == session_id,
            ChatMessageModel.role == "user",
        )
        .order_by(ChatMessageModel.created_at)
        .limit(1)
    )
    first_user = msg_result.scalar_one_or_none()
    if not first_user:
        raise HTTPException(status_code=400, detail="No user messages in session")

    session_obj = await _chat_svc.get_session(db, session_id)
    _gt_project_id = session_obj.project_id if session_obj else ""
    wf_id = await tracker.begin(
        "generate_title",
        context={"project_id": _gt_project_id, "user_id": user["user_id"]},
    )
    _gt_error: str | None = None
    try:
        router = LLMRouter()
        async with tracker.step(
            wf_id, "generate_title:llm_call", "Generate session title", span_type="llm_call"
        ):
            resp = await router.complete(
                messages=[
                    LLMMessage(
                        role="system",
                        content=(
                            "Generate a short title (max 6 words) for a database chat session"
                            " based on the user's first question."
                            " Reply with ONLY the title, no quotes."
                        ),
                    ),
                    LLMMessage(role="user", content=first_user[:300]),
                ],
                max_tokens=30,
                temperature=0.3,
            )
        title = resp.content.strip().strip('"').strip("'")[:80] or first_user[:50]
    except Exception:
        title = first_user[:50]
        _gt_error = "LLM call failed, used fallback title"
    finally:
        trace_svc = getattr(request.app.state, "trace_persistence_service", None)
        if trace_svc:
            try:
                await trace_svc.finalize_trace(
                    wf_id,
                    project_id=_gt_project_id,
                    user_id=user["user_id"],
                    question=f"[generate-title] {first_user[:100]}",
                    response_type="generate_title",
                    status="failed" if _gt_error else "completed",
                    error_message=_gt_error,
                )
            except Exception:
                logger.warning("Failed to finalize generate-title trace", exc_info=True)

    updated = await _chat_svc.update_session_title(db, session_id, title)
    return updated


@router.delete("/sessions/{session_id}")
@limiter.limit("10/minute")
async def delete_session(
    request: Request,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _require_session_owner(db, session_id, user["user_id"])
    deleted = await _chat_svc.delete_session(db, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    metadata_json: str | None = None
    tool_calls_json: str | None = None
    user_rating: int | None = None
    created_at: str


@router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
async def get_session_messages(
    session_id: str,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _require_session_owner(db, session_id, user["user_id"])

    from sqlalchemy import select as sa_select

    from app.models.chat_session import ChatMessage as ChatMessageModel

    stmt = (
        sa_select(ChatMessageModel)
        .where(ChatMessageModel.session_id == session_id)
        .order_by(ChatMessageModel.created_at)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    msgs = result.scalars().all()
    return [
        MessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            metadata_json=m.metadata_json,
            tool_calls_json=m.tool_calls_json,
            user_rating=m.user_rating,
            created_at=m.created_at.isoformat() if m.created_at else "",
        )
        for m in msgs
    ]
