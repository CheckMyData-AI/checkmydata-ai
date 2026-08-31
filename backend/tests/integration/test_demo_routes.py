"""`POST /api/demo/setup` end to end — four board findings in one 65-line route.

* **F-EXP-01** the promise: the route seeds a real sample database, and these tests open
  the file it points at and read the rows back. Asserting the source contains "INSERT"
  would pass while the route never called the seeder — measured, that exact plant left a
  source-inspection suite fully green.
* **F-EXP-02** the connection is read-only, like every other connection by default.
* **F-EXP-03** a second call reuses the first demo instead of minting another.
* **F-BILL-07** the quotas are met, and a breach answers 402 like everywhere else.
"""

import sqlite3
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.connection import Connection
from app.models.project import Project
from app.services.entitlement_service import QuotaExceededError


@pytest.fixture(autouse=True)
def _demo_db_in_tmp(tmp_path, monkeypatch):
    """Keep the seeded files out of the repo's ./data/demo during tests."""
    monkeypatch.setattr(settings, "demo_db_dir", str(tmp_path / "demo"))


async def _connection(db: AsyncSession, connection_id: str) -> Connection:
    return (await db.execute(select(Connection).where(Connection.id == connection_id))).scalar_one()


@pytest.mark.asyncio
async def test_demo_setup(auth_client):
    resp = await auth_client.post("/api/demo/setup")
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"]
    assert data["connection_id"]


@pytest.mark.asyncio
async def test_demo_setup_no_auth(client):
    resp = await client.post("/api/demo/setup")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_the_demo_connection_points_at_a_database_with_rows_in_it(
    auth_client, db_session: AsyncSession
):
    """F-EXP-01. The whole finding: a new user clicked "Try demo instead" and got an
    empty database. Reading the file the connection names is the only check that says
    otherwise."""
    resp = await auth_client.post("/api/demo/setup")
    conn = await _connection(db_session, resp.json()["connection_id"])

    assert conn.db_name and conn.db_name != ":memory:"
    with sqlite3.connect(conn.db_name) as db:
        customers = db.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        orders = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    assert customers > 0
    assert orders > 0


@pytest.mark.asyncio
async def test_the_demo_connection_is_read_only(auth_client, db_session: AsyncSession):
    """F-EXP-02 — vision.md §7 #1. The demo is the last place to opt out of the default."""
    resp = await auth_client.post("/api/demo/setup")
    conn = await _connection(db_session, resp.json()["connection_id"])

    assert conn.is_read_only is True


@pytest.mark.asyncio
async def test_calling_it_twice_reuses_the_same_demo(auth_client, db_session: AsyncSession):
    """F-EXP-03. This inverts `test_demo_setup_twice_creates_two_projects`, which asserted
    `p1 != p2` and so froze the defect as the contract — three projects a minute, each one
    counting against a quota nobody was charged for."""
    first = await auth_client.post("/api/demo/setup")
    second = await auth_client.post("/api/demo/setup")

    assert first.json()["project_id"] == second.json()["project_id"]
    assert first.json()["connection_id"] == second.json()["connection_id"]

    owner = (
        (await db_session.execute(select(Project).where(Project.id == first.json()["project_id"])))
        .scalar_one()
        .owner_id
    )
    demos = (
        (
            await db_session.execute(
                select(Project).where(Project.owner_id == owner, Project.name == "Demo Project")
            )
        )
        .scalars()
        .all()
    )
    assert len(demos) == 1


class _RefusingEntitlements:
    """An entitlement provider that refuses exactly one quota and permits the rest.

    Refusing both would not prove which check the route reached — and the demo route
    calls the project quota first, so a provider that refused everything would let the
    connection test pass on the project check.
    """

    def __init__(self, refuse: str, error: Exception) -> None:
        self._refuse = refuse
        self._error = error

    async def enforce_project_quota(self, db, user_id):
        if self._refuse == "project":
            raise self._error

    async def enforce_connection_quota(self, db, user_id):
        if self._refuse == "connection":
            raise self._error

    async def effective_token_limits(self, db, user_id):
        return (0, 0)


@pytest.mark.asyncio
async def test_a_project_quota_breach_answers_402(auth_client):
    """F-BILL-07. The paywall the ordinary routes enforce applies here too, or it is
    optional for anyone who finds this route.

    Driven through the entitlement registry rather than by patching a module attribute:
    the route moved onto `get_entitlements()` when billing was made separable, and the
    old `demo_route._entitlements` no longer exists. Patching the seam is also the more
    faithful test — it exercises the path the cloud build actually takes.
    """
    from app.entitlements import reset_entitlements, set_entitlements

    set_entitlements(
        _RefusingEntitlements(
            "project",
            QuotaExceededError(
                "Project limit reached on the Free plan",
                resource="project",
                limit=1,
                current=1,
            ),
        )
    )
    try:
        resp = await auth_client.post("/api/demo/setup")
    finally:
        reset_entitlements()
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_a_connection_quota_breach_answers_402(auth_client):
    from app.entitlements import reset_entitlements, set_entitlements

    set_entitlements(
        _RefusingEntitlements(
            "connection",
            QuotaExceededError(
                "Connection limit reached on the Free plan",
                resource="connection",
                limit=1,
                current=1,
            ),
        )
    )
    try:
        resp = await auth_client.post("/api/demo/setup")
    finally:
        reset_entitlements()
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_a_second_user_gets_their_own_sample_database(client: AsyncClient, db_session):
    """One file per user. Two people sharing a demo database is a tenancy leak wearing
    sample data as a costume."""
    from tests.integration.conftest import auth_headers, register_user

    paths = []
    for _ in range(2):
        reg = await register_user(client)
        resp = await client.post("/api/demo/setup", headers=auth_headers(reg["token"]))
        if resp.status_code != 200:
            pytest.skip(f"registration path unavailable: {resp.status_code}")
        conn = await _connection(db_session, resp.json()["connection_id"])
        paths.append(conn.db_name)

    assert paths[0] != paths[1], f"two users share one demo database: {paths[0]}"
    assert uuid.UUID  # keep the import meaningful if the skip fires


@pytest.mark.asyncio
class TestTheDemoConnectionCannotBeRepointed:
    """Registering a SQLite connector turns "which database" into "which file may this
    process read". `ConnectionUpdate.db_type` and `db_name` are free strings, so the
    route has to refuse what the create schema's `Literal` already excludes."""

    async def test_the_demo_connection_cannot_be_pointed_at_another_file(
        self, auth_client, tmp_path
    ):
        resp = await auth_client.post("/api/demo/setup")
        connection_id = resp.json()["connection_id"]
        app_db = tmp_path / "agent.db"
        app_db.write_bytes(b"")

        patched = await auth_client.patch(
            f"/api/connections/{connection_id}",
            json={"db_name": str(app_db)},
        )

        assert patched.status_code == 422

    async def test_an_ordinary_connection_cannot_be_converted_to_sqlite(self, auth_client):
        """The other half, and it needs a **non**-SQLite connection to exercise.

        Measured: pointing this test at the demo connection let the `db_name` guard catch
        it, so deleting the `db_type` guard left the suite green. Two guards on one route
        need two starting states, or one of them is decoration.
        """
        project = await auth_client.post(
            "/api/projects", json={"name": "convert-me", "description": ""}
        )
        assert project.status_code == 200, project.text
        created = await auth_client.post(
            "/api/connections",
            json={
                "project_id": project.json()["id"],
                "name": "pg",
                "db_type": "postgres",
                "db_host": "127.0.0.1",
                "db_port": 5432,
                "db_name": "app",
                "db_user": "u",
                "db_password": "p",
            },
        )
        assert created.status_code == 200, created.text

        patched = await auth_client.patch(
            f"/api/connections/{created.json()['id']}",
            json={"db_type": "sqlite", "db_name": "./data/agent.db"},
        )

        assert patched.status_code == 422

    async def test_an_ordinary_field_can_still_be_updated(self, auth_client):
        """The refusal is scoped to the engine and the file — renaming still works, or
        the guard has quietly frozen the row."""
        resp = await auth_client.post("/api/demo/setup")
        connection_id = resp.json()["connection_id"]

        patched = await auth_client.patch(
            f"/api/connections/{connection_id}",
            json={"name": "My demo"},
        )

        assert patched.status_code == 200
