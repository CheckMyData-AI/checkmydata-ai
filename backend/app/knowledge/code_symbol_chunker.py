"""Raw-code symbol embedding path (CODEIDX-C3).

Reads source spans for each AST-parsed :class:`~app.knowledge.ast_parser.Symbol`
and upserts them into the vector store with :class:`CodeChunkMetadata`
(contract C-E: path, symbol, language, start_line, end_line, kind).

This runs **inside the pipeline's embed stage**, gated on
``settings.hybrid_retrieval_enabled`` (always-on default), so code-Q&A
retrieval can surface actual function/class bodies rather than only the
LLM-generated schema prose.

Design notes
------------
* Line-based extraction: ``start_line`` / ``end_line`` are 1-indexed; we read
  exactly those lines from the on-disk source file (relative to *repo_dir*).
* Oversized symbols are split via the existing ``chunk_document`` infrastructure
  so every stored chunk respects the embedder's context window.
* Doc IDs are deterministic: ``code:{file_path}:{uid}:{chunk_index}`` so upserts
  are idempotent across incremental re-runs.
* Failures per symbol are logged at DEBUG and skipped; the caller is never
  interrupted by a single bad source span.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.knowledge.chunk_metadata import CodeChunkMetadata, validate_chunk_metadata
from app.knowledge.chunker import Chunk, _split_large_section

if TYPE_CHECKING:
    from app.knowledge.ast_parser import ParsedFile, Symbol
    from app.knowledge.tokenizer_window import WindowTokenizer
    from app.knowledge.vector_store import VectorStore

logger = logging.getLogger(__name__)

# Maximum number of chunks flushed to the vector store in one add_documents
# call. Avoids very large ChromaDB upserts for projects with many symbols.
_BATCH_SIZE = 200


def build_code_chunks(
    symbol: Symbol,
    source_text: str,
    tokenizer: WindowTokenizer,
    max_tokens: int,
) -> list[Chunk]:
    """Build Chunk objects for a single AST symbol.

    Parameters
    ----------
    symbol:
        The AST symbol whose span to embed.
    source_text:
        Full source text of the file (may be empty if the file couldn't be
        read — callers should pass ``""`` and handle the resulting empty list).
    tokenizer:
        A :class:`~app.knowledge.tokenizer_window.WindowTokenizer` instance
        used for token counting and truncation.
    max_tokens:
        Maximum tokens per chunk (inclusive).  Should match the embedder's
        context window (``settings.embedder_max_tokens``).

    Returns
    -------
    list[Chunk]
        One or more chunks.  Empty when *source_text* is blank.  Each chunk's
        ``metadata`` satisfies :func:`~app.knowledge.chunk_metadata.validate_chunk_metadata`.
    """
    if not source_text.strip():
        return []

    # Extract the exact source lines for this symbol (1-indexed, inclusive).
    lines = source_text.splitlines(keepends=True)
    start = max(0, symbol.start_line - 1)
    end = min(len(lines), symbol.end_line)
    body = "".join(lines[start:end])

    if not body.strip():
        return []

    # Build the base C-E metadata dict for this symbol.
    base_meta: dict[str, str | int] = CodeChunkMetadata(
        path=symbol.file_path,
        symbol=symbol.name,
        language=symbol.language or "",
        start_line=symbol.start_line,
        end_line=symbol.end_line,
        kind=symbol.kind,
    ).to_dict()

    # Fast path: entire body fits within the window.
    if tokenizer.count_tokens(body) <= max_tokens:
        validate_chunk_metadata(base_meta)
        return [Chunk(content=body, metadata={**base_meta, "chunk_index": "0"})]

    # Split oversized body using the existing paragraph/sentence/word splitter.
    raw_pieces = _split_large_section(body, max_tokens, tokenizer)
    chunks: list[Chunk] = []
    for i, piece in enumerate(raw_pieces):
        if not piece.strip():
            continue
        # Hard-truncate any piece that somehow still exceeds the window
        # (shouldn't happen after _split_large_section, but defensive).
        if tokenizer.count_tokens(piece) > max_tokens:
            piece = tokenizer.truncate_to_tokens(piece, max_tokens)
        meta = {**base_meta, "chunk_index": str(i)}
        validate_chunk_metadata(meta)
        chunks.append(Chunk(content=piece, metadata=meta))

    return chunks


@dataclass
class CodeSymbolChunker:
    """Builds and upserts raw-code chunks for all symbols in parsed_files.

    Parameters
    ----------
    tokenizer:
        A :class:`~app.knowledge.tokenizer_window.WindowTokenizer`.
    max_tokens:
        Per-chunk token ceiling.  Defaults to ``settings.embedder_max_tokens``
        when not supplied (resolved at call time to avoid circular imports at
        module load).
    """

    tokenizer: WindowTokenizer
    max_tokens: int

    def embed_symbols(
        self,
        project_id: str,
        parsed_files: dict[str, ParsedFile],
        repo_dir: Path,
        vector_store: VectorStore,
    ) -> None:
        """Chunk every symbol in *parsed_files* and upsert into *vector_store*.

        This is a **synchronous** operation intended to be wrapped in
        ``asyncio.to_thread`` by the pipeline runner.  Errors per symbol are
        silently skipped so a single unreadable file never aborts the run.

        Parameters
        ----------
        project_id:
            Target ChromaDB collection identifier.
        parsed_files:
            Mapping of repo-relative path → :class:`~app.knowledge.ast_parser.ParsedFile`.
            Keys must match the ``Symbol.file_path`` values.
        repo_dir:
            Absolute path to the checked-out repository root.  Used to resolve
            source files for line extraction.
        vector_store:
            The project's :class:`~app.knowledge.vector_store.VectorStore` instance.
        """
        if not parsed_files:
            return

        # Accumulate all chunks across all files before flushing in batches.
        batch_ids: list[str] = []
        batch_docs: list[str] = []
        batch_metas: list[dict] = []

        for rel_path, parsed_file in parsed_files.items():
            if not parsed_file.symbols:
                continue

            # Read the source file once per file.
            source_text = self._read_source(repo_dir, rel_path)
            if source_text is None:
                # File missing or unreadable — skip all its symbols.
                continue

            for symbol in parsed_file.symbols:
                try:
                    chunks = build_code_chunks(
                        symbol=symbol,
                        source_text=source_text,
                        tokenizer=self.tokenizer,
                        max_tokens=self.max_tokens,
                    )
                except Exception:
                    logger.debug(
                        "code_symbol_chunker: skipping symbol %s in %s",
                        symbol.uid,
                        rel_path,
                        exc_info=True,
                    )
                    continue

                for chunk in chunks:
                    chunk_idx = chunk.metadata.get("chunk_index", "0")
                    doc_id = f"code:{rel_path}:{symbol.uid}:{chunk_idx}"
                    batch_ids.append(doc_id)
                    batch_docs.append(chunk.content)
                    batch_metas.append(chunk.metadata)

                    if len(batch_ids) >= _BATCH_SIZE:
                        self._flush(project_id, batch_ids, batch_docs, batch_metas, vector_store)
                        batch_ids, batch_docs, batch_metas = [], [], []

        if batch_ids:
            self._flush(project_id, batch_ids, batch_docs, batch_metas, vector_store)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read_source(self, repo_dir: Path, rel_path: str) -> str | None:
        """Return the source text for *rel_path*, or None if unreadable."""
        abs_path = repo_dir / rel_path
        try:
            return abs_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError):
            logger.debug(
                "code_symbol_chunker: cannot read %s — skipping its symbols",
                abs_path,
                exc_info=True,
            )
            return None

    @staticmethod
    def _flush(
        project_id: str,
        ids: list[str],
        docs: list[str],
        metas: list[dict],
        vector_store: VectorStore,
    ) -> None:
        """Upsert a batch of chunks into the vector store."""
        try:
            vector_store.add_documents(
                project_id=project_id,
                doc_ids=ids,
                documents=docs,
                metadatas=metas,
            )
            logger.debug(
                "code_symbol_chunker: upserted %d code chunks for project %s",
                len(ids),
                project_id,
            )
        except Exception:
            logger.warning(
                "code_symbol_chunker: failed to upsert %d chunks for project %s",
                len(ids),
                project_id,
                exc_info=True,
            )


def make_chunker(*, max_tokens: int | None = None) -> CodeSymbolChunker:
    """Factory that resolves settings defaults and returns a ready :class:`CodeSymbolChunker`.

    Calling this at runtime (not import time) avoids circular imports from
    ``app.config`` being imported before the application is fully initialised.

    Parameters
    ----------
    max_tokens:
        Override the token ceiling.  When *None*, ``settings.embedder_max_tokens``
        is used.
    """
    from app.config import settings
    from app.knowledge.tokenizer_window import get_tokenizer

    effective_max = max_tokens if max_tokens is not None else settings.embedder_max_tokens
    tokenizer = get_tokenizer(settings.chroma_embedding_model)
    return CodeSymbolChunker(tokenizer=tokenizer, max_tokens=effective_max)
