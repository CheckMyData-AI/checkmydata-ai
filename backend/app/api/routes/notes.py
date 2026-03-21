import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.audit import audit_log
from app.core.rate_limit import limiter
from app.services.connection_service import ConnectionService
from app.services.membership_service import MembershipService
from app.services.note_service import NoteService

logger = logging.getLogger(__name__)

router = APIRouter()
_svc = NoteService()
_conn_svc = ConnectionService()
_membership_svc = MembershipService()

_RAW_RESULT_ROW_CAP = 500


class NoteCreate(BaseModel):
    project_id: str
    connection_id: str | None = None
    title: str = Field(max_length=500)
    comment: str | None = Field(None, max_length=10000)
    sql_query: str = Field(max_length=50000)
    answer_text: str | None = None
    visualization_json: str | None = None
    last_result_json: str | None = None


class NoteUpdate(BaseModel):
    title: str | None = Field(None, max_length=500)
    comment: str | None = Field(None, max_length=10000)
    is_shared: bool | None = None
    shared_by: str | None = None


class NoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    user_id: str
    connection_id: str | None
    title: str
    comment: str | None
    sql_query: str
    answer_text: str | None = None
    visualization_json: str | None = None
    last_result_json: str | None
    is_shared: bool = False
    shared_by: str | None = None
    last_executed_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


class ExecuteResponse(BaseModel):
    id: str
    last_result_json: str | None
    last_executed_at: datetime | None
    error: str | None = None


async def _require_note_owner(
    db: AsyncSession,
    note_id: str,
    user_id: str,
):
    """Load note, verify ownership and project membership. Returns the note or raises."""
    note = await _svc.get(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your note")
    await _membership_svc.require_role(db, note.project_id, user_id, "viewer")
    return note


@router.post("", response_model=NoteResponse)
async def create_note(
    body: NoteCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "viewer")

    if body.connection_id:
        conn = await _conn_svc.get(db, body.connection_id)
        if not conn:
            raise HTTPException(status_code=404, detail="Connection not found")
        if conn.project_id != body.project_id:
            raise HTTPException(
                status_code=400,
                detail="Connection does not belong to this project",
            )

    note = await _svc.create(
        db,
        project_id=body.project_id,
        user_id=user["user_id"],
        connection_id=body.connection_id,
        title=body.title,
        comment=body.comment,
        sql_query=body.sql_query,
        answer_text=body.answer_text,
        visualization_json=body.visualization_json,
        last_result_json=body.last_result_json,
        last_executed_at=datetime.now(UTC) if body.last_result_json else None,
    )
    audit_log(
        "note.create",
        user_id=user["user_id"],
        project_id=note.project_id,
        resource_type="note",
        resource_id=note.id,
    )
    return note


@router.get("", response_model=list[NoteResponse])
async def list_notes(
    project_id: str,
    scope: str = "mine",
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    if scope not in ("mine", "shared", "all"):
        raise HTTPException(status_code=400, detail="scope must be mine, shared, or all")
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    return await _svc.list_by_project(db, project_id, user["user_id"], scope=scope)


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(
    note_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    return await _require_note_owner(db, note_id, user["user_id"])


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: str,
    body: NoteUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    note = await _require_note_owner(db, note_id, user["user_id"])
    updates = body.model_dump(exclude_unset=True)

    if "is_shared" in updates:
        if updates["is_shared"]:
            from app.services.auth_service import AuthService

            auth_svc = AuthService()
            user_obj = await auth_svc.get_by_id(db, user["user_id"])
            updates["shared_by"] = (
                user_obj.display_name if user_obj and user_obj.display_name else user["email"]
            )
        else:
            updates["shared_by"] = None

    updated = await _svc.update(db, note.id, **updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Note not found after update")
    audit_log(
        "note.update",
        user_id=user["user_id"],
        project_id=updated.project_id,
        resource_type="note",
        resource_id=note.id,
    )
    return updated


@router.delete("/{note_id}")
async def delete_note(
    note_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    note = await _require_note_owner(db, note_id, user["user_id"])
    await _svc.delete(db, note.id)
    audit_log(
        "note.delete",
        user_id=user["user_id"],
        project_id=note.project_id,
        resource_type="note",
        resource_id=note.id,
    )
    return {"ok": True}


@router.post("/{note_id}/execute", response_model=ExecuteResponse)
@limiter.limit("10/minute")
async def execute_note(
    request: Request,
    note_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    note = await _require_note_owner(db, note_id, user["user_id"])
    if not note.connection_id:
        raise HTTPException(status_code=400, detail="Note has no connection — cannot execute")

    conn_model = await _conn_svc.get(db, note.connection_id)
    if not conn_model:
        raise HTTPException(status_code=404, detail="Connection not found")
    if conn_model.project_id != note.project_id:
        raise HTTPException(status_code=403, detail="Connection does not belong to note's project")

    config = await _conn_svc.to_config(db, conn_model, user_id=user["user_id"])

    from app.connectors.registry import get_connector
    from app.viz.utils import serialize_value

    connector = get_connector(conn_model.db_type, ssh_exec_mode=config.ssh_exec_mode)
    try:
        await connector.connect(config)
        try:
            result = await connector.execute_query(note.sql_query)
        finally:
            await connector.disconnect()
    except Exception as e:
        logger.exception("Note re-execute failed for note=%s", note_id[:8])
        return ExecuteResponse(
            id=note_id,
            last_result_json=note.last_result_json,
            last_executed_at=note.last_executed_at,
            error=str(e),
        )

    cols = getattr(result, "columns", None)
    rows = getattr(result, "rows", None)
    raw = None
    if cols:
        raw = {
            "columns": list(cols),
            "rows": [
                [serialize_value(v) for v in row] for row in (rows or [])[:_RAW_RESULT_ROW_CAP]
            ],
            "total_rows": getattr(result, "row_count", len(rows or [])),
        }

    result_json = json.dumps(raw, default=str) if raw else None
    updated = await _svc.update_result(db, note_id, result_json)

    audit_log(
        "note.execute",
        user_id=user["user_id"],
        project_id=note.project_id,
        resource_type="note",
        resource_id=note_id,
    )

    return ExecuteResponse(
        id=note_id,
        last_result_json=result_json,
        last_executed_at=updated.last_executed_at if updated else None,
    )
