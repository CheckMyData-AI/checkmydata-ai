"""Tests for CODEIDX-C3: raw-code symbol embedding path.

Verifies that CodeSymbolChunker:
- produces Chunk objects with valid CodeChunkMetadata attached
- sizes chunks to the token window (splitting oversized symbols)
- generates a stable document ID per symbol span
- calls vector_store.add_documents with the right shapes
- degrades gracefully when the source file is missing or unreadable
- is a no-op when parsed_files is empty
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from app.knowledge.ast_parser import ParsedFile, Symbol
from app.knowledge.chunk_metadata import CodeChunkMetadata, validate_chunk_metadata
from app.knowledge.code_symbol_chunker import (
    CodeSymbolChunker,
    build_code_chunks,
)
from app.knowledge.tokenizer_window import WindowTokenizer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_symbol(
    name: str,
    kind: str = "function",
    start_line: int = 1,
    end_line: int = 5,
    file_path: str = "app/foo.py",
    language: str = "python",
) -> Symbol:
    uid = f"{language}:{file_path}:{kind}:{name}:{start_line}"
    return Symbol(
        uid=uid,
        kind=kind,
        name=name,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        language=language,
        signature=f"def {name}():",
        docstring="",
    )


def _make_parsed_file(symbols: list[Symbol], file_path: str = "app/foo.py") -> ParsedFile:
    return ParsedFile(
        file_path=file_path,
        language="python",
        symbols=symbols,
    )


# ---------------------------------------------------------------------------
# Unit tests for build_code_chunks (pure function, no I/O)
# ---------------------------------------------------------------------------


class TestBuildCodeChunks:
    """build_code_chunks(symbol, source_text, tokenizer, max_tokens) -> list[Chunk]"""

    def _tk(self) -> WindowTokenizer:
        return WindowTokenizer("definitely/not-a-real-model-xyz")  # char fallback

    def test_single_chunk_for_small_symbol(self) -> None:
        sym = _make_symbol("my_func", start_line=1, end_line=3)
        source = "def my_func():\n    return 42\n"
        tk = self._tk()
        chunks = build_code_chunks(sym, source, tk, max_tokens=512)

        assert len(chunks) >= 1
        c = chunks[0]
        # Content should contain the source lines
        assert "my_func" in c.content

        # Metadata must carry all C-E required keys
        validate_chunk_metadata(c.metadata)

        meta = c.metadata
        assert meta["path"] == "app/foo.py"
        assert meta["symbol"] == "my_func"
        assert meta["language"] == "python"
        assert meta["start_line"] == 1
        assert meta["end_line"] == 3
        assert meta["kind"] == "function"

    def test_metadata_roundtrip_via_dataclass(self) -> None:
        """CodeChunkMetadata.to_dict() must satisfy validate_chunk_metadata."""
        sym = _make_symbol("svc", kind="class", start_line=10, end_line=20)
        source = "\n" * 9 + "class svc:\n    pass\n" * 5
        tk = self._tk()
        chunks = build_code_chunks(sym, source, tk, max_tokens=512)
        for c in chunks:
            ccm = CodeChunkMetadata(
                path=c.metadata["path"],
                symbol=c.metadata["symbol"],
                language=c.metadata["language"],
                start_line=int(c.metadata["start_line"]),
                end_line=int(c.metadata["end_line"]),
                kind=c.metadata["kind"],
            )
            validate_chunk_metadata(ccm.to_dict())

    def test_oversized_symbol_is_split(self) -> None:
        """A symbol body that exceeds max_tokens must be split into multiple chunks."""
        sym = _make_symbol("big_func", start_line=1, end_line=200)
        # ~3 000 chars > max_tokens=64 (fallback: 3 chars/token)
        source = "    x = 1  # some code\n" * 200
        tk = self._tk()
        chunks = build_code_chunks(sym, source, tk, max_tokens=64)

        assert len(chunks) >= 2, "oversized symbol must produce >1 chunks"
        for c in chunks:
            assert tk.count_tokens(c.content) <= 64, (
                f"chunk exceeds max_tokens: {tk.count_tokens(c.content)}"
            )
            validate_chunk_metadata(c.metadata)
            # All chunks inherit the symbol's path/name/kind
            assert c.metadata["symbol"] == "big_func"
            assert c.metadata["path"] == "app/foo.py"

    def test_empty_source_returns_no_chunks(self) -> None:
        sym = _make_symbol("empty_func", start_line=1, end_line=1)
        chunks = build_code_chunks(sym, "", self._tk(), max_tokens=512)
        assert chunks == []

    def test_chunk_index_increments(self) -> None:
        """Multi-chunk splits must use sequential chunk_index values."""
        sym = _make_symbol("big_func", start_line=1, end_line=100)
        source = "def big_func():\n" + "    pass\n" * 100
        tk = self._tk()
        chunks = build_code_chunks(sym, source, tk, max_tokens=32)
        indices = [c.metadata["chunk_index"] for c in chunks]
        assert indices == [str(i) for i in range(len(chunks))]

    def test_source_line_extraction(self) -> None:
        """Only the symbol's start_line..end_line lines are used."""
        source = "line1\nline2\ndef foo():\n    return 1\nline5\n"
        sym = _make_symbol("foo", start_line=3, end_line=4)
        tk = self._tk()
        chunks = build_code_chunks(sym, source, tk, max_tokens=512)
        assert len(chunks) == 1
        assert "def foo():" in chunks[0].content
        assert "line1" not in chunks[0].content
        assert "line5" not in chunks[0].content


# ---------------------------------------------------------------------------
# Integration-ish test: CodeSymbolChunker.embed_symbols()
# ---------------------------------------------------------------------------


class TestCodeSymbolChunker:
    """CodeSymbolChunker wires build_code_chunks with the vector store."""

    def _chunker(self) -> CodeSymbolChunker:
        return CodeSymbolChunker(
            tokenizer=WindowTokenizer("definitely/not-a-real-model-xyz"),
            max_tokens=512,
        )

    def _sym(self, name: str = "myfunc", start: int = 1, end: int = 3) -> Symbol:
        return _make_symbol(name, start_line=start, end_line=end)

    # --- embed_symbols signature ------------------------------------------------

    def test_embed_symbols_calls_add_documents(self, tmp_path: Path) -> None:
        """embed_symbols must call store.add_documents with valid args."""
        # Write a small source file
        src_file = tmp_path / "app" / "foo.py"
        src_file.parent.mkdir(parents=True)
        src_file.write_text("def myfunc():\n    return 1\n    # end\n")

        parsed_file = _make_parsed_file([self._sym()], file_path="app/foo.py")
        parsed_files = {"app/foo.py": parsed_file}

        mock_store = MagicMock()
        chunker = self._chunker()
        chunker.embed_symbols(
            project_id="proj-1",
            parsed_files=parsed_files,
            repo_dir=tmp_path,
            vector_store=mock_store,
        )

        assert mock_store.add_documents.called
        kwargs = mock_store.add_documents.call_args
        assert kwargs is not None
        kw = (
            kwargs.kwargs
            if kwargs.kwargs
            else dict(
                zip(
                    ("project_id", "doc_ids", "documents", "metadatas"),
                    kwargs.args,
                )
            )
        )
        assert kw["project_id"] == "proj-1"
        assert len(kw["doc_ids"]) >= 1
        assert len(kw["documents"]) == len(kw["doc_ids"])
        assert len(kw["metadatas"]) == len(kw["doc_ids"])
        for meta in kw["metadatas"]:
            validate_chunk_metadata(meta)

    def test_embed_symbols_noop_when_no_parsed_files(self) -> None:
        mock_store = MagicMock()
        chunker = self._chunker()
        chunker.embed_symbols(
            project_id="proj-1",
            parsed_files={},
            repo_dir=Path("/tmp"),
            vector_store=mock_store,
        )
        mock_store.add_documents.assert_not_called()

    def test_embed_symbols_skips_missing_file(self, tmp_path: Path) -> None:
        """If a source file doesn't exist on disk, the symbol is skipped silently."""
        parsed_file = _make_parsed_file([self._sym()])
        parsed_files = {"app/foo.py": parsed_file}

        mock_store = MagicMock()
        chunker = self._chunker()
        # repo_dir has no app/foo.py → must not raise
        chunker.embed_symbols(
            project_id="proj-2",
            parsed_files=parsed_files,
            repo_dir=tmp_path,
            vector_store=mock_store,
        )
        # No documents upserted because the only source was missing
        mock_store.add_documents.assert_not_called()

    def test_embed_symbols_stable_doc_ids(self, tmp_path: Path) -> None:
        """Doc IDs must be deterministic (same run → same IDs, enable upsert idempotency)."""
        src_file = tmp_path / "app" / "foo.py"
        src_file.parent.mkdir(parents=True)
        src_file.write_text("def myfunc():\n    return 1\n    # end\n")

        parsed_file = _make_parsed_file([self._sym()], file_path="app/foo.py")
        parsed_files = {"app/foo.py": parsed_file}

        mock_store = MagicMock()
        chunker = self._chunker()

        chunker.embed_symbols(
            project_id="proj-3",
            parsed_files=parsed_files,
            repo_dir=tmp_path,
            vector_store=mock_store,
        )
        ids_first = list(mock_store.add_documents.call_args.kwargs["doc_ids"])

        mock_store.reset_mock()
        chunker.embed_symbols(
            project_id="proj-3",
            parsed_files=parsed_files,
            repo_dir=tmp_path,
            vector_store=mock_store,
        )
        ids_second = list(mock_store.add_documents.call_args.kwargs["doc_ids"])

        assert ids_first == ids_second

    def test_embed_symbols_multiple_files(self, tmp_path: Path) -> None:
        """embed_symbols processes all files and batches into one add_documents call."""
        for name in ("a.py", "b.py"):
            f = tmp_path / name
            f.write_text("def func():\n    pass\n")

        parsed_files = {
            "a.py": _make_parsed_file([_make_symbol("fa", file_path="a.py")], "a.py"),
            "b.py": _make_parsed_file([_make_symbol("fb", file_path="b.py")], "b.py"),
        }
        mock_store = MagicMock()
        chunker = self._chunker()
        chunker.embed_symbols(
            project_id="proj-4",
            parsed_files=parsed_files,
            repo_dir=tmp_path,
            vector_store=mock_store,
        )
        # Should have called add_documents at least once, total docs >= 2
        assert mock_store.add_documents.called
        all_docs: list[str] = []
        for c in mock_store.add_documents.call_args_list:
            kw = (
                c.kwargs
                if c.kwargs
                else dict(zip(("project_id", "doc_ids", "documents", "metadatas"), c.args))
            )
            all_docs.extend(kw["documents"])
        assert len(all_docs) >= 2

    def test_embed_symbols_no_symbols_in_file(self, tmp_path: Path) -> None:
        """A ParsedFile with no symbols produces no store calls."""
        f = tmp_path / "empty.py"
        f.write_text("# nothing here\n")
        parsed_files = {
            "empty.py": _make_parsed_file([], file_path="empty.py"),
        }
        mock_store = MagicMock()
        chunker = self._chunker()
        chunker.embed_symbols(
            project_id="proj-5",
            parsed_files=parsed_files,
            repo_dir=tmp_path,
            vector_store=mock_store,
        )
        mock_store.add_documents.assert_not_called()
