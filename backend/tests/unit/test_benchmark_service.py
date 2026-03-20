"""Unit tests for BenchmarkService."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.agent_learning  # noqa: F401
import app.models.benchmark  # noqa: F401
import app.models.chat_session  # noqa: F401
import app.models.code_db_sync  # noqa: F401
import app.models.commit_index  # noqa: F401
import app.models.connection  # noqa: F401
import app.models.custom_rule  # noqa: F401
import app.models.data_validation  # noqa: F401
import app.models.indexing_checkpoint  # noqa: F401
import app.models.knowledge_doc  # noqa: F401
import app.models.project  # noqa: F401
import app.models.project_cache  # noqa: F401
import app.models.project_invite  # noqa: F401
import app.models.project_member  # noqa: F401
import app.models.rag_feedback  # noqa: F401
import app.models.saved_note  # noqa: F401
import app.models.session_note  # noqa: F401
import app.models.ssh_key  # noqa: F401
import app.models.user  # noqa: F401
from app.models.base import Base
from app.models.connection import Connection
from app.models.project import Project
from app.services.benchmark_service import BenchmarkService, normalize_metric_key

svc = BenchmarkService()


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def _make_project(db: AsyncSession) -> Project:
    p = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def _make_connection(db: AsyncSession, project_id: str) -> Connection:
    c = Connection(
        project_id=project_id,
        name=f"conn-{uuid.uuid4().hex[:6]}",
        db_type="postgresql",
        db_host="localhost",
        db_port=5432,
        db_name="test",
        db_user="user",
        db_password_encrypted="fake",
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


class TestNormalizeMetricKey:
    def test_basic(self):
        assert normalize_metric_key("Total Revenue") == "total_revenue"

    def test_with_date(self):
        result = normalize_metric_key("Total Revenue for March 2024")
        assert result == "total_revenue_for_march_2024"

    def test_special_chars(self):
        assert normalize_metric_key("Revenue ($)") == "revenue"

    def test_strips_whitespace(self):
        assert normalize_metric_key("  spaces  ") == "spaces"


class TestCreateOrConfirm:
    @pytest.mark.asyncio
    async def test_create_new(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        bm = await svc.create_or_confirm(
            db,
            connection_id=conn.id,
            metric_key="total_revenue",
            value="15000",
            value_numeric=15000.0,
            source="agent_derived",
        )
        assert bm.id is not None
        assert bm.metric_key == "total_revenue"
        assert bm.value == "15000"
        assert bm.times_confirmed == 1
        assert bm.confidence == 0.5  # agent_derived default

    @pytest.mark.asyncio
    async def test_user_confirmed_higher_confidence(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        bm = await svc.create_or_confirm(
            db,
            connection_id=conn.id,
            metric_key="revenue",
            value="1000",
            source="user_confirmed",
        )
        assert bm.confidence == 0.8

    @pytest.mark.asyncio
    async def test_confirm_existing_bumps_count(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        bm1 = await svc.create_or_confirm(db, conn.id, "revenue", "1000")
        assert bm1.times_confirmed == 1

        bm2 = await svc.create_or_confirm(db, conn.id, "revenue", "1050")
        assert bm2.id == bm1.id
        assert bm2.times_confirmed == 2
        assert bm2.value == "1050"

    @pytest.mark.asyncio
    async def test_confirm_with_space_in_key_normalizes(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        bm = await svc.create_or_confirm(db, conn.id, "Total Revenue", "5000")
        assert bm.metric_key == "total_revenue"


class TestFindBenchmark:
    @pytest.mark.asyncio
    async def test_find_by_key(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.create_or_confirm(db, conn.id, "revenue", "1000")
        found = await svc.find_benchmark(db, conn.id, metric_key="revenue")
        assert found is not None
        assert found.metric_key == "revenue"

    @pytest.mark.asyncio
    async def test_find_by_description(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.create_or_confirm(db, conn.id, "total_revenue", "1000")
        found = await svc.find_benchmark(db, conn.id, raw_description="Total Revenue")
        assert found is not None

    @pytest.mark.asyncio
    async def test_find_nonexistent(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        found = await svc.find_benchmark(db, conn.id, metric_key="nonexistent")
        assert found is None

    @pytest.mark.asyncio
    async def test_find_no_key_or_desc(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        found = await svc.find_benchmark(db, conn.id)
        assert found is None


class TestFlagStale:
    @pytest.mark.asyncio
    async def test_flag_reduces_confidence(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        bm = await svc.create_or_confirm(db, conn.id, "revenue", "1000", source="user_confirmed")
        original_conf = bm.confidence

        flagged = await svc.flag_stale(db, conn.id, "revenue")
        assert flagged is not None
        assert flagged.confidence < original_conf

    @pytest.mark.asyncio
    async def test_flag_nonexistent(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        result = await svc.flag_stale(db, conn.id, "nonexistent")
        assert result is None


class TestGetAllForConnection:
    @pytest.mark.asyncio
    async def test_returns_above_min_confidence(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.create_or_confirm(db, conn.id, "rev", "1000", source="user_confirmed")
        await svc.create_or_confirm(db, conn.id, "orders", "50", source="agent_derived")

        bms = await svc.get_all_for_connection(db, conn.id, min_confidence=0.0)
        assert len(bms) == 2

    @pytest.mark.asyncio
    async def test_filters_low_confidence(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.create_or_confirm(db, conn.id, "rev", "1000")
        await svc.flag_stale(db, conn.id, "rev")
        await svc.flag_stale(db, conn.id, "rev")

        bms = await svc.get_all_for_connection(db, conn.id, min_confidence=0.3)
        assert len(bms) == 0
