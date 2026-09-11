"""Three indexing steps reported success for work they did not do (KNOW-05, 07, 08).

P1 row 9, first seam. The three share a shape the rest of this programme keeps meeting: a
step that cannot fail is a step whose green tells you nothing.

**KNOW-05 — a parser outage wipes the code graph and the run reports "complete".**
`_run_graph_build` skips only when `parsed_files` is *empty*. A `ParsedFile` carrying
`parse_errors` and zero symbols is still stored, so on a full rebuild `parsed_files` is
non-empty while `graph.symbols` is empty — and `save()` deletes every symbol and edge before
inserting nothing. The **incremental** path has had the guard for this since R3-3; the full
path, which is the one a fingerprint bump and every `force_full` take, never got it.

**KNOW-07 — `code_symbol_embed` counts its input.** Three layers turn a failure into a
non-event: `_flush` catches per 200-chunk batch and continues, `_run_code_symbol_embed`
catches everything above that, and the count it logs is computed from `parsed_files` rather
than from what the store accepted. Then `complete_step` runs unconditionally. A vector store
rejecting every write produces log warnings and a checkpoint that says the step is done.

**KNOW-08 — the nightly incremental silently continues an abandoned full rebuild.**
`_run_index_background` reuses whatever `IndexingCheckpoint` exists whenever `force_full` is
false, with no record of how that checkpoint was produced. A checkpoint left by an
interrupted `force_full=True` run carries `last_sha = None` and the entire blob list as
`changed_files`, so the nightly run — budgeted at 7 200 s for an incremental — resumes a full
rebuild that measures 5 600–12 300 s, under the wrong ceiling and calling itself incremental.
"""

from __future__ import annotations

import ast
import inspect

from app.knowledge import pipeline_runner as pr


def _fn_source(name: str) -> str:
    import textwrap

    return textwrap.dedent(inspect.getsource(getattr(pr.IndexingPipelineRunner, name)))


class TestAParserOutageDoesNotWipeTheGraph:
    """KNOW-05."""

    def test_the_full_path_has_a_zero_symbol_guard(self) -> None:
        source = _fn_source("_run_graph_build")
        tree = ast.parse(source.replace("async def", "def", 1))
        # Both halves of the condition: the incremental branch has had a `graph.symbols`
        # guard since R3-3, so looking only for that finds the wrong one.
        guards = [
            ast.unparse(n)
            for n in ast.walk(tree)
            if isinstance(n, ast.If)
            and "graph.symbols" in ast.unparse(n.test)
            and "is_full" in ast.unparse(n.test)
        ]
        assert guards, (
            "the full-rebuild path saves whatever the builder produced. A parse that "
            "errored on every file yields zero symbols, and `save()` deletes every symbol "
            "and edge before inserting nothing — the graph is gone and the step reports "
            "success (KNOW-05)"
        )

    def test_the_guard_is_not_only_on_the_incremental_branch(self) -> None:
        """The incremental path has had this since R3-3; the defect is that the full one
        — taken by every `force_full` and every fingerprint bump — did not."""
        source = _fn_source("_run_graph_build")
        head = source.split("if is_full:")[0]
        assert "graph.symbols" in head or "_graph_is_empty" in head, (
            "the zero-symbol check sits inside the incremental branch only"
        )


class TestTheEmbedStepCountsWhatItWrote:
    """KNOW-07."""

    def test_the_step_does_not_checkpoint_after_a_failure(self) -> None:
        """The CALLER has to gate on the verdict — checking the callee's shape is not enough.

        The first version of this test asserted `"return False" in` the step's own source,
        and a planted defect walked straight past it: deleting the `if embedded_ok:` gate in
        the caller leaves the callee untouched. The seam is where the checkpoint is written,
        so that is where the assertion belongs.
        """
        source = _fn_source("_run_steps")
        tree = ast.parse(source.replace("async def", "def", 1))
        # Find the `if` whose OWN BODY writes the checkpoint for this step, and read ITS
        # test. Matching anywhere inside a node finds the enclosing block instead — which
        # is how the second draft of this guard also passed against the planted defect.
        gated = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            direct = "".join(ast.unparse(st) for st in node.body)
            if "complete_step" in direct and "code_symbol_embed" in direct:
                if "embedded" in ast.unparse(node.test):
                    gated = True
        assert gated, (
            "`complete_step(..., 'code_symbol_embed')` runs unconditionally after the step. "
            "A store that rejected every batch then leaves a checkpoint saying the step is "
            "done, and every later resume skips it (KNOW-07)"
        )

    def test_the_count_comes_from_the_store_not_from_the_input(self) -> None:
        source = _fn_source("_run_code_symbol_embed")
        assert "written" in source or "upserted" in source, (
            "the reported symbol count is computed from `parsed_files` — the work asked "
            "for, not the work done. A store that rejected everything reports the same "
            "number as one that accepted everything"
        )

    def test_the_chunker_reports_how_many_it_actually_upserted(self) -> None:
        from app.knowledge.code_symbol_chunker import CodeSymbolChunker

        source = inspect.getsource(CodeSymbolChunker)
        assert "_written" in source or "upserted" in source, (
            "the per-batch `except` continues the loop with no count of what survived, so "
            "nothing above it can tell a partial write from a complete one"
        )


class TestAFullRebuildCheckpointIsNotResumedAsIncremental:
    """KNOW-08."""

    def test_the_checkpoint_records_how_it_was_produced(self) -> None:
        from app.models.indexing_checkpoint import IndexingCheckpoint

        assert hasattr(IndexingCheckpoint, "force_full"), (
            "nothing on the checkpoint says whether it came from a full rebuild, so a "
            "resume cannot tell one from an incremental (KNOW-08)"
        )

    def test_the_resume_path_refuses_a_full_checkpoint(self) -> None:
        """The condition that decides to reuse a checkpoint must read how it was produced.

        Asserting that the word `force_full` appears somewhere in the function is not that
        assertion — `body.force_full` is already there for the caller's own request, so the
        planted defect (dropping `existing_cp.force_full is False` from the reuse condition)
        passed. The check is on the reuse branch's TEST expression.
        """
        import pathlib

        repos = pathlib.Path(inspect.getfile(pr)).parents[1] / "api" / "routes" / "repos.py"
        tree = ast.parse(repos.read_text(encoding="utf-8"))
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
            and n.name == "_run_index_background"
        )
        # The branch that RESUMES is the one whose body assigns `checkpoint = existing_cp`.
        # Collecting every `if` that merely mentions `existing_cp` also collects the log
        # line above it — which still names `force_full`, so the second draft of this guard
        # passed against the planted defect too.
        reuse_conditions = [
            ast.unparse(node.test)
            for node in ast.walk(fn)
            if isinstance(node, ast.If)
            and any(
                isinstance(st, ast.Assign) and "existing_cp" in ast.unparse(st.value)
                for st in node.body
            )
        ]
        assert reuse_conditions, "the checkpoint-reuse branch is gone; this guard is blind"
        assert any("existing_cp.force_full" in cond for cond in reuse_conditions), (
            "no branch consults how the checkpoint it is about to resume was produced. An "
            "abandoned full rebuild then resumes as the nightly incremental — 5 600–12 300 s "
            f"of work under a 7 200 s ceiling. Conditions seen: {reuse_conditions}"
        )
