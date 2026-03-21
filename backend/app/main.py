from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes import (
    auth,
    backup,
    chat,
    connections,
    data_validation,
    invites,
    metrics,
    models,
    notes,
    projects,
    repos,
    rules,
    ssh_keys,
    tasks,
    usage,
    visualizations,
    workflows,
)
from app.config import settings
from app.core.logging_config import configure_logging
from app.core.rate_limit import limiter
from app.models.base import async_session_factory, init_db, run_migrations
from app.services.checkpoint_service import CheckpointService

configure_logging(
    json_format=os.getenv("LOG_FORMAT", "text") == "json",
    level=os.getenv("LOG_LEVEL", "INFO"),
)

logger = logging.getLogger(__name__)


_backup_task: asyncio.Task[None] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _backup_task  # noqa: PLW0603

    await asyncio.to_thread(run_migrations)
    await init_db()
    await _check_alembic_head()
    await _cleanup_stale_checkpoints()
    await _reset_stale_indexing_statuses()
    await _backfill_default_rules()
    await _decay_stale_learnings()
    await _cleanup_pipeline_runs()

    if settings.backup_enabled:
        _backup_task = asyncio.create_task(_backup_cron_loop())
        await _maybe_initial_backup()

    yield

    if _backup_task and not _backup_task.done():
        _backup_task.cancel()
        try:
            await _backup_task
        except asyncio.CancelledError:
            pass
    logger.info("Shutting down: disconnecting connectors and tunnels")
    try:
        sql_agent = chat._agent._orchestrator._sql
        for key, conn in list(sql_agent._connectors.items()):
            try:
                await conn.disconnect()
            except Exception:
                logger.warning("Error disconnecting connector %s", key)
        sql_agent._connectors.clear()
    except Exception:
        logger.exception("Error during connector cleanup")
    for mgr_module in (
        repos,
        __import__("app.connectors.postgres", fromlist=["_tunnel_mgr"]),
        __import__("app.connectors.mysql", fromlist=["_tunnel_mgr"]),
        __import__("app.connectors.mongodb", fromlist=["_tunnel_mgr"]),
        __import__("app.connectors.clickhouse", fromlist=["_tunnel_mgr"]),
    ):
        mgr = getattr(mgr_module, "_tunnel_mgr", None)
        if mgr and hasattr(mgr, "close_all"):
            try:
                await mgr.close_all()
            except Exception:
                logger.exception("Error closing tunnel manager")
    try:
        from app.models.base import engine

        await engine.dispose()
        logger.info("Database engine disposed")
    except Exception:
        logger.exception("Error disposing database engine")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > settings.max_request_body_bytes:
            from starlette.responses import JSONResponse

            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large"},
            )
        return await call_next(request)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assigns a short request ID to every incoming HTTP request for log correlation."""

    async def dispatch(self, request: Request, call_next):
        from app.core.workflow_tracker import request_id_var

        req_id = uuid.uuid4().hex[:12]
        token = request_id_var.set(req_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response
        finally:
            request_id_var.reset(token)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        from app.api.routes.metrics import record_request

        start = time.monotonic()
        try:
            response = await call_next(request)
            latency_ms = (time.monotonic() - start) * 1000
            record_request(request.url.path, latency_ms, response.status_code >= 400)
            return response
        except Exception:
            latency_ms = (time.monotonic() - start) * 1000
            record_request(request.url.path, latency_ms, True)
            raise


app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(connections.router, prefix="/api/connections", tags=["connections"])
app.include_router(repos.router, prefix="/api/repos", tags=["repos"])
app.include_router(ssh_keys.router, prefix="/api/ssh-keys", tags=["ssh-keys"])
app.include_router(visualizations.router, prefix="/api/visualizations", tags=["visualizations"])
app.include_router(workflows.router, prefix="/api/workflows", tags=["workflows"])
app.include_router(rules.router, prefix="/api/rules", tags=["rules"])
app.include_router(notes.router, prefix="/api/notes", tags=["notes"])
app.include_router(invites.router, prefix="/api/invites", tags=["invites"])
app.include_router(models.router, prefix="/api/models", tags=["models"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(metrics.router, prefix="/api", tags=["metrics"])
app.include_router(data_validation.router, prefix="/api/data-validation", tags=["data-validation"])
app.include_router(usage.router, prefix="/api/usage", tags=["usage"])
app.include_router(backup.router, prefix="/api/backup", tags=["backup"])


async def _check_alembic_head() -> None:
    """Warn if the database schema is behind the latest Alembic migration."""
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        from app.models.base import engine

        alembic_cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(alembic_cfg)
        head_rev = script.get_current_head()

        async with engine.connect() as conn:
            current_rev = await conn.run_sync(
                lambda sync_conn: MigrationContext.configure(sync_conn).get_current_revision()
            )

        if current_rev != head_rev:
            logger.warning(
                "Database migration mismatch: current=%s, head=%s. "
                "Run 'alembic upgrade head' to apply pending migrations.",
                current_rev,
                head_rev,
            )
            if settings.environment.lower() in ("development", "dev"):
                logger.info("Dev mode: auto-migrating to head")
                from alembic import command

                await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
        else:
            logger.info("Database schema is up to date (revision=%s)", current_rev)
    except Exception:
        logger.debug("Alembic head check skipped (not available)", exc_info=True)


async def _cleanup_stale_checkpoints() -> None:
    """Mark orphaned 'running' checkpoints as interrupted and remove stale ones."""
    try:
        async with async_session_factory() as session:
            svc = CheckpointService()
            cleaned = await svc.cleanup_stale(session, max_age_hours=24)
            if cleaned:
                logger.info("Startup: cleaned %d stale checkpoints", cleaned)
    except Exception:
        logger.warning("Failed to clean stale checkpoints at startup", exc_info=True)


async def _reset_stale_indexing_statuses() -> None:
    """Reset any 'running' indexing/sync statuses left over from a previous process."""
    try:
        from sqlalchemy import update

        from app.models.code_db_sync import CodeDbSyncSummary
        from app.models.db_index import DbIndexSummary

        async with async_session_factory() as session:
            idx_result = await session.execute(
                update(DbIndexSummary)
                .where(DbIndexSummary.indexing_status == "running")
                .values(indexing_status="failed")
            )
            sync_result = await session.execute(
                update(CodeDbSyncSummary)
                .where(CodeDbSyncSummary.sync_status == "running")
                .values(sync_status="failed")
            )
            total = (idx_result.rowcount or 0) + (sync_result.rowcount or 0)  # type: ignore[attr-defined]
            if total:
                await session.commit()
                logger.info(
                    "Startup: reset stale 'running' statuses — %d indexing, %d sync",
                    idx_result.rowcount or 0,  # type: ignore[attr-defined]
                    sync_result.rowcount or 0,  # type: ignore[attr-defined]
                )
    except Exception:
        logger.warning("Failed to reset stale indexing statuses at startup", exc_info=True)


async def _backfill_default_rules() -> None:
    """One-time: create default rule for existing projects that never had one.

    Projects that already have custom rules (user-created) are marked as
    initialized without creating the default rule, so we never re-create it
    for projects where rules were intentionally deleted.
    """
    try:
        from sqlalchemy import func, select

        from app.models.custom_rule import CustomRule
        from app.models.project import Project
        from app.services.rule_service import RuleService

        svc = RuleService()
        async with async_session_factory() as session:
            result = await session.execute(
                select(Project).where(Project.default_rule_initialized == False)  # noqa: E712
            )
            projects = list(result.scalars().all())
            if not projects:
                return

            created = 0
            for project in projects:
                existing = await session.execute(
                    select(func.count())
                    .select_from(CustomRule)
                    .where(CustomRule.project_id == project.id)
                )
                if existing.scalar() == 0:
                    await svc.ensure_default_rule(session, project.id)
                    created += 1
                else:
                    project.default_rule_initialized = True

            await session.commit()
            if created:
                logger.info("Startup: created default rules for %d projects", created)
    except Exception:
        logger.warning("Failed to backfill default rules at startup", exc_info=True)


async def _decay_stale_learnings() -> None:
    """Reduce confidence of learnings inactive for >30 days (runs once at startup)."""
    try:
        from app.services.agent_learning_service import AgentLearningService

        svc = AgentLearningService()
        async with async_session_factory() as session:
            affected = await svc.decay_stale_learnings(session)
            await session.commit()
            if affected:
                logger.info("Startup: decayed confidence for %d stale learnings", affected)
    except Exception:
        logger.warning("Failed to decay stale learnings at startup", exc_info=True)


async def _periodic_learning_decay() -> None:
    """Daily decay of stale learnings and unverified session notes."""
    try:
        from app.services.agent_learning_service import AgentLearningService

        svc = AgentLearningService()
        async with async_session_factory() as session:
            affected = await svc.decay_stale_learnings(session)
            await session.commit()
            if affected:
                logger.info(
                    "Cron: decayed confidence for %d stale learnings",
                    affected,
                )
    except Exception:
        logger.warning("Periodic learning decay failed", exc_info=True)

    try:
        from app.services.session_notes_service import SessionNotesService

        notes_svc = SessionNotesService()
        async with async_session_factory() as session:
            decayed = await notes_svc.decay_stale_notes(session)
            await session.commit()
            if decayed:
                logger.info(
                    "Cron: decayed %d stale session notes",
                    decayed,
                )
    except Exception:
        logger.warning("Periodic note decay failed", exc_info=True)


async def _cleanup_pipeline_runs() -> None:
    """Delete pipeline_runs older than PIPELINE_RUN_TTL_DAYS."""
    try:
        from datetime import timedelta

        from sqlalchemy import delete

        from app.models.pipeline_run import PipelineRun

        cutoff = datetime.now(UTC) - timedelta(days=settings.pipeline_run_ttl_days)
        async with async_session_factory() as session:
            result = await session.execute(
                delete(PipelineRun).where(PipelineRun.updated_at < cutoff)
            )
            await session.commit()
            deleted = result.rowcount  # type: ignore[attr-defined]
            if deleted:
                logger.info("Startup: cleaned %d expired pipeline_runs", deleted)
    except Exception:
        logger.warning("Failed to clean expired pipeline_runs at startup", exc_info=True)


async def _backup_cron_loop() -> None:
    """Run backup daily at the configured hour (default 00:00 UTC)."""
    from datetime import timedelta

    from app.core.backup_manager import BackupManager
    from app.models.backup_record import BackupRecord

    mgr = BackupManager()
    while True:
        try:
            now = datetime.now(UTC)
            target_hour = settings.backup_hour
            next_run = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            wait_seconds = (next_run - now).total_seconds()
            logger.info(
                "Next scheduled backup in %.0f seconds (at %s)",
                wait_seconds,
                next_run.isoformat(),
            )
            await asyncio.sleep(wait_seconds)
            manifest = await mgr.run_backup("scheduled")
            async with async_session_factory() as session:
                session.add(
                    BackupRecord(
                        reason="scheduled",
                        status="success",
                        size_bytes=manifest.get("total_size_bytes", 0),
                        manifest_json=manifest,
                    )
                )
                await session.commit()
            await _periodic_learning_decay()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Scheduled backup failed, will retry next cycle")
            try:
                async with async_session_factory() as session:
                    session.add(BackupRecord(reason="scheduled", status="failed"))
                    await session.commit()
            except Exception:
                pass
            await asyncio.sleep(60)


async def _maybe_initial_backup() -> None:
    """Run a one-time backup on first startup if no backups exist yet."""
    from pathlib import Path

    backup_path = Path(settings.backup_dir)
    if backup_path.exists() and any(backup_path.iterdir()):
        return
    logger.info("No existing backups found — running initial backup")
    await trigger_initial_backup()


async def trigger_initial_backup() -> None:
    """Trigger a one-time backup after initial project sync."""
    from app.core.backup_manager import BackupManager

    try:
        mgr = BackupManager()
        await mgr.run_backup("initial_sync")
    except Exception:
        logger.exception("Initial sync backup failed")


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


@app.get("/api/health/modules")
async def module_health():
    """Per-module health checks for independent debugging."""
    results: dict[str, dict] = {}

    # Internal database
    try:
        from app.models.base import async_session_factory

        async with async_session_factory() as session:
            await session.execute(__import__("sqlalchemy").text("SELECT 1"))
        results["database"] = {"status": "ok"}
    except Exception:
        results["database"] = {"status": "error", "detail": "Service unavailable"}

    # Vector store (ChromaDB)
    try:
        from app.knowledge.vector_store import VectorStore

        vs = VectorStore()
        vs._client.heartbeat()
        results["vector_store"] = {"status": "ok"}
    except Exception:
        results["vector_store"] = {"status": "error", "detail": "Service unavailable"}

    # SSH tunnels
    try:
        tunnel_info = []
        for mod_path in ("app.connectors.postgres", "app.connectors.mysql"):
            try:
                mod = __import__(mod_path, fromlist=["_tunnel_mgr"])
                mgr = getattr(mod, "_tunnel_mgr", None)
                if mgr:
                    tunnel_info.append({"module": mod_path, "active_tunnels": len(mgr._tunnels)})
            except Exception:
                pass
        results["ssh_tunnels"] = {"status": "ok", "detail": tunnel_info}
    except Exception:
        results["ssh_tunnels"] = {"status": "error", "detail": "Service unavailable"}

    # Active connectors
    try:
        agent = getattr(chat, "_agent", None)
        orch = getattr(agent, "_orchestrator", None) if agent else None
        sql = getattr(orch, "_sql", None) if orch else None
        conns = getattr(sql, "_connectors", {}) if sql else {}
        active = list(conns.keys())
        results["connectors"] = {"status": "ok", "active": len(active)}
    except Exception:
        results["connectors"] = {"status": "error", "detail": "Service unavailable"}

    # LLM provider
    try:
        import asyncio
        import time

        from app.llm.base import Message
        from app.llm.router import LLMRouter

        llm = LLMRouter()
        start = time.monotonic()
        await asyncio.wait_for(
            llm.complete([Message(role="user", content="ping")], max_tokens=1),
            timeout=5.0,
        )
        elapsed = round((time.monotonic() - start) * 1000, 1)
        results["llm"] = {
            "status": "ok",
            "provider": settings.default_llm_provider,
            "response_time_ms": elapsed,
        }
        await llm.close()
    except TimeoutError:
        results["llm"] = {"status": "error", "detail": "Timeout (5s)"}
    except Exception:
        results["llm"] = {"status": "error", "detail": "Service unavailable"}

    overall = "ok" if all(r["status"] == "ok" for r in results.values()) else "degraded"
    return {"status": overall, "modules": results}
