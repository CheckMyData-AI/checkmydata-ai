"""F-AUTH-01 — SQLite FK enforcement so ``ondelete=CASCADE`` is not a silent no-op.

A Core ``DELETE`` on the parent row must cascade to children at the DB level (the same
path ``delete_account`` relies on). Without ``PRAGMA foreign_keys=ON`` this passed for the
wrong reason: nothing cascaded, so there was nothing to assert against.
"""

import uuid

import pytest
from sqlalchemy import delete, select

from app.models.connection import Connection
from app.models.project import Project


@pytest.mark.integration
async def test_core_delete_project_cascades_to_connections(db_session):
    project = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
    db_session.add(project)
    await db_session.commit()
    # No `refresh` here, deliberately. `Project.id` carries a Python-side default
    # and the session is `expire_on_commit=False`, so the id is already on the
    # instance — the refresh was a round-trip that returned nothing and added a
    # failure point. It found one: this test failed on `main` with
    # `InvalidRequestError: Could not refresh instance <Project>` while the very
    # same tree passed on the branch (identical `git diff ea03303 e20141b`), i.e.
    # a flake, not a regression.
    #
    # The underlying cause is test infrastructure, not this test: `engine` is
    # session-scoped over a `StaticPool`, so ALL integration tests share one
    # in-memory SQLite connection and committed rows outlive their test. A
    # background task leaked by an earlier test can roll back or delete on that
    # shared connection between this commit and the next statement. Removing the
    # round-trip removes this test's exposure; the shared-connection design is
    # recorded as AUD-0819-22 rather than pretended away here.

    conn = Connection(
        project_id=project.id,
        name=f"conn-{uuid.uuid4().hex[:6]}",
        db_type="postgresql",
        db_host="localhost",
        db_port=5432,
        db_name="test",
        db_user="user",
        db_password_encrypted="fake-encrypted-secret",
    )
    db_session.add(conn)
    await db_session.commit()
    conn_id = conn.id

    # Core DELETE on the parent — relies on DB-level FK cascade, not ORM cascade.
    await db_session.execute(delete(Project).where(Project.id == project.id))
    await db_session.commit()

    remaining = (
        await db_session.execute(select(Connection).where(Connection.id == conn_id))
    ).scalar_one_or_none()
    assert remaining is None, (
        "Connection row survived parent deletion — SQLite FK enforcement is off, so "
        "ondelete=CASCADE is a no-op (F-AUTH-01)."
    )
