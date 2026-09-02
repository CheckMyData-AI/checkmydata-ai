"""The RAG leg was empty on the production vector backend, and nothing said so.

`_get_hybrid_retriever` asserted `isinstance(self._vector_store, VectorStore)`.
`VectorStore` is the concrete ChromaDB class; `PgVectorStore` implements the same
method surface and inherits from `object` alone. Production resolves to `pgvector`
(`resolve_backend(None, "postgresql…")`), so the assert failed on every request —
and `_rag_artifacts_async` catches `Exception`, logs at **DEBUG**, and returns `[]`.

So `pack.rag_chunks` was always empty, `sources.add("rag")` never fired, and there was
no counter, no event, no sentence and no trace span saying so. Answers were composed
with no documentation context at all, silently, since the 2026-08-28 backend flip.

The assert guarded nothing it could guard: the other two call sites pass the same
object with no assert and work (`knowledge_catalog_service.py:481`,
`context_loader.py:128`). A nominal `isinstance` over a structural contract is a check
that fails exactly when the contract is honoured by a different class.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.knowledge_catalog_service import KnowledgeCatalogService


class _NotAVectorStoreSubclass:
    """The shape `PgVectorStore` has: every method, none of the ancestry."""

    def __init__(self) -> None:
        self.queried = False

    def query(
        self,
        project_id: str,
        query_text: str,
        n_results: int = 5,
        where: dict | None = None,
        **kw: Any,
    ) -> list[dict]:
        # Signature matched to VectorStore.query: HybridRetriever calls it positionally
        # with (project_id, query, n, where); the non-hybrid path uses n_results= by name.
        self.queried = True
        return [
            {
                "document": "Subscriptions lapse after two failed charges.",
                "metadata": {"source": "docs/billing.md", "file_path": "docs/billing.md"},
                "id": "doc-1",
                # PgVectorStore returns `distance` shaped exactly as ChromaDB does, and
                # the fused path drops any hit that has none — a stub without it would
                # pass for the wrong reason.
                "distance": 0.20,
            }
        ]

    def get_or_create_collection(self, project_id: str) -> Any:  # pragma: no cover - shape only
        raise NotImplementedError

    def add_documents(self, *a: Any, **k: Any) -> Any:  # pragma: no cover - shape only
        raise NotImplementedError

    def delete_by_source_path(self, *a: Any, **k: Any) -> int:  # pragma: no cover - shape only
        raise NotImplementedError

    def delete_collection(self, project_id: str) -> None:  # pragma: no cover - shape only
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - shape only
        return None


def test_pgvector_store_is_not_a_vector_store_subclass() -> None:
    """The premise, pinned: if this ever becomes True the assert was harmless after all."""
    from app.knowledge.pgvector_store import PgVectorStore
    from app.knowledge.vector_store import VectorStore

    assert not issubclass(PgVectorStore, VectorStore)


def test_production_resolves_to_the_backend_the_assert_rejected() -> None:
    from app.knowledge.vector_store import resolve_backend

    assert resolve_backend(None, "postgresql+asyncpg://user@host/db") == "pgvector"


async def test_the_rag_leg_returns_documents_on_a_non_chroma_store(monkeypatch) -> None:
    """The whole defect in one call: hybrid on, a store that is not a Chroma subclass."""
    store = _NotAVectorStoreSubclass()
    svc = KnowledgeCatalogService(vector_store=store)

    # Keep the test on the seam under repair: BM25 is a separate leg with its own
    # snapshot on disk, so it is stubbed to contribute nothing rather than to fail.
    class _NoBm25:
        def query(self, *a: Any, **k: Any) -> list:
            return []

        def query_with_reason(self, *a: Any, **k: Any) -> tuple[list, str]:
            return [], "no_match"

    monkeypatch.setattr("app.knowledge.bm25_index.BM25Index", lambda *a, **k: _NoBm25())

    artifacts = await svc._rag_artifacts_async(
        project_id="p1", question="when does a subscription lapse", n_results=3
    )
    assert artifacts, "the RAG leg returned nothing on the production vector backend"
    assert store.queried, "the dense leg was never asked"


async def test_a_real_retrieval_failure_is_logged_loudly(monkeypatch, caplog) -> None:
    """`[]` on failure is the right behaviour; hiding the reason at DEBUG is not."""

    class _Broken:
        def query(self, *a: Any, **k: Any) -> list[dict]:
            raise RuntimeError("vector store is down")

        def query_with_reason(self, *a: Any, **k: Any) -> tuple[list, str]:
            raise RuntimeError("vector store is down")

    svc = KnowledgeCatalogService(vector_store=_Broken())
    monkeypatch.setattr("app.config.settings.hybrid_retrieval_enabled", False)

    with caplog.at_level(logging.WARNING):
        assert await svc._rag_artifacts_async(project_id="p1", question="q", n_results=3) == []
    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "a broken retrieval store still degrades in silence — DEBUG is invisible in production"
    )
