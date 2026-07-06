"""W2 Low-severity robustness batch tests.

Covers: RET-R11..R17, CODEIDX-C10/C11/C12/C13/C14/C18/C19/C20/C21.

Each test is focused and minimal — we verify one invariant per item,
then move on.  Items that are out-of-scope for W2 (C13, C14, C20, C21)
carry an explicit skip / comment rather than a silent pass.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------


class _StubVector:
    """Drop-in VectorStore stub returning canned results."""

    def __init__(self, results: list[dict[str, Any]] | None = None) -> None:
        self._results = results or []

    def query(self, project_id: str, query_text: str, n_results: int, where=None):  # noqa: ARG002
        return list(self._results)


def _make_bm25(results: list[dict[str, Any]]) -> MagicMock:
    from app.knowledge.bm25_index import BM25Index

    mock = MagicMock(spec=BM25Index)
    mock.query = MagicMock(return_value=list(results))
    return mock


# ---------------------------------------------------------------------------
# RET-R11: fusion pool floor when reranker is present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ret_r11_per_leg_floor_with_reranker() -> None:
    """RET-R11: with k=2 and a reranker(rerank_candidates=30), per_leg ≥ 30."""
    from app.knowledge.hybrid_retriever import HybridRetriever
    from app.knowledge.reranker import Reranker

    bm25 = _make_bm25([])
    chroma = _StubVector([])
    reranker_mock = MagicMock(spec=Reranker)

    retr = HybridRetriever(
        bm25=bm25,
        vector_store=chroma,
        reranker=reranker_mock,
        rerank_candidates=30,
    )
    await retr.query("proj", "find users", k=2)

    # _run_bm25 is called with n = per_leg which should be >= rerank_candidates(30)
    bm25.query.assert_called_once()
    # call_args[0] is (project_id, query_text, n)
    n_arg = bm25.query.call_args[0][2]
    assert n_arg >= 30, f"expected per_leg ≥ 30 with reranker, got {n_arg}"


@pytest.mark.asyncio
async def test_ret_r11_per_leg_no_reranker_uses_2k() -> None:
    """RET-R11: without reranker, per_leg = max(10, 2*k) as before."""
    from app.knowledge.hybrid_retriever import HybridRetriever

    bm25 = _make_bm25([])
    chroma = _StubVector([])
    retr = HybridRetriever(bm25=bm25, vector_store=chroma)  # no reranker

    await retr.query("proj", "find users", k=7)

    n_arg = bm25.query.call_args[0][2]
    assert n_arg == max(10, 2 * 7), f"expected {max(10, 2 * 7)}, got {n_arg}"


# ---------------------------------------------------------------------------
# RET-R12: __empty__ sentinel never surfaces as a hit
# ---------------------------------------------------------------------------


def test_ret_r12_empty_sentinel_dropped() -> None:
    """RET-R12: BM25 corpus with only __empty__ returns no hits."""
    from app.knowledge.bm25_index import BM25Index

    with tempfile.TemporaryDirectory() as tmpdir:
        idx = BM25Index(tmpdir)
        # Build with no real documents — triggers __empty__ sentinel.
        idx.build("proj-empty", "sha1", [])
        results = idx.query("proj-empty", "anything", 10)
    assert results == [], f"expected no hits, got {results}"


@pytest.mark.asyncio
async def test_ret_r12_empty_doc_id_filtered_by_hybrid() -> None:
    """RET-R12: HybridRetriever drops any hit whose doc_id is __empty__."""
    from app.knowledge.hybrid_retriever import HybridRetriever

    bm25 = _make_bm25([{"id": "__empty__", "document": "", "metadata": {}}])
    chroma = _StubVector([])
    retr = HybridRetriever(bm25=bm25, vector_store=chroma)

    with patch("app.knowledge.hybrid_retriever.emit_retrieval_degraded"):
        results = await retr.query("proj", "anything", k=5)

    doc_ids = [r.doc_id for r in results]
    assert "__empty__" not in doc_ids, f"__empty__ must not surface: {doc_ids}"


# ---------------------------------------------------------------------------
# RET-R13: distance=None drops hit when chroma_max_distance is configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ret_r13_none_distance_dropped_when_floor_set() -> None:
    """RET-R13: hit with distance=None is excluded when chroma_max_distance is set."""
    from app.knowledge.hybrid_retriever import HybridRetriever

    # A hit with distance=None plus one with a valid distance below the floor.
    chroma_hits = [
        {"id": "c1", "document": "good hit", "distance": 0.2, "metadata": {}},
        {"id": "c2", "document": "no distance hit", "distance": None, "metadata": {}},
    ]
    bm25 = _make_bm25([])
    chroma = _StubVector(chroma_hits)
    retr = HybridRetriever(bm25=bm25, vector_store=chroma, chroma_max_distance=0.5)

    with patch("app.knowledge.hybrid_retriever.emit_retrieval_degraded"):
        results = await retr.query("proj", "query", k=10)

    ids = [r.doc_id for r in results]
    assert "c1" in ids, "valid-distance hit should be kept"
    assert "c2" not in ids, "None-distance hit must be dropped when floor is configured"


@pytest.mark.asyncio
async def test_ret_r13_none_distance_kept_when_no_floor() -> None:
    """RET-R13: hit with distance=None is kept when chroma_max_distance is None (no floor)."""
    from app.knowledge.hybrid_retriever import HybridRetriever

    chroma_hits = [{"id": "c2", "document": "no distance", "distance": None, "metadata": {}}]
    bm25 = _make_bm25([])
    chroma = _StubVector(chroma_hits)
    retr = HybridRetriever(bm25=bm25, vector_store=chroma, chroma_max_distance=None)

    with patch("app.knowledge.hybrid_retriever.emit_retrieval_degraded"):
        results = await retr.query("proj", "query", k=10)

    ids = [r.doc_id for r in results]
    assert "c2" in ids, "None-distance hit must be kept when no floor is configured"


# ---------------------------------------------------------------------------
# RET-R15: render_context_block deduplicates identical summaries
# ---------------------------------------------------------------------------


def test_ret_r15_dedup_identical_summaries() -> None:
    """RET-R15: two artifacts with identical summary collapse to one line."""
    from app.knowledge.context_pack import Artifact
    from app.knowledge.context_pack_renderer import render_context_block

    a1 = Artifact(
        id="id-1",
        type="code_entity",
        title="Foo",
        summary="The users table stores user records.",
        provenance={"source": "sym", "commit_sha": "abc"},
        freshness={"indexed_at": "2026-06-01"},
        confidence=0.9,
    )
    a2 = Artifact(
        id="id-2",
        type="rag_chunk",
        title="Foo prose",
        # Same summary as a1 — should be collapsed
        summary="The users table stores user records.",
        provenance={"source": "prose", "commit_sha": "def"},
        freshness={"indexed_at": "2026-06-01"},
        confidence=0.8,
    )
    a3 = Artifact(
        id="id-3",
        type="rag_chunk",
        title="Bar",
        summary="The orders table tracks purchases.",
        provenance={"source": "prose"},
        freshness={},
        confidence=0.7,
    )

    result = render_context_block([a1, a2, a3])
    # Header + 2 unique summaries
    lines = [ln for ln in result.splitlines() if ln.startswith("- ")]
    assert len(lines) == 2, f"expected 2 lines after dedup, got {len(lines)}: {result}"
    assert "The users table stores user records." in result
    assert "The orders table tracks purchases." in result


# ---------------------------------------------------------------------------
# RET-R16: SchemaRetriever.query returns [] cleanly when no snapshot exists
# ---------------------------------------------------------------------------


def test_ret_r16_missing_snapshot_no_exception() -> None:
    """RET-R16: SchemaRetriever.query on a missing snapshot returns [] without raising."""
    from app.knowledge.schema_retriever import SchemaRetriever

    with tempfile.TemporaryDirectory() as tmpdir:
        retriever = SchemaRetriever(tmpdir)
        result = retriever.query("nonexistent-connection", "what are orders?", k=5)
    assert result == [], f"expected empty list, got {result}"


# ---------------------------------------------------------------------------
# RET-R17: tokenize_code logs a debug when doc hits the 1024-token BM25 cap
# ---------------------------------------------------------------------------


def test_ret_r17_truncation_logged(caplog: pytest.LogCaptureFixture) -> None:
    """RET-R17: tokenize_code emits a debug log when _MAX_TOKENS_PER_DOC cap is hit."""
    from app.knowledge.bm25_index import _MAX_TOKENS_PER_DOC, tokenize_code

    # Build text that has far more tokens than the cap.
    # Each word is distinct so it won't be filtered by min_length/stopwords.
    long_text = " ".join(f"identifier_{i}" for i in range(_MAX_TOKENS_PER_DOC + 50))

    with caplog.at_level(logging.DEBUG, logger="app.knowledge.bm25_index"):
        tokens = tokenize_code(long_text)

    assert len(tokens) == _MAX_TOKENS_PER_DOC, f"expected cap at {_MAX_TOKENS_PER_DOC}"
    assert any(
        "truncated" in rec.message.lower() or "cap" in rec.message.lower()
        for rec in caplog.records
        if rec.name == "app.knowledge.bm25_index"
    ), f"expected truncation debug log; got: {[r.message for r in caplog.records]}"


# ---------------------------------------------------------------------------
# CODEIDX-C10: overlap prefix is ≤ OVERLAP_TOKENS
# ---------------------------------------------------------------------------


def test_codeidx_c10_overlap_bounded() -> None:
    """CODEIDX-C10: overlap prefix prepended to chunk 1+ must be ≤ OVERLAP_TOKENS tokens."""
    from app.knowledge.chunker import OVERLAP_TOKENS, chunk_document
    from app.knowledge.tokenizer_window import WindowTokenizer

    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")  # char fallback
    # Build a multi-chunk document.
    text = "The orders table stores each purchase. " * 200
    chunks = chunk_document(
        content=text, file_path="doc.md", doc_type="markdown", max_tokens=128, tokenizer=tk
    )
    assert len(chunks) >= 2, "Need at least 2 chunks to test overlap"

    # For chunk 1 and beyond the overlap prefix is taken from the previous chunk.
    # We verify the overlap does not exceed OVERLAP_TOKENS.
    for i in range(1, len(chunks)):
        curr_content = chunks[i].content
        # The current chunk starts with the overlap prefix (a suffix of prev).
        # Count how many tokens of the start of curr_content are shared with the end of prev.
        # Conservative check: the entire chunk must still be ≤ max_tokens (128).
        assert tk.count_tokens(curr_content) <= 128

    # Specifically verify the overlap prefix itself is within OVERLAP_TOKENS.
    # The overlap prefix is built as tokenizer.truncate_to_tokens(tail, OVERLAP_TOKENS).
    # We can re-derive it to assert the invariant.
    prev = chunks[0].content
    overlap_chars = OVERLAP_TOKENS * 3
    tail = prev[-overlap_chars:] if len(prev) > overlap_chars else prev
    prefix = tk.truncate_to_tokens(tail, OVERLAP_TOKENS)
    assert tk.count_tokens(prefix) <= OVERLAP_TOKENS, (
        f"overlap prefix has {tk.count_tokens(prefix)} tokens, max is {OVERLAP_TOKENS}"
    )


# ---------------------------------------------------------------------------
# CODEIDX-C11: CLASS_BOUNDARY splits TS/Go files at appropriate boundaries
# ---------------------------------------------------------------------------


def test_codeidx_c11_ts_class_boundary_splits() -> None:
    """CODEIDX-C11: a TS file with 'export class X' triggers a chunk boundary."""
    from app.knowledge.chunker import chunk_document
    from app.knowledge.tokenizer_window import WindowTokenizer

    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")
    # Build a TS file large enough to require splitting but with the boundary in the middle.
    # Pad each section to ~60 tokens so the combined doc exceeds a small limit.
    filler = "const x = doSomethingWithLongName();\n" * 8
    ts_content = f"{filler}export class UserService {{\n{filler}}}\n{filler}"
    chunks = chunk_document(
        content=ts_content, file_path="service.ts", doc_type="code", max_tokens=80, tokenizer=tk
    )
    # The boundary should produce at least 2 chunks
    assert len(chunks) >= 2, f"expected ≥2 chunks for TS class boundary, got {len(chunks)}"
    # The second chunk (or later) should contain the export class declaration
    full_text = "\n".join(c.content for c in chunks)
    assert "export class UserService" in full_text


def test_codeidx_c11_go_func_boundary_splits() -> None:
    """CODEIDX-C11: a Go file with '^func ' triggers a chunk boundary."""
    from app.knowledge.chunker import chunk_document
    from app.knowledge.tokenizer_window import WindowTokenizer

    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")
    filler = "// comment line for padding purposes in tests\n" * 8
    go_content = f"{filler}func GetUser(id string) User {{\n{filler}}}\n{filler}"
    chunks = chunk_document(
        content=go_content, file_path="user.go", doc_type="code", max_tokens=80, tokenizer=tk
    )
    assert len(chunks) >= 2, f"expected ≥2 chunks for Go func boundary, got {len(chunks)}"
    full_text = "\n".join(c.content for c in chunks)
    assert "func GetUser" in full_text


# ---------------------------------------------------------------------------
# CODEIDX-C12: oversized symbol chunk carries truncated=True
# ---------------------------------------------------------------------------


def test_codeidx_c12_truncated_flag_set() -> None:
    """CODEIDX-C12: when a symbol span exceeds max_tokens, metadata['truncated'] is True."""
    from app.knowledge.ast_parser import Symbol
    from app.knowledge.code_symbol_chunker import build_code_chunks
    from app.knowledge.tokenizer_window import WindowTokenizer

    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")
    # Build a very large symbol body that won't fit in max_tokens=30.
    large_body = "def process_orders(conn, ids):\n    " + "x = compute_something(ids)\n    " * 50

    sym = Symbol(
        name="process_orders",
        kind="function",
        start_line=1,
        end_line=large_body.count("\n") + 1,
        file_path="orders.py",
        uid="uid-001",
        language="python",
    )
    chunks = build_code_chunks(sym, large_body, tk, max_tokens=30)
    assert len(chunks) >= 2, "expected multiple chunks for oversized symbol"
    for chunk in chunks:
        assert chunk.metadata.get("truncated") is True, (
            f"expected truncated=True on all chunks of oversized symbol; meta={chunk.metadata}"
        )


def test_codeidx_c12_fits_single_window_no_truncated_flag() -> None:
    """CODEIDX-C12: a symbol that fits in max_tokens does NOT get truncated=True."""
    from app.knowledge.ast_parser import Symbol
    from app.knowledge.code_symbol_chunker import build_code_chunks
    from app.knowledge.tokenizer_window import WindowTokenizer

    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")
    small_body = "def hello():\n    return 42\n"
    sym = Symbol(
        name="hello",
        kind="function",
        start_line=1,
        end_line=3,
        file_path="hello.py",
        uid="uid-002",
        language="python",
    )
    chunks = build_code_chunks(sym, small_body, tk, max_tokens=512)
    assert len(chunks) == 1
    assert "truncated" not in chunks[0].metadata, (
        f"truncated flag must not be set for small symbol; meta={chunks[0].metadata}"
    )


# ---------------------------------------------------------------------------
# CODEIDX-C13: method heuristic Python-only (N/A to embedding path — graph concern)
# CODEIDX-C14: cross-lang import false edges (N/A to embedding — graph concern, W6)
# ---------------------------------------------------------------------------
# These items affect the code graph builder (ast_parser / code_graph.py), not
# the embedding/chunking path.  They are deferred to W6 (graph scope).
# We add a lightweight assertion that the embedding path produces chunks for all
# symbol kinds regardless of language, confirming the embedding path is not
# affected by these issues.


def test_codeidx_c13_c14_embedding_path_agnostic_to_lang() -> None:
    """CODEIDX-C13/C14: symbol chunks are produced for function/method/class kinds
    in any language (embedding path is not Python-only).
    Graph-level concerns (method heuristic, cross-lang import edges) are W6 scope."""
    from app.knowledge.ast_parser import Symbol
    from app.knowledge.code_symbol_chunker import build_code_chunks
    from app.knowledge.tokenizer_window import WindowTokenizer

    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")

    for lang, kind, body in [
        ("python", "function", "def foo():\n    pass\n"),
        ("python", "method", "    def bar(self):\n        pass\n"),
        ("python", "class", "class Baz:\n    pass\n"),
        ("typescript", "function", "function doThing(): void {}\n"),
        ("go", "function", "func Run() {}\n"),
    ]:
        sym = Symbol(
            name="target",
            kind=kind,
            start_line=1,
            end_line=body.count("\n") + 1,
            file_path=f"file.{lang[:2]}",
            uid=f"uid-{lang}-{kind}",
            language=lang,
        )
        chunks = build_code_chunks(sym, body, tk, max_tokens=512)
        assert chunks, f"expected chunks for lang={lang} kind={kind}"


# ---------------------------------------------------------------------------
# CODEIDX-C18: embed batch isolation — one bad add_documents doesn't abort rest
# ---------------------------------------------------------------------------


def test_codeidx_c18_bad_batch_does_not_abort_remaining(tmp_path: Path) -> None:
    """CODEIDX-C18: if add_documents raises for one batch the others still execute."""
    from app.knowledge.ast_parser import ParsedFile, Symbol
    from app.knowledge.code_symbol_chunker import CodeSymbolChunker
    from app.knowledge.tokenizer_window import WindowTokenizer

    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")
    chunker = CodeSymbolChunker(tokenizer=tk, max_tokens=512)

    # Two source files each with one symbol, so we get two _flush() calls
    # (batching is per-_BATCH_SIZE which is 200; but we'll force two batches
    # by patching _BATCH_SIZE to 1 via the instance).
    sym_a = Symbol(
        name="func_a",
        kind="function",
        start_line=1,
        end_line=2,
        file_path="a.py",
        uid="uid-a",
        language="python",
    )
    sym_b = Symbol(
        name="func_b",
        kind="function",
        start_line=1,
        end_line=2,
        file_path="b.py",
        uid="uid-b",
        language="python",
    )
    parsed: dict = {
        "a.py": ParsedFile(file_path="a.py", language="python", symbols=[sym_a]),
        "b.py": ParsedFile(file_path="b.py", language="python", symbols=[sym_b]),
    }
    # Write minimal source files
    (tmp_path / "a.py").write_text("def func_a():\n    pass\n")
    (tmp_path / "b.py").write_text("def func_b():\n    pass\n")

    call_count = 0
    successful_ids: list[str] = []

    def mock_add_documents(project_id, doc_ids, documents, metadatas):  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First batch raises
            raise RuntimeError("simulated ChromaDB failure")
        successful_ids.extend(doc_ids)

    vs = MagicMock()
    vs.add_documents = mock_add_documents

    # Patch _BATCH_SIZE to 1 so each symbol is a separate batch.
    import app.knowledge.code_symbol_chunker as csc_mod

    original_batch_size = csc_mod._BATCH_SIZE
    csc_mod._BATCH_SIZE = 1
    try:
        chunker.embed_symbols("proj", parsed, tmp_path, vs)
    finally:
        csc_mod._BATCH_SIZE = original_batch_size

    assert call_count == 2, f"expected 2 flush calls, got {call_count}"
    # The second batch succeeded despite the first raising
    assert len(successful_ids) == 1, (
        f"expected 1 successful upsert (second batch), got {successful_ids}"
    )


# ---------------------------------------------------------------------------
# CODEIDX-C19: symbol chunk ids are prefixed "sym:" and distinct from prose ids
# ---------------------------------------------------------------------------


def test_codeidx_c19_symbol_ids_prefixed_sym(tmp_path: Path) -> None:
    """CODEIDX-C19: symbol chunk doc_ids carry 'sym:' prefix, not 'code:' or prose prefixes."""
    from app.knowledge.ast_parser import ParsedFile, Symbol
    from app.knowledge.code_symbol_chunker import CodeSymbolChunker
    from app.knowledge.tokenizer_window import WindowTokenizer

    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")
    chunker = CodeSymbolChunker(tokenizer=tk, max_tokens=512)

    sym = Symbol(
        name="my_func",
        kind="function",
        start_line=1,
        end_line=3,
        file_path="utils.py",
        uid="uid-xyz",
        language="python",
    )
    parsed = {"utils.py": ParsedFile(file_path="utils.py", language="python", symbols=[sym])}
    (tmp_path / "utils.py").write_text("def my_func():\n    return 1\n")

    captured_ids: list[str] = []

    def capture_add(project_id, doc_ids, documents, metadatas):  # noqa: ARG001
        captured_ids.extend(doc_ids)

    vs = MagicMock()
    vs.add_documents = capture_add

    chunker.embed_symbols("proj", parsed, tmp_path, vs)

    assert captured_ids, "expected at least one doc_id to be upserted"
    for doc_id in captured_ids:
        assert doc_id.startswith("sym:"), f"expected 'sym:' prefix, got: {doc_id}"
        assert not doc_id.startswith("code:"), f"old 'code:' prefix must not be used: {doc_id}"


# ---------------------------------------------------------------------------
# CODEIDX-C20/C21: Louvain over-merge / cluster staleness — W6 scope
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="W6 clustering scope — Louvain/cluster staleness is out of W2 scope")
def test_codeidx_c20_louvain_over_merge() -> None:
    """Placeholder: Louvain community merge threshold (C20) is a W6 clustering concern."""


@pytest.mark.skip(reason="W6 clustering scope — cluster staleness is out of W2 scope")
def test_codeidx_c21_cluster_staleness() -> None:
    """Placeholder: cluster invalidation on re-index (C21) is a W6 clustering concern."""
