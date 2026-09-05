"""Symbol chunks were never deleted, because deletion looked for another key (2.10).

Two metadata keys for one concept. `chunker.py:98` gives a prose chunk
`source_path`; `code_symbol_chunker.py:87-94` gives a symbol chunk `path`, and
`REQUIRED_CHUNK_METADATA_KEYS` does not contain `source_path` at all. Both
`delete_by_source_path` implementations filter on `source_path`.

So a re-index replaced a file's prose chunks and its symbol chunks **accumulated
forever**. The store ends up holding symbols for code that no longer exists, and
dense retrieval returns them: the agent can cite a function deleted months ago.

The fix is in two halves, and both are needed:

* **Rename** the symbol key to `source_path`, so the divergence stops growing.
  Safe because the key is write-only — nothing in `app/` reads chunk metadata's
  `path` (the only `path` reads are `git_agent`'s tool arguments, a different
  thing entirely).
* **Accept the legacy key when deleting.** A rename alone fixes nothing already
  stored: production holds ~25 000 symbol chunks written under `path`, and no
  rebuild can remove them, because removal is what fails to match. This half
  needs no re-index and sweeps them on the next indexing run.

It is also a hard prerequisite for changing the symbol chunk id (board row 2.2's
`sym:` derivation): `force_full` only resets `last_sha`, nothing clears the
collection, and the chunker never deletes — so changing an id while chunks are
unprunable would orphan every existing vector permanently.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_settings():
    with patch("app.knowledge.vector_store.settings") as m:
        m.chroma_server_url = ""
        m.chroma_persist_dir = "/tmp/test_chroma_prune"
        m.chroma_embedding_model = ""
        m.embedding_upsert_batch_size = 8
        yield m


@pytest.fixture
def mock_chromadb(mock_settings):
    with patch("app.knowledge.vector_store.chromadb") as m:
        client = MagicMock()
        m.PersistentClient.return_value = client
        m.HttpClient.return_value = client
        yield m, client


@pytest.fixture
def store(mock_chromadb):
    from app.knowledge.vector_store import VectorStore

    with patch("app.knowledge.vector_store.Path.mkdir"):
        return VectorStore()


class TestChromaDeletionMatchesBothKeys:
    def test_the_where_clause_accepts_the_legacy_key(self, store, mock_chromadb):
        """The half that actually cleans production."""
        _, client = mock_chromadb
        coll = MagicMock()
        client.get_or_create_collection.return_value = coll
        coll.get.return_value = {"ids": ["sym:a.py:X:0"]}

        store.delete_by_source_path("proj", "a.py")

        where = coll.get.call_args.kwargs["where"]
        rendered = json.dumps(where)
        assert "source_path" in rendered, "the current key must still match"
        assert '"path"' in rendered, (
            "chunks already stored carry `path`; without it the existing symbol "
            "chunks stay unreachable and a rename fixes nothing that exists"
        )

    def test_it_still_deletes_what_it_finds(self, store, mock_chromadb):
        _, client = mock_chromadb
        coll = MagicMock()
        client.get_or_create_collection.return_value = coll
        coll.get.return_value = {"ids": ["c1", "c2"]}

        assert store.delete_by_source_path("proj", "a.py") == 2
        coll.delete.assert_called_once_with(ids=["c1", "c2"])

    def test_it_still_returns_zero_on_a_failure(self, store, mock_chromadb):
        """Unchanged: deletion is best-effort and must never break indexing."""
        _, client = mock_chromadb
        coll = MagicMock()
        client.get_or_create_collection.return_value = coll
        coll.get.side_effect = RuntimeError("ChromaDB down")

        assert store.delete_by_source_path("proj", "a.py") == 0


class TestPgvectorDeletionMatchesBothKeys:
    """The other backend. `VECTOR_STORE_BACKEND=auto` resolves to pgvector on
    Postgres, which is every real deployment — so a fix that reached only Chroma
    would fix only development."""

    def test_the_statement_names_both_keys(self):
        import inspect

        from app.knowledge.pgvector_store import PgVectorStore

        sql = inspect.getsource(PgVectorStore.delete_by_source_path)
        assert "'source_path'" in sql
        assert "'path'" in sql, (
            "the legacy key must be matched here too, or production — which runs "
            "pgvector — keeps its orphans"
        )


class TestTheSymbolChunkCarriesTheKeyDeletionUses:
    def test_the_metadata_contract_requires_source_path(self):
        from app.knowledge.chunk_metadata import REQUIRED_CHUNK_METADATA_KEYS

        assert "source_path" in REQUIRED_CHUNK_METADATA_KEYS

    def test_a_built_chunk_carries_it(self):
        from app.knowledge.chunk_metadata import CodeChunkMetadata

        meta = CodeChunkMetadata(
            source_path="app/foo.py",
            symbol="do_thing",
            language="python",
            start_line=1,
            end_line=9,
            kind="function",
        ).to_dict()
        assert meta["source_path"] == "app/foo.py"

    def test_validation_refuses_a_chunk_without_it(self):
        from app.knowledge.chunk_metadata import validate_chunk_metadata

        with pytest.raises(ValueError, match="source_path"):
            validate_chunk_metadata(
                {
                    "symbol": "y",
                    "language": "python",
                    "start_line": 1,
                    "end_line": 2,
                    "kind": "function",
                }
            )
