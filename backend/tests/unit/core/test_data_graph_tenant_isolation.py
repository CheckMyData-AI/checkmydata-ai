"""Tenant-isolation tests for DataGraphService (F-GRAPH-01).

A member of project A must not be able to delete project B's metric by passing
the bare metric id. `delete_metric` is scoped to (metric_id, project_id): it
returns False (route then 404s) when the metric does not belong to the caller's
project, and the row must survive.
"""

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.metric_definition  # noqa: F401
from app.core.data_graph import DataGraphService
from app.models.base import Base
from app.models.metric_definition import MetricDefinition


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    await engine.dispose()


async def _make_metric(session: AsyncSession, project_id: str, name: str) -> MetricDefinition:
    metric = MetricDefinition(project_id=project_id, name=name, display_name=name)
    session.add(metric)
    await session.flush()
    return metric


class TestDeleteMetricTenantIsolation:
    @pytest.mark.asyncio
    async def test_delete_metric_wrong_project_returns_false_and_keeps_row(self, db_session):
        svc = DataGraphService()
        metric_a = await _make_metric(db_session, "project-a", "revenue")

        # A member of project B deletes by bare id under their own project scope.
        deleted = await svc.delete_metric(db_session, metric_a.id, "project-b")

        assert deleted is False
        # The metric still exists — no cross-tenant destruction.
        survivor = (
            await db_session.execute(
                select(MetricDefinition).where(MetricDefinition.id == metric_a.id)
            )
        ).scalar_one_or_none()
        assert survivor is not None
        assert survivor.project_id == "project-a"

    @pytest.mark.asyncio
    async def test_delete_metric_correct_project_returns_true_and_removes_row(self, db_session):
        svc = DataGraphService()
        metric = await _make_metric(db_session, "project-a", "revenue")

        deleted = await svc.delete_metric(db_session, metric.id, "project-a")

        assert deleted is True
        gone = (
            await db_session.execute(
                select(MetricDefinition).where(MetricDefinition.id == metric.id)
            )
        ).scalar_one_or_none()
        assert gone is None

    @pytest.mark.asyncio
    async def test_delete_metric_only_touches_caller_project(self, db_session):
        """Two projects own same-named metrics; deleting under A leaves B intact."""
        svc = DataGraphService()
        metric_a = await _make_metric(db_session, "project-a", "shared_metric")
        metric_b = await _make_metric(db_session, "project-b", "shared_metric")

        deleted = await svc.delete_metric(db_session, metric_b.id, "project-b")

        assert deleted is True
        remaining = (await db_session.execute(select(MetricDefinition))).scalars().all()
        ids = {m.id for m in remaining}
        assert metric_a.id in ids
        assert metric_b.id not in ids
