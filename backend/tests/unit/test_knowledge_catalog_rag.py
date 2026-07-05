"""RET-R2: ContextPack rag_chunks through HybridRetriever.

Verifies that ``KnowledgeCatalogService._rag_artifacts_async`` (and therefore
the ``rag_chunks`` leg of ``get_context_pack``) uses ``HybridRetriever`` when
hybrid retrieval is enabled, degrades to dense-only ``vector_store.query`` when
hybrid is disabled, and maps raw results into the correct ``Artifact`` shape.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.knowledge.context_pack import Artifact
from app.knowledge.hybrid_retriever import HybridResult
from app.services.knowledge_catalog_service import KnowledgeCatalogService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hybrid_hit(
    doc_id: str = "chunk:1",
    document: str = "some doc text",
    source_path: str = "app/models/order.py",
    chunk_id: str = "c1",
    indexed_at: str | None = "2024-01-01T00:00:00",
    commit_sha: str | None = "abc123",
) -> HybridResult:
    return HybridResult(
        doc_id=doc_id,
        document=document,
        metadata={
            "source_path": source_path,
            "chunk_id": chunk_id,
            "indexed_at": indexed_at,
            "commit_sha": commit_sha,
            "file_path": source_path,
        },
        rrf_score=0.85,
        bm25_rank=1,
        chroma_rank=2,
        sources=("bm25", "chroma"),
    )


def _dense_hit(
    document: str = "dense doc text",
    source_path: str = "app/models/user.py",
    chunk_id: str = "c2",
) -> dict:
    return {
        "id": "chunk:2",
        "document": document,
        "metadata": {
            "source_path": source_path,
            "chunk_id": chunk_id,
            "indexed_at": "2024-01-02T00:00:00",
            "commit_sha": "def456",
            "file_path": source_path,
        },
        "distance": 0.15,
    }


def _clean_freshness() -> AsyncMock:
    return AsyncMock(return_value={"overall_stale": False, "warnings": []})


# ---------------------------------------------------------------------------
# Unit tests: _rag_artifacts_async (the new async RAG method)
# ---------------------------------------------------------------------------


class TestRagArtifactsAsyncHybridEnabled:
    """When hybrid_retrieval_enabled=True, the async RAG leg uses HybridRetriever."""

    @pytest.mark.asyncio
    async def test_calls_hybrid_retriever_not_vector_store_directly(self):
        """The hybrid retriever must be called; vector_store.query must NOT be."""
        vector_store = MagicMock()
        vector_store.query = MagicMock(return_value=[])

        svc = KnowledgeCatalogService(vector_store=vector_store)

        mock_retriever = AsyncMock()
        mock_retriever.query = AsyncMock(return_value=[_hybrid_hit()])

        with (
            patch("app.config.settings") as mock_settings,
            patch.object(svc, "_get_hybrid_retriever", return_value=mock_retriever),
        ):
            mock_settings.hybrid_retrieval_enabled = True
            mock_settings.hybrid_k = 20
            artifacts = await svc._rag_artifacts_async(
                project_id="p1", question="how many orders?", n_results=3
            )

        # HybridRetriever.query called, dense vector_store.query NOT called
        mock_retriever.query.assert_called_once()
        vector_store.query.assert_not_called()
        assert len(artifacts) == 1

    @pytest.mark.asyncio
    async def test_artifact_shape_from_hybrid_result(self):
        """Artifacts must have the correct shape consumed by ContextPack."""
        vector_store = MagicMock()
        svc = KnowledgeCatalogService(vector_store=vector_store)

        hit = _hybrid_hit(
            doc_id="chunk:99",
            document="SELECT COUNT(*) explains here",
            source_path="docs/orders.md",
            chunk_id="ck99",
            commit_sha="sha999",
        )
        mock_retriever = AsyncMock()
        mock_retriever.query = AsyncMock(return_value=[hit])

        with (
            patch("app.config.settings") as mock_settings,
            patch.object(svc, "_get_hybrid_retriever", return_value=mock_retriever),
        ):
            mock_settings.hybrid_retrieval_enabled = True
            mock_settings.hybrid_k = 20
            artifacts = await svc._rag_artifacts_async(
                project_id="proj1", question="count orders", n_results=5
            )

        assert len(artifacts) == 1
        art = artifacts[0]
        assert isinstance(art, Artifact)
        assert art.type == "rag_chunk"
        assert art.id == "rag:proj1::ck99"
        assert art.title == "docs/orders.md"
        assert "SELECT COUNT" in art.summary
        assert art.provenance["source"] == "rag"
        assert art.provenance["produced_by"] == "embed_and_store"
        assert art.provenance["commit_sha"] == "sha999"
        assert art.payload["file_path"] == "docs/orders.md"
        assert art.confidence == 0.5

    @pytest.mark.asyncio
    async def test_hybrid_query_called_with_correct_project_and_question(self):
        """k passed to HybridRetriever is max(n_results, hybrid_k)."""
        vector_store = MagicMock()
        svc = KnowledgeCatalogService(vector_store=vector_store)

        mock_retriever = AsyncMock()
        mock_retriever.query = AsyncMock(return_value=[])

        with (
            patch("app.config.settings") as mock_settings,
            patch.object(svc, "_get_hybrid_retriever", return_value=mock_retriever),
        ):
            mock_settings.hybrid_retrieval_enabled = True
            mock_settings.hybrid_k = 10
            await svc._rag_artifacts_async(
                project_id="myproj", question="find users by email", n_results=5
            )

        mock_retriever.query.assert_called_once_with("myproj", "find users by email", k=10)

    @pytest.mark.asyncio
    async def test_filters_empty_document_hits(self):
        """Hits with empty document text must be silently dropped."""
        vector_store = MagicMock()
        svc = KnowledgeCatalogService(vector_store=vector_store)

        hits = [
            _hybrid_hit(doc_id="c1", document=""),
            _hybrid_hit(doc_id="c2", document="  "),
            _hybrid_hit(doc_id="c3", document="real content here"),
        ]
        mock_retriever = AsyncMock()
        mock_retriever.query = AsyncMock(return_value=hits)

        with (
            patch("app.config.settings") as mock_settings,
            patch.object(svc, "_get_hybrid_retriever", return_value=mock_retriever),
        ):
            mock_settings.hybrid_retrieval_enabled = True
            mock_settings.hybrid_k = 20
            artifacts = await svc._rag_artifacts_async(
                project_id="p1", question="test", n_results=5
            )

        assert len(artifacts) == 1
        assert "real content" in artifacts[0].summary

    @pytest.mark.asyncio
    async def test_hybrid_exception_returns_empty_list(self):
        """Hybrid retriever failure must degrade to [] (vision #5)."""
        vector_store = MagicMock()
        svc = KnowledgeCatalogService(vector_store=vector_store)

        mock_retriever = AsyncMock()
        mock_retriever.query = AsyncMock(side_effect=RuntimeError("chroma down"))

        with (
            patch("app.config.settings") as mock_settings,
            patch.object(svc, "_get_hybrid_retriever", return_value=mock_retriever),
        ):
            mock_settings.hybrid_retrieval_enabled = True
            mock_settings.hybrid_k = 20
            artifacts = await svc._rag_artifacts_async(
                project_id="p1", question="test", n_results=3
            )

        assert artifacts == []


class TestRagArtifactsAsyncHybridDisabled:
    """When hybrid_retrieval_enabled=False, fall back to dense vector_store.query."""

    @pytest.mark.asyncio
    async def test_calls_vector_store_directly_when_hybrid_disabled(self):
        """Dense-only path must use vector_store.query, not HybridRetriever."""
        vector_store = MagicMock()
        vector_store.query = MagicMock(return_value=[_dense_hit()])
        svc = KnowledgeCatalogService(vector_store=vector_store)

        with patch("app.config.settings") as mock_settings:
            mock_settings.hybrid_retrieval_enabled = False
            artifacts = await svc._rag_artifacts_async(
                project_id="p1", question="count users", n_results=3
            )

        vector_store.query.assert_called_once_with("p1", "count users", n_results=3)
        assert len(artifacts) == 1
        assert artifacts[0].type == "rag_chunk"

    @pytest.mark.asyncio
    async def test_artifact_shape_from_dense_result(self):
        """Dense-path artifacts must have the same shape as hybrid-path artifacts."""
        vector_store = MagicMock()
        hit = _dense_hit(
            document="dense knowledge here",
            source_path="docs/guide.md",
            chunk_id="dc1",
        )
        vector_store.query = MagicMock(return_value=[hit])
        svc = KnowledgeCatalogService(vector_store=vector_store)

        with patch("app.config.settings") as mock_settings:
            mock_settings.hybrid_retrieval_enabled = False
            artifacts = await svc._rag_artifacts_async(
                project_id="proj2", question="guide", n_results=3
            )

        assert len(artifacts) == 1
        art = artifacts[0]
        assert art.type == "rag_chunk"
        assert art.id == "rag:proj2::dc1"
        assert art.title == "docs/guide.md"
        assert "dense knowledge" in art.summary
        assert art.provenance["source"] == "rag"
        assert art.payload["file_path"] == "docs/guide.md"


class TestRagArtifactsAsyncNoVectorStore:
    """When vector_store is None, must return []."""

    @pytest.mark.asyncio
    async def test_no_vector_store_returns_empty(self):
        svc = KnowledgeCatalogService(vector_store=None)
        artifacts = await svc._rag_artifacts_async(project_id="p1", question="q", n_results=3)
        assert artifacts == []


# ---------------------------------------------------------------------------
# Integration: get_context_pack uses _rag_artifacts_async
# ---------------------------------------------------------------------------


class TestGetContextPackUsesHybridRag:
    """get_context_pack must call _rag_artifacts_async, not the old sync _rag_artifacts."""

    @pytest.mark.asyncio
    async def test_rag_chunks_populated_from_hybrid_retriever(self):
        """rag_chunks in the assembled ContextPack come from HybridRetriever."""
        vector_store = MagicMock()
        svc = KnowledgeCatalogService(vector_store=vector_store)

        expected_art = Artifact(
            id="rag:p1::c1",
            type="rag_chunk",
            title="docs/foo.md",
            summary="doc content",
            provenance={
                "source": "rag",
                "source_ref": "docs/foo.md",
                "produced_by": "embed_and_store",
                "commit_sha": None,
            },
            freshness={"indexed_at": None},
            confidence=0.5,
            payload={"file_path": "docs/foo.md"},
        )

        with (
            patch("app.services.db_index_service.DbIndexService"),
            patch("app.services.code_db_sync_service.CodeDbSyncService"),
            patch("app.services.agent_learning_service.AgentLearningService"),
            patch("app.core.insight_memory.InsightMemoryService"),
            patch("app.knowledge.custom_rules.CustomRulesEngine"),
            patch.object(svc, "_freshness", new=_clean_freshness()),
            patch.object(
                svc,
                "_rag_artifacts_async",
                new=AsyncMock(return_value=[expected_art]),
            ) as mock_rag,
        ):
            pack = await svc.get_context_pack(
                AsyncMock(),
                project_id="p1",
                connection_id=None,
                question="show doc",
            )

        mock_rag.assert_called_once_with(project_id="p1", question="show doc", n_results=3)
        assert len(pack.rag_chunks) == 1
        assert pack.rag_chunks[0].id == "rag:p1::c1"
        assert "rag" in pack.sources_used

    @pytest.mark.asyncio
    async def test_old_sync_rag_artifacts_no_longer_called_directly(self):
        """The sync _rag_artifacts method must NOT be called by get_context_pack."""
        vector_store = MagicMock()
        vector_store.query = MagicMock(return_value=[])
        svc = KnowledgeCatalogService(vector_store=vector_store)

        with (
            patch("app.services.db_index_service.DbIndexService"),
            patch("app.services.code_db_sync_service.CodeDbSyncService"),
            patch("app.services.agent_learning_service.AgentLearningService"),
            patch("app.core.insight_memory.InsightMemoryService"),
            patch("app.knowledge.custom_rules.CustomRulesEngine"),
            patch.object(svc, "_freshness", new=_clean_freshness()),
            patch.object(svc, "_rag_artifacts", wraps=svc._rag_artifacts) as mock_old_rag,
            patch.object(svc, "_rag_artifacts_async", new=AsyncMock(return_value=[])),
        ):
            await svc.get_context_pack(
                AsyncMock(),
                project_id="p1",
                connection_id=None,
                question="find something",
            )

        mock_old_rag.assert_not_called()
