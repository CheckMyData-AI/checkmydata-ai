"""F-KNOW-12: the snapshot is written on one dyno and read on another.

`Procfile` declares `web` and `worker` as separate Heroku process types, so they have
separate ephemeral filesystems. `bm25_data_dir` is a local path (`config.py:653`) with
no shared volume. The repo index — which writes the `.pkl` — runs in the **worker**
(`worker.py:221`); every reader on the chat path (`context_loader.py:79`,
`knowledge_agent.py:61`, `knowledge_catalog_service.py:89`) runs in the **web** dyno.

So the BM25 leg of hybrid retrieval had no snapshot to read at all in that deployment —
not "after a restart", which is how the finding was written. The fix has to rebuild the
snapshot in whichever process is about to read it, from Postgres, at start-up.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.knowledge_doc  # noqa: F401
import app.models.project  # noqa: F401
import app.models.repository  # noqa: F401
import app.models.user  # noqa: F401
from app.knowledge.bm25_index import BM25Index
from app.models.base import Base
from app.models.knowledge_doc import KnowledgeDoc
from app.models.project import Project
from app.models.repository import ProjectRepository


@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _project_with_docs(factory, *, docs: int = 3, commit: str | None = "abc123") -> str:
    async with factory() as s:
        p = Project(name=f"p-{uuid.uuid4().hex[:6]}")
        s.add(p)
        await s.flush()
        if commit:
            s.add(
                ProjectRepository(
                    project_id=p.id,
                    name="r",
                    repo_url="https://example.com/r.git",
                    last_indexed_commit=commit,
                )
            )
        for i in range(docs):
            s.add(
                KnowledgeDoc(
                    project_id=p.id,
                    source_path=f"src/mod_{i}.py",
                    doc_type="code",
                    content=f"def analyze_query_{i}(payload):\n    return validate(payload)\n",
                )
            )
        await s.commit()
        return p.id


class TestLocalSnapshotReconcile:
    @pytest.mark.asyncio
    async def test_a_missing_snapshot_is_rebuilt_from_postgres(
        self, factory, tmp_path, monkeypatch
    ):
        from app.config import settings
        from app.ops.bm25_local_reconcile import reconcile_local_bm25

        monkeypatch.setattr(settings, "bm25_data_dir", str(tmp_path), raising=False)
        monkeypatch.setattr(settings, "hybrid_retrieval_enabled", True, raising=False)
        pid = await _project_with_docs(factory)

        idx = BM25Index(str(tmp_path))
        assert idx.indexed_sha(pid) is None, "nothing on this disk yet — that is the defect"

        out = await reconcile_local_bm25(session_factory=factory)

        assert out.rebuilt == 1
        assert idx.indexed_sha(pid) == "abc123"
        hits, reason = idx.query_with_reason(pid, "analyze_query_1")
        assert reason != "no_snapshot"

    @pytest.mark.asyncio
    async def test_an_existing_snapshot_is_left_alone(self, factory, tmp_path, monkeypatch):
        """Idempotent, and cheap on the second boot."""
        from app.config import settings
        from app.ops.bm25_local_reconcile import reconcile_local_bm25

        monkeypatch.setattr(settings, "bm25_data_dir", str(tmp_path), raising=False)
        monkeypatch.setattr(settings, "hybrid_retrieval_enabled", True, raising=False)
        await _project_with_docs(factory)

        first = await reconcile_local_bm25(session_factory=factory)
        second = await reconcile_local_bm25(session_factory=factory)
        assert first.rebuilt == 1
        assert second.rebuilt == 0
        assert second.skipped_present == 1

    @pytest.mark.asyncio
    async def test_a_stale_snapshot_is_not_touched(self, factory, tmp_path, monkeypatch):
        """At boot there is no clone, so the true head SHA is unknowable.

        Rebuilding on a SHA mismatch here would stamp the snapshot with whatever the
        last *indexed* commit was and call it current — a claim this process has no
        way to support. Staleness stays the pipeline's job, which has a clone.
        """
        from app.config import settings
        from app.ops.bm25_local_reconcile import reconcile_local_bm25

        monkeypatch.setattr(settings, "bm25_data_dir", str(tmp_path), raising=False)
        monkeypatch.setattr(settings, "hybrid_retrieval_enabled", True, raising=False)
        pid = await _project_with_docs(factory)
        await reconcile_local_bm25(session_factory=factory)

        # Move the recorded commit on: the snapshot is now stale by that measure.
        async with factory() as s:
            import sqlalchemy

            repo = (await s.scalars(sqlalchemy.select(ProjectRepository))).one()
            repo.last_indexed_commit = "def456"
            await s.commit()

        out = await reconcile_local_bm25(session_factory=factory)
        assert out.rebuilt == 0
        assert BM25Index(str(tmp_path)).indexed_sha(pid) == "abc123"

    @pytest.mark.asyncio
    async def test_a_project_with_no_docs_is_skipped(self, factory, tmp_path, monkeypatch):
        """Building an empty snapshot would make `no_snapshot` unreachable and turn a
        real gap into a silent `no_match`."""
        from app.config import settings
        from app.ops.bm25_local_reconcile import reconcile_local_bm25

        monkeypatch.setattr(settings, "bm25_data_dir", str(tmp_path), raising=False)
        monkeypatch.setattr(settings, "hybrid_retrieval_enabled", True, raising=False)
        pid = await _project_with_docs(factory, docs=0)

        out = await reconcile_local_bm25(session_factory=factory)
        assert out.rebuilt == 0
        assert out.skipped_no_docs == 1
        assert BM25Index(str(tmp_path)).indexed_sha(pid) is None

    @pytest.mark.asyncio
    async def test_a_project_with_docs_but_no_recorded_commit_still_rebuilds(
        self, factory, tmp_path, monkeypatch
    ):
        """The SHA is a staleness stamp, not a precondition — refusing to build without
        one would leave the retriever dense-only for exactly the projects that have
        content."""
        from app.config import settings
        from app.ops.bm25_local_reconcile import reconcile_local_bm25

        monkeypatch.setattr(settings, "bm25_data_dir", str(tmp_path), raising=False)
        monkeypatch.setattr(settings, "hybrid_retrieval_enabled", True, raising=False)
        pid = await _project_with_docs(factory, commit=None)

        out = await reconcile_local_bm25(session_factory=factory)
        assert out.rebuilt == 1
        assert BM25Index(str(tmp_path)).indexed_sha(pid) is not None

    @pytest.mark.asyncio
    async def test_it_does_nothing_when_hybrid_retrieval_is_off(
        self, factory, tmp_path, monkeypatch
    ):
        from app.config import settings
        from app.ops.bm25_local_reconcile import reconcile_local_bm25

        monkeypatch.setattr(settings, "bm25_data_dir", str(tmp_path), raising=False)
        monkeypatch.setattr(settings, "hybrid_retrieval_enabled", False, raising=False)
        await _project_with_docs(factory)

        out = await reconcile_local_bm25(session_factory=factory)
        assert out.status == "disabled"
        assert out.rebuilt == 0

    @pytest.mark.asyncio
    async def test_one_failing_project_does_not_abandon_the_others(
        self, factory, tmp_path, monkeypatch
    ):
        from app.config import settings
        from app.ops import bm25_local_reconcile as mod

        monkeypatch.setattr(settings, "bm25_data_dir", str(tmp_path), raising=False)
        monkeypatch.setattr(settings, "hybrid_retrieval_enabled", True, raising=False)
        await _project_with_docs(factory)
        await _project_with_docs(factory)

        calls = {"n": 0}
        real = mod._build_one

        async def _flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("disk full")
            return await real(*a, **k)

        monkeypatch.setattr(mod, "_build_one", _flaky)
        out = await mod.reconcile_local_bm25(session_factory=factory)

        assert out.rebuilt == 1
        assert out.failed == 1, "the failure must be counted, not swallowed"

    @pytest.mark.asyncio
    async def test_build_one_refuses_to_write_an_empty_snapshot(self, factory, tmp_path):
        """Asserted where the guard lives, not through the caller.

        `reconcile_local_bm25` filters to projects that have docs, which makes this
        branch unreachable from there — a plant removing the guard left every
        behavioural test green. But an empty snapshot is worse than none: it turns
        `no_snapshot` (a real gap, reported) into `no_match` (silence).
        """
        from app.ops.bm25_local_reconcile import _build_one

        pid = await _project_with_docs(factory, docs=0)
        idx = BM25Index(str(tmp_path))
        async with factory() as s:
            written = await _build_one(s, pid, idx)

        assert written == 0
        assert idx.indexed_sha(pid) is None, "an empty snapshot hides the gap it should report"
