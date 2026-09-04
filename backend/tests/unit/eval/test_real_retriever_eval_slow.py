"""The same golden set through the REAL embedder (Ш1 · opt-in).

`test_real_retriever_eval.py` runs in CI on every PR in milliseconds, with a real
BM25 leg and a stub dense leg. It cannot see the one layer a stub replaces:
**the embedder**. Two production defects lived exactly there —

* chunks were sized for a 512-token window while the bundled ONNX MiniLM
  truncates at 256, so 28.9% of documents were silently cut;
* `CHROMA_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5` (768-d) was ignored without a
  word, because `sentence-transformers` is not in the image and Chroma fell back
  to 384-d `all-MiniLM-L6-v2`.

Neither is visible to a stub, and neither would be caught by asserting the
config: the whole point is that the configured value and the running one differed.
So this file embeds the fixture corpus with whatever embedder the process actually
has, and measures retrieval through it.

**Opt-in, marked `slow_eval`, deselected by default** and not run in CI. The
operator's call, and the reason is honest rather than convenient: the model is
~90 MB and the backend job already takes 15–16 minutes. What that costs is stated
plainly — an embedder regression reaches `main` and is caught by whoever next runs
`pytest -m slow_eval`, not by the gate. That is a real hole, and naming it is the
difference between a deliberate trade and an accident.

    pytest -m slow_eval tests/unit/eval/test_real_retriever_eval_slow.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.eval import run_eval
from app.knowledge.bm25_index import BM25Index
from app.knowledge.hybrid_retriever import HybridRetriever

from .test_real_retriever_eval import _CORPUS, _PROJECT, _SHA

pytestmark = pytest.mark.slow_eval

chromadb = pytest.importorskip("chromadb", reason="the real embedder needs chromadb")


@pytest.fixture
def real_store(tmp_path: Path, monkeypatch):
    """A real ChromaDB store with the embedder this process actually has.

    `VectorStore.__init__` reads `settings.chroma_persist_dir`, so the directory
    is redirected rather than the client faked — the embedding path under test is
    the production one.
    """
    from app.config import settings
    from app.knowledge.vector_store import VectorStore

    monkeypatch.setattr(settings, "chroma_persist_dir", str(tmp_path / "chroma"), raising=False)
    monkeypatch.setattr(settings, "chroma_server_url", "", raising=False)
    store = VectorStore()
    doc_ids = list(_CORPUS)
    store.add_documents(
        _PROJECT,
        doc_ids,
        [_CORPUS[d] for d in doc_ids],
        [{"source": "fixture"} for _ in doc_ids],
    )
    return store


@pytest.fixture
def real_bm25(tmp_path: Path) -> BM25Index:
    index = BM25Index(tmp_path / "bm25")
    index.build(
        _PROJECT,
        _SHA,
        [(doc_id, text, {"source": "fixture"}) for doc_id, text in _CORPUS.items()],
    )
    return index


class TestTheRealEmbedderRetrieves:
    async def test_the_dense_leg_finds_something_semantically(self, real_store):
        """Before the fused metrics mean anything, the embedder must work at all.

        A query using none of the document's own words: if this returns the right
        document, embeddings are doing the work rather than lexical overlap.
        """
        hits = real_store.query(_PROJECT, "how much money did we give back to buyers", n_results=5)
        ids = [h.get("id") for h in hits]
        assert ids, "the real embedder returned nothing"
        assert {"refunds", "payments", "transactions"} & set(ids), (
            f"semantic retrieval missed every payment document; got {ids}"
        )

    async def test_the_golden_set_clears_the_floors_through_the_real_embedder(
        self, real_bm25, real_store
    ):
        from app.config import settings

        retriever = HybridRetriever(
            bm25=real_bm25,
            vector_store=real_store,
            rrf_k=settings.hybrid_rrf_k,
            min_score=settings.hybrid_min_score,
            max_rank=settings.hybrid_max_rank,
        )

        async def retrieve(question: str) -> list[str]:
            return [r.doc_id for r in await retriever.query(_PROJECT, question, k=10)]

        report = await run_eval(retrieve, k=10)
        assert report.passed, (
            f"retrieval through the REAL embedder regressed: {report.failures} · {report.metrics}"
        )


class TestTheEmbedderIsTheOneWeThinkItIs:
    def test_the_running_dimension_matches_the_declared_one(self, real_store):
        """The 768-d defect in one assertion.

        `CHROMA_EMBEDDING_MODEL` was set to a 768-d model and silently ignored;
        the collection kept embedding at 384. Asserting the config would have
        passed — the config was right and the runtime disagreed with it. So this
        asks the collection what it actually stored.
        """
        from app.core.embedder import EMBEDDING_DIM

        collection = real_store.get_or_create_collection(_PROJECT)
        got = collection.get(ids=[next(iter(_CORPUS))], include=["embeddings"])
        vectors = got.get("embeddings")
        # Chroma returns a numpy array, whose truthiness is ambiguous — `assert
        # vectors` raises rather than failing. Length is the unambiguous check,
        # and this cost one red run to learn.
        assert vectors is not None and len(vectors) > 0, (
            "the collection stored no embedding for a document it holds"
        )
        assert len(vectors[0]) == EMBEDDING_DIM, (
            f"the running embedder produces {len(vectors[0])}-d vectors while "
            f"app.core.embedder declares {EMBEDDING_DIM}. A silent fallback to a "
            "different model is exactly the 2026-08 defect"
        )
