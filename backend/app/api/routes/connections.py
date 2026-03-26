from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.connectors.base import ConnectionConfig

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
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
                "%s %s failed: %s", label, resource_id, exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    return _cb


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
    ssh_pre_commands: list[str] | None = None
    mcp_server_command: str | None = Field(None, max_length=500)
    mcp_server_args: list[str] | None = None
    mcp_server_url: str | None = Field(None, max_length=2000)
    mcp_transport_type: str | None = Field(None, max_length=50)
    mcp_env: dict[str, str] | None = None


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
                        task = asyncio.create_task(
                            _run_db_index_background(connection_id, config, conn.project_id)
                        )
                        task.add_done_callback(_log_task_error("DB index", connection_id))
                        _db_index_tasks[connection_id] = task
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
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "owner")

    config = await _svc.to_config(db, conn, user_id=user["user_id"])
    try:
        from app.connectors.registry import get_connector

        connector = get_connector(conn.db_type, ssh_exec_mode=config.ssh_exec_mode)
        await connector.connect(config)
        try:
            schema = await connector.introspect_schema()
        finally:
            await connector.disconnect()
        return {
            "ok": True,
            "tables": len(schema.tables),
            "db_type": schema.db_type,
        }
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

        config = await _svc.to_config(db, conn, user_id=user["user_id"])
        project_id = conn.project_id

        await _db_index_svc.set_indexing_status(db, connection_id, "running")
        await db.commit()

        task = asyncio.create_task(_run_db_index_background(connection_id, config, project_id))
        task.add_done_callback(_log_task_error("DB index", connection_id))
        _db_index_tasks[connection_id] = task

    logger.info(
        "DB index started: connection=%s type=%s project=%s",
        connection_id[:8],
        conn.db_type,
        project_id[:8],
    )

    return JSONResponse(
        status_code=202,
        content={"status": "started", "connection_id": connection_id},
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

    if db_running and not in_memory_running:
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


async def _run_db_index_background(
    connection_id: str,
    connection_config: ConnectionConfig,
    project_id: str,
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
        )
        if isinstance(result, dict) and result.get("status") == "failed":
            logger.error(
                "DB index pipeline returned failure: connection=%s error=%s",
                connection_id[:8],
                result.get("error", "unknown"),
            )
            final_status = "failed"
        else:
            logger.info(
                "DB index completed: connection=%s tables=%s",
                connection_id[:8],
                result.get("tables_indexed") if isinstance(result, dict) else "ok",
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
        task = asyncio.create_task(_run_sync_background(connection_id, project_id))
        task.add_done_callback(_log_task_error("Code-DB sync", connection_id))
        _sync_tasks[connection_id] = task

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

    if db_running and not in_memory_running:
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


# ------------------------------------------------------------------
# Agent Learnings endpoints
# ------------------------------------------------------------------


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


@router.patch("/{connection_id}/learnings/{learning_id}")
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


@router.delete("/{connection_id}/learnings/{learning_id}")
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
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "owner")

    from app.models.agent_learning import AgentLearning

    check = await db.get(AgentLearning, learning_id)
    if not check or check.connection_id != connection_id:
        raise HTTPException(status_code=404, detail="Learning not found")

    deleted = await _learning_svc.delete_learning(db, learning_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Learning not found")
    await db.commit()
    return {"ok": True}


@router.delete("/{connection_id}/learnings")
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
