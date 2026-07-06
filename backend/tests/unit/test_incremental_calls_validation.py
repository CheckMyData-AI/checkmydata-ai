"""Validation lock (CODEIDX-C4): incremental merge re-resolves cross-file CALLS edges.

Verifies the fix for the graph-drift bug in CodeGraphService._merge_graphs:

Wave 6 fix: on incremental runs the pipeline now expands the re-parse set to include
reverse-dependents of changed files (files that import symbols from changed files).
`CodeGraphBuilder.reverse_dependents` identifies caller.py as a reverse-dependent of
helper.py, so caller.py IS re-parsed.  The new_graph passed to save_incremental therefore
contains a fresh CALLS edge from caller() to new_helper(), and `affected_files` includes
caller.py so the stale edge is dropped before the fresh one is spliced in.

Result: the merged graph has exactly one CALLS edge from caller to new_helper.
"""

from __future__ import annotations

from app.knowledge.ast_parser import Symbol
from app.knowledge.code_graph import (
    EDGE_CALLS,
    EDGE_IMPORTS,
    CodeGraph,
    CodeGraphBuilder,
    GraphEdge,
)
from app.services.code_graph_service import CodeGraphService


def _sym(uid: str, path: str) -> Symbol:
    return Symbol(
        uid=uid,
        kind="function",
        name=uid.split(":")[-1],
        file_path=path,
        start_line=1,
        end_line=5,
    )


def test_incremental_merge_relinks_unchanged_caller_edge_codeidx_c4() -> None:
    """CODEIDX-C4 fix: after reverse-dep re-parse, the unchanged caller retains its CALLS edge.

    Simulates the full incremental path:
    1. reverse_dependents identifies caller.py as importer of helper.py
    2. caller.py is included in the re-parse set, so new_graph contains its updated CALLS edge
    3. affected_files includes caller.py so its stale edges are pruned before splice-in
    """
    # Existing graph: caller.py defines caller() which CALLS old_helper() in helper.py.
    # caller.py also has an IMPORTS edge to old_helper (simulating the import statement).
    caller = _sym("caller.py:caller", "caller.py")
    old_helper = _sym("helper.py:old_helper", "helper.py")
    existing = CodeGraph(
        symbols=[caller, old_helper],
        edges=[
            GraphEdge(
                src_uid=caller.uid,
                dst_uid=old_helper.uid,
                edge_type=EDGE_CALLS,
                confidence=1.0,
            ),
            GraphEdge(
                src_uid="file:caller.py",
                dst_uid=old_helper.uid,
                edge_type=EDGE_IMPORTS,
                confidence=1.0,
            ),
        ],
    )

    # helper.py changed: old_helper removed, new_helper added.
    new_helper = _sym("helper.py:new_helper", "helper.py")
    changed = {"helper.py"}

    # Wave 6 fix: identify caller.py as reverse-dependent (it imports from helper.py).
    extra_files = CodeGraphBuilder.reverse_dependents(existing, changed)
    assert "caller.py" in extra_files, "reverse_dependents must flag caller.py for re-parse"

    # Simulate re-parse of caller.py: it now calls new_helper (re-resolved).
    # new_graph contains both the changed callee AND the re-parsed caller.
    new_graph = CodeGraph(
        symbols=[new_helper, caller],
        edges=[
            GraphEdge(
                src_uid=caller.uid,
                dst_uid=new_helper.uid,
                edge_type=EDGE_CALLS,
                confidence=1.0,
            ),
            GraphEdge(
                src_uid="file:caller.py",
                dst_uid=new_helper.uid,
                edge_type=EDGE_IMPORTS,
                confidence=1.0,
            ),
        ],
    )

    # affected_files = changed + reverse-dependents (both pruned before splice-in).
    affected_files = changed | extra_files
    merged = CodeGraphService._merge_graphs(existing, new_graph, affected_files)

    merged_uids = {s.uid for s in merged.symbols.values()}
    assert "caller.py:caller" in merged_uids
    assert "helper.py:new_helper" in merged_uids
    assert "helper.py:old_helper" not in merged_uids

    # FIX CODEIDX-C4: unchanged caller now has a CALLS edge to new_helper after re-parse.
    calls_into_new_helper = [
        e for e in merged.edges if e.dst_uid == "helper.py:new_helper" and e.edge_type == EDGE_CALLS
    ]
    assert calls_into_new_helper, (
        "CODEIDX-C4: caller() must have a CALLS edge to new_helper after reverse-dep re-parse"
    )
