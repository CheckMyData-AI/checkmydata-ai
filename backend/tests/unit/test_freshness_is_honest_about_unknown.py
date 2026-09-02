"""Freshness had two states where it needed three, and no signal for the failure this
repository documents most carefully.

**"We could not check" read as "we checked and it is fresh."** `context_loader` catches
every exception from `check_staleness`, logs at DEBUG and returns `None`. That `None`
becomes the answer's `staleness_warning`, and `Seal.tsx` reads its absence as freshness:
`return stalenessWarning ? "inferred" : "verified"`. So a crashed check and a clean check
produced the identical green seal. The invariant's whole point is that the third state —
unknown — must be visible, and the code had only two.

The same shape sits inside the service: all five of its checks swallow their exception and
drop the signal, so a snapshot with no warnings means either "nothing is stale" or
"nothing could be examined".

**And the failure it exists to warn about is invisible to it.** The service combines
DB-index age, code↔DB sync, code-graph symbols and git HEAD versus the indexed SHA — and
never asks the vector store how many chunks it holds. The SHA lives in Postgres and
survives the dyno restart that wipes an ephemeral Chroma directory, so after the wipe this
repository documents ("`index_repo` completed 16 times in 94 runs") every signal still
reads fresh while the store is empty and the answer is synthesised from nothing.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.services.knowledge_freshness_service import (
    FreshnessWarningDetail,
    KnowledgeFreshness,
    KnowledgeFreshnessService,
)


class _Store:
    def __init__(self, n: int = 0, *, boom: bool = False) -> None:
        self._n = n
        self._boom = boom

    def count(self, project_id: str) -> int:
        if self._boom:
            raise RuntimeError("vector store unreachable")
        return self._n


@pytest.fixture
def svc():
    return KnowledgeFreshnessService()


@pytest_asyncio.fixture()
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _categories(snapshot: KnowledgeFreshness) -> set[str]:
    return {d.category for d in snapshot.details}


class TestAnEmptyVectorStoreIsAWarning:
    async def test_zero_chunks_is_reported(self, svc, db_session) -> None:
        snap = await svc.evaluate(
            db_session, project_id="p1", connection_id=None, vector_store=_Store(0)
        )
        assert "vector_store" in _categories(snap), (
            "an empty knowledge index reads as fresh; the answer is synthesised from "
            "nothing and nothing says so"
        )

    async def test_zero_chunks_is_critical(self, svc, db_session) -> None:
        snap = await svc.evaluate(
            db_session, project_id="p1", connection_id=None, vector_store=_Store(0)
        )
        detail = next(d for d in snap.details if d.category == "vector_store")
        assert detail.severity == "critical"
        assert detail.action_kind == "reindex_repo"

    async def test_a_populated_store_is_silent(self, svc, db_session) -> None:
        snap = await svc.evaluate(
            db_session, project_id="p1", connection_id=None, vector_store=_Store(4200)
        )
        assert "vector_store" not in _categories(snap)


class TestACheckThatCouldNotRunSaysSo:
    async def test_a_failing_check_is_not_silence(self, svc, db_session) -> None:
        """Dropping the exception makes 'nothing is stale' and 'nothing could be
        examined' the same snapshot."""
        snap = await svc.evaluate(
            db_session, project_id="p1", connection_id=None, vector_store=_Store(boom=True)
        )
        assert any("could not" in d.message.lower() for d in snap.details), (
            "a check that crashed left no trace in the snapshot"
        )

    async def test_the_unknown_state_is_not_dressed_as_stale(self, svc, db_session) -> None:
        """'Could not check' is its own thing — reporting it as `critical` would teach
        the reader to ignore critical."""
        snap = await svc.evaluate(
            db_session, project_id="p1", connection_id=None, vector_store=_Store(boom=True)
        )
        unknown = [d for d in snap.details if "could not" in d.message.lower()]
        assert unknown and all(d.severity != "critical" for d in unknown)


class _NullTracker:
    async def emit(self, *a, **k) -> None:
        return None


class TestTheSealCannotReadSilenceAsFreshness:
    async def test_a_failed_staleness_check_returns_a_warning_not_none(self, monkeypatch) -> None:
        """`Seal.tsx` does `stalenessWarning ? "inferred" : "verified"`, so `None` from a
        crashed check is rendered as a verified answer."""
        from app.agents.context_loader import ContextLoader

        async def _boom(*a, **k):
            raise RuntimeError("freshness service is down")

        monkeypatch.setattr(
            "app.services.knowledge_freshness_service.KnowledgeFreshnessService.evaluate_summary",
            _boom,
        )
        loader = ContextLoader(vector_store=None, tracker=_NullTracker(), mcp_cache=None)
        out = await loader.check_staleness("p1", connection_id=None)
        assert out is not None, "a crashed freshness check produces the same seal as a clean one"
        assert "could not" in out.lower()


def test_the_warning_detail_carries_the_three_severities() -> None:
    """Pinned because the whole point is that `unknown` is neither `fresh` nor `stale`."""
    assert FreshnessWarningDetail(category="x", message="m").severity == "warning"
    assert FreshnessWarningDetail(category="x", message="m", severity="info").severity == "info"


class TestTheSignalStaysWired:
    """The service refuses to build a store, so the signal exists only where a caller
    passes one. That makes this test the thing that keeps it alive in production."""

    def test_every_production_caller_passes_a_vector_store(self) -> None:
        import pathlib
        import re

        app = pathlib.Path(__file__).parents[2] / "app"
        callers = [
            p
            for p in app.rglob("*.py")
            if re.search(r"\.evaluate(_summary)?\(\s*\n?\s*session", p.read_text(encoding="utf-8"))
            and "KnowledgeFreshnessService" in p.read_text(encoding="utf-8")
        ]
        assert callers, "no caller found; this guard is checking nothing"
        missing = [
            p.relative_to(app).as_posix()
            for p in callers
            if "vector_store=" not in p.read_text(encoding="utf-8")
        ]
        assert not missing, (
            f"{missing} call the freshness service without a vector store, so the "
            "empty-index signal is silently absent there"
        )

    async def test_no_store_means_no_signal_rather_than_a_false_unknown(
        self, svc, db_session
    ) -> None:
        snap = await svc.evaluate(db_session, project_id="p1", connection_id=None)
        assert not any(d.category == "vector_store" for d in snap.details)
