"""What a BM25 corpus contains was defined twice, in two processes (S1).

`pipeline_runner._run_bm25_build` and `ops/bm25_local_reconcile._build_one` each
looped `KnowledgeDoc -> chunk_document -> (id, content, metadata)` independently.
The same shape, written twice, and the two run in **different processes**: the
builder on `worker`, the reconcile on `web` — which is the whole reason the
reconcile exists (F-KNOW-12: separate Heroku process types, separate disks).

So a change to what a document *is* that reached one and not the other would
make the reader's corpus differ from the writer's, and the symptom — retrieval
behaving differently depending on whether the snapshot came from an index run or
a boot reconcile — is close to undiagnosable.

Nothing was wrong with either copy today. This exists because the next change to
the corpus is already planned (symbol documents, board row 2.2), and a
definition living in two places is one that will be edited in one.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass
from pathlib import Path

from app.knowledge.bm25_corpus import corpus_entries_for_docs


@dataclass
class _Doc:
    """Duck-typed stand-in: the corpus builder must not need the ORM."""

    id: str
    content: str
    source_path: str
    doc_type: str


class TestTheDefinition:
    def test_one_document_becomes_at_least_one_entry(self):
        entries = corpus_entries_for_docs(
            [
                _Doc(
                    id="d1",
                    content="The sync resolver lives here.",
                    source_path="a.py",
                    doc_type="orm_model",
                )
            ]
        )
        assert entries, "a document with content must produce at least one corpus entry"

    def test_the_id_is_the_convention_both_legs_share(self):
        """RRF fuses on `doc_id` (`hybrid_retriever.py:269`), and the vector store
        writes prose chunks as `f"{doc.id}:{chunk_index}"` (`pipeline_runner.py:1214`).
        A different id here would make the same chunk two documents and split its
        rank instead of reinforcing it."""
        entries = corpus_entries_for_docs(
            [_Doc(id="d1", content="x y z", source_path="a.py", doc_type="raw_sql")]
        )
        assert entries[0][0].startswith("d1:")

    def test_metadata_carries_the_source_path_and_doc_type(self):
        entries = corpus_entries_for_docs(
            [_Doc(id="d1", content="x y z", source_path="pkg/a.py", doc_type="migration")]
        )
        meta = entries[0][2]
        assert meta["source_path"] == "pkg/a.py"
        assert meta["doc_type"] == "migration"

    def test_an_empty_document_contributes_nothing(self):
        assert (
            corpus_entries_for_docs(
                [_Doc(id="d1", content="", source_path="a.py", doc_type="raw_sql")]
            )
            == []
        )


class TestBothProcessesAskIt:
    """The point of the module. A source-level check, because the two callers
    live in different processes and no runtime test sees both at once."""

    def test_the_pipeline_builder_uses_it(self):
        src = Path("app/knowledge/pipeline_runner.py").read_text(encoding="utf-8")
        assert "corpus_entries_for_docs" in src

    def test_the_boot_reconcile_uses_it(self):
        src = Path("app/ops/bm25_local_reconcile.py").read_text(encoding="utf-8")
        assert "corpus_entries_for_docs" in src

    def test_the_bm25_builders_do_not_chunk_documents_themselves(self):
        """An inline loop left inside a BM25 builder is how the two drift back.

        Scoped to the two functions that build a snapshot, and **not** to the
        whole file: `pipeline_runner` legitimately calls `chunk_document` twice
        more on the embed path (`:1208`, `:1288`), writing the vector store. A
        first draft of this test forbade the call anywhere in the file and was
        simply wrong — the code was right and the assertion was too wide.

        That third site matters and is the reason this one is narrow rather than
        deleted: it writes prose chunks with the **same** `f"{doc.id}:{idx}"` id
        this corpus produces, which is what lets `HybridRetriever._fuse` merge
        the legs at all. Three chunking sites, one id convention, and only the
        two BM25 ones share a definition.
        """
        offenders = []
        for path, func in (
            ("app/knowledge/pipeline_runner.py", "_run_bm25_build"),
            ("app/ops/bm25_local_reconcile.py", "_build_one"),
        ):
            tree = ast.parse(Path(path).read_text(encoding="utf-8"))
            target = next(
                (
                    n
                    for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func
                ),
                None,
            )
            assert target is not None, f"{path} no longer defines {func}"
            for node in ast.walk(target):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "chunk_document"
                ):
                    offenders.append(f"{path}:{node.lineno} ({func})")
        assert not offenders, (
            f"these build corpus entries themselves instead of asking the shared "
            f"definition: {offenders}"
        )


class TestItDoesNotDragTheOrmIn:
    def test_the_module_imports_no_model(self):
        """Duck-typed on purpose: the reconcile and the pipeline pass different
        row objects, and a test should not need a database to check the shape."""
        src = Path(inspect.getfile(corpus_entries_for_docs)).read_text(encoding="utf-8")
        model_imports = {
            n.module
            for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("app.models")
        }
        assert not model_imports, f"expected no model import; found {model_imports}"
