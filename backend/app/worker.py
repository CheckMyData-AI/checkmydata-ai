"""ARQ worker entry-point.

Run with::

    arq app.worker.WorkerSettings

The worker picks up jobs enqueued via :func:`app.core.task_queue.enqueue`
and executes them in a separate process, keeping the API event loop free.

When ``REDIS_URL`` is not set the module is never loaded; all tasks run
in-process via the asyncio fallback in ``task_queue.py``.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task implementations — accept only JSON-serialisable arguments
# ---------------------------------------------------------------------------


async def run_db_index(ctx: dict, *, connection_id: str, project_id: str) -> None:  # noqa: ARG001
    """Background DB index for a single connection."""
    from app.models.base import async_session_factory
    from app.services.connection_service import ConnectionService
    from app.services.db_index_service import DbIndexService

    svc = ConnectionService()
    idx_svc = DbIndexService()

    async with async_session_factory() as session:
        conn = await svc.get(session, connection_id)
        if not conn:
            logger.error("run_db_index: connection %s not found", connection_id[:8])
            return
        config = await svc.to_config(session, conn)

    final_status = "failed"
    try:
        async with async_session_factory() as session:
            await idx_svc.set_indexing_status(session, connection_id, "running")
            await session.commit()

        from app.config import settings as app_settings
        from app.knowledge.db_index_pipeline import DbIndexPipeline

        pipeline = DbIndexPipeline(
            db_index_batch_size=app_settings.db_index_batch_size,
        )
        result = await pipeline.run(
            connection_id=connection_id,
            connection_config=config,
            project_id=project_id,
        )
        if isinstance(result, dict) and result.get("status") == "failed":
            logger.error(
                "run_db_index pipeline failure: connection=%s error=%s",
                connection_id[:8],
                result.get("error", "unknown"),
            )
        else:
            logger.info("run_db_index completed: connection=%s", connection_id[:8])
            final_status = "completed"
    except Exception:
        logger.exception("run_db_index failed for %s", connection_id[:8])
    finally:
        try:
            async with async_session_factory() as session:
                await idx_svc.set_indexing_status(session, connection_id, final_status)
                await session.commit()
        except Exception:
            logger.debug("Failed to update indexing_status", exc_info=True)


async def run_code_db_sync(ctx: dict, *, connection_id: str, project_id: str) -> None:  # noqa: ARG001
    """Background code-DB sync for a single connection."""
    from app.models.base import async_session_factory
    from app.services.code_db_sync_service import CodeDbSyncService

    sync_svc = CodeDbSyncService()
    final_status = "failed"
    try:
        async with async_session_factory() as session:
            await sync_svc.set_sync_status(session, connection_id, "running")
            await session.commit()

        from app.knowledge.code_db_sync_pipeline import CodeDbSyncPipeline

        pipeline = CodeDbSyncPipeline()
        result = await pipeline.run(
            connection_id=connection_id,
            project_id=project_id,
        )
        if isinstance(result, dict) and result.get("status") == "failed":
            logger.error(
                "run_code_db_sync pipeline failure: connection=%s error=%s",
                connection_id[:8],
                result.get("error", "unknown"),
            )
        else:
            logger.info("run_code_db_sync completed: connection=%s", connection_id[:8])
            final_status = "completed"
    except Exception:
        logger.exception("run_code_db_sync failed for %s", connection_id[:8])
    finally:
        try:
            async with async_session_factory() as session:
                await sync_svc.set_sync_status(session, connection_id, final_status)
                await session.commit()
        except Exception:
            logger.debug("Failed to update sync_status", exc_info=True)


async def run_batch(ctx: dict, *, batch_id: str, connection_id: str, user_id: str) -> None:  # noqa: ARG001
    """Background batch query execution."""
    from app.services.batch_service import BatchService

    svc = BatchService()
    await svc.execute_batch(batch_id, connection_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Startup / shutdown hooks
# ---------------------------------------------------------------------------


async def startup(ctx: dict) -> None:  # noqa: ARG001
    """Called once when the worker starts."""
    from app.core.logging_config import configure_logging
    from app.models.base import init_db, run_migrations

    configure_logging(
        json_format=os.getenv("LOG_FORMAT", "text") == "json",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )
    run_migrations()
    await init_db()
    logger.info("ARQ worker started")


async def shutdown(ctx: dict) -> None:  # noqa: ARG001
    """Called once when the worker stops."""
    from app.models.base import engine

    await engine.dispose()
    logger.info("ARQ worker stopped")


# ---------------------------------------------------------------------------
# ARQ WorkerSettings
# ---------------------------------------------------------------------------


def _redis_settings():  # pragma: no cover
    """Build ARQ RedisSettings from REDIS_URL env var."""
    from arq.connections import RedisSettings

    url = os.getenv("REDIS_URL", "redis://localhost:6379")
    return RedisSettings.from_dsn(url)


class WorkerSettings:  # pragma: no cover
    """ARQ discovers this class automatically."""

    functions = [
        run_db_index,
        run_code_db_sync,
        run_batch,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _redis_settings()
    max_jobs = 8
    job_timeout = 1800  # 30 min
    poll_delay = 1.0
