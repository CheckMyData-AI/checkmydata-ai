"""Unit tests for CodeGraphBuilder.reverse_dependents (CODEIDX-C4).

Verifies that the helper correctly identifies files that import a symbol from
a changed file so they can be re-parsed on incremental runs.
"""

from __future__ import annotations

from app.knowledge.ast_parser import Symbol
from app.knowledge.code_graph import EDGE_IMPORTS, CodeGraph, CodeGraphBuilder, GraphEdge


def _sym(uid: str, file_path: str) -> Symbol:
    return Symbol(
        uid=uid,
        kind="function",
        name=uid.split(":")[-2],
        file_path=file_path,
        start_line=1,
        end_line=2,
        language="python",
    )


def test_reverse_dependents_finds_importers_of_changed_file() -> None:
    # b.py imports helper from a.py  ->  changing a.py must re-parse b.py.
    a = _sym("python:a.py:function:helper", "a.py")
    b = _sym("python:b.py:function:driver", "b.py")
    edges = [GraphEdge(src_uid="file:b.py", dst_uid=a.uid, edge_type=EDGE_IMPORTS, confidence=1.0)]
    graph = CodeGraph(symbols=[a, b], edges=edges)

    deps = CodeGraphBuilder.reverse_dependents(graph, {"a.py"})

    assert deps == {"b.py"}


def test_reverse_dependents_excludes_changed_files_and_unrelated() -> None:
    a = _sym("python:a.py:function:helper", "a.py")
    c = _sym("python:c.py:function:lonely", "c.py")
    graph = CodeGraph(symbols=[a, c], edges=[])
    assert CodeGraphBuilder.reverse_dependents(graph, {"a.py"}) == set()


def test_reverse_dependents_empty_changed_set() -> None:
    a = _sym("python:a.py:function:helper", "a.py")
    graph = CodeGraph(symbols=[a], edges=[])
    assert CodeGraphBuilder.reverse_dependents(graph, set()) == set()


def test_reverse_dependents_sym_uid_src() -> None:
    # IMPORTS edge with a symbol UID as src (not "file:" prefix) is also handled.
    a = _sym("python:a.py:function:helper", "a.py")
    b = _sym("python:b.py:function:driver", "b.py")
    edges = [GraphEdge(src_uid=b.uid, dst_uid=a.uid, edge_type=EDGE_IMPORTS, confidence=1.0)]
    graph = CodeGraph(symbols=[a, b], edges=edges)

    deps = CodeGraphBuilder.reverse_dependents(graph, {"a.py"})

    assert deps == {"b.py"}


def test_reverse_dependents_does_not_include_changed_file_itself() -> None:
    # a.py imports from itself (degenerate) — should not be in result.
    a = _sym("python:a.py:function:helper", "a.py")
    edges = [GraphEdge(src_uid="file:a.py", dst_uid=a.uid, edge_type=EDGE_IMPORTS, confidence=1.0)]
    graph = CodeGraph(symbols=[a], edges=edges)

    deps = CodeGraphBuilder.reverse_dependents(graph, {"a.py"})

    assert deps == set()


def test_reverse_dependents_multiple_importers() -> None:
    # Both b.py and c.py import from a.py.
    a = _sym("python:a.py:function:helper", "a.py")
    b = _sym("python:b.py:function:b_fn", "b.py")
    c = _sym("python:c.py:function:c_fn", "c.py")
    edges = [
        GraphEdge(src_uid="file:b.py", dst_uid=a.uid, edge_type=EDGE_IMPORTS, confidence=1.0),
        GraphEdge(src_uid="file:c.py", dst_uid=a.uid, edge_type=EDGE_IMPORTS, confidence=1.0),
    ]
    graph = CodeGraph(symbols=[a, b, c], edges=edges)

    deps = CodeGraphBuilder.reverse_dependents(graph, {"a.py"})

    assert deps == {"b.py", "c.py"}
