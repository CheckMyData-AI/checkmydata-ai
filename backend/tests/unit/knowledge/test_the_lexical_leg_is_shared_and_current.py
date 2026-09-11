"""The BM25 leg was rebuilt per question, and then never rebuilt at all.

P2 row 15; RET-05 and RET-06. Opposite halves of the same seam — one process pays
for the corpus over and over, and the process paying for it serves a copy that can
never change.

**RET-05 — every ContextPack request builds a fresh catalog service.** The snapshot
cache is an *instance* attribute on `BM25Index`, and `build_context_pack` creates a
`KnowledgeCatalogService` as a local variable — so each question constructs a new
service, a new `HybridRetriever`, a new `BM25Index` with an empty cache, and
gunzips and re-indexes the whole corpus. Measured at production shape (31 392 chunks
from 763 docs): **2.23 s and ~245 MiB of RSS per question**, on the dyno type that
has repeatedly been SIGKILLed for memory. The two long-lived retrievers —
`ContextLoader`'s and `KnowledgeAgent`'s — do cache; this third path never did.

**RET-06 — and that corpus is frozen at the first read after boot.** `web` and
`worker` are separate Heroku process types with separate filesystems. Every writer of
a snapshot runs in the worker; the start-up reconcile on web rebuilds **missing**
snapshots only, deliberately; and `BM25Index._snapshots` caches for the life of the
process with no invalidation and no TTL. So after the nightly re-index, a question
about a file added that night fuses a current dense hit against a lexical corpus that
has never seen it — and a file deleted that night still returns a BM25 hit whose
`doc_id` no longer exists in the vector store. `query_with_reason` reported `"ok"`
throughout: staleness had no reason code at all.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from app.knowledge.bm25_index import BM25Index


class TestOneCorpusPerProcess:
    """RET-05."""

    def test_the_context_pack_does_not_build_a_catalog_per_question(self) -> None:
        from app.agents.context_loader import ContextLoader

        tree = ast.parse(textwrap.dedent(inspect.getsource(ContextLoader.build_context_pack)))
        constructions = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and ast.unparse(node.func).endswith("KnowledgeCatalogService")
        ]
        assert not constructions, (
            "a fresh KnowledgeCatalogService per call means a fresh HybridRetriever, a "
            "fresh BM25Index and an empty snapshot cache — so the whole corpus is "
            f"gunzipped and re-indexed per question: {constructions}. Measured at "
            "production shape, 2.23 s and ~245 MiB of RSS, on the process type that "
            "has repeatedly been SIGKILLed for memory (RET-05)"
        )

    def test_the_loader_keeps_one(self) -> None:
        from app.agents.context_loader import ContextLoader

        source = inspect.getsource(ContextLoader)
        assert "_get_catalog" in source, (
            "ContextLoader already keeps one HybridRetriever for exactly this reason "
            "and did not do the same for the catalog service"
        )


class TestTheCorpusCanChangeUnderneath:
    """RET-06."""

    def test_a_rewritten_snapshot_is_noticed(self, tmp_path) -> None:
        """The cache had no invalidation and no TTL, so a rewrite was invisible."""
        index = BM25Index(str(tmp_path))
        index.build("p1", "sha-1", [("d1", "alpha beta gamma", {})])
        assert index.load("p1") is not None

        # Another process — the worker, in production — writes a new corpus.
        BM25Index(str(tmp_path)).build("p1", "sha-2", [("d2", "delta epsilon zeta", {})])

        snap = index.load("p1")
        assert snap is not None
        assert snap.indexed_sha == "sha-2", (
            "the in-process cache serves the corpus as it stood at the first read "
            "after boot, for the life of the process. Every writer runs in the "
            "worker and the start-up reconcile on web rebuilds MISSING snapshots "
            "only — so after a nightly re-index the lexical leg has never seen a file "
            "the dense leg already returns, and a deleted file still scores (RET-06)"
        )

    def test_the_reconcile_can_refresh_a_stale_one(self) -> None:
        from app.ops.bm25_local_reconcile import reconcile_local_bm25

        sig = inspect.signature(reconcile_local_bm25)
        assert "refresh_stale" in sig.parameters, (
            "the reconcile is missing-only, and nothing else on the web dyno ever "
            "rewrites the file — so the corpus is frozen for the life of the process"
        )

    @pytest.mark.asyncio
    async def test_a_stale_snapshot_is_rebuilt_and_a_current_one_is_left_alone(
        self, tmp_path, monkeypatch
    ) -> None:
        """Rows in, snapshot out — the fingerprint is what decides.

        A signature check passes for a parameter nobody reads, which this programme
        has now learned four times; this drives the real reconcile over a real
        database and counts what it rebuilt.
        """
        import datetime as dt
        import uuid

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.config import settings
        from app.models.base import Base
        from app.models.knowledge_doc import KnowledgeDoc
        from app.models.project import Project
        from app.ops.bm25_local_reconcile import reconcile_local_bm25

        monkeypatch.setattr(settings, "bm25_data_dir", str(tmp_path))

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        project_id = uuid.uuid4().hex
        async with sm() as session:
            session.add(Project(id=project_id, name="p"))
            session.add(
                KnowledgeDoc(
                    project_id=project_id,
                    doc_type="file",
                    source_path="a.py",
                    content="alpha beta gamma",
                )
            )
            await session.commit()

        first = await reconcile_local_bm25(session_factory=sm, refresh_stale=True)
        assert first.rebuilt == 1, "the premise is wrong: nothing was built"

        second = await reconcile_local_bm25(session_factory=sm, refresh_stale=True)
        assert second.rebuilt == 0 and second.skipped_present == 1, (
            "a snapshot that matches the corpus was rebuilt anyway — the check is "
            f"not reading the fingerprint: {second}"
        )

        async with sm() as session:
            session.add(
                KnowledgeDoc(
                    project_id=project_id,
                    doc_type="file",
                    source_path="b.py",
                    content="delta epsilon zeta",
                    updated_at=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=5),
                )
            )
            await session.commit()

        third = await reconcile_local_bm25(session_factory=sm, refresh_stale=True)
        await engine.dispose()

        assert third.rebuilt == 1, (
            "the corpus grew by a document and the snapshot was left as it was — "
            f"which is RET-06 exactly: {third}"
        )

    def test_staleness_has_a_name(self) -> None:
        from app.knowledge.bm25_index import BM25_DEGRADED_REASONS

        assert any("stale" in reason for reason in BM25_DEGRADED_REASONS), (
            "`query_with_reason` reports 'ok' while serving a corpus from before the "
            "last re-index, and the degradation vocabulary has no member for it — so "
            "the counter this repository added to make the leg's health measurable "
            "cannot see the condition (RET-06)"
        )


class TestSomethingActuallyRunsTheRefresh:
    """RET-06, the half that makes the rest reachable."""

    def test_the_lifespan_starts_a_refresh_loop(self) -> None:
        from app import main

        source = inspect.getsource(main.lifespan)
        assert "_bm25_refresh_loop" in source, (
            "the reconcile can refresh a stale snapshot and nothing calls it that way, "
            "so the web dyno's corpus is still frozen for the life of the process"
        )

    def test_the_loop_asks_for_the_refresh(self) -> None:
        from app import main

        tree = ast.parse(textwrap.dedent(inspect.getsource(main._bm25_refresh_loop)))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and "reconcile_local_bm25" in ast.unparse(node.func)
        ]
        assert calls, "the loop does not call the reconcile at all"
        assert any(
            kw.arg == "refresh_stale"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for call in calls
            for kw in call.keywords
        ), (
            "the loop calls the reconcile in its missing-only mode, so it rebuilds "
            "nothing a boot would not already have rebuilt"
        )

    def test_the_interval_is_configurable_with_a_floor(self) -> None:
        from app.config import Settings

        assert Settings().bm25_refresh_interval_seconds >= 60
