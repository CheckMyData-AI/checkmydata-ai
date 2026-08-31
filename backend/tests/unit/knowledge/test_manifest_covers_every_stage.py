"""A 26-minute stage was missing from the manifest, so progress stood still through it.

`RunCoordinator._record` looks a step up in the run's manifest and journals it without
touching `current_step` when it is absent (`run_coordinator.py:530-536`). `code_symbol_embed`
was absent, so for the whole of it — measured at 2 300 s on the 9 981-file repository, and
26.5 min on the 2026-08-31 rebuild — `current_step` still read `graph_build` and
`progress_pct` did not move. An operator watching a three-hour run saw it stall.

The fix is not two names. It is this test: every stage-level step the pipeline emits must
be either in a manifest or on the journal-only list below, with a reason. Adding a stage
and forgetting the manifest is otherwise invisible — the run completes, nothing errors,
and only the progress bar lies.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).parents[3]

#: Emitted keys that deliberately never reach `current_step`.
#:
#: A manifest entry is a promise the step runs on a normal pass, because `total_steps`
#: divides the progress bar by it. These break that promise in two different ways, so
#: each is listed with which one.
JOURNAL_ONLY: dict[str, str] = {
    # Sub-events of `generate_docs`, emitted per document. They report *within* a step
    # that is already in the manifest; promoting them would make one stage read as three.
    "generate_docs.doc_failed": "per-document sub-event of generate_docs",
    "generate_docs.partial_completion": "per-document sub-event of generate_docs",
    # Control markers, not work. `no_changes` says the pipeline stopped early;
    # `pipeline_resume` says it started late.
    "no_changes": "control marker — the run is ending, not progressing",
    "pipeline_resume": "control marker — a resume, not a stage",
    # Data-conditional repair: it fires only when the embedding store is found corrupt.
    # In the manifest it would divide every healthy run's progress by a step that never
    # runs, which is the same lie in the other direction.
    "repair_embeddings": "fires only on detected corruption, not on a normal pass",
}


def _emitted_step_keys() -> set[str]:
    """Every key `pipeline_runner` passes to `tracker.step`/`tracker.emit`."""
    tree = ast.parse((BACKEND / "app" / "knowledge" / "pipeline_runner.py").read_text("utf-8"))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) in ("step", "emit"):
            for arg in node.args[1:2]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    keys.add(arg.value)
    return keys


def _manifest_step_keys() -> set[str]:
    tree = ast.parse((BACKEND / "app" / "knowledge" / "run_manifests.py").read_text("utf-8"))
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "Step"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }


def test_the_scan_finds_something() -> None:
    """Guard on the guard: a regex or AST walk that silently matches nothing would make
    every assertion below pass vacuously."""
    emitted = _emitted_step_keys()
    assert len(emitted) >= 15, f"the emit scan found only {len(emitted)} keys; it broke"
    assert "code_symbol_embed" in emitted
    assert len(_manifest_step_keys()) >= 25


def test_every_emitted_stage_is_in_a_manifest_or_declared_journal_only() -> None:
    unaccounted = sorted(_emitted_step_keys() - _manifest_step_keys() - set(JOURNAL_ONLY))
    assert not unaccounted, (
        f"{unaccounted} are emitted but reach no manifest, so `current_step` freezes and "
        "`progress_pct` stalls for their whole duration. Add each to a manifest, or to "
        "JOURNAL_ONLY with the reason it is not a stage."
    )


def test_the_longest_stage_is_covered() -> None:
    """Named on its own because it is the one that was missing, and the one where the
    absence cost most: 26.5 minutes of a 3.3-hour run reporting no movement."""
    assert "code_symbol_embed" in _manifest_step_keys()


def test_journal_only_entries_are_not_also_in_a_manifest() -> None:
    """Both lists is a contradiction — the key would move `current_step` while claiming
    it should not."""
    overlap = sorted(set(JOURNAL_ONLY) & _manifest_step_keys())
    assert not overlap, f"{overlap} are declared journal-only and also manifest steps"


@pytest.mark.parametrize("flag", ["hybrid_retrieval_enabled"])
def test_the_new_step_is_gated_on_the_flag_that_actually_guards_it(flag) -> None:
    """`code_symbol_embed` runs under `settings.hybrid_retrieval_enabled`
    (`pipeline_runner.py:610`). Listing it under a different flag would put a step in the
    manifest that the pipeline then skips — progress that never reaches 100%."""
    from app.knowledge.run_manifests import resolve_manifest

    on = {s.key for s in resolve_manifest("index_repo", flags={flag: True})}
    off = {s.key for s in resolve_manifest("index_repo", flags={flag: False})}
    assert "code_symbol_embed" in on
    assert "code_symbol_embed" not in off


def test_it_sits_where_it_runs() -> None:
    """The manifest is ordered, and `step_position` drives `progress_pct`. Out of order,
    the bar would jump backwards."""
    from app.knowledge.run_manifests import resolve_manifest

    keys = [
        s.key
        for s in resolve_manifest(
            "index_repo", flags={"code_graph_enabled": True, "hybrid_retrieval_enabled": True}
        )
    ]
    assert keys.index("graph_build") < keys.index("code_symbol_embed")
    assert keys.index("code_symbol_embed") < keys.index("bm25_build")


# ---------------------------------------------------------------------------
# Order, and the label the user actually reads
# ---------------------------------------------------------------------------


def test_progress_never_moves_backwards() -> None:
    """`progress_for` weighs the manifest PREFIX, so the list must be in execution order.

    It was not: flag-gated steps were appended after the unconditional ones, and the live
    rebuild of 2026-08-31 (run `3a0fdd16`) reported 86 % at `graph_build`, then **36 %**
    at `analyze_files`, then 100 % at `graph_db_bridge` — where it sat for the 2.6 hours
    `generate_docs` takes. A bar that goes backwards is worse than no bar: it is read as
    the job restarting.
    """
    from app.knowledge.run_manifests import progress_for, resolve_manifest, step_position

    flags = {
        "code_graph_enabled": True,
        "hybrid_retrieval_enabled": True,
        "schema_retrieval_enabled": True,
        "lineage_enabled": True,
        "clustering_enabled": True,
    }
    manifest = resolve_manifest("index_repo", flags=flags)
    seen = [progress_for(manifest, step_position(manifest, s.key)) for s in manifest]
    assert seen == sorted(seen), f"progress moves backwards: {seen}"
    assert seen[-1] == 100, f"the run ends at {seen[-1]}%, not 100%"


def test_the_order_matches_the_journal_of_a_real_run() -> None:
    """Pinned to observed order, not to the source file's line numbers — several steps are
    emitted from helpers defined far from where they are called, so reading the source
    gives a different and wrong answer."""
    from app.knowledge.run_manifests import resolve_manifest

    keys = [
        s.key
        for s in resolve_manifest(
            "index_repo",
            flags={
                "code_graph_enabled": True,
                "hybrid_retrieval_enabled": True,
                "lineage_enabled": True,
            },
        )
    ]
    observed = [
        "resolve_ssh_key",
        "clone_or_pull",
        "detect_changes",
        "project_profile",
        "ast_parse",
        "graph_build",
        "code_symbol_embed",
        "analyze_files",
        "cross_file_analysis",
        "graph_db_bridge",
        "generate_docs",
    ]
    positions = [keys.index(k) for k in observed]
    assert positions == sorted(positions), (
        f"manifest order disagrees with the journal of run 3a0fdd16: {keys}"
    )


def test_every_manifest_step_has_a_label_the_user_can_read() -> None:
    """`ActiveTasksWidget` falls back to `|| task.currentStep`, so a missing label shows
    the raw key and never looks broken enough to report. Every flag-gated step was
    missing, which is what a run in `code_symbol_embed` displayed for 26 minutes."""
    import re

    from app.knowledge.run_manifests import _BASE, resolve_manifest

    labels_ts = BACKEND.parent / "frontend" / "src" / "components" / "tasks" / "stepLabels.ts"
    text = labels_ts.read_text("utf-8")
    # `[a-z0-9_]+`, not `[a-z_]+`: the first version silently skipped `bm25_build` —
    # a key-name scan that drops keys containing digits reports a pass it never made.
    labelled = set(re.findall(r"^\s{2}([a-z0-9_]+):\s*\"", text, re.MULTILINE))
    assert len(labelled) >= 25, f"the label scan found only {len(labelled)}; it broke"

    every_flag = dict.fromkeys(
        [
            "code_graph_enabled",
            "hybrid_retrieval_enabled",
            "schema_retrieval_enabled",
            "lineage_enabled",
            "clustering_enabled",
        ],
        True,
    )
    keys = {s.key for s in resolve_manifest("index_repo", flags=every_flag)}
    for kind in _BASE:
        keys |= {s.key for s in resolve_manifest(kind)}
    missing = sorted(keys - labelled)
    assert not missing, f"{missing} have no label; the UI will print the raw key"
