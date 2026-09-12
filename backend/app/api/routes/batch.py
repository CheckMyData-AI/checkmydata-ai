import asyncio
import io
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core import task_queue
from app.core.audit import audit_log
from app.core.background import spawn_tracked
from app.core.rate_limit import limiter
from app.core.task_queue import EnqueueFailedError, enqueue_or_fail
from app.services.batch_service import BatchService
from app.services.connection_service import ConnectionService
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)

router = APIRouter()
_svc = BatchService()
_conn_svc = ConnectionService()
_membership_svc = MembershipService()


class BatchQueryItem(BaseModel):
    sql: str = Field(max_length=50000)
    title: str = Field(max_length=200)


class BatchExecuteRequest(BaseModel):
    project_id: str
    connection_id: str
    title: str = Field(max_length=200)
    # API-11: `note_ids` has been capped at 100 and `sql` at 50 000 characters since
    # this schema was written, so the bounds were placed deliberately — `queries` had
    # none, leaving `max_request_body_bytes` (10 MB) as the only ceiling. ~150 000
    # minimal items was an accepted request. Matched to `note_ids`, because the two
    # arrive at the same executor and are subject to the same concurrency.
    queries: list[BatchQueryItem] = Field(default_factory=list, max_length=100)
    note_ids: list[str] | None = Field(None, max_length=100)


class BatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    project_id: str
    connection_id: str
    title: str
    queries_json: str
    note_ids_json: str | None
    status: str
    results_json: str | None
    created_at: datetime | None
    completed_at: datetime | None


@router.post("/execute", response_model=dict, status_code=202)
@limiter.limit("10/minute")
async def execute_batch(
    request: Request,
    body: BatchExecuteRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    # Membership first, so a non-member cannot probe which connection ids exist.
    await _membership_svc.require_role(db, body.project_id, user["user_id"])

    conn = await _conn_svc.get(db, body.connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    if conn.project_id != body.project_id:
        raise HTTPException(status_code=400, detail="Connection does not belong to this project")

    # COR-06: and now the role the STATEMENTS need, which is knowable only once the
    # connection is resolved. A batch is a list of arbitrary SQL run against the
    # customer's database; it was gated at the lowest role the ladder has, while a
    # dashboard needed `editor` and a schedule needed `owner`.
    await _membership_svc.require_write_role(
        db,
        body.project_id,
        user["user_id"],
        connection_is_read_only=bool(conn.is_read_only),
        subject="Running a batch",
    )

    if not body.queries and not body.note_ids:
        raise HTTPException(status_code=400, detail="Provide at least one query or note_id")

    queries_dicts = [q.model_dump() for q in body.queries]
    batch = await _svc.create_batch(
        db,
        user_id=user["user_id"],
        project_id=body.project_id,
        connection_id=body.connection_id,
        title=body.title,
        queries=queries_dicts,
        note_ids=body.note_ids,
    )

    audit_log(
        "batch.create",
        user_id=user["user_id"],
        project_id=body.project_id,
        resource_type="batch",
        resource_id=batch.id,
    )

    def _on_batch_done(t: asyncio.Task[None]) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logger.error(
                "Batch %s failed: %s",
                batch.id,
                exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    # API-11: the batch runs on the worker when there is one. Every other heavy
    # operation in the API already does; this one ran as an in-process asyncio task
    # on the process that must stay responsive, executing the caller's whole list
    # against the customer's database with no run row, no heartbeat and no cancel.
    if task_queue.is_arq_active():
        try:
            await enqueue_or_fail(
                "run_batch",
                batch_id=batch.id,
                connection_id=body.connection_id,
                user_id=user["user_id"],
                allow_in_process=False,
            )
        except EnqueueFailedError as exc:
            # Claims come from outcomes (API-03): the batch row exists and nothing is
            # running it, so say so rather than answering "pending".
            # No `error` column on this model; the results blob is where a batch
            # already records what went wrong.
            batch.status = "failed"
            batch.results_json = json.dumps({"error": str(exc)})
            batch.completed_at = datetime.now(UTC)
            await db.commit()
            raise HTTPException(
                status_code=503,
                detail="Could not queue the batch; please try again.",
            ) from exc
        return {"batch_id": batch.id, "status": "pending"}

    # F-PROJ-05: a done-callback is bookkeeping, not a lifetime — asyncio keeps only a
    # weak reference, and this handler returns on the next line. `spawn_tracked` holds it
    # until it finishes and logs a failure; the callback below still does the domain work
    # of marking the batch.
    task = spawn_tracked(
        _svc.execute_batch(batch.id, body.connection_id, user_id=user["user_id"]),
        name=f"batch:{batch.id}",
    )
    task.add_done_callback(_on_batch_done)

    return {"batch_id": batch.id, "status": "pending"}


@router.get("/{batch_id}", response_model=BatchResponse)
async def get_batch(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    batch = await _svc.get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.user_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="Not your batch")
    await _membership_svc.require_role(db, batch.project_id, user["user_id"], "viewer")
    return batch


@router.get("", response_model=list[BatchResponse])
async def list_batches(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    return await _svc.list_batches(db, project_id, user["user_id"])


@router.delete("/{batch_id}")
@limiter.limit("20/minute")
async def delete_batch(
    request: Request,
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    batch = await _svc.get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.user_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="Not your batch")

    await _svc.delete_batch(db, batch_id)
    audit_log(
        "batch.delete",
        user_id=user["user_id"],
        project_id=batch.project_id,
        resource_type="batch",
        resource_id=batch_id,
    )
    return {"ok": True}


def _safe_sheet_name(title: str, idx: int) -> str:
    name = title[:28] if len(title) > 28 else title
    invalid = ["\\", "/", "*", "?", ":", "[", "]"]
    for ch in invalid:
        name = name.replace(ch, "_")
    return f"{idx + 1}_{name}" if name else f"Query_{idx + 1}"


@router.post("/{batch_id}/export")
@limiter.limit("10/minute")
async def export_batch(
    request: Request,
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    batch = await _svc.get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.user_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="Not your batch")
    if not batch.results_json:
        raise HTTPException(status_code=400, detail="No results to export")

    results = json.loads(batch.results_json)
    wb = Workbook()
    wb.remove(wb.active)

    for idx, res in enumerate(results):
        sheet_name = _safe_sheet_name(res.get("title", f"Query {idx + 1}"), idx)
        ws = wb.create_sheet(title=sheet_name[:31])

        if res.get("status") == "failed":
            ws.append(["Error", res.get("error", "Unknown error")])
            continue

        columns = res.get("columns", [])
        rows = res.get("rows", [])
        if columns:
            ws.append(columns)
        for row in rows:
            ws.append(row)

    if not wb.sheetnames:
        ws = wb.create_sheet(title="Empty")
        ws.append(["No results"])

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    safe_title = batch.title.replace('"', "'")[:50]
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="batch_{safe_title}.xlsx"'},
    )
