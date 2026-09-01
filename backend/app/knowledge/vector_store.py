import importlib.util
import logging
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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


def _sentence_transformers_available() -> bool:
    """True when the optional ``sentence-transformers`` package is importable.

    Cheap check (``find_spec`` only — no import, no model download). A custom
    ``chroma_embedding_model`` can only be loaded when this is True; otherwise
    ChromaDB's built-in default ONNX model (``all-MiniLM-L6-v2``, 384-dim) is
    used. Never raises — any lookup error is treated as "unavailable".
    """
    try:
        return importlib.util.find_spec("sentence_transformers") is not None
    except Exception:
        return False


def _get_embedding_function() -> EmbeddingFunction | None:
    """Return a custom embedding function if configured & loadable, else None.

    Returning None makes ChromaDB use its bundled default ONNX embedding model
    (``all-MiniLM-L6-v2``, 384-dim), which needs no extra packages. When a
    custom model is configured but ``sentence-transformers`` is not installed
    we log a single concise WARNING (no alarming traceback) and degrade to the
    default — a known, handled condition, not a crash. Genuine unexpected load
    failures keep the diagnostic traceback.

    Also runs a best-effort startup check: if the loaded model's
    ``max_seq_length`` disagrees with ``settings.embedder_max_tokens`` a
    WARNING is logged so operators know a ``queue_embedding_reindex`` run is
    required before search quality is reliable.
    """
    model_name = settings.chroma_embedding_model
    if not model_name:
        return None
    if SentenceTransformerEmbeddingFunction is None or not _sentence_transformers_available():
        logger.warning(
            "Embedding model %s requires the optional 'sentence-transformers' "
            "package, which is not installed; using ChromaDB's built-in default "
            "(all-MiniLM-L6-v2, 384-dim). Install sentence-transformers "
            "(needs ~1GB RAM) to enable %s.",
            model_name,
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


def _parse_chroma_server_url(value: str) -> tuple[str, int, bool]:
    """Split ``CHROMA_SERVER_URL`` into the ``(host, port, ssl)`` HttpClient wants.

    AUD-0819-23. ``chromadb.HttpClient`` takes a HOSTNAME, not a URL, and this
    setting's name invites a URL — the value was passed straight through as
    ``host``, so ``https://chroma.example.com`` became
    ``http://https://chroma.example.com:8000``. Every test mocked ``chromadb``
    wholesale, so the construction was never exercised.

    A bare host keeps the historical ``port=8000, ssl=False`` so an existing
    deployment is not silently repointed. An unparseable value raises rather than
    falling back to localhost: a typo that quietly reads an empty index looks
    exactly like a working deployment with no data.
    """
    # Strip whitespace first, but test for the scheme BEFORE trimming slashes:
    # `rstrip("/")` turns "https://" into "https:", which no longer contains
    # "://" and would then parse as a bare host named "https".
    stripped = (value or "").strip()
    if "://" in stripped:
        parsed = urlparse(stripped.rstrip("/"))
        host = parsed.hostname
        if not host:
            raise ValueError(
                f"CHROMA_SERVER_URL is not a usable address: {value!r}. "
                "Expected e.g. https://chroma.example.com or chroma.internal:8000."
            )
        secure = parsed.scheme == "https"
        return host, parsed.port or (443 if secure else 80), secure
    host, _, port_text = stripped.rstrip("/").partition(":")
    if not host:
        raise ValueError(
            f"CHROMA_SERVER_URL is not a usable address: {value!r}. "
            "Expected e.g. https://chroma.example.com or chroma.internal:8000."
        )
    try:
        port = int(port_text) if port_text else 8000
    except ValueError as exc:
        raise ValueError(f"CHROMA_SERVER_URL has a non-numeric port: {value!r}.") from exc
    return host, port, False


class VectorStore:
    """ChromaDB-backed vector store for RAG retrieval.

    Supports both embedded PersistentClient and remote HttpClient.
    Set ``CHROMA_SERVER_URL`` to use a remote ChromaDB instance.
    Set ``CHROMA_EMBEDDING_MODEL`` to use a custom sentence-transformer model
    (e.g. ``nomic-ai/nomic-embed-text-v1``).
    """

    def __init__(self):
        if settings.chroma_server_url:
            host, port, ssl = _parse_chroma_server_url(settings.chroma_server_url)
            self._client = chromadb.HttpClient(host=host, port=port, ssl=ssl)
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
        if not doc_ids:
            return
        collection = self.get_or_create_collection(project_id)
        # AUD-0819-01: the batch handed to one `upsert` decides peak memory, and
        # the cap lives here rather than at the three call sites because the
        # constraint belongs to the embedder they share. ChromaDB's bundled ONNX
        # MiniLM pads every document to 256 tokens, so the transformer's
        # activations are sized by the batch and by nothing else — measured at
        # 839 MiB for 32, 415 MiB for 8, with the small batch also the faster one.
        # An unbounded batch is what SIGKILLed the production worker (R15,
        # 1053 MiB against a 512 MiB quota) with no run reaching `pipeline_end`.
        step = max(1, settings.embedding_upsert_batch_size)
        for start in range(0, len(doc_ids), step):
            end = start + step
            collection.upsert(
                ids=doc_ids[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end] if metadatas is not None else None,  # type: ignore[arg-type]
            )
        logger.debug(
            "Upserted %d documents to collection %s in batches of %d",
            len(doc_ids),
            project_id,
            step,
        )

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


def resolve_backend(configured: str | None, database_url: str) -> str:
    """Which store this process will use: ``"chroma"`` or ``"pgvector"``.

    Separate from :func:`make_vector_store` because constructing ``PgVectorStore`` opens a
    psycopg pool and registers the vector type against a live server — so the DECISION
    cannot otherwise be checked anywhere Postgres is absent, which includes the whole test
    suite and every development machine.

    ``auto`` is the default and resolves by database: SQLite gets chroma, because the
    migration that creates ``doc_embeddings`` is deliberately a no-op there; anything else
    gets pgvector. Neither literal would serve both — ``pgvector`` breaks a fresh
    ``make setup``, and ``chroma`` leaves a real deployment on a store written to the
    dyno's container filesystem, wiped on every restart and unshared between web and
    worker.

    An explicit value is honoured and an explicit ``pgvector`` on SQLite RAISES rather than
    quietly falling back: ``auto`` is how you ask for whatever fits, so naming a backend is
    a claim about where the vectors are, and a silent downgrade would make that claim false
    without saying so.
    """
    backend = (configured or "").strip().lower() or "auto"
    is_sqlite = database_url.startswith("sqlite")

    # Refused before the database is consulted, so a typo reads as a typo rather than as
    # "pgvector requires PostgreSQL".
    if backend not in {"auto", "chroma", "pgvector"}:
        raise ValueError(
            f"VECTOR_STORE_BACKEND={backend!r} is not a backend; "
            "expected 'auto', 'chroma' or 'pgvector'"
        )
    if backend == "auto":
        return "chroma" if is_sqlite else "pgvector"
    if backend == "pgvector" and is_sqlite:
        raise ValueError(
            "VECTOR_STORE_BACKEND=pgvector requires a PostgreSQL DATABASE_URL; "
            "on SQLite the doc_embeddings migration is a no-op and the table "
            "does not exist"
        )
    return backend


def make_vector_store() -> "VectorStore | Any":
    """Return the configured vector store.

    Both backends expose the same six methods and the same shapes, so nothing
    downstream branches on which one it got. The switch exists because the change is
    a storage move under a live product: `chroma` is what production has always run,
    `pgvector` is what fixes it, and one flag lets the flip be a decision on a
    verified deployment rather than a side effect of a deploy.

    `pgvector` needs Postgres. Development and the test suite run on SQLite, where
    the migration that creates `doc_embeddings` is deliberately a no-op — so asking
    for it there is a configuration error, and it says so instead of failing later on
    a missing table.
    """
    configured = (settings.vector_store_backend or "").strip().lower() or "auto"
    backend = resolve_backend(configured, settings.database_url)
    if configured == "auto":
        # `auto` means the answer is not written anywhere an operator can read, so the
        # boot log is the only place it appears. A store that silently differs between two
        # deployments is what took thirteen days to notice last time.
        logger.info(
            "vector store: %s (auto-resolved from DATABASE_URL; set VECTOR_STORE_BACKEND to pin)",
            backend,
        )
    else:
        logger.info("vector store: %s (pinned by VECTOR_STORE_BACKEND)", backend)

    if backend == "chroma":
        return VectorStore()

    from app.knowledge.pgvector_store import PgVectorStore

    return PgVectorStore()
