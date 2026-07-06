import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.deploy_state import DeployState


@pytest.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[DeployState.__table__]))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_deploy_state_round_trip(session_factory):
    async with session_factory() as s:
        s.add(DeployState(key="embedding_fingerprint", value="m|1"))
        await s.commit()
    async with session_factory() as s:
        row = await s.get(DeployState, "embedding_fingerprint")
    assert row is not None
    assert row.value == "m|1"
    assert row.updated_at is not None
