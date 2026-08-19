"""AUD-0819-01: the upsert batch is capped where the embedder lives.

The production worker was SIGKILLed at `code_symbol_embed` — R15, 1053 MiB
against a 512 MiB quota — and `grep -c pipeline_end` over a two-hour window of
logs returned 0, so no repository index ever completed.

The driver was measured, not guessed. `state.parsed_files` at production scale
(8541 files / 25192 symbols) retains only ~24 MiB, and the worker's whole import
baseline including chromadb and the tree-sitter grammars is ~106 MiB. The jump
happens on the FIRST upsert and then stays flat, because ChromaDB's bundled ONNX
MiniLM pads every document to 256 tokens and the transformer's intermediate
activations are sized by the batch:

    batch=200 -> peak 967.1 MiB,  9.27 s   (the old behaviour)
    batch=8   -> peak 414.5 MiB, 10.86 s   (the new default)

Measured through `VectorStore.add_documents`, 960 chunks, base RSS 290 MiB: ~552
MiB saved for about 17% more wall clock, which is the difference between
finishing and being killed. The cap belongs to the
vector store rather than to each caller: there are three call sites (the symbol
chunker plus the prose and repair paths in `pipeline_runner`) and the constraint
is a property of the embedder they share.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.knowledge.vector_store import VectorStore


def _store_with_fake_collection(collection: MagicMock) -> VectorStore:
    vs = VectorStore.__new__(VectorStore)  # bypass client construction
    vs.get_or_create_collection = lambda _pid: collection  # type: ignore[method-assign]
    return vs


class TestUpsertBatching:
    def test_a_large_call_is_split_into_capped_upserts(self):
        coll = MagicMock()
        vs = _store_with_fake_collection(coll)
        n = 25
        with patch("app.knowledge.vector_store.settings") as s:
            s.embedding_upsert_batch_size = 8
            vs.add_documents(
                project_id="p1",
                doc_ids=[f"d{i}" for i in range(n)],
                documents=[f"body {i}" for i in range(n)],
                metadatas=[{"i": str(i)} for i in range(n)],
            )
        sizes = [len(c.kwargs["ids"]) for c in coll.upsert.call_args_list]
        assert sizes == [8, 8, 8, 1], f"batch not capped at 8: {sizes}"

    def test_every_document_arrives_exactly_once_and_in_order(self):
        coll = MagicMock()
        vs = _store_with_fake_collection(coll)
        n = 20
        with patch("app.knowledge.vector_store.settings") as s:
            s.embedding_upsert_batch_size = 6
            vs.add_documents(
                project_id="p1",
                doc_ids=[f"d{i}" for i in range(n)],
                documents=[f"body {i}" for i in range(n)],
                metadatas=[{"i": str(i)} for i in range(n)],
            )
        ids, docs, metas = [], [], []
        for c in coll.upsert.call_args_list:
            ids += list(c.kwargs["ids"])
            docs += list(c.kwargs["documents"])
            metas += list(c.kwargs["metadatas"])
        assert ids == [f"d{i}" for i in range(n)]
        assert docs == [f"body {i}" for i in range(n)]
        # The slices must stay aligned — a shifted metadata list would attach the
        # wrong file path to a chunk, which no test of counts alone would catch.
        assert metas == [{"i": str(i)} for i in range(n)]

    def test_metadatas_none_is_carried_through_per_batch(self):
        coll = MagicMock()
        vs = _store_with_fake_collection(coll)
        with patch("app.knowledge.vector_store.settings") as s:
            s.embedding_upsert_batch_size = 4
            vs.add_documents(
                project_id="p1",
                doc_ids=[f"d{i}" for i in range(9)],
                documents=[f"b{i}" for i in range(9)],
                metadatas=None,
            )
        assert [len(c.kwargs["ids"]) for c in coll.upsert.call_args_list] == [4, 4, 1]
        assert all(c.kwargs["metadatas"] is None for c in coll.upsert.call_args_list)

    def test_an_empty_call_touches_the_collection_not_at_all(self):
        coll = MagicMock()
        vs = _store_with_fake_collection(coll)
        with patch("app.knowledge.vector_store.settings") as s:
            s.embedding_upsert_batch_size = 8
            vs.add_documents(project_id="p1", doc_ids=[], documents=[], metadatas=[])
        coll.upsert.assert_not_called()

    def test_a_batch_at_the_cap_is_one_call(self):
        coll = MagicMock()
        vs = _store_with_fake_collection(coll)
        with patch("app.knowledge.vector_store.settings") as s:
            s.embedding_upsert_batch_size = 8
            vs.add_documents(
                project_id="p1",
                doc_ids=[f"d{i}" for i in range(8)],
                documents=[f"b{i}" for i in range(8)],
                metadatas=[{} for _ in range(8)],
            )
        assert coll.upsert.call_count == 1
