"""What a project's BM25 corpus contains — defined once, for two processes.

`pipeline_runner._run_bm25_build` writes the snapshot on the **worker**;
`ops/bm25_local_reconcile._build_one` rebuilds it on the **web** dyno at start-up.
They are separate Heroku process types with separate filesystems — that split is
the entire reason the reconcile exists (F-KNOW-12) — and each had its own copy of
the loop that turns stored documents into corpus entries.

Nothing was wrong with either copy. The risk is directional: a change to what a
document *is* that reaches the builder and not the reconcile makes the reader's
corpus differ from the writer's, and the symptom is retrieval behaving
differently depending on which process last produced the snapshot. That is close
to undiagnosable from the outside, and board row 2.2 is about to change exactly
this definition.

**Duck-typed deliberately.** The two callers pass different row objects and this
module imports no model, so the shape can be tested without a database.

**The entry id is a contract, not a detail.** `HybridRetriever._fuse` merges the
two legs on `doc_id`, and the vector store writes a prose chunk as
``f"{doc.id}:{chunk_index}"``. An id invented here would make one chunk two
documents and **split** its rank across the legs instead of reinforcing it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Protocol

from app.knowledge.chunk_metadata import symbol_chunk_id
from app.knowledge.chunker import chunk_document

#: One corpus entry: ``(doc_id, text, metadata)`` — the tuple ``BM25Index.build``
#: takes.
CorpusEntry = tuple[str, str, dict[str, Any]]


class StoredDoc(Protocol):
    """The four fields a corpus entry needs. Satisfied by ``KnowledgeDoc``."""

    id: str
    content: str
    source_path: str
    doc_type: str


def corpus_entries_for_docs(docs: Iterable[StoredDoc]) -> list[CorpusEntry]:
    """Turn stored documents into the entries a BM25 snapshot is built from.

    A document with no content contributes nothing rather than an empty entry:
    an empty document dilutes every IDF in the corpus while never matching.
    """
    entries: list[CorpusEntry] = []
    for doc in docs:
        if not doc.content:
            continue
        for chunk in chunk_document(
            content=doc.content,
            file_path=doc.source_path,
            doc_type=doc.doc_type,
        ):
            meta = dict(chunk.metadata)
            meta.setdefault("source_path", doc.source_path)
            meta.setdefault("doc_type", doc.doc_type)
            entries.append(
                (f"{doc.id}:{chunk.metadata.get('chunk_index', '0')}", chunk.content, meta)
            )
    return entries


class StoredSymbol(Protocol):
    """What ``code_graph_symbols`` can say about a symbol without a clone."""

    uid: str
    name: str
    kind: str
    file_path: str
    start_line: int
    signature: str
    docstring: str
    decorators_json: str


def corpus_entries_for_symbols(symbols: Iterable[StoredSymbol]) -> list[CorpusEntry]:
    """One lexical document per code symbol (board row 2.2).

    Until this existed the corpus was built from ``KnowledgeDoc`` rows alone, and
    their content is **LLM-generated documentation** rather than source
    (``pipeline_runner`` stores ``generated_content``). So the lexical leg had
    never indexed a line of code: an identifier reached it only when the model
    happened to write one into a summary, while the dense leg carried symbol
    chunks with real bodies. Two legs, two corpora.

    **The document is not the body, and that is a constraint rather than a
    preference.** ``bm25_local_reconcile`` rebuilds this snapshot on the web dyno
    "with no clone, no network and no LLM" — its own contract, and F-KNOW-12 is
    what a snapshot needing something the reading process lacks costs. Postgres
    holds a symbol's name, signature, docstring, decorators and span; it does not
    hold its body. What remains is precisely what a lexical index wants:
    identifiers, parameter names, and the prose of a docstring.

    **The id is the chunker's**, through the shared ``symbol_chunk_id``.
    ``HybridRetriever._fuse`` merges the legs on ``doc_id``, so a symbol document
    under any other id would be a *second* document for the same symbol — its RRF
    contribution splitting across two entries instead of reinforcing one, which
    is worse than not indexing it at all. ``chunk_index=0`` always: a symbol too
    large for one chunk has ``:1``, ``:2`` … in the vector store only, so those
    stay dense-only while ``:0`` fuses. Stated so the asymmetry is not read later
    as a bug.
    """
    entries: list[CorpusEntry] = []
    for sym in symbols:
        text = " ".join(
            part
            for part in (
                sym.name,
                sym.signature,
                _decorator_words(sym.decorators_json),
                sym.docstring,
                sym.file_path,
            )
            if part
        ).strip()
        # No name, no entry. The identifier is what a lexical document for a
        # symbol is FOR, and a symbol reduced to its file path adds a document
        # that says nothing the file's own prose document does not already say —
        # while diluting every IDF in the corpus.
        if not sym.name or not text:
            continue
        entries.append(
            (
                symbol_chunk_id(
                    source_path=sym.file_path,
                    uid=sym.uid,
                    start_line=sym.start_line,
                    chunk_index=0,
                ),
                text,
                {
                    "source_path": sym.file_path,
                    "doc_type": "code_symbol",
                    "symbol": sym.name,
                    "kind": sym.kind,
                    "start_line": sym.start_line,
                },
            )
        )
    return entries


def _decorator_words(raw: str) -> str:
    """Decorator names as plain text.

    A malformed value costs this symbol its decorators, never the project's
    snapshot: ``decorators_json`` is a TEXT column and nothing validates it on
    the way in.
    """
    try:
        loaded = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return ""
    if not isinstance(loaded, list):
        return ""
    return " ".join(str(item) for item in loaded if item)
