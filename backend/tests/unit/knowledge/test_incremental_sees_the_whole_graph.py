"""An incremental run resolved against the batch and forgot what it did not re-read.

P1 row 9, third seam; KNOW-04 and KNOW-06. Both have the same shape: the incremental path
treats "the files I re-read" as if it were "everything there is" — once when resolving calls,
once when deciding what still exists.

**KNOW-04 — every changed file loses its out-edges to unchanged files.** `_resolve_call`
resolves a callee through `file_local`, `import_map` and `global_index`, and all three are
built from the symbols of `parsed_files`. On an incremental run that holds only the changed
files, so a call from a changed file to a function in an unchanged one resolves to nothing
and the edge is not emitted — while `save_incremental` has already deleted the edges that
file owned. The graph therefore *loses* edges on every incremental run and regains them only
at the next full rebuild.

**KNOW-06 — a model deleted from a file it still owns never goes away.** `_incremental_update`
copies every cached entity whose name is absent from the freshly-extracted set, and the only
removal is for entities whose `file_path` is in `deleted_files`. Delete one model from a file
that still defines three others and the fourth stays in the knowledge forever: the file was
changed, not deleted, so nothing drops it — and it keeps being described to the agent as a
table that exists.
"""

from __future__ import annotations

import inspect

from app.knowledge.code_graph import CodeGraphBuilder
from app.knowledge.entity_extractor import _incremental_update


class TestCallsResolveAgainstTheMergedGraph:
    """KNOW-04."""

    def test_a_call_into_an_unparsed_file_still_produces_an_edge(self) -> None:
        """The behaviour, because the signature check passes for an ignored parameter.

        The first version of this class asserted that `build` *takes* `resolution_symbols`
        and that the pipeline *passes* it — both true while the loop that consumes it was
        planted out, and both green. Building a two-file case and looking for the edge is
        the only assertion that fails when the resolution does.
        """
        from app.knowledge.ast_parser import CallSite, ParsedFile, Symbol

        callee = Symbol(
            uid="py:app/service.py:function:do_work",
            kind="function",
            name="do_work",
            file_path="app/service.py",
            start_line=1,
            end_line=5,
        )
        caller = Symbol(
            uid="py:app/caller.py:function:handler",
            kind="function",
            name="handler",
            file_path="app/caller.py",
            start_line=1,
            end_line=9,
        )
        changed_only = {
            "app/caller.py": ParsedFile(
                file_path="app/caller.py",
                language="python",
                symbols=[caller],
                call_sites=[CallSite(caller_uid=caller.uid, callee_name="do_work", line=4)],
            )
        }
        builder = CodeGraphBuilder()

        without = builder.build(changed_only)
        with_context = builder.build(changed_only, resolution_symbols=[callee])

        def _calls_to(graph) -> list:
            return [e for e in graph.edges if e.dst_uid == callee.uid]

        assert not _calls_to(without), (
            "the premise of this test is wrong: the callee resolved without being given"
        )
        assert _calls_to(with_context), (
            "a call from a changed file into an unchanged one produced no edge even with "
            "the unchanged file's symbols supplied — and `save_incremental` has already "
            "deleted the edges that file owned, so the graph LOSES this edge on every "
            "incremental run (KNOW-04)"
        )

    def test_the_builder_accepts_symbols_it_did_not_parse(self) -> None:
        sig = inspect.signature(CodeGraphBuilder.build)
        assert "resolution_symbols" in sig.parameters, (
            "`build` resolves callees only against the symbols of the files it was handed. "
            "On an incremental run that is the changed files alone, so every call into an "
            "unchanged file resolves to nothing — and `save_incremental` has already "
            "deleted the edges that file owned (KNOW-04)"
        )

    def test_those_symbols_are_used_for_resolution_and_not_emitted(self) -> None:
        """They belong to files this run did not parse; emitting them would duplicate rows
        the merge is about to preserve."""
        source = inspect.getsource(CodeGraphBuilder.build)
        assert "resolution_symbols" in source
        emitted = source.split("resolution_symbols")[-1]
        assert "all_symbols.extend(resolution_symbols" not in emitted, (
            "symbols from unparsed files are being added to the graph's own symbol list"
        )

    def test_the_incremental_path_passes_the_existing_graph(self) -> None:
        from app.knowledge import pipeline_runner as pr

        source = inspect.getsource(pr.IndexingPipelineRunner._run_graph_build)
        assert "resolution_symbols" in source, (
            "the incremental branch already loads the pre-merge graph for the "
            "reverse-dependency closure and still builds without it"
        )

    def test_the_extraction_schema_was_bumped(self) -> None:
        """A resolver that starts seeing more needs a rebuild to see it everywhere.

        `save_incremental` merges by FILE, so a run that resolves better only fixes the
        files it happens to touch. `GRAPH_EXTRACTION_SCHEMA` rides `embedding_fingerprint`,
        which is what makes the deploy enqueue one idempotent full rebuild.
        """
        from app.knowledge.ast_parser import GRAPH_EXTRACTION_SCHEMA

        assert GRAPH_EXTRACTION_SCHEMA >= 3, (
            f"GRAPH_EXTRACTION_SCHEMA is {GRAPH_EXTRACTION_SCHEMA}; the CALLS resolver now "
            "sees symbols it could not see before, and nothing will rebuild the graph "
            "unless this moves"
        )


class TestWhyKnow06IsNotFixedHere:
    """KNOW-06 stays open, and this records the measurement that stopped it.

    The audit's fix direction reads: *"rebuild the per-file entity set on change: drop
    entities whose defining file no longer yields them."* That presumes `_incremental_update`
    re-extracts entities per **file**. It does not — `knowledge.entities` comes from
    `_extract_entities_from_schemas`, i.e. from the **database schemas**, and `file_path`
    only records where a matching model was once found.

    So "absent from the fresh set" cannot distinguish *the file stopped defining it* from
    *no schemas were passed to this run*, and dropping on that basis deletes live entities.
    Measured, not reasoned: implementing it that way turned
    `test_deleted_file_entities_removed` red on a **changed** file whose class is still
    present. Closing KNOW-06 needs a per-file model re-scan that does not exist yet.
    """

    def test_entities_come_from_schemas_not_from_the_changed_files(self) -> None:
        from pathlib import Path

        from app.knowledge.entity_extractor import EntityInfo, ProjectKnowledge

        cached = ProjectKnowledge()
        cached.entities["StillThere"] = EntityInfo(name="StillThere", file_path="app/models.py")

        merged = _incremental_update(
            repo_dir=Path("/nonexistent"),
            schemas=[],
            cached=cached,
            changed_files=["app/models.py"],
        )

        assert "StillThere" in merged.entities, (
            "an entity whose file was changed survives a run that was given no schemas — "
            "which is exactly why the obvious KNOW-06 fix cannot be applied here: with no "
            "schemas there is no fresh set to be absent from"
        )
