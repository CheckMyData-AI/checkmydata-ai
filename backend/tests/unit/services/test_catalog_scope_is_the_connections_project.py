"""A project's own membership is not permission to read another's index (row 1.10).

`POST /semantic-layer/{project_id}/build/{connection_id}` and
`POST /data-graph/{project_id}/discover/{connection_id}` both check membership of
`project_id` with `require_role`, and both validate the *shape* of
`connection_id` with `validate_safe_id`. Neither established that the connection
**belongs** to that project.

`SemanticLayerService.build_catalog` and `DataGraphService.auto_discover_from_db_index`
then queried:

    select(DbIndex).where(DbIndex.connection_id == connection_id, ...)

— `project_id` accepted as a parameter and never used in the WHERE clause. So an
owner of project A could name project B's connection and read B's schema index.
That is not only table and column names: `db_index` carries
`column_distinct_values_json` and `column_stats_json`, which are **sampled values
from the tenant's data**. `build_catalog` then writes metric definitions derived
from them into A.

Fourth occurrence in this programme of one shape, and the sharpest: #267 created
`ConnectionService.get_in_project` precisely to stop it, with a docstring saying
*"a getter that cannot be called without a project cannot be forgotten at a
fourth entry point"*. These two are that fourth entry point — and they slipped
past not by calling `get()` instead, but by **never resolving a Connection at
all**, passing the raw id into a service that went straight to `DbIndex`.

So the check goes in the SERVICE, where the ignored parameter was: a scope in the
query cannot be skipped by a future caller, while an `if` at the route can.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.connection import Connection
from app.models.db_index import DbIndex
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
        s.add(
            DbIndex(
                id=f"idx-{cid}",
                connection_id=cid,
                table_name="salaries",
                table_schema="public",
                is_active=True,
            )
        )
    await s.commit()
    try:
        yield s
    finally:
        await s.close()
        await engine.dispose()


class TestSemanticLayerBuild:
    async def test_it_reads_the_index_of_a_connection_in_its_own_project(self, session):
        from app.core.semantic_layer import SemanticLayerService

        candidates = await SemanticLayerService().build_catalog(session, _MINE, _MY_CONN)
        assert candidates is not None, "the ordinary path must keep working"

    async def test_another_project_s_connection_is_refused(self, session):
        """The breach, reproduced. An owner of `_MINE` naming `_THEIRS`' connection."""
        from app.core.semantic_layer import SemanticLayerService

        with pytest.raises(ConnectionOutOfProjectError):
            await SemanticLayerService().build_catalog(session, _MINE, _THEIR_CONN)

    async def test_a_connection_that_does_not_exist_is_refused_the_same_way(self, session):
        """Same error for absent and out-of-project: a different one would confirm
        that another tenant's connection exists."""
        from app.core.semantic_layer import SemanticLayerService

        with pytest.raises(ConnectionOutOfProjectError):
            await SemanticLayerService().build_catalog(session, _MINE, "conn-nobody")


class TestDataGraphDiscover:
    async def test_it_discovers_from_a_connection_in_its_own_project(self, session):
        from app.core.data_graph import DataGraphService

        result = await DataGraphService().auto_discover_from_db_index(session, _MINE, _MY_CONN)
        assert result is not None

    async def test_another_project_s_connection_is_refused(self, session):
        from app.core.data_graph import DataGraphService

        with pytest.raises(ConnectionOutOfProjectError):
            await DataGraphService().auto_discover_from_db_index(session, _MINE, _THEIR_CONN)


class TestTheScopeIsInTheQueryNotAnIf:
    """#267's own lesson, applied at the fourth entry point it predicted."""

    @pytest.mark.parametrize(
        ("module", "func"),
        [
            ("app/core/semantic_layer.py", "build_catalog"),
            ("app/core/data_graph.py", "auto_discover_from_db_index"),
        ],
    )
    def test_the_service_uses_the_project_it_is_given(self, module, func):
        """A parameter accepted and never used reads as "handled" to every reader.

        Both took `project_id` and never referenced it again. The point is not
        that a route could check instead — it is that a service which ignores the
        scope it was handed will be called by a route that forgets to.
        """
        from pathlib import Path

        src = Path(module).read_text(encoding="utf-8")
        start = src.index(f"async def {func}")
        end = src.find("\n    async def ", start + 10)
        body = src[start:] if end == -1 else src[start:end]
        assert "require_in_project" in body, (
            f"{func} must resolve the connection through the RAISING project-scoped "
            "resolver. `get_in_project` returns None, which a caller can ignore by "
            "forgetting an `if` — and taking project_id and ignoring it is exactly "
            "how project A came to read project B's index"
        )
