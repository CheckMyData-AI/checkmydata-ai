from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.knowledge.vector_store import VectorStore, _get_embedding_function


@pytest.fixture
def mock_settings():
    with patch("app.knowledge.vector_store.settings") as m:
        m.chroma_server_url = ""
        m.chroma_persist_dir = "/tmp/test_chroma"
        m.chroma_embedding_model = ""
        yield m


@pytest.fixture
def mock_chromadb(mock_settings):
    with patch("app.knowledge.vector_store.chromadb") as m:
        mock_client = MagicMock()
        m.PersistentClient.return_value = mock_client
        m.HttpClient.return_value = mock_client
        yield m, mock_client


@pytest.fixture
def store(mock_chromadb):
    with patch("app.knowledge.vector_store.Path.mkdir"):
        return VectorStore()


class TestInit:
    def test_uses_persistent_client_when_no_server_url(self, mock_settings, mock_chromadb):
        mock_settings.chroma_server_url = ""
        chroma_mod, _ = mock_chromadb
        with patch("app.knowledge.vector_store.Path.mkdir"):
            VectorStore()
        chroma_mod.PersistentClient.assert_called_once()

    def test_uses_http_client_when_server_url_set(self, mock_settings, mock_chromadb):
        mock_settings.chroma_server_url = "http://chroma:8000"
        chroma_mod, _ = mock_chromadb
        VectorStore()
        chroma_mod.HttpClient.assert_called_once_with(host="http://chroma:8000")


class TestCollectionName:
    def test_replaces_hyphens(self, store):
        assert store._collection_name("abc-def") == "project_abc_def"

    def test_truncates_long_id(self, store):
        long_id = "a" * 100
        name = store._collection_name(long_id)
        assert name.startswith("project_")
        assert len(name) <= len("project_") + 50


class TestGetOrCreateCollection:
    def test_creates_collection(self, store, mock_chromadb):
        _, client = mock_chromadb
        mock_coll = MagicMock()
        client.get_or_create_collection.return_value = mock_coll

        result = store.get_or_create_collection("proj1")
        assert result is mock_coll
        client.get_or_create_collection.assert_called_once()

    def test_caches_collection(self, store, mock_chromadb):
        _, client = mock_chromadb
        mock_coll = MagicMock()
        client.get_or_create_collection.return_value = mock_coll

        store.get_or_create_collection("proj1")
        store.get_or_create_collection("proj1")
        client.get_or_create_collection.assert_called_once()

    def test_passes_embedding_function_when_set(self, mock_chromadb):
        _, client = mock_chromadb
        mock_coll = MagicMock()
        client.get_or_create_collection.return_value = mock_coll

        with patch("app.knowledge.vector_store.Path.mkdir"):
            vs = VectorStore()
        mock_fn = MagicMock()
        vs._embedding_fn = mock_fn

        vs.get_or_create_collection("proj2")
        call_kwargs = client.get_or_create_collection.call_args[1]
        assert call_kwargs["embedding_function"] is mock_fn


class TestAddDocuments:
    def test_upserts_to_collection(self, store, mock_chromadb):
        _, client = mock_chromadb
        mock_coll = MagicMock()
        client.get_or_create_collection.return_value = mock_coll

        store.add_documents(
            project_id="p1",
            doc_ids=["d1", "d2"],
            documents=["doc1", "doc2"],
            metadatas=[{"k": "v1"}, {"k": "v2"}],
        )
        mock_coll.upsert.assert_called_once_with(
            ids=["d1", "d2"],
            documents=["doc1", "doc2"],
            metadatas=[{"k": "v1"}, {"k": "v2"}],
        )

    def test_upserts_without_metadatas(self, store, mock_chromadb):
        _, client = mock_chromadb
        mock_coll = MagicMock()
        client.get_or_create_collection.return_value = mock_coll

        store.add_documents(
            project_id="p1",
            doc_ids=["d1"],
            documents=["doc1"],
        )
        mock_coll.upsert.assert_called_once_with(
            ids=["d1"],
            documents=["doc1"],
            metadatas=None,
        )


class TestQuery:
    def test_returns_parsed_results(self, store, mock_chromadb):
        _, client = mock_chromadb
        mock_coll = MagicMock()
        client.get_or_create_collection.return_value = mock_coll
        mock_coll.query.return_value = {
            "ids": [["id1", "id2"]],
            "documents": [["doc1", "doc2"]],
            "distances": [[0.1, 0.5]],
            "metadatas": [[{"src": "a"}, {"src": "b"}]],
        }

        results = store.query("proj", "search term", n_results=2)
        assert len(results) == 2
        assert results[0]["id"] == "id1"
        assert results[0]["document"] == "doc1"
        assert results[0]["distance"] == 0.1
        assert results[0]["metadata"] == {"src": "a"}

    def test_returns_empty_list_when_no_results(self, store, mock_chromadb):
        _, client = mock_chromadb
        mock_coll = MagicMock()
        client.get_or_create_collection.return_value = mock_coll
        mock_coll.query.return_value = {
            "ids": [[]],
            "documents": [[]],
            "distances": [[]],
            "metadatas": [[]],
        }

        results = store.query("proj", "nothing")
        assert results == []

    def test_passes_where_filter(self, store, mock_chromadb):
        _, client = mock_chromadb
        mock_coll = MagicMock()
        client.get_or_create_collection.return_value = mock_coll
        mock_coll.query.return_value = {
            "ids": [[]],
            "documents": [[]],
        }

        store.query("proj", "q", where={"type": "sql"})
        call_kwargs = mock_coll.query.call_args[1]
        assert call_kwargs["where"] == {"type": "sql"}

    def test_handles_no_distances(self, store, mock_chromadb):
        _, client = mock_chromadb
        mock_coll = MagicMock()
        client.get_or_create_collection.return_value = mock_coll
        mock_coll.query.return_value = {
            "ids": [["id1"]],
            "documents": [["doc1"]],
        }

        results = store.query("proj", "q")
        assert results[0]["distance"] is None


class TestDeleteBySourcePath:
    def test_deletes_matching_ids(self, store, mock_chromadb):
        _, client = mock_chromadb
        mock_coll = MagicMock()
        client.get_or_create_collection.return_value = mock_coll
        mock_coll.get.return_value = {"ids": ["c1", "c2"]}

        count = store.delete_by_source_path("proj", "path/to/file.py")
        assert count == 2
        mock_coll.delete.assert_called_once_with(ids=["c1", "c2"])

    def test_returns_zero_when_no_matches(self, store, mock_chromadb):
        _, client = mock_chromadb
        mock_coll = MagicMock()
        client.get_or_create_collection.return_value = mock_coll
        mock_coll.get.return_value = {"ids": []}

        count = store.delete_by_source_path("proj", "nofile")
        assert count == 0
        mock_coll.delete.assert_not_called()

    def test_returns_zero_on_exception(self, store, mock_chromadb):
        _, client = mock_chromadb
        mock_coll = MagicMock()
        client.get_or_create_collection.return_value = mock_coll
        mock_coll.get.side_effect = RuntimeError("ChromaDB down")

        count = store.delete_by_source_path("proj", "file.py")
        assert count == 0


class TestDeleteCollection:
    def test_deletes_and_clears_cache(self, store, mock_chromadb):
        _, client = mock_chromadb
        mock_coll = MagicMock()
        client.get_or_create_collection.return_value = mock_coll

        store.get_or_create_collection("proj1")
        assert "proj1" in store._collections

        store.delete_collection("proj1")
        assert "proj1" not in store._collections
        client.delete_collection.assert_called_once()

    def test_handles_delete_error_gracefully(self, store, mock_chromadb):
        _, client = mock_chromadb
        client.delete_collection.side_effect = RuntimeError("fail")
        store.delete_collection("proj_x")


class TestGetEmbeddingFunction:
    def test_returns_none_when_no_model(self):
        with patch("app.knowledge.vector_store.settings") as m:
            m.chroma_embedding_model = ""
            result = _get_embedding_function()
        assert result is None

    def test_returns_embedding_fn_when_model_set(self):
        with (
            patch("app.knowledge.vector_store.settings") as m,
            patch(
                "app.knowledge.vector_store."
                "chromadb.utils.embedding_functions."
                "SentenceTransformerEmbeddingFunction",
                create=True,
            ) as mock_cls,
        ):
            m.chroma_embedding_model = "model-v1"
            mock_fn = MagicMock()
            mock_cls.return_value = mock_fn

            with patch.dict(
                "sys.modules",
                {
                    "chromadb.utils.embedding_functions": MagicMock(
                        SentenceTransformerEmbeddingFunction=mock_cls
                    )
                },
            ):
                result = _get_embedding_function()
        assert result is mock_fn

    def test_falls_back_on_import_error(self):
        with patch("app.knowledge.vector_store.settings") as m:
            m.chroma_embedding_model = "bad-model"
            with patch.dict("sys.modules", {"chromadb.utils.embedding_functions": None}):
                result = _get_embedding_function()
        assert result is None
