import logging
import threading
from pathlib import Path

import chromadb
from chromadb.api.types import EmbeddingFunction

from app.config import settings

logger = logging.getLogger(__name__)

try:
    from chromadb.utils.embedding_functions import (
        SentenceTransformerEmbeddingFunction,
    )
except Exception:  # pragma: no cover
    SentenceTransformerEmbeddingFunction = None  # type: ignore[assignment,misc]


def _check_window_mismatch(ef: object, configured_max: int, model_name: str) -> None:
    """Emit a WARNING when the loaded model's ``max_seq_length`` differs from
    ``settings.embedder_max_tokens``.

    This is a best-effort check: if the attribute is missing (model didn't
    expose it) or any other error occurs the check is silently skipped so the
    startup path is never disrupted.
    """
    try:
        model_max = ef._model.max_seq_length  # type: ignore[attr-defined]
        if model_max != configured_max:
            logger.warning(
                "Embedding window mismatch: model '%s' max_seq_length=%d but "
                "embedder_max_tokens=%d. Existing ChromaDB collections hold "
                "stale/truncated vectors. Run queue_embedding_reindex() to "
                "drop and re-embed all project collections before serving queries.",
                model_name,
                model_max,
                configured_max,
            )
    except Exception:
        # Attribute absent or any other error — skip silently.
        pass


def _get_embedding_function() -> EmbeddingFunction | None:
    """Return a custom embedding function if configured, else None (ChromaDB default).

    Also runs a best-effort startup check: if the loaded model's
    ``max_seq_length`` disagrees with ``settings.embedder_max_tokens`` a
    WARNING is logged so operators know a ``queue_embedding_reindex`` run is
    required before search quality is reliable.
    """
    model_name = settings.chroma_embedding_model
    if not model_name:
        return None
    if SentenceTransformerEmbeddingFunction is None:
        logger.warning(
            "Failed to load embedding model %s, falling back to default",
            model_name,
        )
        return None
    try:
        logger.info("ChromaDB: using custom embedding model %s", model_name)
        ef = SentenceTransformerEmbeddingFunction(model_name=model_name)
        _check_window_mismatch(ef, settings.embedder_max_tokens, model_name)
        return ef
    except Exception:
        logger.warning(
            "Failed to load embedding model %s, falling back to default",
            model_name,
            exc_info=True,
        )
        return None


class VectorStore:
    """ChromaDB-backed vector store for RAG retrieval.

    Supports both embedded PersistentClient and remote HttpClient.
    Set ``CHROMA_SERVER_URL`` to use a remote ChromaDB instance.
    Set ``CHROMA_EMBEDDING_MODEL`` to use a custom sentence-transformer model
    (e.g. ``nomic-ai/nomic-embed-text-v1``).
    """

    def __init__(self):
        if settings.chroma_server_url:
            self._client = chromadb.HttpClient(
                host=settings.chroma_server_url,
            )
            logger.debug("ChromaDB: using remote server at %s", settings.chroma_server_url)
        else:
            persist_dir = Path(settings.chroma_persist_dir)
            persist_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(persist_dir))
            logger.debug("ChromaDB: using local PersistentClient at %s", persist_dir)

        self._embedding_fn = _get_embedding_function()
        self._collections: dict[str, chromadb.Collection] = {}
        self._lock = threading.Lock()

    def _collection_name(self, project_id: str) -> str:
        safe = project_id.replace("-", "_")[:50]
        return f"project_{safe}"

    def get_or_create_collection(self, project_id: str) -> chromadb.Collection:
        with self._lock:
            cached = self._collections.get(project_id)
            if cached is not None:
                return cached
            kwargs: dict = {
                "name": self._collection_name(project_id),
                "metadata": {"hnsw:space": "cosine"},
            }
            if self._embedding_fn is not None:
                kwargs["embedding_function"] = self._embedding_fn
            coll = self._client.get_or_create_collection(**kwargs)
            self._collections[project_id] = coll
            return coll

    def add_documents(
        self,
        project_id: str,
        doc_ids: list[str],
        documents: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        collection = self.get_or_create_collection(project_id)
        collection.upsert(
            ids=doc_ids,
            documents=documents,
            metadatas=metadatas,  # type: ignore[arg-type]
        )
        logger.debug("Upserted %d documents to collection %s", len(doc_ids), project_id)

    def query(
        self,
        project_id: str,
        query_text: str,
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        collection = self.get_or_create_collection(project_id)
        kwargs: dict = {
            "query_texts": [query_text],
            "n_results": n_results,
        }
        if where:
            kwargs["where"] = where

        results = collection.query(**kwargs)

        docs = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                entry = {
                    "id": results["ids"][0][i] if results["ids"] else None,
                    "document": doc,
                    "distance": results["distances"][0][i] if results.get("distances") else None,  # type: ignore[index]
                }
                if results.get("metadatas") and results["metadatas"][0]:  # type: ignore[index]
                    entry["metadata"] = results["metadatas"][0][i]  # type: ignore[index]
                docs.append(entry)

        return docs

    def delete_by_source_path(
        self,
        project_id: str,
        source_path: str,
    ) -> int:
        """Delete all chunks whose metadata.source_path matches *source_path*.

        Returns the number of IDs removed (0 if collection doesn't exist yet).
        """
        try:
            collection = self.get_or_create_collection(project_id)
            existing = collection.get(
                where={"source_path": source_path},
                include=[],
            )
            ids_to_delete = existing["ids"]
            if ids_to_delete:
                collection.delete(ids=ids_to_delete)
                logger.debug(
                    "Deleted %d stale chunks for source_path=%s in project %s",
                    len(ids_to_delete),
                    source_path,
                    project_id,
                )
            return len(ids_to_delete)
        except Exception:
            logger.warning(
                "Failed to delete chunks for source_path=%s in project %s",
                source_path,
                project_id,
                exc_info=True,
            )
            return 0

    def delete_collection(self, project_id: str) -> None:
        with self._lock:
            self._collections.pop(project_id, None)
        try:
            self._client.delete_collection(self._collection_name(project_id))
        except Exception:
            logger.warning("Failed to delete collection for project %s", project_id, exc_info=True)

    def close(self) -> None:
        """Release ChromaDB resources on shutdown."""
        with self._lock:
            self._collections.clear()
        if hasattr(self._client, "_identifier_to_system"):
            for system in self._client._identifier_to_system.values():
                system.stop()
        elif hasattr(self._client, "close"):
            self._client.close()
        logger.info("VectorStore closed")
