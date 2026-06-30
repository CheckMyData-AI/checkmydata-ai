"""Owner-gated read API for captured query failures (spec §3.6 / plan T7).

Exercises the real route handlers in ``app.api.routes.logs`` against a real
in-memory DB session (so the membership gate + tenant scoping are tested
end-to-end, not mocked away). Asserts:

- owner can list + get detail;
- a non-owner (viewer) role gets 403;
- filters narrow results;
- a failure from another project is NOT returned and detail 404s across
  projects (tenant isolation, R3).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import app.models  # noqa: F401 — register all models
from app.api.routes.logs import (
    get_query_failure_detail,
    list_query_failures,
)
from app.models.base import Base
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.query_failure import QueryFailure
from app.models.user import User


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


def _fake_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "root_path": "",
        "app": None,
    }
    return Request(scope)


async def _user(db: AsyncSession) -> User:
    u = User(
        email=f"u-{uuid.uuid4().hex[:6]}@test.com",
        password_hash="fake",
        display_name="Tester",
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _project(db: AsyncSession, owner_id: str) -> Project:
    p = Project(name=f"proj-{uuid.uuid4().hex[:6]}", owner_id=owner_id)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def _member(db: AsyncSession, project_id: str, user_id: str, role: str) -> None:
    db.add(ProjectMember(project_id=project_id, user_id=user_id, role=role))
    await db.commit()


async def _failure(
    db: AsyncSession,
    project_id: str,
    *,
    connection_id: str | None = "conn-1",
    error_type: str = "syntax_error",
    final_status: str = "failed",
    failed_sql: str = "SELECT 1 GROUP BY 1",
    raw_error: str = "ERROR: syntax error",
    attempts: list | None = None,
    created_at: datetime | None = None,
) -> QueryFailure:
    import json

    f = QueryFailure(
        project_id=project_id,
        connection_id=connection_id,
        workflow_id=str(uuid.uuid4()),
        trace_id=None,
        session_id=None,
        message_id=None,
        db_type="postgres",
        question="why?",
        failed_sql=failed_sql,
        error_type=error_type,
        raw_error=raw_error,
        attempts_json=json.dumps(
            attempts
            or [
                {
                    "attempt": 1,
                    "query": failed_sql,
                    "error_type": error_type,
                    "raw_error": raw_error,
                    "elapsed_ms": 12.0,
                }
            ]
        ),
        attempt_count=1,
        final_status=final_status,
    )
    if created_at:
        f.created_at = created_at
    db.add(f)
    await db.commit()
    await db.refresh(f)
    return f


# ---------------------------------------------------------------------------
# List endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_can_list(db):
    owner = await _user(db)
    proj = await _project(db, owner.id)
    await _member(db, proj.id, owner.id, "owner")
    await _failure(db, proj.id)
    await _failure(db, proj.id, error_type="table_not_found", final_status="recovered")

    res = await list_query_failures(
        request=_fake_request(),
        project_id=proj.id,
        error_type=None,
        connection_id=None,
        final_status=None,
        date_from=None,
        date_to=None,
        limit=50,
        offset=0,
        db=db,
        user={"user_id": owner.id},
    )

    assert res["total"] == 2
    assert len(res["items"]) == 2
    # Summary dicts must NOT include the attempts payload.
    assert "attempts" not in res["items"][0]
    assert "failed_sql" in res["items"][0]


@pytest.mark.asyncio
async def test_non_owner_gets_403(db):
    owner = await _user(db)
    viewer = await _user(db)
    proj = await _project(db, owner.id)
    await _member(db, proj.id, owner.id, "owner")
    await _member(db, proj.id, viewer.id, "viewer")
    await _failure(db, proj.id)

    with pytest.raises(HTTPException) as exc:
        await list_query_failures(
            request=_fake_request(),
            project_id=proj.id,
            error_type=None,
            connection_id=None,
            final_status=None,
            date_from=None,
            date_to=None,
            limit=50,
            offset=0,
            db=db,
            user={"user_id": viewer.id},
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_filters_narrow_results(db):
    owner = await _user(db)
    proj = await _project(db, owner.id)
    await _member(db, proj.id, owner.id, "owner")
    await _failure(db, proj.id, error_type="syntax_error", final_status="failed")
    await _failure(db, proj.id, error_type="table_not_found", final_status="recovered")
    await _failure(
        db, proj.id, error_type="syntax_error", final_status="recovered", connection_id="conn-2"
    )

    # error_type filter
    res = await list_query_failures(
        request=_fake_request(),
        project_id=proj.id,
        error_type="syntax_error",
        connection_id=None,
        final_status=None,
        date_from=None,
        date_to=None,
        limit=50,
        offset=0,
        db=db,
        user={"user_id": owner.id},
    )
    assert res["total"] == 2
    assert all(i["error_type"] == "syntax_error" for i in res["items"])

    # final_status + connection_id filters combined
    res2 = await list_query_failures(
        request=_fake_request(),
        project_id=proj.id,
        error_type=None,
        connection_id="conn-2",
        final_status="recovered",
        date_from=None,
        date_to=None,
        limit=50,
        offset=0,
        db=db,
        user={"user_id": owner.id},
    )
    assert res2["total"] == 1
    assert res2["items"][0]["connection_id"] == "conn-2"
    assert res2["items"][0]["final_status"] == "recovered"


@pytest.mark.asyncio
async def test_date_range_filter(db):
    owner = await _user(db)
    proj = await _project(db, owner.id)
    await _member(db, proj.id, owner.id, "owner")
    now = datetime.now(UTC)
    await _failure(db, proj.id, created_at=now - timedelta(days=10))
    await _failure(db, proj.id, created_at=now)

    res = await list_query_failures(
        request=_fake_request(),
        project_id=proj.id,
        error_type=None,
        connection_id=None,
        final_status=None,
        date_from=(now - timedelta(days=1)).isoformat(),
        date_to=None,
        limit=50,
        offset=0,
        db=db,
        user={"user_id": owner.id},
    )
    assert res["total"] == 1


@pytest.mark.asyncio
async def test_tenant_isolation_list(db):
    owner = await _user(db)
    proj_a = await _project(db, owner.id)
    proj_b = await _project(db, owner.id)
    await _member(db, proj_a.id, owner.id, "owner")
    await _member(db, proj_b.id, owner.id, "owner")
    await _failure(db, proj_a.id, failed_sql="SELECT a")
    await _failure(db, proj_b.id, failed_sql="SELECT b")

    res = await list_query_failures(
        request=_fake_request(),
        project_id=proj_a.id,
        error_type=None,
        connection_id=None,
        final_status=None,
        date_from=None,
        date_to=None,
        limit=50,
        offset=0,
        db=db,
        user={"user_id": owner.id},
    )
    assert res["total"] == 1
    assert res["items"][0]["failed_sql"] == "SELECT a"


# ---------------------------------------------------------------------------
# Detail endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_can_get_detail_with_attempts(db):
    owner = await _user(db)
    proj = await _project(db, owner.id)
    await _member(db, proj.id, owner.id, "owner")
    f = await _failure(db, proj.id)

    res = await get_query_failure_detail(
        request=_fake_request(),
        project_id=proj.id,
        failure_id=f.id,
        db=db,
        user={"user_id": owner.id},
    )
    assert res["id"] == f.id
    assert "attempts" in res
    assert res["attempts"][0]["attempt"] == 1


@pytest.mark.asyncio
async def test_detail_non_owner_403(db):
    owner = await _user(db)
    viewer = await _user(db)
    proj = await _project(db, owner.id)
    await _member(db, proj.id, owner.id, "owner")
    await _member(db, proj.id, viewer.id, "viewer")
    f = await _failure(db, proj.id)

    with pytest.raises(HTTPException) as exc:
        await get_query_failure_detail(
            request=_fake_request(),
            project_id=proj.id,
            failure_id=f.id,
            db=db,
            user={"user_id": viewer.id},
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_detail_404_when_missing(db):
    owner = await _user(db)
    proj = await _project(db, owner.id)
    await _member(db, proj.id, owner.id, "owner")

    with pytest.raises(HTTPException) as exc:
        await get_query_failure_detail(
            request=_fake_request(),
            project_id=proj.id,
            failure_id="does-not-exist",
            db=db,
            user={"user_id": owner.id},
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_detail_tenant_isolation_404_across_projects(db):
    owner = await _user(db)
    proj_a = await _project(db, owner.id)
    proj_b = await _project(db, owner.id)
    await _member(db, proj_a.id, owner.id, "owner")
    await _member(db, proj_b.id, owner.id, "owner")
    f_b = await _failure(db, proj_b.id)

    # Owner of proj_a (also owner of proj_b) requests proj_b's failure scoped to
    # proj_a → must 404, never leak across the project boundary.
    with pytest.raises(HTTPException) as exc:
        await get_query_failure_detail(
            request=_fake_request(),
            project_id=proj_a.id,
            failure_id=f_b.id,
            db=db,
            user={"user_id": owner.id},
        )
    assert exc.value.status_code == 404
