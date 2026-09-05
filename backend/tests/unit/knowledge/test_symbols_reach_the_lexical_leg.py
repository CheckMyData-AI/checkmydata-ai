"""The lexical leg had never indexed a line of code (board row 2.2).

`KnowledgeDoc.content` is LLM-generated documentation — `pipeline_runner.py:1172`
stores `generated_content`, the output of `doc_generator`. The BM25 corpus is
built from those rows, so the lexical half of hybrid retrieval has only ever seen
a model's summary of each file. An identifier reached it when the model happened
to write one down, and nowhere else.

The dense leg, meanwhile, carries symbol chunks with real bodies. So the two legs
index different corpora, and a question naming a function — the natural way to
ask about code — reached BM25 only through prose.

**Why the document is not the body.** `bm25_local_reconcile` rebuilds the
snapshot on the web dyno "from `KnowledgeDoc` rows in Postgres, with no clone, no
network and no LLM" — its own contract, and F-KNOW-12 is what happens when the
snapshot needs something the reading process does not have. `code_graph_symbols`
holds `name`, `signature`, `docstring`, `decorators`, `file_path` and the line
span; it does **not** hold the body. So a symbol document is what Postgres can
say about a symbol, which is exactly the part a lexical index wants: identifiers,
parameter names, and the prose a docstring carries.

**Why the id must be the chunker's.** `HybridRetriever._fuse` merges the legs on
`doc_id`. A symbol document under a different id would be a *second* document for
the same symbol — the RRF contribution splits across two entries instead of
reinforcing one, which is worse than not indexing it at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.knowledge.bm25_corpus import corpus_entries_for_symbols
from app.knowledge.chunk_metadata import symbol_chunk_id


@dataclass
class _Symbol:
    uid: str = "app.sync.resolve_sync_status"
    name: str = "resolve_sync_status"
    kind: str = "function"
    file_path: str = "app/sync.py"
    start_line: int = 40
    end_line: int = 88
    language: str | None = "python"
    signature: str = "(code_cols: set[str], db_cols: set[str]) -> str"
    docstring: str = "Decide the sync status from both column sets."
    decorators_json: str = '["staticmethod"]'
    extra: dict = field(default_factory=dict)


class TestOneDocumentPerSymbol:
    def test_a_symbol_becomes_an_entry(self):
        assert len(corpus_entries_for_symbols([_Symbol()])) == 1

    def test_the_id_is_the_one_the_chunker_writes(self):
        """The fusion contract. A different id splits the symbol's rank."""
        (doc_id, _text, _meta) = corpus_entries_for_symbols([_Symbol()])[0]
        assert doc_id == symbol_chunk_id(
            source_path="app/sync.py",
            uid="app.sync.resolve_sync_status",
            start_line=40,
            chunk_index=0,
        )

    def test_the_text_carries_the_identifier(self):
        """The whole point, and it pairs with the tokenizer change: the compound
        is emitted as a term, so naming the function finds it."""
        (_id, text, _meta) = corpus_entries_for_symbols([_Symbol()])[0]
        assert "resolve_sync_status" in text

    def test_the_text_carries_the_signature_and_docstring(self):
        (_id, text, _meta) = corpus_entries_for_symbols([_Symbol()])[0]
        assert "code_cols" in text, "parameter names are high-value lexical content"
        assert "Decide the sync status" in text

    def test_the_metadata_uses_the_key_deletion_uses(self):
        (_id, _text, meta) = corpus_entries_for_symbols([_Symbol()])[0]
        assert meta["source_path"] == "app/sync.py"

    def test_it_is_marked_as_a_symbol_document(self):
        """Distinguishable from a prose chunk in the results, and in metrics."""
        (_id, _text, meta) = corpus_entries_for_symbols([_Symbol()])[0]
        assert meta["doc_type"] == "code_symbol"


class TestItRefusesWhatItCannotIndex:
    def test_a_symbol_with_no_text_at_all_contributes_nothing(self):
        """Name, signature and docstring all empty — an entry would dilute every
        IDF in the corpus while never matching."""
        bare = _Symbol(name="", signature="", docstring="", decorators_json="[]")
        assert corpus_entries_for_symbols([bare]) == []

    def test_a_symbol_with_only_a_name_is_still_indexed(self):
        """A name is the single most valuable term here, so this is the floor,
        not an edge case."""
        named = _Symbol(signature="", docstring="", decorators_json="[]")
        assert len(corpus_entries_for_symbols([named])) == 1

    def test_malformed_decorators_do_not_break_the_build(self):
        """`decorators_json` is a TEXT column; a bad value must cost that
        symbol's decorators, not the whole project's snapshot."""
        broken = _Symbol(decorators_json="{not json")
        entries = corpus_entries_for_symbols([broken])
        assert len(entries) == 1
        assert "resolve_sync_status" in entries[0][1]


class TestBothProcessesIndexThem:
    """Same reason as the prose corpus: the builder runs on the worker and the
    reconcile on the web dyno, and a corpus that differs between them is a
    retrieval difference nobody can attribute."""

    def test_the_pipeline_builder_includes_symbols(self):
        from pathlib import Path

        src = Path("app/knowledge/pipeline_runner.py").read_text(encoding="utf-8")
        assert "corpus_entries_for_symbols" in src

    def test_the_boot_reconcile_includes_symbols(self):
        from pathlib import Path

        src = Path("app/ops/bm25_local_reconcile.py").read_text(encoding="utf-8")
        assert "corpus_entries_for_symbols" in src
