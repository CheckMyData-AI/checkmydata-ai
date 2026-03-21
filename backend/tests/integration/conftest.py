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
    backup_record,
    chat_session,
    code_db_sync,
    commit_index,
    connection,
    custom_rule,
    db_index,
    indexing_checkpoint,
    knowledge_doc,
    pipeline_run,
    project,
    project_cache,
    project_invite,
    project_member,
    rag_feedback,
    repository,
    saved_note,
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
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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
async def auth_client(client: AsyncClient):
    """Authenticated client — registers a fresh user and sets the Bearer header."""
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
    client.headers["Authorization"] = f"Bearer {token}"
    yield client
    client.headers.pop("Authorization", None)


async def register_user(client: AsyncClient, email: str | None = None) -> dict:
    """Helper: register a user and return {token, user_id, email}."""
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
    return {"token": data["token"], "user_id": data["user"]["id"], "email": email}


def auth_headers(token: str) -> dict[str, str]:
    """Build Authorization header dict from a JWT token."""
    return {"Authorization": f"Bearer {token}"}
