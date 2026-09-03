"""One resolver for "which analytics connection may this project read?" (A1 · REQ-2).

#267 was a check written once per entry point where one entry point did not have
it: three chat endpoints resolved a connection by bare id and any authenticated
user reached any tenant's database. The fix scoped each call site.

The pipeline stage is a **fourth** caller of the same decision. Copying the
dispatcher's inline comparison into it would rebuild the shape #267 came from, so
the decision lives in one function and both callers ask it. The reason codes are
part of the contract because the two callers must render different things — the
dispatcher returns a string an LLM reads, the stage returns a typed category the
scheduler acts on — and neither may re-derive *why* from prose.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.connection import Connection
from app.services.connection_service import (
    AnalyticsConnectionUnavailableError,
    ConnectionService,
)


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    s = sm()
    try:
        yield s
    finally:
        await s.close()
        await engine.dispose()


async def _add(session: AsyncSession, **kw) -> Connection:
    conn = Connection(
        id=kw.pop("id"),
        project_id=kw.pop("project_id"),
        name=kw.pop("name", "a source"),
        source_type=kw.pop("source_type", "ga4"),
        **kw,
    )
    session.add(conn)
    await session.commit()
    return conn


class TestAnExplicitId:
    async def test_a_connection_in_this_project_resolves(self, session):
        await _add(session, id="c1", project_id="p1", name="Marketing GA4")

        conn = await ConnectionService().resolve_analytics_connection(
            session, project_id="p1", connection_id="c1"
        )

        assert conn.id == "c1"
        assert conn.source_type == "ga4"

    async def test_another_project_s_connection_is_refused(self, session):
        """The id comes from an LLM, which means it comes from whatever the user
        typed. "The model asked for it" is not authority to read another
        tenant's collected analytics."""
        await _add(session, id="c1", project_id="OTHER", name="Their GA4")

        with pytest.raises(AnalyticsConnectionUnavailableError) as exc:
            await ConnectionService().resolve_analytics_connection(
                session, project_id="p1", connection_id="c1"
            )

        assert exc.value.reason == "wrong_project"

    async def test_a_missing_id_is_not_found(self, session):
        with pytest.raises(AnalyticsConnectionUnavailableError) as exc:
            await ConnectionService().resolve_analytics_connection(
                session, project_id="p1", connection_id="nope"
            )

        assert exc.value.reason == "not_found"

    async def test_a_database_connection_is_not_an_analytics_source(self, session):
        """Right project, wrong kind. Reported as not-found rather than
        wrong-project: from the caller's side there is no analytics source by
        that id, and saying "wrong project" about a connection the project does
        own would be a false statement about ownership."""
        await _add(session, id="c1", project_id="p1", source_type="database", db_type="postgres")

        with pytest.raises(AnalyticsConnectionUnavailableError) as exc:
            await ConnectionService().resolve_analytics_connection(
                session, project_id="p1", connection_id="c1"
            )

        assert exc.value.reason == "not_found"


class TestNoIdGiven:
    async def test_the_project_s_only_analytics_source_is_used(self, session):
        await _add(session, id="db1", project_id="p1", source_type="database")
        await _add(session, id="an1", project_id="p1", source_type="ga4")

        conn = await ConnectionService().resolve_analytics_connection(session, project_id="p1")

        assert conn.id == "an1"

    async def test_a_project_with_none_says_so(self, session):
        await _add(session, id="db1", project_id="p1", source_type="database")

        with pytest.raises(AnalyticsConnectionUnavailableError) as exc:
            await ConnectionService().resolve_analytics_connection(session, project_id="p1")

        assert exc.value.reason == "none_connected"

    async def test_another_project_s_source_is_never_borrowed(self, session):
        await _add(session, id="an1", project_id="OTHER", source_type="ga4")

        with pytest.raises(AnalyticsConnectionUnavailableError) as exc:
            await ConnectionService().resolve_analytics_connection(session, project_id="p1")

        assert exc.value.reason == "none_connected"

    async def test_every_reserved_vendor_is_eligible(self, session):
        """Vendor gating is deliberately vendor-agnostic: the agent refuses a
        vendor it has no report catalogue for, with a message naming it. The
        resolver must not become a second, silent gate."""
        from app.analytics.source_types import ANALYTICS_SOURCE_TYPES

        await _add(session, id="an1", project_id="p1", source_type=ANALYTICS_SOURCE_TYPES[-1])

        conn = await ConnectionService().resolve_analytics_connection(session, project_id="p1")

        assert conn.id == "an1"


class TestTheReasonCodes:
    def test_the_exception_carries_a_machine_readable_reason(self):
        exc = AnalyticsConnectionUnavailableError("wrong_project")
        assert exc.reason == "wrong_project"
        assert "wrong_project" in str(exc)

    def test_an_unknown_reason_is_a_programming_error(self):
        """A typo'd reason must fail here, not silently render as a blank
        message in front of a user."""
        with pytest.raises(ValueError):
            AnalyticsConnectionUnavailableError("whoops")
