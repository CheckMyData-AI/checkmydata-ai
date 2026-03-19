import logging
from pathlib import Path

import chromadb
from chromadb.api.types import EmbeddingFunction

from app.config import settings

logger = logging.getLogger(__name__)


def _get_embedding_function() -> EmbeddingFunction | None:
    """Return a custom embedding function if configured, else None (ChromaDB default)."""
    model_name = settings.chroma_embedding_model
    if not model_name:
        return None
    try:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

        logger.info("ChromaDB: using custom embedding model %s", model_name)
        return SentenceTransformerEmbeddingFunction(model_name=model_name)
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

    def _collection_name(self, project_id: str) -> str:
        safe = project_id.replace("-", "_")[:50]
        return f"project_{safe}"

    def get_or_create_collection(self, project_id: str) -> chromadb.Collection:
        kwargs: dict = {
            "name": self._collection_name(project_id),
            "metadata": {"hnsw:space": "cosine"},
        }
        if self._embedding_fn is not None:
            kwargs["embedding_function"] = self._embedding_fn
        return self._client.get_or_create_collection(**kwargs)

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
        try:
            self._client.delete_collection(self._collection_name(project_id))
        except Exception:
            logger.warning("Failed to delete collection for project %s", project_id, exc_info=True)
