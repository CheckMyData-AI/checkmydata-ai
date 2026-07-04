"""Validation lock: incremental merge misses new cross-file CALLS edges (CODEIDX-C4).

Pins the graph-drift bug in CodeGraphService._merge_graphs:

When helper.py changes (old_helper removed, new_helper added), caller.py is NOT re-parsed
because it is unchanged.  _merge_graphs keeps existing edges from unchanged files — but the
existing CALLS edge pointed at old_helper (now removed), so it is pruned as dangling.
No new CALLS edge from caller to new_helper is created because caller.py was not re-parsed.
Result: the merged graph correctly drops old_helper but has NO edge from caller to new_helper.

Wave 6 will re-resolve reverse-dependencies (re-parse callers of symbols in affected files)
to fix this. When that fix lands, the final assertion (calls_into_new_helper == []) should
be flipped.
"""

from __future__ import annotations

from app.knowledge.ast_parser import Symbol
from app.knowledge.code_graph import CodeGraph, GraphEdge
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


def test_incremental_merge_misses_unchanged_caller_edge_codeidx_c4() -> None:
    # existing graph: caller.py defines caller() (UNCHANGED); helper.py defines old_helper().
    caller = _sym("caller.py:caller", "caller.py")
    old_helper = _sym("helper.py:old_helper", "helper.py")
    existing = CodeGraph(
        symbols=[caller, old_helper],
        edges=[
            GraphEdge(
                src_uid=caller.uid,
                dst_uid=old_helper.uid,
                edge_type="CALLS",
                confidence=1.0,
            )
        ],
    )
    # helper.py changed: old_helper removed, new_helper added. caller.py NOT re-parsed.
    new_helper = _sym("helper.py:new_helper", "helper.py")
    new_graph = CodeGraph(symbols=[new_helper], edges=[])

    merged = CodeGraphService._merge_graphs(existing, new_graph, {"helper.py"})

    merged_uids = {s.uid for s in merged.symbols.values()}
    assert "caller.py:caller" in merged_uids
    assert "helper.py:new_helper" in merged_uids
    assert "helper.py:old_helper" not in merged_uids
    # BUG CODEIDX-C4: caller() still (semantically) calls the helper, but there is NO CALLS edge
    # into new_helper because caller.py was not re-parsed.  Documents the drift.
    calls_into_new_helper = [
        e for e in merged.edges if e.dst_uid == "helper.py:new_helper" and e.edge_type == "CALLS"
    ]
    assert calls_into_new_helper == []  # <-- Wave 6 will re-resolve reverse-deps to fix this
