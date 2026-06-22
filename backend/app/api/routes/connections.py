from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.connectors.base import ConnectionConfig

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.connectors.ssh_pre_commands import validate_pre_commands
from app.core import task_queue
from app.core.audit import audit_log
from app.core.rate_limit import limiter
from app.services.agent_learning_service import AgentLearningService
from app.services.code_db_sync_service import CodeDbSyncService
from app.services.connection_service import ConnectionService
from app.services.db_index_service import DbIndexService
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)

router = APIRouter()
_svc = ConnectionService()
_membership_svc = MembershipService()
_db_index_svc = DbIndexService()
_sync_svc = CodeDbSyncService()

_db_index_tasks: dict[str, asyncio.Task] = {}
_sync_tasks: dict[str, asyncio.Task] = {}
_db_index_start_locks: dict[str, asyncio.Lock] = {}
_sync_start_locks: dict[str, asyncio.Lock] = {}


def _log_task_error(label: str, resource_id: str) -> Callable[[asyncio.Task], None]:
    def _cb(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logger.error(
                "%s %s failed: %s",
                label,
                resource_id,
                exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    return _cb


async def _ensure_db_index_wf(connection_id: str, project_id: str) -> str:
    """Return a workflow id for a db_index run, creating an :class:`IndexingRun`
    (or reusing the active one) so the pipeline's events land on a run record.

    Used by auto-index callers (reconciler / post-test) that do not mint the run
    themselves the way the manual ``index_database`` route does.
    """
    from app.models.base import async_session_factory
    from app.services.run_coordinator import RunAlreadyActiveError, RunCoordinator

    coord = RunCoordinator()
    async with async_session_factory() as rdb:
        try:
            run = await coord.start(
                rdb,
                kind="db_index",
                project_id=project_id,
                connection_id=connection_id,
                trigger="auto",
            )
            return run.workflow_id
        except RunAlreadyActiveError:
            active = await coord._find_active(rdb, project_id, "db_index", connection_id)
            return active.workflow_id if active else ""


async def _dispatch_db_index(
    connection_id: str,
    config: ConnectionConfig,
    project_id: str,
    *,
    wf_id: str | None = None,
) -> None:
    """Single entry point for starting a DB index run.

    When ARQ/Redis is configured the run is enqueued out-of-process via
    :func:`task_queue.enqueue`; otherwise it runs in-process and is tracked in
    ``_db_index_tasks`` so the status endpoint and the 409 conflict guard keep
    working. ``wf_id`` is minted by the manual route (so it can return the id);
    auto-index callers omit it and a run is created here.

    Callers must already hold the per-connection start lock and have set the
    persisted ``indexing_status`` to ``running``.
    """
    if wf_id is None:
        wf_id = await _ensure_db_index_wf(connection_id, project_id)
    if task_queue.is_arq_active():
        await task_queue.enqueue(
            "run_db_index",
            task_id=f"db_index:{connection_id}:{uuid.uuid4().hex[:8]}",
            connection_id=connection_id,
            project_id=project_id,
            wf_id=wf_id,
        )
        # No local handle in ARQ mode — the persisted status is authoritative.
        return

    task = asyncio.create_task(
        _run_db_index_background(connection_id, config, project_id, wf_id=wf_id)
    )
    task.add_done_callback(_log_task_error("DB index", connection_id))
    _db_index_tasks[connection_id] = task


async def _dispatch_code_db_sync(
    connection_id: str,
    project_id: str,
) -> None:
    """Single entry point for starting a code↔DB sync run.

    Mirrors :func:`_dispatch_db_index` (Phase 0 consolidation): enqueue to the
    ARQ worker's ``run_code_db_sync`` when Redis is configured, otherwise run
    in-process and track in ``_sync_tasks`` so the status endpoint and 409 guard
    keep working. Also used by the Phase 2 auto index→sync chain.

    Callers must already hold the per-connection sync start lock and have set the
    persisted ``sync_status`` to ``running``.
    """
    if task_queue.is_arq_active():
        await task_queue.enqueue(
            "run_code_db_sync",
            task_id=f"code_db_sync:{connection_id}:{uuid.uuid4().hex[:8]}",
            connection_id=connection_id,
            project_id=project_id,
        )
        logger.info(
            "code_db_sync dispatched mode=arq connection=%s project=%s",
            connection_id[:8],
            project_id[:8],
        )
        return

    logger.info(
        "code_db_sync dispatched mode=inprocess connection=%s project=%s",
        connection_id[:8],
        project_id[:8],
    )
    task = asyncio.create_task(_run_sync_background(connection_id, project_id))
    task.add_done_callback(_log_task_error("Code-DB sync", connection_id))
    _sync_tasks[connection_id] = task


async def maybe_autostart_db_index(connection_id: str, project_id: str) -> bool:
    """Best-effort kick off a DB index run (Phase 2 FreshnessReconciler).

    Acquires the same start lock + dedup guards as the manual index route so a
    concurrent user-initiated index is never double-run. Returns ``True`` when an
    index was dispatched. All failures are swallowed (logged).
    """
    from app.models.base import async_session_factory

    try:
        start_lock = _db_index_start_locks.setdefault(connection_id, asyncio.Lock())
        async with start_lock:
            existing = _db_index_tasks.get(connection_id)
            if existing and not existing.done():
                return False

            async with async_session_factory() as session:
                if await _db_index_svc.get_indexing_status(session, connection_id) == "running":
                    return False
                conn = await _svc.get(session, connection_id)
                if not conn:
                    return False
                config = await _svc.to_config(session, conn)
                await _db_index_svc.set_indexing_status(session, connection_id, "running")
                await session.commit()

            await _dispatch_db_index(connection_id, config, project_id)
            logger.info(
                "Reconciler DB re-index started: connection=%s project=%s",
                connection_id[:8],
                project_id[:8],
            )
            return True
    except Exception:
        logger.warning(
            "Reconciler DB re-index dispatch failed for connection=%s",
            connection_id[:8],
            exc_info=True,
        )
        return False


async def maybe_autostart_sync(connection_id: str, project_id: str) -> bool:
    """Best-effort kick off a code↔DB sync after a repo index completes.

    Used by the Phase 2 index→sync chain (``auto_sync_after_index``). Acquires
    the same start lock and dedup guards as the manual ``trigger_sync`` path so a
    concurrent user-initiated sync is never double-run. Returns ``True`` when a
    sync was dispatched.

    Safe to call from any background task: all failures are swallowed (logged)
    because the auto-chain must never crash the index that triggered it.
    """
    from app.models.base import async_session_factory

    try:
        sync_start_lock = _sync_start_locks.setdefault(connection_id, asyncio.Lock())
        async with sync_start_lock:
            existing = _sync_tasks.get(connection_id)
            if existing and not existing.done():
                return False

            async with async_session_factory() as session:
                if await _sync_svc.get_sync_status(session, connection_id) == "running":
                    return False
                if not await _db_index_svc.is_indexed(session, connection_id):
                    logger.info(
                        "Auto index→sync skipped: connection=%s not DB-indexed yet",
                        connection_id[:8],
                    )
                    return False
                await _sync_svc.set_sync_status(session, connection_id, "running")
                await session.commit()

            await _dispatch_code_db_sync(connection_id, project_id)
            logger.info(
                "Auto index→sync started: connection=%s project=%s",
                connection_id[:8],
                project_id[:8],
            )
            return True
    except Exception:
        logger.warning(
            "Auto index→sync dispatch failed for connection=%s",
            connection_id[:8],
            exc_info=True,
        )
        return False


async def cancel_background_tasks() -> None:
    """Cancel all in-flight indexing and sync tasks (called on shutdown)."""
    for tasks in (_db_index_tasks, _sync_tasks):
        for task in tasks.values():
            if not task.done():
                task.cancel()
        for task in tasks.values():
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        tasks.clear()


_learning_svc = AgentLearningService()


class ConnectionCreate(BaseModel):
    project_id: str = Field(max_length=255)
    name: str = Field(max_length=255)
    db_type: Literal["postgres", "mysql", "mongodb", "clickhouse", "mcp"] = Field(max_length=50)
    source_type: str = Field(default="database", max_length=50)
    ssh_host: str | None = Field(None, max_length=255)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_user: str | None = Field(None, max_length=255)
    ssh_key_id: str | None = Field(None, max_length=255)
    db_host: str = Field(default="127.0.0.1", max_length=255)
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = Field(default="", max_length=255)
    db_user: str | None = Field(None, max_length=255)
    db_password: str | None = Field(None, max_length=1024)
    connection_string: str | None = Field(None, max_length=2048)
    is_read_only: bool = True
    ssh_exec_mode: bool = False
    ssh_command_template: str | None = Field(None, max_length=2048)
    ssh_pre_commands: list[str] | None = Field(None, max_length=20)
    # MCP-specific fields
    mcp_server_command: str | None = Field(None, max_length=1024)
    mcp_server_args: list[str] | None = Field(None, max_length=50)
    mcp_server_url: str | None = Field(None, max_length=1024)
    mcp_transport_type: Literal["stdio", "sse"] | None = None
    mcp_env: dict[str, str] | None = None

    @field_validator("mcp_env", mode="before")
    @classmethod
    def validate_mcp_env(cls, v: dict | None) -> dict | None:
        if v is not None:
            if len(v) > 50:
                raise ValueError("mcp_env cannot have more than 50 entries")
            for key, val in v.items():
                if len(str(key)) > 255 or len(str(val)) > 4096:
                    raise ValueError("mcp_env keys max 255 chars, values max 4096 chars")
        return v

    @field_validator("ssh_pre_commands")
    @classmethod
    def validate_ssh_pre_commands(cls, v: list[str] | None) -> list[str] | None:
        # F-SEC-5: restrict pre-commands to the env-setup allowlist.
        if v is not None:
            validate_pre_commands(v)
        return v

    @field_validator("name", "connection_string", mode="before")
    @classmethod
    def strip_strings(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def require_conn_string_or_host(self):
        if self.db_type == "mcp":
            if not self.mcp_server_command and not self.mcp_server_url:
                raise ValueError(
                    "MCP connections require either mcp_server_command (stdio) "
                    "or mcp_server_url (SSE)"
                )
            self.source_type = "mcp"
            return self
        if not self.connection_string and not (self.db_host and self.db_name):
            raise ValueError("Provide either a connection string or db_host + db_name")
        return self


class ConnectionUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    db_type: str | None = Field(None, max_length=50)
    source_type: str | None = Field(None, max_length=50)
    ssh_host: str | None = Field(None, max_length=255)
    ssh_port: int | None = Field(None, ge=1, le=65535)
    ssh_user: str | None = Field(None, max_length=100)
    ssh_key_id: str | None = Field(None, max_length=64)
    db_host: str | None = Field(None, max_length=255)
    db_port: int | None = Field(None, ge=1, le=65535)
    db_name: str | None = Field(None, max_length=200)
    db_user: str | None = Field(None, max_length=100)
    db_password: str | None = Field(None, max_length=500)
    connection_string: str | None = Field(None, max_length=2000)
    is_read_only: bool | None = None
    ssh_exec_mode: bool | None = None
    ssh_command_template: str | None = Field(None, max_length=2000)
    ssh_pre_commands: list[str] | None = Field(None, max_length=20)
    mcp_server_command: str | None = Field(None, max_length=500)
    mcp_server_args: list[str] | None = None
    mcp_server_url: str | None = Field(None, max_length=2000)
    mcp_transport_type: str | None = Field(None, max_length=50)
    mcp_env: dict[str, str] | None = None

    @field_validator("ssh_pre_commands")
    @classmethod
    def validate_ssh_pre_commands(cls, v: list[str] | None) -> list[str] | None:
        # F-SEC-5: restrict pre-commands to the env-setup allowlist.
        if v is not None:
            validate_pre_commands(v)
        return v


class ConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    db_type: str
    source_type: str = "database"
    ssh_host: str | None
    ssh_port: int
    ssh_user: str | None
    ssh_key_id: str | None
    db_host: str
    db_port: int
    db_name: str
    db_user: str | None
    is_read_only: bool
    is_active: bool
    ssh_exec_mode: bool
    ssh_command_template: str | None
    ssh_pre_commands: str | None
    mcp_server_command: str | None = None
    mcp_server_url: str | None = None
    mcp_transport_type: str | None = None


@router.post("", response_model=ConnectionResponse)
@limiter.limit("10/minute")
async def create_connection(
    request: Request,
    body: ConnectionCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "owner")
    # T-BILL-2: plan-based paywall on connection count (402 + upgrade payload).
    from app.services.entitlement_service import EntitlementService, QuotaExceededError

    try:
        await EntitlementService().enforce_connection_quota(db, user["user_id"])
    except QuotaExceededError as exc:
        raise HTTPException(status_code=402, detail=exc.as_payload()) from exc
    conn = await _svc.create(db, **body.model_dump())
    logger.info(
        "Connection created: name=%s type=%s project=%s",
        body.name,
        body.db_type,
        body.project_id[:8],
    )
    audit_log(
        "connection.create",
        user_id=user["user_id"],
        project_id=body.project_id,
        resource_type="connection",
        resource_id=conn.id,
    )
    return conn


@router.get("/project/{project_id}", response_model=list[ConnectionResponse])
async def list_connections(
    project_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    return await _svc.list_by_project(db, project_id, skip=skip, limit=limit)


@router.get("/{connection_id}", response_model=ConnectionResponse)
async def get_connection(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "viewer")
    return conn


@router.patch("/{connection_id}", response_model=ConnectionResponse)
@limiter.limit("20/minute")
async def update_connection(
    request: Request,
    connection_id: str,
    body: ConnectionUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "owner")
    updates = body.model_dump(exclude_unset=True)

    merged_conn_string = updates.get("connection_string")
    if merged_conn_string is None and conn.connection_string_encrypted:
        merged_conn_string = True
    merged_db_host = updates.get("db_host", conn.db_host)
    merged_db_name = updates.get("db_name", conn.db_name)
    if not merged_conn_string and not (merged_db_host and merged_db_name):
        raise HTTPException(
            status_code=422,
            detail="Provide either a connection string or db_host + db_name",
        )

    conn = await _svc.update(db, connection_id, **updates)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    audit_log(
        "connection.update",
        user_id=user["user_id"],
        project_id=conn.project_id,
        resource_type="connection",
        resource_id=connection_id,
    )
    return conn


@router.delete("/{connection_id}")
@limiter.limit("10/minute")
async def delete_connection(
    request: Request,
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "owner")
    await _svc.delete(db, connection_id)
    logger.info("Connection deleted: id=%s name=%s", connection_id[:8], conn.name)
    audit_log(
        "connection.delete",
        user_id=user["user_id"],
        project_id=conn.project_id,
        resource_type="connection",
        resource_id=connection_id,
    )
    return {"ok": True}


@router.post("/{connection_id}/test")
@limiter.limit("20/minute")
async def test_connection(
    request: Request,
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "viewer")
    result = await _svc.test_connection(db, connection_id)

    if result.get("success"):
        from app.config import settings as app_settings

        if app_settings.auto_index_db_on_test:
            auto_lock = _db_index_start_locks.setdefault(connection_id, asyncio.Lock())
            async with auto_lock:
                existing = _db_index_tasks.get(connection_id)
                if not (existing and not existing.done()):
                    try:
                        config = await _svc.to_config(db, conn, user_id=user["user_id"])
                        await _db_index_svc.set_indexing_status(db, connection_id, "running")
                        await db.commit()
                        await _dispatch_db_index(connection_id, config, conn.project_id)
                        result["auto_indexing"] = True
                        logger.info(
                            "Auto-indexing triggered after test: connection=%s",
                            connection_id[:8],
                        )
                    except Exception:
                        logger.debug("Auto-index trigger failed", exc_info=True)

    return result


@router.post("/{connection_id}/test-ssh")
@limiter.limit("10/minute")
async def test_ssh(
    request: Request,
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Test SSH connectivity independently from the database."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "viewer")
    result = await _svc.test_ssh(db, connection_id, user_id=user["user_id"])
    return result


@router.post("/{connection_id}/refresh-schema")
@limiter.limit("10/minute")
async def refresh_schema(
    request: Request,
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Invalidate the cached schema for this connection and re-introspect."""
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

        known_tables = {t.name for t in schema.tables}
        validation = {"checked": 0, "deactivated": 0, "valid": 0}
        if known_tables:
            try:
                validation = await _learning_svc.validate_learnings_against_schema(
                    db,
                    connection_id,
                    known_tables,
                )
                await db.commit()
            except Exception:
                logger.debug("Learning schema validation skipped", exc_info=True)

        rules_issues: list[dict] = []
        if known_tables and conn.project_id:
            try:
                from app.services.rule_service import RuleService

                rules_issues = await RuleService().validate_rules_against_schema(
                    db,
                    conn.project_id,
                    known_tables,
                )
            except Exception:
                logger.debug("Rule schema validation skipped", exc_info=True)

        # R2-2: a live re-introspection alone leaves the stored ``db_index``
        # rows and BM25 schema retriever stale. If this connection has been
        # indexed before, trigger a background re-index so the persisted
        # schema knowledge tracks the refreshed live schema.
        reindex_triggered = False
        if known_tables:
            try:
                reindex_triggered = await _maybe_start_db_index(
                    db, connection_id, config, conn.project_id
                )
            except Exception:
                logger.debug("Auto-reindex after refresh-schema failed", exc_info=True)

        return {
            "ok": True,
            "tables": len(schema.tables),
            "db_type": schema.db_type,
            "learnings_validation": validation,
            "rules_issues": rules_issues,
            "reindex_triggered": reindex_triggered,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Schema refresh failed: %s", e)
        raise HTTPException(status_code=500, detail="Schema refresh failed")


# ------------------------------------------------------------------
# Database Index endpoints
# ------------------------------------------------------------------


@router.post("/{connection_id}/index-db", status_code=202)
@limiter.limit("5/minute")
async def index_database(
    request: Request,
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Trigger database indexing pipeline (runs in background)."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "editor")

    config = await _svc.to_config(db, conn, user_id=user["user_id"])
    project_id = conn.project_id

    idx_start_lock = _db_index_start_locks.setdefault(connection_id, asyncio.Lock())
    async with idx_start_lock:
        existing = _db_index_tasks.get(connection_id)
        if existing and not existing.done():
            raise HTTPException(
                status_code=409,
                detail="Database indexing already in progress for this connection",
            )

        db_status = await _db_index_svc.get_indexing_status(db, connection_id)
        if db_status == "running" and not (existing and existing.done()):
            raise HTTPException(
                status_code=409,
                detail="Database indexing already in progress for this connection",
            )

        from app.services.run_coordinator import RunAlreadyActiveError, RunCoordinator

        try:
            run = await RunCoordinator().start(
                db,
                kind="db_index",
                project_id=project_id,
                connection_id=connection_id,
                trigger="manual",
            )
        except RunAlreadyActiveError as exc:
            raise HTTPException(
                status_code=409,
                detail="Database indexing already in progress for this connection",
            ) from exc

        await _db_index_svc.set_indexing_status(db, connection_id, "running")
        await db.commit()

        await _dispatch_db_index(connection_id, config, project_id, wf_id=run.workflow_id)

    logger.info(
        "DB index started: connection=%s type=%s project=%s",
        connection_id[:8],
        conn.db_type,
        project_id[:8],
    )

    return JSONResponse(
        status_code=202,
        content={
            "status": "started",
            "run_id": run.id,
            "workflow_id": run.workflow_id,
            "connection_id": connection_id,
        },
    )


@router.get("/{connection_id}/index-db/status")
async def index_db_status(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get database index status for a connection."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "viewer")

    status = await _db_index_svc.get_status(db, connection_id)

    existing = _db_index_tasks.get(connection_id)
    in_memory_running = existing is not None and not existing.done()
    db_running = status.get("indexing_status") == "running"

    # In ARQ mode the run executes out-of-process in the worker, so there is no
    # local task handle — the persisted status is authoritative and must not be
    # reset. Only the in-process fallback path can have an orphaned 'running'
    # status (e.g. after an API restart that lost the asyncio task).
    if db_running and not in_memory_running and not task_queue.is_arq_active():
        logger.warning(
            "Stale indexing_status='running' with no in-memory task: "
            "connection=%s — resetting to 'failed'",
            connection_id[:8],
        )
        await _db_index_svc.set_indexing_status(db, connection_id, "failed")
        await db.commit()
        status["indexing_status"] = "failed"
        db_running = False

    status["is_indexing"] = in_memory_running or db_running

    return status


@router.get("/{connection_id}/index-db")
async def get_db_index(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get the full database index for a connection."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "viewer")

    entries = await _db_index_svc.get_index(db, connection_id)
    summary = await _db_index_svc.get_summary(db, connection_id)

    if not entries:
        return {"tables": [], "summary": None}

    return _db_index_svc.index_to_response(entries, summary)


@router.delete("/{connection_id}/index-db")
@limiter.limit("10/minute")
async def delete_db_index(
    request: Request,
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Clear the database index for a connection."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "owner")

    await _db_index_svc.delete_all(db, connection_id)
    logger.info("DB index cleared: connection=%s", connection_id[:8])
    return {"ok": True}


async def _regenerate_overview(project_id: str, connection_id: str | None = None) -> None:
    """Best-effort regenerate the project knowledge overview."""
    from app.models.base import async_session_factory
    from app.services.project_overview_service import ProjectOverviewService

    try:
        async with async_session_factory() as session:
            svc = ProjectOverviewService()
            await svc.save_overview(session, project_id, connection_id)
        logger.info("Project overview regenerated: project=%s", project_id[:8])
    except Exception:
        logger.debug("Failed to regenerate project overview", exc_info=True)


async def _maybe_start_db_index(
    db: AsyncSession,
    connection_id: str,
    config: ConnectionConfig,
    project_id: str,
    *,
    require_prior_index: bool = True,
) -> bool:
    """Start a background DB index run if one isn't already in flight.

    Returns ``True`` when a new task was scheduled. Guarded by the same
    per-connection start lock as the ``/index-db`` endpoint so concurrent
    refresh + manual index requests can't double-start. When
    ``require_prior_index`` is set (the refresh-schema path, R2-2) it only
    re-indexes connections that already have a stored ``db_index``.
    """
    if require_prior_index:
        try:
            existing_entries = await _db_index_svc.get_index(db, connection_id)
            if not existing_entries:
                return False
        except Exception:
            logger.debug("Could not check existing db_index entries", exc_info=True)
            return False

    idx_start_lock = _db_index_start_locks.setdefault(connection_id, asyncio.Lock())
    async with idx_start_lock:
        existing = _db_index_tasks.get(connection_id)
        if existing and not existing.done():
            return False

        db_status = await _db_index_svc.get_indexing_status(db, connection_id)
        if db_status == "running" and not (existing and existing.done()):
            return False

        await _db_index_svc.set_indexing_status(db, connection_id, "running")
        await db.commit()

        await _dispatch_db_index(connection_id, config, project_id)

    logger.info("Auto DB re-index started: connection=%s", connection_id[:8])
    return True


async def _run_db_index_background(
    connection_id: str,
    connection_config: ConnectionConfig,
    project_id: str,
    *,
    wf_id: str,
) -> None:
    from app.models.base import async_session_factory

    final_status = "failed"
    try:
        from app.config import settings as app_settings
        from app.knowledge.db_index_pipeline import DbIndexPipeline

        pipeline = DbIndexPipeline(
            db_index_batch_size=app_settings.db_index_batch_size,
        )
        result = await pipeline.run(
            connection_id=connection_id,
            connection_config=connection_config,
            project_id=project_id,
            wf_id=wf_id,
        )
        if isinstance(result, dict) and result.get("status") == "failed":
            logger.error(
                "DB index pipeline returned failure: connection=%s error=%s",
                connection_id[:8],
                result.get("error", "unknown"),
            )
            final_status = "failed"
        else:
            is_partial = isinstance(result, dict) and result.get("partial")
            if is_partial:
                logger.warning(
                    "DB index completed with PARTIAL evidence: connection=%s "
                    "tables=%s sample_failures=%s distinct_failures=%s embed_failed=%s",
                    connection_id[:8],
                    result.get("tables"),
                    result.get("sample_failures"),
                    result.get("distinct_failures"),
                    result.get("embed_failed"),
                )
                final_status = "completed_partial"
            else:
                logger.info(
                    "DB index completed: connection=%s tables=%s",
                    connection_id[:8],
                    # R2-6: the pipeline returns the indexed-table count under
                    # "tables" (see DbIndexPipeline.run); the old "tables_indexed"
                    # key never existed, so this line always logged tables=None.
                    result.get("tables") if isinstance(result, dict) else "ok",
                )
                final_status = "completed"
            await _regenerate_overview(project_id, connection_id)
            await _run_data_probes(
                connection_id,
                connection_config,
                project_id,
            )
    except Exception:
        logger.exception("DB index background task failed: connection=%s", connection_id[:8])
    finally:
        _db_index_tasks.pop(connection_id, None)
        try:
            async with async_session_factory() as session:
                await _db_index_svc.set_indexing_status(session, connection_id, final_status)
                await session.commit()
        except Exception:
            logger.debug("Failed to update indexing_status", exc_info=True)


async def _run_data_probes(
    connection_id: str,
    connection_config: ConnectionConfig,
    project_id: str,
) -> None:
    """Best-effort run probes on top tables after indexing."""
    from app.models.base import async_session_factory
    from app.services.db_index_service import DbIndexService
    from app.services.probe_service import ProbeService

    try:
        idx_svc = DbIndexService()
        async with async_session_factory() as session:
            entries = await idx_svc.get_index(session, connection_id)
            table_names = sorted(
                [(e.table_name, e.row_count or 0) for e in entries],
                key=lambda t: t[1],
                reverse=True,
            )
            top_tables = [t[0] for t in table_names[:5]]
            if not top_tables:
                return

            probe_svc = ProbeService()
            report = await probe_svc.run_probes(
                session,
                connection_id,
                project_id,
                connection_config,
                top_tables,
            )
            await session.commit()

            total_findings = sum(len(e.get("findings", [])) for e in report)
            if total_findings:
                logger.info(
                    "Data probes complete: connection=%s findings=%d",
                    connection_id[:8],
                    total_findings,
                )
    except Exception:
        logger.debug("Data probes failed (non-critical)", exc_info=True)


# ------------------------------------------------------------------
# Code-DB Sync endpoints
# ------------------------------------------------------------------


@router.post("/{connection_id}/sync", status_code=202)
@limiter.limit("5/minute")
async def trigger_sync(
    request: Request,
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Trigger code-database synchronization (runs in background)."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "editor")

    sync_start_lock = _sync_start_locks.setdefault(connection_id, asyncio.Lock())
    async with sync_start_lock:
        existing = _sync_tasks.get(connection_id)
        if existing and not existing.done():
            raise HTTPException(
                status_code=409,
                detail="Code-DB sync already in progress for this connection",
            )

        sync_status = await _sync_svc.get_sync_status(db, connection_id)
        if sync_status == "running" and not (existing and existing.done()):
            raise HTTPException(
                status_code=409,
                detail="Code-DB sync already in progress for this connection",
            )

        db_indexed = await _db_index_svc.is_indexed(db, connection_id)
        if not db_indexed:
            raise HTTPException(
                status_code=400,
                detail="Database must be indexed before running sync. Run 'Index DB' first.",
            )

        await _sync_svc.set_sync_status(db, connection_id, "running")
        await db.commit()

        project_id = conn.project_id
        await _dispatch_code_db_sync(connection_id, project_id)

    logger.info(
        "Code-DB sync started: connection=%s project=%s",
        connection_id[:8],
        project_id[:8],
    )

    return JSONResponse(
        status_code=202,
        content={"status": "started", "connection_id": connection_id},
    )


@router.get("/{connection_id}/sync/status")
async def sync_status(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get code-DB sync status for a connection."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "viewer")

    status = await _sync_svc.get_status(db, connection_id)

    existing = _sync_tasks.get(connection_id)
    in_memory_running = existing is not None and not existing.done()
    db_running = status.get("sync_status") == "running"

    if db_running and not in_memory_running and not task_queue.is_arq_active():
        logger.warning(
            "Stale sync_status='running' with no in-memory task: "
            "connection=%s — resetting to 'failed'",
            connection_id[:8],
        )
        await _sync_svc.set_sync_status(db, connection_id, "failed")
        await db.commit()
        status["sync_status"] = "failed"
        db_running = False

    status["is_syncing"] = in_memory_running or db_running

    return status


@router.get("/{connection_id}/sync")
async def get_sync(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get the full code-DB sync results for a connection."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "viewer")

    entries = await _sync_svc.get_sync(db, connection_id)
    summary = await _sync_svc.get_summary(db, connection_id)

    if not entries:
        return {"tables": [], "summary": None}

    return _sync_svc.sync_to_response(entries, summary)


@router.delete("/{connection_id}/sync")
@limiter.limit("10/minute")
async def delete_sync(
    request: Request,
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Clear the code-DB sync data for a connection."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "owner")

    await _sync_svc.delete_all(db, connection_id)
    logger.info("Code-DB sync cleared: connection=%s", connection_id[:8])
    return {"ok": True}


async def _run_sync_background(
    connection_id: str,
    project_id: str,
) -> None:
    from app.models.base import async_session_factory

    final_status = "failed"
    try:
        from app.knowledge.code_db_sync_pipeline import CodeDbSyncPipeline

        pipeline = CodeDbSyncPipeline()
        result = await pipeline.run(
            connection_id=connection_id,
            project_id=project_id,
        )
        if isinstance(result, dict) and result.get("status") == "failed":
            logger.error(
                "Code-DB sync pipeline returned failure: connection=%s error=%s",
                connection_id[:8],
                result.get("error", "unknown"),
            )
            final_status = "failed"
        else:
            logger.info(
                "Code-DB sync completed: connection=%s",
                connection_id[:8],
            )
            final_status = "completed"
            await _regenerate_overview(project_id, connection_id)
    except Exception:
        logger.exception("Code-DB sync background task failed: connection=%s", connection_id[:8])
    finally:
        _sync_tasks.pop(connection_id, None)
        try:
            async with async_session_factory() as session:
                await _sync_svc.set_sync_status(session, connection_id, final_status)
                await session.commit()
        except Exception:
            logger.debug("Failed to update sync_status", exc_info=True)
