"""Raw-code embedding chunk metadata schema (contract C-E; consumed in Wave 2).

The file-path key is ``source_path``, and it was ``path`` until 2026-09-05. That
was two keys for one concept: `chunker.py` gives a prose chunk ``source_path``,
and both `delete_by_source_path` implementations filter on it — so symbol chunks,
carrying ``path``, were never matched and accumulated forever while the code they
described was deleted. Renaming was safe because the key was **write-only**:
nothing in ``app/`` read it.

Renaming alone fixes nothing already stored, so deletion also accepts the legacy
key; see the vector stores.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

REQUIRED_CHUNK_METADATA_KEYS: frozenset[str] = frozenset(
    {"source_path", "symbol", "language", "start_line", "end_line", "kind"}
)


@dataclass
class CodeChunkMetadata:
    source_path: str
    symbol: str
    language: str
    start_line: int
    end_line: int
    kind: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "source_path": self.source_path,
            "symbol": self.symbol,
            "language": self.language,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "kind": self.kind,
        }


def validate_chunk_metadata(meta: dict) -> None:
    missing = REQUIRED_CHUNK_METADATA_KEYS - set(meta)
    if missing:
        raise ValueError(f"chunk metadata missing required keys: {sorted(missing)}")


logger = logging.getLogger(__name__)

#: Bumped when the SHAPE of a symbol chunk id changes. It rides
#: ``embedding_fingerprint()`` so a deploy rebuilds rather than orphaning: every
#: stored chunk keeps its old id, and only a rebuild rewrites them under the new
#: one. Separate from ``SYMBOL_UID_SCHEMA`` (what a symbol *is*) and
#: ``GRAPH_EXTRACTION_SCHEMA`` (what is extracted), because a symbol can keep its
#: identity and its edges while the id addressing its chunks changes.
SYMBOL_CHUNK_ID_SCHEMA = 1


def symbol_chunk_id(*, source_path: str, uid: str, start_line: int, chunk_index: object) -> str:
    """The id of one chunk of one symbol — a pure function of that symbol.

    It was ``sym:{path}:{uid}{suffix}:{idx}``, where ``suffix`` came from a
    counter kept across every file in the run. That made the id depend on parse
    ORDER: a file appearing earlier shifted the suffix of later duplicates, so
    editing one file churned chunk ids belonging to another.

    It also made the id unreproducible from the database, which blocks board row
    2.2: the BM25 corpus must carry symbol documents under the *same* ids the
    vector store uses, because ``HybridRetriever._fuse`` merges the legs on
    ``doc_id`` — a different id makes one symbol two documents and splits its
    rank instead of reinforcing it. Replaying the old suffix would mean replaying
    which files were skipped for an unreadable source, and that is recorded
    nowhere.

    ``(file_path, uid, start_line)`` are all columns on ``code_graph_symbols``,
    so this form is computable on both sides. The ``sym:`` prefix is kept from
    CODEIDX-C19: it is what distinguishes a symbol chunk id from a prose chunk
    id, which is prefixed with the document's database id.
    """
    return f"sym:{source_path}:{uid}@{start_line}:{chunk_index}"


def dedupe_chunk_id(chunk_id: str, seen: dict[str, int]) -> str:
    """Guarantee uniqueness within one indexing run, and say when it had to.

    ChromaDB rejects an entire batch on a duplicate id: on 2026-08-18 production
    lost nine batches of 200 chunks to one ``DuplicateIDError`` with only a
    WARNING behind it. The guard therefore stays even though a collision on
    ``(path, uid, start_line)`` should be impossible.

    The first occurrence keeps its id verbatim, so a deploy does not churn every
    existing vector. A later one gets a suffix — **and a warning**, because a
    suffixed id is precisely the one the BM25 corpus builder cannot reproduce
    from Postgres, and a silent fallback would make the two legs disagree about a
    document's identity with nothing to show for it.
    """
    count = seen.get(chunk_id, 0)
    seen[chunk_id] = count + 1
    if count == 0:
        return chunk_id
    logger.warning(
        "symbol chunk id collision on %s (occurrence %d) — the BM25 corpus cannot "
        "reproduce a suffixed id, so this symbol will not fuse across retrieval legs",
        chunk_id,
        count + 1,
    )
    return f"{chunk_id}#{count}"
