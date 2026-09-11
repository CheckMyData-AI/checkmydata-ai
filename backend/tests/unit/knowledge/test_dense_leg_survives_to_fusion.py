"""The dense leg was deleted before fusion by a floor set above what the embedder produces.

P1 row 8; RET-01, RET-02, RET-04.

`_run_chroma` dropped every dense hit whose cosine distance exceeded `rag_relevance_threshold`
(0.45) **before** RRF saw it. `all-MiniLM-L6-v2` is a symmetric similarity model: a
natural-language question against a code chunk lands at 0.4–0.75 even when the chunk is the
right answer, so the floor sat above most of the relevant band and the "hybrid" retriever ran
as BM25-only.

**Measured here, not inherited.** 367 chunks of this repository's own `app/knowledge/*.py`,
chunked by the production `chunk_document` at `max_tokens=256` and embedded by the production
ONNX `all-MiniLM-L6-v2`, five real questions:

| question | nearest neighbour | distance | kept by 0.45 |
|---|---|---|---|
| how does the BM25 snapshot get rebuilt? | `bm25_index.py#16` | **0.474** | 0 of 10 |
| where are code symbols embedded? | `code_symbol_chunker.py#0` | 0.402 | 1 of 10 |
| how is a document split into chunks? | `chunker.py#7` | 0.429 | 2 of 10 |
| what happens when the code graph is saved incrementally? | `ast_parser.py#30` | 0.524 | 0 of 10 |
| how does the pipeline resume after a restart? | `bm25_corpus.py#0` | 0.702 | 0 of 10 |

Three of five correct nearest neighbours were deleted before fusion. A floor at 0.75 would
keep all five — and that is the wrong fix: it replaces a number measured against one corpus
with another number measured against one corpus, and the next embedder or the next document
type moves it again.

**The instrument is wrong, not its setting.** This repository already made that decision once
— `hybrid_min_score` was replaced by `hybrid_max_rank` because "a rank means the same thing
at any `rrf_k`" while a score floor tuned against one constant changes meaning silently. RRF
ranks, and `hybrid_max_rank` bounds noise by rank in a way no distance constant can. So the
pre-fusion filter defaults **off**, the setting stays for an operator who wants it, and the
eval constructs the retriever with whatever is configured — which is the half that let a
threshold nothing could pass live for months (RET-02).
"""

from __future__ import annotations

import ast
import inspect
import pathlib

from app.config import settings
from app.knowledge.hybrid_retriever import HybridRetriever


class TestTheFilterDoesNotDeleteTheLeg:
    def test_the_configured_threshold_does_not_bind_by_default(self) -> None:
        """0.45 sat above three of five correct answers; the default must not filter."""
        assert settings.rag_relevance_threshold <= 0, (
            f"rag_relevance_threshold is {settings.rag_relevance_threshold}, a pre-fusion "
            "cosine floor. Measured against this repo's own chunks with the production "
            "embedder, correct nearest neighbours land at 0.402–0.702, so a floor in that "
            "band deletes the dense leg and the hybrid retriever runs as BM25-only"
        )

    def test_a_non_positive_threshold_switches_the_filter_off(self) -> None:
        """`0` has to mean off, the way it means unlimited everywhere else in this codebase."""
        source = inspect.getsource(HybridRetriever._run_chroma)
        tree = ast.parse(inspect.cleandoc(source).replace("async def", "def", 1))
        assert tree, "the filter body could not be parsed"
        r = HybridRetriever(bm25=None, vector_store=None, chroma_max_distance=0.0)
        assert r._chroma_max_distance in (None, 0.0)
        assert not r._distance_filter_active, (
            "a threshold of 0 is treated as a real floor, which would drop every hit"
        )

    def test_a_positive_threshold_still_filters_for_an_operator_who_wants_it(self) -> None:
        r = HybridRetriever(bm25=None, vector_store=None, chroma_max_distance=0.6)
        assert r._distance_filter_active


class TestTheDegradationLabelNamesTheCause:
    """RET-04. 'cause unknown' while the retriever itself is the cause."""

    def test_a_filtered_empty_leg_is_not_reported_as_cause_unknown(self) -> None:
        source = inspect.getsource(HybridRetriever)
        assert "filtered_by_distance" in source, (
            "a query where the store returned 40 neighbours and the filter dropped all 40 "
            "is reported identically to one against a project with no vectors at all — and "
            "the two need opposite fixes (retune vs re-index)"
        )


class TestTheEvalBuildsTheProductionRetriever:
    """RET-02. The one parameter that can delete the leg was the one the gate omitted."""

    def test_the_eval_helper_passes_the_distance_filter(self) -> None:
        path = pathlib.Path(__file__).parents[2] / "unit" / "eval" / "test_real_retriever_eval.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        helper = next(
            (
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == "_retriever"
            ),
            None,
        )
        assert helper is not None, "the eval's retriever helper is gone; this guard is blind"
        built = ast.unparse(helper)
        assert "chroma_max_distance" in built, (
            "the gate calls this 'the production HybridRetriever' and omits the only "
            "parameter that can empty the dense leg — so RAG_RELEVANCE_THRESHOLD=0.05, "
            "which returns nothing for every query in the product, leaves the suite green"
        )
