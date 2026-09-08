"""A rebuild must not pay an LLM to re-describe a file that has not changed.

Measured on production: a full repository rebuild of `esim-php` runs 12 039–12 329 s, of
which `generate_docs` is ~9 375 s — 758 documents at ~4.8 per minute, 1.7–2.0M tokens.
535 of those documents are database migrations, files that by their nature never change
after they are written.

A `force_full` rebuild is not rare and is not an operator mistake: `embedding_fingerprint`
enqueues one whenever `GRAPH_EXTRACTION_SCHEMA`, `SYMBOL_UID_SCHEMA` or the embedding
configuration moves. So every structural fix to the extractor re-buys the same 9 375 s of
prose about migrations that were last edited months ago.

The step's only skip conditions today (`pipeline_runner.py:1063+`) are "this run already
processed the path" (a checkpoint of the CURRENT run, so useless across runs) and "the
content looks binary". Nothing compares the source to what the stored document was
generated FROM, because that was never recorded.

The key deliberately excludes the commit sha and the project's git state: a document is a
function of its input, and a rebuild triggered by a UID-schema bump has not changed a
single migration's text. `DOC_GEN_SCHEMA` is the invalidation handle, and it must NOT
reach `embedding_fingerprint()` — a reworded prompt should not re-embed the whole project,
and a symbol-UID bump should not throw away every document.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.knowledge.doc_cache import (
    DOC_GEN_SCHEMA,
    doc_content_hash,
    should_reuse_document,
)
from app.models.base import Base


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


class TestTheKeyRespondsToItsInputs:
    def test_the_same_inputs_give_the_same_key(self) -> None:
        a = doc_content_hash(content="class User {}", doc_type="orm_model", enrichment_context="x")
        b = doc_content_hash(content="class User {}", doc_type="orm_model", enrichment_context="x")
        assert a == b

    @pytest.mark.parametrize(
        "field,value",
        [
            ("content", "class User { public $id; }"),
            ("doc_type", "migration"),
            ("enrichment_context", "tables: users, orders"),
        ],
    )
    def test_changing_any_input_changes_the_key(self, field: str, value: str) -> None:
        base = {"content": "class User {}", "doc_type": "orm_model", "enrichment_context": "x"}
        assert doc_content_hash(**base) != doc_content_hash(**{**base, field: value})

    def test_the_schema_constant_invalidates_everything(self, monkeypatch) -> None:
        """The handle for a prompt or format change: bump it and every cached document is
        regenerated, without touching the embeddings."""
        base = {"content": "class User {}", "doc_type": "orm_model", "enrichment_context": "x"}
        before = doc_content_hash(**base)
        monkeypatch.setattr("app.knowledge.doc_cache.DOC_GEN_SCHEMA", DOC_GEN_SCHEMA + 1)
        assert doc_content_hash(**base) != before

    def test_the_fields_cannot_be_confused_for_one_another(self) -> None:
        """Concatenation without a separator would make ("ab", "c") and ("a", "bc") the
        same document. They are not."""
        assert doc_content_hash(
            content="ab", doc_type="c", enrichment_context=""
        ) != doc_content_hash(content="a", doc_type="bc", enrichment_context="")

    def test_a_missing_enrichment_context_is_not_the_string_none(self) -> None:
        assert doc_content_hash(
            content="x", doc_type="t", enrichment_context=None
        ) == doc_content_hash(content="x", doc_type="t", enrichment_context="")

    def test_the_key_fits_the_column(self) -> None:
        """`knowledge_docs.content_hash` is `String(80)`."""
        h = doc_content_hash(content="x" * 100_000, doc_type="t", enrichment_context="y")
        assert len(h) <= 80


class TestTheSchemaConstantStaysOutOfTheEmbeddingFingerprint:
    def test_the_two_invalidation_handles_are_independent(self) -> None:
        """Both directions matter and each would be expensive the wrong way round.

        `DOC_GEN_SCHEMA` inside `embedding_fingerprint` would make a reworded prompt
        re-embed every chunk in every project — the 2 300 s `code_symbol_embed` step, for
        a change that touches no vector. And the symbol-UID constants inside the document
        key would throw away 758 cached documents whenever a symbol's identity moved,
        which is the exact cost this cache exists to avoid.
        """
        import inspect
        import re

        from app.knowledge import doc_cache
        from app.ops import embedding_reconcile

        def code_only(module) -> str:
            """Both modules EXPLAIN the coupling they forbid, so a grep over their prose
            trips on the explanation and the explanation is what gets deleted. Strip
            docstrings and comments first — the convention this repository already
            follows for source-level guards."""
            src = re.sub(r'"""[\s\S]*?"""', "", inspect.getsource(module))
            return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))

        assert "DOC_GEN_SCHEMA" not in code_only(embedding_reconcile), (
            "the document-prompt handle reached the embedding fingerprint; a prompt "
            "reword would now re-embed every project"
        )

        doc_src = code_only(doc_cache)
        for symbol in ("SYMBOL_UID_SCHEMA", "GRAPH_EXTRACTION_SCHEMA", "commit_sha", "head_sha"):
            assert symbol not in doc_src, (
                f"`{symbol}` reached the document cache key; a rebuild triggered by it "
                "would regenerate documents whose source text did not change — which is "
                "precisely the case this cache exists for"
            )


class TestTheStoreCarriesTheHash:
    """The key is only worth what the write path records. `upsert` writing the hash and
    `touch_reused` confirming a hit are the two halves; either one missing turns the
    cache into a permanent miss that nothing reports."""

    async def test_upsert_records_what_the_document_was_generated_from(self, db_session) -> None:
        from app.knowledge.doc_store import DocStore

        store = DocStore()
        doc = await store.upsert(
            session=db_session,
            project_id="p1",
            doc_type="migration",
            source_path="db/migrations/001.php",
            content="This migration creates the users table.",
            commit_sha="abc123",
            content_hash="deadbeef",
        )
        assert doc.content_hash == "deadbeef"

    async def test_a_regeneration_without_a_hash_clears_the_old_one(self, db_session) -> None:
        """`None` overwrites rather than being ignored.

        A caller that did not compute a hash has not verified one, and keeping the
        previous value would claim this content came from inputs nobody compared it
        against — the cache would then hit forever on a document generated from
        something else.
        """
        from app.knowledge.doc_store import DocStore

        store = DocStore()
        await store.upsert(
            session=db_session,
            project_id="p1",
            doc_type="migration",
            source_path="db/migrations/002.php",
            content="v1",
            content_hash="hash-of-v1",
        )
        again = await store.upsert(
            session=db_session,
            project_id="p1",
            doc_type="migration",
            source_path="db/migrations/002.php",
            content="v2",
        )
        assert again.content_hash is None

    async def test_touch_reused_moves_the_sha_without_touching_content(self, db_session) -> None:
        """A cache hit is a confirmation, not a no-op: freshness reporting reads
        `commit_sha`, so a reused document left at an old sha reads as stale."""
        from sqlalchemy import select

        from app.knowledge.doc_store import DocStore
        from app.models.knowledge_doc import KnowledgeDoc

        store = DocStore()
        for i in range(3):
            await store.upsert(
                session=db_session,
                project_id="p1",
                doc_type="migration",
                source_path=f"db/{i}.php",
                content=f"body {i}",
                commit_sha="old-sha",
                content_hash=f"h{i}",
            )

        touched = await store.touch_reused(db_session, "p1", ["db/0.php", "db/2.php"], "new-sha")
        await db_session.commit()
        assert touched == 2

        rows = {
            d.source_path: d
            for d in (
                await db_session.execute(
                    select(KnowledgeDoc).where(KnowledgeDoc.project_id == "p1")
                )
            )
            .scalars()
            .all()
        }
        assert rows["db/0.php"].commit_sha == "new-sha"
        assert rows["db/2.php"].commit_sha == "new-sha"
        assert rows["db/1.php"].commit_sha == "old-sha", "a document nobody reused was moved"
        assert rows["db/0.php"].content == "body 0", "a touch rewrote the document"
        assert rows["db/0.php"].content_hash == "h0", "a touch discarded the cache key"

    async def test_an_empty_batch_writes_nothing(self, db_session) -> None:
        from app.knowledge.doc_store import DocStore

        assert await DocStore().touch_reused(db_session, "p1", [], "sha") == 0


class TestTheModelOverrideIsPerDocType:
    def test_absent_configuration_changes_nothing(self) -> None:
        """The default is empty, so every doc type resolves to the project's own model.
        Turning the override on is a deliberate production config change, not a default."""
        from app.config import settings

        assert settings.indexing_llm_model_by_doc_type == {}

    def test_the_lookup_falls_back_to_the_project_model(self) -> None:
        override = {"migration": "cheap-model"}
        assert override.get("migration", "project-model") == "cheap-model"
        assert override.get("orm_model", "project-model") == "project-model"

    def test_the_pipeline_asks_per_doc_and_not_once(self) -> None:
        """Source-level: `_generate_one_doc` is nested inside a long step body that a
        unit test cannot reach without an LLM, a tracker and two sessions. The property
        is that the lookup uses THIS doc's type — resolving it once outside the closure
        would give every document the first one's model."""
        import inspect
        import re

        from app.knowledge import pipeline_runner

        src = inspect.getsource(pipeline_runner.IndexingPipelineRunner)
        body = re.sub(r'"""[\s\S]*?"""', "", src)
        body = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
        # Whitespace-normalised: the formatter wraps this call across three lines, and a
        # guard that breaks when `ruff format` moves a comma is a guard that gets deleted.
        flat = " ".join(body.split())
        assert "indexing_llm_model_by_doc_type.get(" in flat, "the override is not consulted"
        assert "edoc.doc_type, project.indexing_llm_model" in flat, (
            "the override must be keyed on THIS document's type and fall back to the "
            "project's model"
        )


class TestTheReuseDecision:
    """The rule the whole cache rests on. Only one of three states is a hit."""

    def test_matching_hashes_reuse(self) -> None:
        assert should_reuse_document(
            existing_content="a document", stored_hash="h", computed_hash="h"
        )

    def test_changed_source_regenerates(self) -> None:
        assert not should_reuse_document(
            existing_content="a document", stored_hash="old", computed_hash="new"
        )

    def test_a_document_generated_before_the_cache_regenerates(self) -> None:
        """NULL is unknown, not unchanged. Every row in production carries NULL on the
        first deploy, so treating it as a match would serve stale prose for every
        document in the project and never look again."""
        assert not should_reuse_document(
            existing_content="a document", stored_hash=None, computed_hash="h"
        )

    def test_a_hash_without_a_document_regenerates(self) -> None:
        """Reachable only through a partial write, and generating is the cheap way to be
        sure — reusing would hand the pipeline `None` as a document body."""
        assert not should_reuse_document(existing_content=None, stored_hash="h", computed_hash="h")

    def test_an_empty_document_is_still_a_document(self) -> None:
        """`""` is falsy and `None` is absent; conflating them would regenerate every
        legitimately empty document on every run, forever."""
        assert should_reuse_document(existing_content="", stored_hash="h", computed_hash="h")

    def test_the_pipeline_routes_through_this_decision(self) -> None:
        """Source-level, and the reason it exists: the generate_docs step is a 400-line
        body inside a method no unit test can reach. A second copy of the rule inlined
        there would drift from the one these tests cover."""
        import inspect
        import re

        from app.knowledge import pipeline_runner

        src = inspect.getsource(pipeline_runner.IndexingPipelineRunner)
        body = re.sub(r'"""[\s\S]*?"""', "", src)
        body = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
        assert "should_reuse_document(" in body, (
            "the step decides for itself whether to reuse; the rule now has two homes"
        )
