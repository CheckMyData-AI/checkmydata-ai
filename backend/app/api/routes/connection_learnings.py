"""Connection learnings router (T24).

Split out of ``connections.py`` so that the per-connection learnings
CRUD / confirm / contradict / recompile endpoints live in their own file.
Mounted under the same ``/connections/{connection_id}/learnings`` prefix
by ``app/main.py``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.schemas import AckWithCountResponse, OkResponse, OkWithIdResponse
from app.core.rate_limit import limiter
from app.services.agent_learning_service import AgentLearningService
from app.services.connection_service import ConnectionService
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)

router = APIRouter()
_svc = ConnectionService()
_membership_svc = MembershipService()
_learning_svc = AgentLearningService()


@router.get("/{connection_id}/learnings")
async def list_learnings(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List all active agent learnings for a connection."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "viewer")

    learnings = await _learning_svc.get_learnings(db, connection_id)
    return [
        {
            "id": lrn.id,
            "category": lrn.category,
            "subject": lrn.subject,
            "lesson": lrn.lesson,
            "confidence": round(lrn.confidence, 2),
            "times_confirmed": lrn.times_confirmed,
            "times_applied": lrn.times_applied,
            "is_active": lrn.is_active,
            "source_query": lrn.source_query,
            "source_error": lrn.source_error,
            "created_at": lrn.created_at.isoformat() if lrn.created_at else None,
            "updated_at": lrn.updated_at.isoformat() if lrn.updated_at else None,
        }
        for lrn in learnings
    ]


@router.get("/{connection_id}/learnings/status")
async def learnings_status(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get learning status (count, last compiled time)."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "viewer")

    return await _learning_svc.get_status(db, connection_id)


@router.get("/{connection_id}/learnings/summary")
async def learnings_summary(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get compiled learning summary prompt."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "viewer")

    prompt = await _learning_svc.get_or_compile_summary(db, connection_id)
    return {"compiled_prompt": prompt}


class LearningUpdate(BaseModel):
    lesson: str | None = Field(None, max_length=10000)
    is_active: bool | None = None
    confidence: float | None = Field(None, ge=0.0, le=1.0)


@router.patch("/{connection_id}/learnings/{learning_id}", response_model=OkWithIdResponse)
@limiter.limit("20/minute")
async def update_learning(
    request: Request,
    connection_id: str,
    learning_id: str,
    body: LearningUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Edit a learning (user override)."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "editor")

    kwargs: dict = {}
    if body.lesson is not None:
        kwargs["lesson"] = body.lesson
    if body.is_active is not None:
        kwargs["is_active"] = body.is_active
    if body.confidence is not None:
        kwargs["confidence"] = max(0.0, min(1.0, body.confidence))

    if not kwargs:
        raise HTTPException(status_code=400, detail="No fields to update")

    from app.models.agent_learning import AgentLearning

    check = await db.get(AgentLearning, learning_id)
    if not check or check.connection_id != connection_id:
        raise HTTPException(status_code=404, detail="Learning not found")

    entry = await _learning_svc.update_learning(db, learning_id, **kwargs)
    if not entry:
        raise HTTPException(status_code=404, detail="Learning not found")
    await db.commit()
    return {"ok": True, "id": entry.id}


@router.delete("/{connection_id}/learnings/{learning_id}", response_model=OkResponse)
@limiter.limit("20/minute")
async def delete_learning(
    request: Request,
    connection_id: str,
    learning_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Remove a specific learning."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "editor")

    from app.models.agent_learning import AgentLearning

    check = await db.get(AgentLearning, learning_id)
    if not check or check.connection_id != connection_id:
        raise HTTPException(status_code=404, detail="Learning not found")

    deleted = await _learning_svc.delete_learning(db, learning_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Learning not found")
    await db.commit()
    return {"ok": True}


@router.delete("/{connection_id}/learnings", response_model=AckWithCountResponse)
@limiter.limit("5/minute")
async def clear_learnings(
    request: Request,
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Clear all learnings for a connection."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "owner")

    count = await _learning_svc.delete_all(db, connection_id)
    await db.commit()
    return {"ok": True, "deleted": count}


@router.post("/{connection_id}/learnings/recompile")
@limiter.limit("5/minute")
async def recompile_learnings(
    request: Request,
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Force recompile the learnings prompt."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "editor")

    prompt = await _learning_svc.compile_prompt(db, connection_id)
    await db.commit()
    return {"ok": True, "compiled_prompt": prompt}


@router.post("/{connection_id}/learnings/validate-schema")
@limiter.limit("10/minute")
async def validate_learnings_schema(
    request: Request,
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Cross-check learnings against the current DB schema.

    Deactivates learnings whose subject no longer exists as a table.
    """
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "editor")

    config = await _svc.to_config(db, conn, user_id=user["user_id"])
    try:
        from app.connectors.registry import get_connector

        connector = get_connector(conn.db_type, ssh_exec_mode=config.ssh_exec_mode)
        await connector.connect(config)
        try:
            schema = await connector.introspect_schema()
        finally:
            await connector.disconnect()
    except Exception as e:
        logger.exception("Schema introspection failed for validation: %s", e)
        raise HTTPException(status_code=500, detail="Could not introspect schema")

    known_tables = {t.name for t in schema.tables}
    result = await _learning_svc.validate_learnings_against_schema(
        db,
        connection_id,
        known_tables,
    )
    await db.commit()
    return {"ok": True, **result}


@router.post("/{connection_id}/learnings/{learning_id}/confirm")
@limiter.limit("30/minute")
async def confirm_learning(
    request: Request,
    connection_id: str,
    learning_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Upvote a learning — bumps confidence and times_confirmed."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "editor")

    from app.models.agent_learning import AgentLearning

    check = await db.get(AgentLearning, learning_id)
    if not check or check.connection_id != connection_id:
        raise HTTPException(status_code=404, detail="Learning not found")

    entry = await _learning_svc.confirm_learning(db, learning_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Learning not found")
    await db.commit()
    return {
        "ok": True,
        "id": entry.id,
        "confidence": round(entry.confidence, 2),
        "times_confirmed": entry.times_confirmed,
    }


@router.post("/{connection_id}/learnings/{learning_id}/contradict")
@limiter.limit("30/minute")
async def contradict_learning(
    request: Request,
    connection_id: str,
    learning_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Downvote a learning — reduces confidence, may deactivate."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "editor")

    from app.models.agent_learning import AgentLearning

    check = await db.get(AgentLearning, learning_id)
    if not check or check.connection_id != connection_id:
        raise HTTPException(status_code=404, detail="Learning not found")

    entry = await _learning_svc.contradict_learning(db, learning_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Learning not found")
    await db.commit()
    return {
        "ok": True,
        "id": entry.id,
        "confidence": round(entry.confidence, 2),
        "is_active": entry.is_active,
    }
