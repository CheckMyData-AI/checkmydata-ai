"""Run control + read endpoints (cancel / retry / detail / events)."""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core import task_queue
from app.core.rate_limit import limiter
from app.models.indexing_run import IndexingRun, IndexingRunEvent
from app.services.membership_service import MembershipService
from app.services.run_coordinator import RunCoordinator

logger = logging.getLogger(__name__)
router = APIRouter()
_membership = MembershipService()
_coord = RunCoordinator()


async def _load_run(db: AsyncSession, run_id: str) -> IndexingRun:
    run = await db.get(IndexingRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


class RetryBody(BaseModel):
    force_full: bool = False


def _run_to_dict(run: IndexingRun) -> dict:
    return {
        "id": run.id,
        "kind": run.kind,
        "status": run.status,
        "trigger": run.trigger,
        "project_id": run.project_id,
        "connection_id": run.connection_id,
        "current_step": run.current_step,
        "step_index": run.step_index,
        "total_steps": run.total_steps,
        "progress_pct": run.progress_pct,
        "error": run.error,
        "failure_kind": run.failure_kind,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "workflow_id": run.workflow_id,
    }


@router.post("/{run_id}/cancel")
@limiter.limit("20/minute")
async def cancel_run(
    request: Request,
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    run = await _load_run(db, run_id)
    await _membership.require_role(db, run.project_id, user["user_id"], "editor")
    ok = await _coord.request_cancel(db, run_id)
    _cancel_inproc_task(run)
    return {"cancelled": ok, "run_id": run_id}


@router.post("/{run_id}/retry")
@limiter.limit("10/minute")
async def retry_run(
    request: Request,
    run_id: str,
    body: RetryBody | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    run = await _load_run(db, run_id)
    await _membership.require_role(db, run.project_id, user["user_id"], "editor")
    body = body or RetryBody()
    new = await _coord.retry(db, run_id, force_full=body.force_full)
    await _dispatch_for_kind(db, new)
    return {"run_id": new.id, "workflow_id": new.workflow_id, "status": new.status}


@router.get("/{run_id}")
async def get_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    run = await _load_run(db, run_id)
    await _membership.require_role(db, run.project_id, user["user_id"], "viewer")
    return _run_to_dict(run)


@router.get("/{run_id}/events")
async def get_run_events(
    run_id: str,
    level: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    run = await _load_run(db, run_id)
    await _membership.require_role(db, run.project_id, user["user_id"], "viewer")
    stmt = select(IndexingRunEvent).where(IndexingRunEvent.run_id == run_id)
    if level:
        stmt = stmt.where(IndexingRunEvent.level == level)
    rows = (await db.execute(stmt.order_by(IndexingRunEvent.ts))).scalars().all()
    return [
        {
            "ts": e.ts.isoformat() if e.ts else None,
            "step": e.step,
            "status": e.status,
            "detail": e.detail,
            "elapsed_ms": e.elapsed_ms,
            "progress_pct": e.progress_pct,
            "level": e.level,
        }
        for e in rows
    ]


def _cancel_inproc_task(run: IndexingRun) -> None:
    """Cancel the in-process asyncio task backing this run, if present."""
    try:
        if run.kind == "index_repo":
            from app.api.routes.repos import _indexing_tasks

            t = _indexing_tasks.get(run.project_id)
        elif run.kind == "db_index":
            from app.api.routes.connections import _db_index_tasks

            t = _db_index_tasks.get(run.connection_id or "")
        elif run.kind == "code_db_sync":
            from app.api.routes.connections import _sync_tasks

            t = _sync_tasks.get(run.connection_id or "")
        else:
            t = None
        if t is not None and not t.done():
            t.cancel()
    except Exception:  # noqa: BLE001
        logger.debug("in-proc cancel best-effort failed", exc_info=True)


async def _dispatch_for_kind(db: AsyncSession, run: IndexingRun) -> None:
    connection_id = run.connection_id
    if run.kind == "db_index":
        if connection_id is None:
            return
        from app.api.routes.connections import _dispatch_db_index
        from app.services.connection_service import ConnectionService

        svc = ConnectionService()
        conn = await svc.get(db, connection_id)
        if conn is None:
            return
        cfg = await svc.to_config(db, conn)
        await _dispatch_db_index(connection_id, cfg, run.project_id, wf_id=run.workflow_id)
    elif run.kind == "code_db_sync":
        if connection_id is None:
            return
        from app.api.routes.connections import _dispatch_code_db_sync

        await _dispatch_code_db_sync(connection_id, run.project_id, wf_id=run.workflow_id)
    elif run.kind == "index_repo":
        if task_queue.is_arq_active():
            await task_queue.enqueue(
                "run_repo_index",
                task_id=f"repo_index:{run.project_id}:{uuid.uuid4().hex[:8]}",
                project_id=run.project_id,
                force_full=True,
                wf_id=run.workflow_id,
            )
        else:
            from app.api.routes.repos import run_repo_index_task

            asyncio.create_task(
                run_repo_index_task(run.project_id, force_full=True, wf_id=run.workflow_id)
            )
