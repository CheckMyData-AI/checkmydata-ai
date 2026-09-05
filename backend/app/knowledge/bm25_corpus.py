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

from collections.abc import Iterable
from typing import Any, Protocol

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
