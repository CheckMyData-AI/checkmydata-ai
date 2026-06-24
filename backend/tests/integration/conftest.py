"""Shared fixtures for integration tests.

Uses a real async SQLite database per test session, overriding the FastAPI
dependency so every endpoint hits an actual DB instead of mocks.
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import (  # noqa: F401
    agent_learning,
    audit_log,
    backup_record,
    batch_query,
    benchmark,
    chat_session,
    code_db_sync,
    code_graph,
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
    pipeline_run,
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
from app.models.base import Base


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    from app.models.base import enable_sqlite_fk

    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    enable_sqlite_fk(eng)  # F-AUTH-01: cascade tests must exercise real FK enforcement
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            __import__("sqlalchemy").text(
                "CREATE TRIGGER IF NOT EXISTS test_grant_can_create_projects "
                "AFTER INSERT ON users BEGIN "
                "UPDATE users SET can_create_projects = 1 WHERE id = NEW.id; "
                "END;"
            )
        )
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture()
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture()
async def client(engine, db_session: AsyncSession):
    """Unauthenticated client — use for auth endpoints only."""
    import app.models.base as base_mod
    from app.api.deps import get_db
    from app.core.rate_limit import limiter
    from app.main import app

    async def _override():
        yield db_session

    test_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    orig_factory = base_mod.async_session_factory

    app.dependency_overrides[get_db] = _override
    base_mod.async_session_factory = test_factory
    limiter.enabled = False
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    base_mod.async_session_factory = orig_factory
    limiter.enabled = True


@pytest_asyncio.fixture()
async def auth_client(client: AsyncClient, db_session: AsyncSession):
    """Authenticated client — registers a fresh user and sets the Bearer header.

    The user is automatically granted ``can_create_projects`` so existing
    project-related tests continue to pass.
    """
    email = f"test-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "testpass123",
            "display_name": "Test User",
        },
    )
    assert resp.status_code == 200, f"Registration failed: {resp.text}"
    token = resp.json()["token"]
    user_id = resp.json()["user"]["id"]

    await _grant_project_creation(db_session, user_id)

    client.headers["Authorization"] = f"Bearer {token}"
    yield client
    client.headers.pop("Authorization", None)


async def _grant_project_creation(db_session: AsyncSession, user_id: str) -> None:
    """Set ``can_create_projects = True`` for a test user."""
    from sqlalchemy import update

    from app.models.user import User

    await db_session.execute(
        update(User).where(User.id == user_id).values(can_create_projects=True)
    )
    await db_session.flush()


async def register_user(
    client: AsyncClient,
    email: str | None = None,
    *,
    db_session: AsyncSession | None = None,
) -> dict:
    """Helper: register a user and return {token, user_id, email}.

    When ``db_session`` is passed the user is automatically granted
    ``can_create_projects`` so it can own projects in tests.
    """
    email = email or f"user-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "testpass123",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    user_id = data["user"]["id"]

    if db_session is not None:
        await _grant_project_creation(db_session, user_id)

    return {"token": data["token"], "user_id": user_id, "email": email}


def auth_headers(token: str) -> dict[str, str]:
    """Build Authorization header dict from a JWT token."""
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Parent-row seeding helpers (F-AUTH-01).
#
# With SQLite FK enforcement now on, service-level tests can no longer insert
# child rows (token_usage, batch_queries, benchmarks, …) against random
# non-existent user/project/connection ids. These helpers create the real
# parent rows so the inserts are valid and the tests assert against the real
# cascade path instead of passing for the wrong reason.
# ---------------------------------------------------------------------------


async def make_user(db_session: AsyncSession, *, user_id: str | None = None) -> str:
    """Insert a User and return its id."""
    from app.models.user import User

    uid = user_id or str(uuid.uuid4())
    db_session.add(User(id=uid, email=f"u-{uid[:8]}@test.com", display_name="Seed"))
    await db_session.commit()
    return uid


async def make_project(
    db_session: AsyncSession, *, project_id: str | None = None, owner_id: str | None = None
) -> str:
    """Insert a Project (owner auto-seeded if not given) and return its id."""
    from app.models.project import Project

    if owner_id is None:
        owner_id = await make_user(db_session)
    pid = project_id or str(uuid.uuid4())
    db_session.add(Project(id=pid, name=f"proj-{pid[:6]}", owner_id=owner_id))
    await db_session.commit()
    return pid


async def make_connection(
    db_session: AsyncSession, *, connection_id: str | None = None, project_id: str | None = None
) -> str:
    """Insert a Connection (project auto-seeded if not given) and return its id."""
    from app.models.connection import Connection

    if project_id is None:
        project_id = await make_project(db_session)
    cid = connection_id or str(uuid.uuid4())
    db_session.add(
        Connection(
            id=cid,
            project_id=project_id,
            name=f"conn-{cid[:6]}",
            db_type="postgresql",
            db_host="localhost",
            db_port=5432,
            db_name="test",
            db_user="user",
        )
    )
    await db_session.commit()
    return cid


async def make_chat_session(
    db_session: AsyncSession, *, session_id: str | None = None, project_id: str | None = None
) -> str:
    """Insert a ChatSession (project auto-seeded if not given) and return its id."""
    from app.models.chat_session import ChatSession

    if project_id is None:
        project_id = await make_project(db_session)
    sid = session_id or str(uuid.uuid4())
    db_session.add(ChatSession(id=sid, project_id=project_id, title="seed"))
    await db_session.commit()
    return sid
