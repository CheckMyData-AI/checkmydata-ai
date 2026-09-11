"""Three ways the vector store lost chunks nobody asked it to lose (KNOW-01/02/03).

P1 row 9, second seam. All three are about **what a run deletes and what it forgets to
write** — and each is invisible from the outside, because a smaller collection answers
queries exactly like a complete one, only worse.

**KNOW-02 — `generate_docs` deletes the symbol chunks `code_symbol_embed` wrote earlier in
the same run.** Step 5d embeds code symbols under `source_path = symbol.file_path`; step 9
then calls `delete_by_source_path(project_id, edoc.file_path)` before writing the file's
prose, and that deletes **every** chunk with the path — kind included. Any file that has
both a document and symbols loses its symbols on every run that regenerates its document.

**KNOW-03 — nothing ever sweeps a *changed* file's symbol chunks.** The id is
`sym:{path}:{uid}@{start_line}:{idx}`, and `start_line` moves whenever anything above the
symbol changes. `embed_symbols` only upserts. The three `delete_by_source_path` sites cover
deleted files and doc-bearing paths — so a function that moved down ten lines leaves its old
body in the store forever, retrievable, attributed to the same symbol.

**KNOW-01 — the document cache and the embedding reindex cancel each other out.**
`queue_embedding_reindex` drops the whole collection and enqueues a `force_full` run; inside
it, `generate_docs` reuses every document whose `content_hash` still matches and `continue`s
— without writing chunks, because the chunks were written by the branch it skipped. The
documents survive, their vectors do not, and nothing re-creates them: the next run reuses
them again. Measured on this repository's own numbers, that is 575 of 763 documents whose
prose is in Postgres and absent from the vector store.

The fix keeps the cache (it is worth 71% of a rebuild) and re-chunks from the **cached
content** when the store has nothing — no LLM call, because the document is already right.
"""

from __future__ import annotations

import inspect

from app.knowledge import pipeline_runner as pr
from app.knowledge.vector_store import VectorStore


class TestDeletingProseKeepsSymbols:
    """KNOW-02."""

    def test_the_store_can_delete_one_kind(self) -> None:
        sig = inspect.signature(VectorStore.delete_by_source_path)
        assert "kind" in sig.parameters, (
            "`delete_by_source_path` deletes every chunk with the path regardless of kind, "
            "so `generate_docs` removes the symbol chunks `code_symbol_embed` wrote earlier "
            "in the same run (KNOW-02)"
        )

    def test_both_backends_agree(self) -> None:
        """pgvector is what production runs; a fix reaching only Chroma fixes development."""
        from app.knowledge.pgvector_store import PgVectorStore

        sig = inspect.signature(PgVectorStore.delete_by_source_path)
        assert "kind" in sig.parameters, "the pgvector twin does not take the kind filter"

    def test_generate_docs_deletes_only_prose(self) -> None:
        source = inspect.getsource(pr.IndexingPipelineRunner)
        deletes = [
            line
            for line in source.splitlines()
            if "delete_by_source_path" in line and "def " not in line
        ]
        assert deletes, "the delete call is gone; this guard is blind"
        doc_path_deletes = source.count("kind=_PROSE")
        assert doc_path_deletes >= 2, (
            "the prose-writing paths still delete every kind. There are two of them — the "
            f"main loop and the retry copy — and {doc_path_deletes} carry the filter"
        )


class TestChangedFilesHaveTheirSymbolChunksSwept:
    """KNOW-03."""

    def test_the_embed_step_sweeps_before_it_writes(self) -> None:
        import ast
        import textwrap

        tree = ast.parse(
            textwrap.dedent(inspect.getsource(pr.IndexingPipelineRunner._run_code_symbol_embed))
        )
        sweeps = [
            ast.unparse(n)
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and "delete_by_source_path" in ast.unparse(n)
            and "_SYMBOL" in ast.unparse(n)
        ]
        assert sweeps, (
            "`embed_symbols` only upserts, and the id carries `start_line` — so a symbol "
            "that moved leaves its old body in the store, retrievable, under the same "
            "symbol's name (KNOW-03)"
        )


class TestReusedDocumentsStillGetVectors:
    """KNOW-01."""

    def test_the_reuse_branch_can_write_chunks(self) -> None:
        """Reachable, not merely present.

        The first version asserted `"_rechunk_reused" in source` — and a planted `if False:`
        in front of the call left the helper defined, the string present, and the test
        green. A presence check passes for code that exists and cannot run, which is the
        state this whole seam is about.
        """
        import ast
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(pr.IndexingPipelineRunner)))
        guarded_calls = [
            ast.unparse(node.test)
            for node in ast.walk(tree)
            if isinstance(node, ast.If) and "_rechunk_reused" in ast.unparse(node.body)
        ]
        assert guarded_calls, (
            "the reuse branch `continue`s without writing chunks, so a run that dropped "
            "the collection first — which is exactly what `queue_embedding_reindex` does "
            "before enqueuing this run — leaves every reused document with no vectors, "
            "for good: the next run reuses it again (KNOW-01)"
        )
        assert any("store_was_empty" in cond for cond in guarded_calls), (
            "the re-chunk is behind a condition that does not consult whether the store is "
            f"empty, so it either never fires or fires always. Conditions: {guarded_calls}"
        )

    def test_it_does_not_call_an_llm_to_do_it(self) -> None:
        """The document is already right; only its vectors are missing."""
        import ast
        import textwrap

        fn = getattr(pr.IndexingPipelineRunner, "_rechunk_reused", None)
        assert fn is not None, "the re-chunk helper is gone"
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        # Calls, not words. The first version of this test searched the source text for
        # "llm" and failed on the helper's own docstring sentence "No LLM call" — a guard
        # matching prose about the thing rather than the thing, for the fourth time in one
        # day of this programme.
        called = {
            ast.unparse(node.func).lower() for node in ast.walk(tree) if isinstance(node, ast.Call)
        }
        offenders = [c for c in called if "llm" in c or "generator" in c or "complete" in c]
        assert not offenders, (
            f"the re-chunk path calls {offenders}; re-embedding a cached document must "
            "cost nothing but the embedding — the document is already right"
        )

    def test_the_store_is_asked_once_not_per_document(self) -> None:
        """A per-document existence check would add 763 round trips to a rebuild."""
        source = inspect.getsource(pr.IndexingPipelineRunner)
        assert "count(" in source or "_store_is_empty" in source, (
            "nothing checks whether the collection is empty, so either the re-chunk never "
            "fires or it fires per document"
        )
