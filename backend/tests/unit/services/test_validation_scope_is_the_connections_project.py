"""Validation and benchmarks are scoped by the connection's project (row 1.11).

Three endpoints in `data_validation.py` checked membership of `project_id` and
then handed `connection_id` on untouched:

    POST /validate                      -> record_validation(connection_id=…)   WRITES
    GET  /validation-stats/{conn}       -> get_accuracy_stats(db, conn)         reads
    GET  /benchmarks/{conn}             -> get_all_for_connection(db, conn)     reads

So a member of any project could name another tenant's connection and read its
accuracy statistics and its benchmarks — which carry `metric_description`,
`value` and `unit`, i.e. the other tenant's business numbers — and write
validation records against it.

Fifth and sixth occurrence of the shape #267 named. The sharpest detail is in the
same file: `get_feedback_analytics` scopes correctly, with
`select(Connection.id).where(Connection.project_id == project_id)`. The pattern
was present, understood, and simply not applied three functions above.

The guard goes in the SERVICE for the reason row 1.10 established: a route can
forget, and a service that ignores the scope it was handed will eventually be
called by one that does.

**Not changed here, and deliberately:** `POST /validate` accepts role `viewer`
for a write. That is a question about privilege, not about tenancy — a viewer
marking an answer wrong is plausibly the intent — so it is reported rather than
altered.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.connection import Connection
from app.services.connection_service import ConnectionOutOfProjectError

_MINE, _THEIRS = "project-mine", "project-theirs"
_MY_CONN, _THEIR_CONN = "conn-mine", "conn-theirs"


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    s = sm()
    for pid, cid in ((_MINE, _MY_CONN), (_THEIRS, _THEIR_CONN)):
        s.add(Connection(id=cid, project_id=pid, name=f"{pid} db", source_type="database"))
    await s.commit()
    try:
        yield s
    finally:
        await s.close()
        await engine.dispose()


class TestAccuracyStats:
    async def test_its_own_connection_is_readable(self, session):
        from app.services.data_validation_service import DataValidationService

        stats = await DataValidationService().get_accuracy_stats(
            session, _MY_CONN, project_id=_MINE
        )
        assert stats is not None, "the ordinary path must keep working"

    async def test_another_project_s_connection_is_refused(self, session):
        from app.services.data_validation_service import DataValidationService

        with pytest.raises(ConnectionOutOfProjectError):
            await DataValidationService().get_accuracy_stats(session, _THEIR_CONN, project_id=_MINE)


class TestBenchmarks:
    async def test_its_own_connection_is_readable(self, session):
        from app.services.benchmark_service import BenchmarkService

        rows = await BenchmarkService().get_all_for_connection(session, _MY_CONN, project_id=_MINE)
        assert rows is not None

    async def test_another_project_s_connection_is_refused(self, session):
        """Benchmarks carry `metric_description`, `value` and `unit` — the other
        tenant's business numbers, not just metadata."""
        from app.services.benchmark_service import BenchmarkService

        with pytest.raises(ConnectionOutOfProjectError):
            await BenchmarkService().get_all_for_connection(session, _THEIR_CONN, project_id=_MINE)


class TestRecordValidationWrites:
    async def test_writing_against_another_project_s_connection_is_refused(self, session):
        """The only WRITE of the three, and the one that matters most."""
        from app.services.data_validation_service import DataValidationService

        with pytest.raises(ConnectionOutOfProjectError):
            await DataValidationService().record_validation(
                session,
                connection_id=_THEIR_CONN,
                project_id=_MINE,
                session_id="s1",
                message_id="m1",
                query="SELECT 1",
                verdict="incorrect",
            )


class TestTheGuardIsInTheServiceNotTheRoute:
    @pytest.mark.parametrize(
        ("module", "func"),
        [
            ("app/services/data_validation_service.py", "get_accuracy_stats"),
            ("app/services/data_validation_service.py", "record_validation"),
            ("app/services/benchmark_service.py", "get_all_for_connection"),
        ],
    )
    def test_the_service_resolves_the_connection_in_its_project(self, module, func):
        from pathlib import Path

        src = Path(module).read_text(encoding="utf-8")
        start = src.index(f"def {func}")
        end = src.find("\n    async def ", start + 10)
        if end == -1:
            end = src.find("\n    def ", start + 10)
        body = src[start:] if end == -1 else src[start:end]
        assert "require_in_project" in body, (
            f"{func} must resolve the connection through the raising project-scoped "
            "resolver; the route checking is not enough, because the next route will "
            "forget"
        )

    def test_the_agent_passes_its_project_too(self):
        """`BenchmarkService.get_all_for_connection` has a second caller — the SQL
        agent. Its connection is already resolved in-project by the chat entry
        points since #267, so this is defence in depth rather than a fix; a
        signature that lets one caller omit the scope is how the first one did.
        """
        from pathlib import Path

        src = Path("app/agents/sql_agent.py").read_text(encoding="utf-8")
        start = src.index("get_all_for_connection(")
        assert "project_id" in src[start : start + 200], (
            "the agent call site must supply the project it already has on its context"
        )
