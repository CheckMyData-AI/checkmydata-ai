import logging
import subprocess
from contextlib import contextmanager
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


def enable_sqlite_fk(async_engine) -> None:  # noqa: ANN001
    """Enforce foreign keys on SQLite connections.

    SQLite does not enforce ``FOREIGN KEY`` constraints unless
    ``PRAGMA foreign_keys=ON`` is issued on **every** connection, so without this
    every ``ondelete=CASCADE`` is a silent no-op in dev/tests (F-AUTH-01) — leaving
    orphaned rows (including Fernet-encrypted secrets) and making cascade tests pass
    for the wrong reason. Registering it on ``sync_engine`` covers the aiosqlite
    DBAPI connection. Reused by the integration test engine so cascade tests exercise
    the real path. No-op for non-SQLite engines (Postgres enforces FKs natively).
    """
    from sqlalchemy import event

    @event.listens_for(async_engine.sync_engine, "connect")
    def _fk_pragma(dbapi_conn, _record):  # noqa: ANN001, ANN202
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


engine = create_async_engine(settings.database_url, **_engine_kwargs)
if settings.database_url.startswith("sqlite"):
    enable_sqlite_fk(engine)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


#: Serialises `alembic upgrade head` across processes. DATA-10: three callers fire on a
#: restart — the `web` start command, the `web` lifespan and `worker.startup` — and none of
#: them took a lock, while every *idempotent* reconcile in `app/ops/` takes one. A deploy
#: carrying a new migration restarted both process types at once; both read the same
#: revision, both planned the same DDL, and the second failed on a column that now existed.
_MIGRATION_LOCK_KEY = 0x4D49_4752_4154_4501

#: Failures that mean "this environment cannot lend us a lock", as opposed to a defect here.
#: Built at import rather than written as `except Exception`, and `psycopg.Error` is on it
#: for a reason worth keeping: a refused connection raises `psycopg.OperationalError`, which
#: does **not** inherit from `OSError` — the first draft of this narrow catch would have let
#: it escape and turned a missing lock into a failed boot.
_LOCK_UNAVAILABLE: tuple[type[BaseException], ...] = (ImportError, OSError)
try:  # pragma: no cover - depends on the installed driver set
    import psycopg as _psycopg

    _LOCK_UNAVAILABLE += (_psycopg.Error,)
except ImportError:
    pass


def _migration_lock_connection():
    """A psycopg connection for the migration advisory lock, or raise.

    Separate from the app's pool on purpose: the lock is **session-level**, so it must
    outlive the statement that takes it and die with a connection nobody else is using.
    """
    import psycopg

    from app.core.db_url import sync_dsn

    return psycopg.connect(sync_dsn(settings.database_url), autocommit=True)


@contextmanager
def _serialised_across_processes():
    """Hold the migration lock for the duration, on PostgreSQL only.

    **Blocking (`pg_advisory_lock`), not the `try_` form the reconciles use.** They are right
    to skip when someone else holds it — their work is idempotent and the holder is doing it.
    This one must not skip: the caller's next line assumes the schema is at head, so a
    migration that quietly did not run is worse than one that waited.

    A database that cannot be reached for the lock does not stop the migration: the attempt
    that follows will fail on its own and say why, and refusing to migrate because an
    advisory lock could not be taken would turn a degraded path into an outage.
    """
    from app.core.db_url import is_postgres

    if not is_postgres(settings.database_url):
        yield
        return

    # Narrow on purpose: a driver that is absent (ImportError) or a database that refuses
    # the connection (OSError, psycopg.Error) is a degraded environment the migration can
    # still be attempted in. Anything else is a bug here and must not be swallowed.
    try:
        conn = _migration_lock_connection()
    except _LOCK_UNAVAILABLE as exc:
        logger.warning(
            "Could not open a connection for the migration lock (%s); running unserialised",
            exc.__class__.__name__,
        )
        yield
        return

    try:
        with conn as c:
            c.execute(f"SELECT pg_advisory_lock({_MIGRATION_LOCK_KEY})")
            try:
                yield
            finally:
                c.execute(f"SELECT pg_advisory_unlock({_MIGRATION_LOCK_KEY})")
    finally:
        conn.close()


def run_migrations() -> None:
    """Run Alembic migrations programmatically (sync, called at startup)."""
    with _serialised_across_processes():
        _run_alembic()


def _run_alembic() -> None:
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
        audit_log,
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
        request_trace,
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
        audit_log,
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
        request_trace,
        saved_note,
        scheduled_query,
        session_note,
        ssh_key,
        token_usage,
        user,
    )
