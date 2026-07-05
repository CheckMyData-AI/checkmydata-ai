"""ARQ worker entry-point.

Run with::

    arq app.worker.WorkerSettings

The worker picks up jobs enqueued via :func:`app.core.task_queue.enqueue`
and executes them in a separate process, keeping the API event loop free.

When ``REDIS_URL`` is not set the module is never loaded; all tasks run
in-process via the asyncio fallback in ``task_queue.py``.
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task implementations — accept only JSON-serialisable arguments
# ---------------------------------------------------------------------------


async def run_db_index(  # noqa: ARG001
    ctx: dict, *, connection_id: str, project_id: str, wf_id: str
) -> None:
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
            wf_id=wf_id,
        )
        if isinstance(result, dict) and result.get("status") == "failed":
            logger.error(
                "run_db_index pipeline failure: connection=%s error=%s",
                connection_id[:8],
                result.get("error", "unknown"),
            )
        else:
            # R2-6: mirror the in-process background path (connections.py
            # _run_db_index_background) so the worker route doesn't silently
            # skip post-index steps. Without this, deployments running ARQ
            # (REDIS_URL set) never regenerate the project overview or run data
            # probes, and never surface the PARTIAL evidence status -- a quiet
            # behavioural divergence from the in-process fallback.
            is_partial = isinstance(result, dict) and result.get("partial")
            if is_partial:
                logger.warning(
                    "run_db_index completed with PARTIAL evidence: connection=%s "
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
                    "run_db_index completed: connection=%s tables=%s",
                    connection_id[:8],
                    result.get("tables") if isinstance(result, dict) else "ok",
                )
                final_status = "completed"
            # Bust the per-agent 300-second schema cache so the next query
            # re-introspects the freshly-indexed schema instead of serving
            # stale column names (DBIDX-D12).
            try:
                from app.core.schema_cache_registry import invalidate_connection

                invalidate_connection(connection_id)
            except Exception:
                logger.debug(
                    "run_db_index: schema cache invalidation failed for %s",
                    connection_id[:8],
                    exc_info=True,
                )
            try:
                from app.api.routes.connections import (
                    _regenerate_overview,
                    _run_data_probes,
                )

                await _regenerate_overview(project_id, connection_id)
                await _run_data_probes(connection_id, config, project_id)
            except Exception:
                logger.debug(
                    "run_db_index post-index steps failed for %s",
                    connection_id[:8],
                    exc_info=True,
                )
    except Exception:
        logger.exception("run_db_index failed for %s", connection_id[:8])
    finally:
        try:
            async with async_session_factory() as session:
                await idx_svc.set_indexing_status(session, connection_id, final_status)
                await session.commit()
        except Exception:
            logger.debug("Failed to update indexing_status", exc_info=True)


async def run_code_db_sync(  # noqa: ARG001
    ctx: dict, *, connection_id: str, project_id: str, wf_id: str
) -> None:
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
            wf_id=wf_id,
        )
        if isinstance(result, dict) and result.get("status") == "failed":
            logger.error(
                "run_code_db_sync pipeline failure: connection=%s error=%s",
                connection_id[:8],
                result.get("error", "unknown"),
            )
        else:
            tables = result.get("total_tables") if isinstance(result, dict) else None
            matched = result.get("synced") if isinstance(result, dict) else None
            logger.info(
                "run_code_db_sync completed: connection=%s tables=%s matched=%s",
                connection_id[:8],
                tables,
                matched,
            )
            final_status = "completed"
            try:
                from app.api.routes.connections import _regenerate_overview

                await _regenerate_overview(project_id, connection_id)
            except Exception:
                logger.debug(
                    "run_code_db_sync post-sync overview failed for %s",
                    connection_id[:8],
                    exc_info=True,
                )
    except Exception:
        logger.exception("run_code_db_sync failed for %s", connection_id[:8])
    finally:
        try:
            async with async_session_factory() as session:
                await sync_svc.set_sync_status(session, connection_id, final_status)
                await session.commit()
        except Exception:
            logger.debug("Failed to update sync_status", exc_info=True)


async def run_repo_index(  # noqa: ARG001
    ctx: dict, *, project_id: str, force_full: bool = False, wf_id: str | None = None
) -> None:
    """Background repository index for a single project (Phase 2 trigger target).

    Enqueued by the git webhook / cron poll / manual route when ARQ is active.
    Delegates to the shared in-process runner so checkpoint/resume, doc/BM25
    generation, overview regeneration, and the auto index→sync chain all match
    the non-ARQ path exactly.
    """
    from app.api.routes.repos import run_repo_index_task

    await run_repo_index_task(project_id, force_full=force_full, wf_id=wf_id)


async def run_batch(ctx: dict, *, batch_id: str, connection_id: str, user_id: str) -> None:  # noqa: ARG001
    """Background batch query execution."""
    from app.services.batch_service import BatchService

    svc = BatchService()
    await svc.execute_batch(batch_id, connection_id, user_id=user_id)


async def run_daily_project_knowledge_sync(ctx: dict, *, project_id: str) -> None:  # noqa: ARG001
    """Daily orchestrator: repo index → DB index → code↔DB sync for one project."""
    from app.services.daily_knowledge_sync_service import DailyKnowledgeSyncService

    await DailyKnowledgeSyncService().run_for_project(project_id)


# ---------------------------------------------------------------------------
# Startup / shutdown hooks
# ---------------------------------------------------------------------------


async def startup(ctx: dict) -> None:  # noqa: ARG001
    """Called once when the worker starts."""
    from app.core import redis_client
    from app.core.logging_config import configure_logging
    from app.core.workflow_tracker import tracker
    from app.models.base import init_db, run_migrations

    configure_logging(
        json_format=os.getenv("LOG_FORMAT", "text") == "json",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )
    run_migrations()
    await init_db()
    redis_url = os.getenv("REDIS_URL")
    await redis_client.connect(redis_url)
    tracker.enable_cross_process_publish()
    from app.services.run_coordinator import RunCoordinator

    RunCoordinator().attach()
    from app.core.reaper_loop import reaper_loop, run_reaper_sweep

    await run_reaper_sweep()
    ctx["reaper_task"] = asyncio.create_task(reaper_loop())
    logger.info("ARQ worker started")


async def shutdown(ctx: dict) -> None:  # noqa: ARG001
    """Called once when the worker stops."""
    task = ctx.get("reaper_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    from app.core import redis_client
    from app.models.base import engine

    await redis_client.close()
    await engine.dispose()
    logger.info("ARQ worker stopped")


# ---------------------------------------------------------------------------
# ARQ WorkerSettings
# ---------------------------------------------------------------------------


def _redis_settings():  # pragma: no cover
    """Build ARQ RedisSettings from REDIS_URL env var."""
    from app.core.redis_tls import arq_redis_settings

    url = os.getenv("REDIS_URL", "redis://localhost:6379")
    return arq_redis_settings(url)


class WorkerSettings:  # pragma: no cover
    """ARQ discovers this class automatically."""

    functions = [
        run_db_index,
        run_code_db_sync,
        run_repo_index,
        run_batch,
        run_daily_project_knowledge_sync,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _redis_settings()
    max_jobs = 8
    job_timeout = 1800  # 30 min
    poll_delay = 1.0
