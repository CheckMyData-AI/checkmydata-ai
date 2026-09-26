"""Shared fixtures for integration tests.

Uses a real async SQLite database per test session, overriding the FastAPI
dependency so every endpoint hits an actual DB instead of mocks.
"""

import os
import socket
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Every table, not a hand-kept list: the list here lacked `llm_credit` and the harness
# never created it (B-02, 2026-09-23). `app.models` is kept complete by a test.
import app.models  # noqa: F401
from app.models.base import Base

#: Every test user may create projects. Written twice because the two engines spell a
#: trigger differently, and the PostgreSQL form needs a function to carry the body.
_GRANT_TRIGGER_SQLITE = (
    "CREATE TRIGGER IF NOT EXISTS test_grant_can_create_projects "
    "AFTER INSERT ON users BEGIN "
    "UPDATE users SET can_create_projects = 1 WHERE id = NEW.id; "
    "END;"
)
#: Three statements, sent one at a time: asyncpg prepares every statement it is given
#: and PostgreSQL refuses `cannot insert multiple commands into a prepared statement`,
#: so a single `text()` carrying all three fails where SQLite's one-liner does not.
_GRANT_TRIGGER_PG = (
    """
    CREATE OR REPLACE FUNCTION test_grant_can_create_projects() RETURNS trigger AS $$
    BEGIN
        NEW.can_create_projects := TRUE;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS test_grant_can_create_projects ON users",
    """
    CREATE TRIGGER test_grant_can_create_projects
        BEFORE INSERT ON users
        FOR EACH ROW EXECUTE FUNCTION test_grant_can_create_projects()
    """,
)


#: B-02. The integration suite runs on SQLite by default and against PostgreSQL when
#: this is set, which CI does in a second job with a `postgres:17` service.
#:
#: The defect class it exists for: **a `Text` column accepts a dict on SQLite and
#: refuses it on PostgreSQL, and a `Numeric` column accepts a float on one and not the
#: other.** Both differences are invisible to every test in this repository, and both
#: have already shipped — `asyncpg.exceptions.DataError: invalid input for query
#: argument $6: {} (expected str)` took four consecutive nightly `code_db_sync` runs
#: out while every test stayed green.
#:
#: The integration suite is the right — and the proportionate — place. It is what
#: writes through the ORM; the 128 unit-test files that build their own in-memory
#: engine do so deliberately, for speed, and rewriting them would be a project that
#: buys nothing this does not.
#: **Setting this today does not give a green suite, and that is the finding.** Measured
#: 2026-09-15 against `pgvector/pgvector:pg17`, three differences SQLite cannot show:
#:
#: 1. `doc_embeddings.embedding` is `vector(384)`, so `create_all` fails without the
#:    extension — on SQLite that whole migration is a deliberate no-op.
#: 2. asyncpg prepares every statement, so PostgreSQL refuses `cannot insert multiple
#:    commands into a prepared statement`; the grant trigger had to be split into three.
#: 3. **The harness holds an uncommitted transaction, and every second connection
#:    blocks on it.** `client` overrides `get_db` to yield this fixture's `db_session`
#:    while replacing `async_session_factory` with one that opens its OWN connections.
#:    Under `StaticPool` on SQLite both are one physical connection and a lock is
#:    impossible; on PostgreSQL they are two. Reproduced from `pg_stat_activity`:
#:    `_grant_project_creation` leaves `UPDATE users SET can_create_projects` *idle in
#:    transaction* holding the row, and the request path's `UPDATE users SET
#:    email_verified` waits on `Lock`/`transactionid` forever. A run that takes 198 s on
#:    SQLite had not finished in 33 minutes.
#:
#: The fourth difference is the one that matters beyond the harness: PostgreSQL aborts
#: the whole transaction after a failed statement and refuses everything until rollback
#: (`InFailedSQLTransactionError`), where SQLite lets the session continue. Any code that
#: swallows a database error and keeps using the same session is therefore already broken
#: in production and green in CI — which is exactly what B-02 exists to expose.
#:
#: **Resolved 2026-09-23.** The single-open-transaction model was replaced by emptying the
#: tables after every test (`_truncate_all`), the harness commits like the application does,
#: and every model is imported (`llm_credit` was missing). The suite is 698/698 on both
#: engines. CI runs it on `pgvector/pgvector:pg17` too (`backend-integration-postgres` in
#: `.github/workflows/ci.yml`); locally, set `TEST_DATABASE_URL=postgresql+asyncpg://…`.
#: Its first run found a real production defect the SQLite job could not: the request's
#: session left aborted by a swallowed error in `resolve_account_key` (now a SAVEPOINT).
_TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

#: Filled by the `engine` fixture: the tables that exist, which `_truncate_all` empties.
_CREATED_TABLES: set[str] = set()
_ON_SQLITE = _TEST_DB_URL.startswith("sqlite")


@pytest_asyncio.fixture(scope="session")
async def engine():
    from app.models.base import enable_sqlite_fk

    if _ON_SQLITE:
        # A bare ``sqlite+aiosqlite:///:memory:`` engine gives every pooled
        # connection its OWN empty in-memory database. ``Base.metadata.create_all``
        # below runs on one connection, so as soon as the pool opens a second
        # connection (concurrent sessions, e.g. the request-scoped session plus a
        # service opening its own) that connection sees an empty DB and every
        # subsequent test errors at setup with ``no such table: users``. StaticPool
        # keeps a single shared connection for the whole session-scoped engine, so
        # all sessions hit the same in-memory DB with the schema present.
        eng = create_async_engine(
            _TEST_DB_URL,
            echo=False,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        enable_sqlite_fk(eng)  # F-AUTH-01: cascade tests must exercise real FK enforcement
    else:
        # A real server needs none of the above: separate connections see the same
        # database, and foreign keys are enforced without being asked.
        eng = create_async_engine(_TEST_DB_URL, echo=False)
        # `doc_embeddings.embedding` is `vector(384)`, so the table cannot be created
        # without the extension — which is exactly the kind of thing SQLite hides, since
        # there the whole migration is a deliberate no-op. Production carries pgvector
        # 0.8.2; the CI service image ships it.
        async with eng.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        if _ON_SQLITE:
            await conn.execute(text(_GRANT_TRIGGER_SQLITE))
        else:
            for statement in _GRANT_TRIGGER_PG:
                await conn.execute(text(statement))
        from sqlalchemy import inspect as _inspect

        _CREATED_TABLES.clear()
        _CREATED_TABLES.update(await conn.run_sync(lambda c: _inspect(c).get_table_names()))
    yield eng
    await eng.dispose()


async def _truncate_all(engine) -> None:
    """Empty every table after a test — the isolation model (B-02, 2026-09-23).

    The suite used to rely on one uncommitted transaction per test, rolled back in
    teardown. That model was already half-fictional — the request path's `get_db`
    yields this same session and route handlers COMMIT through it, so on SQLite the
    rollback undid little and tests were really isolated by unique emails and ids — and
    on PostgreSQL it deadlocked: a flushed-but-uncommitted `UPDATE users` held the row
    while the app's own session factory waited on it (B-02's measurement). Emptying the
    tables after each test isolates on both engines and lets the harness COMMIT like the
    application does. The schema and the grant trigger are session-scoped and survive.
    """
    # Only the tables `create_all` actually made: a model imported LATER in the run (a
    # route module pulling in `llm_credit`, say) joins `Base.metadata` without a table.
    tables = [t.name for t in reversed(Base.metadata.sorted_tables) if t.name in _CREATED_TABLES]
    async with engine.begin() as conn:
        if _ON_SQLITE:
            for name in tables:
                await conn.execute(text(f'DELETE FROM "{name}"'))
        else:
            quoted = ", ".join(f'"{name}"' for name in tables)
            await conn.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture()
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await _truncate_all(engine)


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
    # COMMIT, not flush (B-02): a flushed row stays locked by this session's open
    # transaction, and on PostgreSQL the request path's own session then waits on it
    # for ever. Isolation comes from `_truncate_all`, not from rolling this back.
    await db_session.commit()


async def mark_email_verified(user_id: str) -> None:
    """Confirm a registered test user's address, as `/api/auth/verify-email` would.

    AUTH-01 made a verified address a precondition for accepting an invitation, and
    `/api/auth/register` deliberately leaves `email_verified=False` — that is the whole
    point of the gate. Most tests here reach an invite only to arrange a *membership*,
    so they need the flag set the way a real user would have set it by clicking the
    link in their inbox, not a hole in the gate.

    Uses the app's own session factory rather than the `db_session` fixture, because
    `register_user` is called from tests that take no session and would otherwise have
    to thread one through purely to satisfy this.
    """
    from sqlalchemy import update

    from app.models.base import async_session_factory
    from app.models.user import User

    async with async_session_factory() as session:
        await session.execute(update(User).where(User.id == user_id).values(email_verified=True))
        await session.commit()


async def register_user(
    client: AsyncClient,
    email: str | None = None,
    *,
    db_session: AsyncSession | None = None,
    email_verified: bool = True,
) -> dict:
    """Helper: register a user and return {token, user_id, email}.

    When ``db_session`` is passed the user is automatically granted
    ``can_create_projects`` so it can own projects in tests.

    ``email_verified`` defaults to True (AUTH-01). Registration itself leaves it False —
    that is the gate — and nearly every test here reaches an invite only to arrange a
    membership, so they want a user who has clicked the link. Pass ``False`` to test the
    gate itself.
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
    if email_verified:
        await mark_email_verified(user_id)

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


#: Hosts the integration suite names in repository URLs. `validate_repo_url` DNS-resolves
#: the host as an SSRF guard (FA-004) and rejects anything it cannot resolve, so every one
#: of these tests silently depended on the runner having working public DNS. On 2026-09-09
#: it did not, and five tests failed with `422` — `assert 422 == 200` — on a docs-only
#: branch, which is the worst way for a test to fail: loudly, and about nothing it tests.
#:
#: Resolution is stubbed only for these names. Anything else falls through to the real
#: resolver, so a test that deliberately points at a private or unresolvable host still
#: exercises the guard. The guard's own tests live in `tests/unit/` and are untouched.
_PUBLIC_GIT_HOSTS = {"github.com", "gitlab.com", "bitbucket.org", "example.com"}
_STUB_ADDRINFO = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
_real_getaddrinfo = socket.getaddrinfo


@pytest.fixture(autouse=True)
def _public_git_hosts_resolve():
    """Make the SSRF guard deterministic for the hosts these tests name.

    Not `repo_allow_private_hosts=True`: that switches the guard off entirely and would
    let a genuine SSRF regression through a suite that currently catches it.
    """

    def _resolve(host, *args, **kwargs):
        if host in _PUBLIC_GIT_HOSTS:
            return _STUB_ADDRINFO
        return _real_getaddrinfo(host, *args, **kwargs)

    with patch("socket.getaddrinfo", side_effect=_resolve):
        yield
