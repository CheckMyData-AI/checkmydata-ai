"""What needs the user, on return — the shortest true list.

Every input already exists and none of it is surfaced when somebody comes back:
production ran 143 failed runs, and `index_repo` completed 16 times in 94 runs, and a
user could learn neither from the interface without going looking. `SCN-150`.

Three properties this file exists to hold, because each has a failure mode that reads
as success:

* **absent is not the same as empty.** "Nothing needs you" and "I could not check" must
  never render the same, so a source that fails is named rather than dropped.
* **the list is short and ordered by severity**, or it becomes a second inbox nobody
  reads.
* **it is cheap.** This runs on every sign-in, so every source is a plain indexed read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.billing  # noqa: F401
import app.models.db_index  # noqa: F401
import app.models.indexing_run  # noqa: F401
from app.models.base import Base
from app.models.connection import Connection
from app.models.db_index import DbIndexSummary
from app.models.indexing_run import IndexingRun
from app.models.project import Project
from app.models.user import User
from app.services.attention_service import AttentionService
from app.services.stale_run_reaper import REAP_ERROR


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def project(db_session):
    db_session.add(User(id="u1", email="owner@test.com"))
    await db_session.flush()
    p = Project(id="p1", name="esim-php", owner_id="u1", repo_url="git@github.com:t/r.git")
    db_session.add(p)
    await db_session.flush()
    return p


def _kinds(items):
    return [i.kind for i in items]


class TestAFailedRunIsTheLoudestThing:
    async def test_a_failed_index_is_reported_with_its_step(self, db_session, project):
        db_session.add(
            IndexingRun(
                workflow_id="w1",
                project_id="p1",
                kind="index_repo",
                trigger="schedule",
                status="failed",
                current_step="graph_build",
                error="boom",
                finished_at=datetime.now(UTC) - timedelta(hours=2),
            )
        )
        await db_session.flush()

        report = await AttentionService().for_project(db_session, "p1")
        assert "index_failed" in _kinds(report.items)
        item = next(i for i in report.items if i.kind == "index_failed")
        assert "graph_build" in item.what
        assert item.severity == "critical"

    async def test_a_reaped_run_says_it_was_reaped(self, db_session, project):
        """`stale run reaped` is a guess the reaper made, not a failure the work
        reported, and the two must not read the same — one is a bug in the job, the
        other may be a bug in the reaping."""
        db_session.add(
            IndexingRun(
                workflow_id="w2",
                project_id="p1",
                kind="index_repo",
                trigger="schedule",
                status="failed",
                current_step="code_symbol_embed",
                error=REAP_ERROR,
                finished_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        await db_session.flush()

        report = await AttentionService().for_project(db_session, "p1")
        item = next(i for i in report.items if i.kind == "index_failed")
        assert "reaped" in item.what.lower()

    async def test_an_old_failure_is_not_news(self, db_session, project):
        """A month-old failure is history. Left in, the group never empties and stops
        being read."""
        db_session.add(
            IndexingRun(
                workflow_id="w3",
                project_id="p1",
                kind="index_repo",
                trigger="schedule",
                status="failed",
                error="boom",
                finished_at=datetime.now(UTC) - timedelta(days=30),
            )
        )
        await db_session.flush()

        report = await AttentionService().for_project(db_session, "p1")
        assert "index_failed" not in _kinds(report.items)

    async def test_a_later_success_clears_the_earlier_failure(self, db_session, project):
        """The question is "does this need me now", not "did anything ever fail"."""
        db_session.add(
            IndexingRun(
                workflow_id="w4",
                project_id="p1",
                kind="index_repo",
                trigger="schedule",
                status="failed",
                error="boom",
                finished_at=datetime.now(UTC) - timedelta(hours=5),
            )
        )
        db_session.add(
            IndexingRun(
                workflow_id="w5",
                project_id="p1",
                kind="index_repo",
                trigger="schedule",
                status="completed",
                finished_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        await db_session.flush()

        report = await AttentionService().for_project(db_session, "p1")
        assert "index_failed" not in _kinds(report.items)


class TestNeverIndexedIsDifferentFromStale:
    async def test_a_repository_that_was_never_indexed(self, db_session, project):
        report = await AttentionService().for_project(db_session, "p1")
        item = next(i for i in report.items if i.kind == "repo_never_indexed")
        assert item.severity == "warning"

    async def test_a_project_with_no_repository_is_not_nagged(self, db_session):
        db_session.add(User(id="u2", email="b@test.com"))
        await db_session.flush()
        db_session.add(Project(id="p2", name="no repo", owner_id="u2", repo_url=None))
        await db_session.flush()

        report = await AttentionService().for_project(db_session, "p2")
        assert "repo_never_indexed" not in _kinds(report.items)

    async def test_a_connection_that_was_never_indexed(self, db_session, project):
        db_session.add(
            Connection(id="c1", project_id="p1", name="prod", db_type="postgres", is_active=True)
        )
        await db_session.flush()

        report = await AttentionService().for_project(db_session, "p1")
        item = next(i for i in report.items if i.kind == "connection_never_indexed")
        assert "prod" in item.subject

    async def test_an_indexed_connection_is_quiet(self, db_session, project):
        db_session.add(
            Connection(id="c2", project_id="p1", name="prod", db_type="postgres", is_active=True)
        )
        await db_session.flush()
        db_session.add(DbIndexSummary(connection_id="c2", total_tables=10))
        await db_session.flush()

        report = await AttentionService().for_project(db_session, "p1")
        assert "connection_never_indexed" not in _kinds(report.items)

    async def test_an_inactive_connection_is_not_nagged(self, db_session, project):
        db_session.add(
            Connection(id="c3", project_id="p1", name="off", db_type="postgres", is_active=False)
        )
        await db_session.flush()

        report = await AttentionService().for_project(db_session, "p1")
        assert "connection_never_indexed" not in _kinds(report.items)


class TestTheWithheldScheduleIsVisibleHere:
    """`SCN-147` says the absence of automation must be visible where the automation
    would have been. Until the workspace exists, this is that place."""

    async def test_an_account_without_a_plan_is_told_its_schedule_will_not_run(
        self, db_session, project, monkeypatch
    ):
        from app.entitlements import reset_entitlements, set_entitlements

        class Deny:
            async def may_run_scheduled_work(self, db, user_id):  # noqa: ANN001, ANN201
                return False

        set_entitlements(Deny())
        try:
            report = await AttentionService().for_project(db_session, "p1")
        finally:
            reset_entitlements()

        item = next(i for i in report.items if i.kind == "schedule_withheld")
        assert item.severity == "info"

    async def test_an_entitled_account_hears_nothing_about_it(self, db_session, project):
        report = await AttentionService().for_project(db_session, "p1")
        assert "schedule_withheld" not in _kinds(report.items)


class TestTheShapeOfTheAnswer:
    async def test_nothing_to_report_is_an_empty_list_not_a_placeholder(self, db_session):
        db_session.add(User(id="u3", email="c@test.com"))
        await db_session.flush()
        db_session.add(Project(id="p3", name="quiet", owner_id="u3", repo_url=None))
        await db_session.flush()

        report = await AttentionService().for_project(db_session, "p3")
        assert report.items == [] and report.more == 0 and report.degraded == []

    async def test_items_are_ordered_by_severity(self, db_session, project):
        db_session.add(
            Connection(id="c4", project_id="p1", name="prod", db_type="postgres", is_active=True)
        )
        db_session.add(
            IndexingRun(
                workflow_id="w6",
                project_id="p1",
                kind="index_repo",
                trigger="schedule",
                status="failed",
                error="boom",
                finished_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        await db_session.flush()

        report = await AttentionService().for_project(db_session, "p1")
        order = {"critical": 0, "warning": 1, "info": 2}
        severities = [order[i.severity] for i in report.items]
        assert severities == sorted(severities)

    async def test_the_list_is_capped_and_says_how_many_it_dropped(self, db_session, project):
        for n in range(9):
            db_session.add(
                Connection(
                    id=f"cc{n}",
                    project_id="p1",
                    name=f"conn-{n}",
                    db_type="postgres",
                    is_active=True,
                )
            )
        await db_session.flush()

        report = await AttentionService().for_project(db_session, "p1")
        assert len(report.items) == AttentionService.MAX_ITEMS
        assert report.more > 0, "a silent truncation reads as 'that is everything'"

    async def test_a_source_that_fails_is_named_not_dropped(self, db_session, project):
        """ "Nothing needs you" and "I could not check" must never render the same."""
        from app.services import attention_service as mod

        async def boom(*a, **k):
            raise RuntimeError("no")

        original = mod.AttentionService._failed_runs
        mod.AttentionService._failed_runs = boom  # type: ignore[method-assign]
        try:
            report = await AttentionService().for_project(db_session, "p1")
        finally:
            mod.AttentionService._failed_runs = original  # type: ignore[method-assign]

        assert "runs" in report.degraded
        assert "index_failed" not in _kinds(report.items)

    async def test_every_item_routes_somewhere(self, db_session, project):
        db_session.add(
            Connection(id="c5", project_id="p1", name="prod", db_type="postgres", is_active=True)
        )
        await db_session.flush()

        report = await AttentionService().for_project(db_session, "p1")
        assert report.items, "fixture should produce at least one item"
        for item in report.items:
            assert item.route, f"{item.kind} has nowhere to go, so it cannot be acted on"


class TestTheEndpoint:
    async def test_it_is_project_scoped_and_needs_membership(self) -> None:
        """Every project-scoped route checks membership; this one reads run failures and
        connection names, so it is no different."""
        import inspect

        from app.api.routes import projects as routes

        src = inspect.getsource(routes.project_attention)
        assert "require_role" in src

    @pytest.mark.parametrize("field", ["kind", "subject", "what", "severity", "route"])
    def test_the_item_carries_what_a_line_of_the_rail_needs(self, field: str) -> None:
        from app.services.attention_service import AttentionItem

        assert field in AttentionItem.__dataclass_fields__
