import logging
import subprocess
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

if settings.database_url.startswith("sqlite"):
    _db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
    if _db_path and not _db_path.startswith(":"):
        Path(_db_path).parent.mkdir(parents=True, exist_ok=True)

_engine_kwargs: dict = {"echo": settings.sql_echo}
if not settings.database_url.startswith("sqlite"):
    _engine_kwargs.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_overflow,
        pool_pre_ping=True,
        pool_recycle=settings.db_pool_recycle,
        pool_timeout=settings.db_pool_timeout,
    )

engine = create_async_engine(settings.database_url, **_engine_kwargs)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def run_migrations() -> None:
    """Run Alembic migrations programmatically (sync, called at startup)."""
    import os

    backend_dir = Path(__file__).resolve().parent.parent.parent
    try:
        subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=str(backend_dir),
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(backend_dir)},
        )
        logger.info("Alembic migrations applied successfully")
    except FileNotFoundError:
        logger.warning("alembic CLI not found — falling back to create_all")
        _fallback_create_all()
    except subprocess.CalledProcessError as exc:
        logger.error("Alembic migration failed: %s", exc.stderr)
        raise


def _fallback_create_all() -> None:
    """Fallback for environments without Alembic CLI (e.g. minimal Docker)."""
    import asyncio

    from app.models import (  # noqa: F401
        agent_learning,
        batch_query,
        benchmark,
        chat_session,
        code_db_sync,
        commit_index,
        connection,
        custom_rule,
        dashboard,
        data_validation,
        db_index,
        indexing_checkpoint,
        insight_record,
        knowledge_doc,
        metric_definition,
        notification,
        project,
        project_cache,
        project_invite,
        project_member,
        rag_feedback,
        repository,
        saved_note,
        scheduled_query,
        session_note,
        ssh_key,
        token_usage,
        user,
    )

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            pool.submit(asyncio.run, _create()).result()
    else:
        asyncio.run(_create())


async def init_db():
    """Called at app startup. Imports all models so relationships are registered."""
    from app.models import (  # noqa: F401
        agent_learning,
        batch_query,
        benchmark,
        chat_session,
        code_db_sync,
        commit_index,
        connection,
        custom_rule,
        dashboard,
        data_validation,
        db_index,
        indexing_checkpoint,
        insight_record,
        knowledge_doc,
        metric_definition,
        notification,
        project,
        project_cache,
        project_invite,
        project_member,
        rag_feedback,
        repository,
        saved_note,
        scheduled_query,
        session_note,
        ssh_key,
        token_usage,
        user,
    )
