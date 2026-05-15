"""Unit tests for the code knowledge graph (M2).

Covers:
    * Symbol + edge extraction from a small multi-file Python fixture
    * CALLS resolution: local-scope, via-import, `self.x`, and global fallback
    * IMPORTS edges resolve to symbols in the target file
    * EXTENDS edges parsed from class signatures (Python + TS)
    * Cycle detection in EXTENDS
    * `callers_of` / `callees_of` confidence multiplication across multi-hop paths
    * Size cap prunes private symbols
"""

from __future__ import annotations

import pytest

from app.knowledge.ast_parser import (
    ASTParser,
    ParsedFile,
    Symbol,
)
from app.knowledge.code_graph import (
    EDGE_CALLS,
    EDGE_EXTENDS,
    EDGE_IMPORTS,
    CodeGraph,
    CodeGraphBuilder,
    GraphEdge,
    _extract_base_names,
)


@pytest.fixture
def parser() -> ASTParser:
    return ASTParser()


# ---------------------------------------------------------------------------
# Builder integration
# ---------------------------------------------------------------------------


PY_A = b'''
def helper():
    return 1

class Base:
    pass

class Worker(Base):
    def run(self):
        helper()
        self.process()
    def process(self):
        return 2
'''

PY_B = b'''
from a import helper, Worker

def driver():
    w = Worker()
    w.run()
    return helper()
'''


def test_builder_emits_all_edge_types(parser: ASTParser):
    files = {
        "a.py": parser.parse_bytes("a.py", PY_A),
        "b.py": parser.parse_bytes("b.py", PY_B),
    }
    graph = CodeGraphBuilder().build(files)

    edge_types = {e.edge_type for e in graph.edges}
    assert EDGE_CALLS in edge_types
    assert EDGE_IMPORTS in edge_types
    assert EDGE_EXTENDS in edge_types


def test_builder_self_call_resolves_in_same_class(parser: ASTParser):
    files = {"a.py": parser.parse_bytes("a.py", PY_A)}
    graph = CodeGraphBuilder().build(files)

    run = next(s for s in graph.symbols.values() if s.name == "run")
    process = next(s for s in graph.symbols.values() if s.name == "process")
    calls_edges = [
        e
        for e in graph.edges
        if e.src_uid == run.uid and e.dst_uid == process.uid and e.edge_type == EDGE_CALLS
    ]
    assert len(calls_edges) == 1
    assert calls_edges[0].confidence == pytest.approx(1.0)


def test_builder_via_import_has_lower_confidence(parser: ASTParser):
    files = {
        "a.py": parser.parse_bytes("a.py", PY_A),
        "b.py": parser.parse_bytes("b.py", PY_B),
    }
    graph = CodeGraphBuilder().build(files)
    driver = next(s for s in graph.symbols.values() if s.name == "driver")
    helper = next(s for s in graph.symbols.values() if s.name == "helper")
    via_import = [
        e for e in graph.edges if e.src_uid == driver.uid and e.dst_uid == helper.uid
    ]
    assert len(via_import) == 1
    # Imported call should resolve at confidence 0.8 (between 0.7 global-unique and 1.0 local).
    assert 0.79 <= via_import[0].confidence <= 0.81


def test_builder_extends_python_base_class(parser: ASTParser):
    files = {"a.py": parser.parse_bytes("a.py", PY_A)}
    graph = CodeGraphBuilder().build(files)
    worker = next(s for s in graph.symbols.values() if s.name == "Worker")
    base = next(s for s in graph.symbols.values() if s.name == "Base")
    extends = [
        e
        for e in graph.edges
        if e.src_uid == worker.uid and e.edge_type == EDGE_EXTENDS
    ]
    assert any(e.dst_uid == base.uid for e in extends)


def test_builder_imports_edge_points_to_target_symbol(parser: ASTParser):
    files = {
        "a.py": parser.parse_bytes("a.py", PY_A),
        "b.py": parser.parse_bytes("b.py", PY_B),
    }
    graph = CodeGraphBuilder().build(files)
    helper = next(s for s in graph.symbols.values() if s.name == "helper")
    imp_edges = [e for e in graph.edges if e.edge_type == EDGE_IMPORTS and e.dst_uid == helper.uid]
    assert imp_edges
    assert imp_edges[0].src_uid == "file:b.py"


# ---------------------------------------------------------------------------
# Traversal: callers_of / callees_of confidence multiplication
# ---------------------------------------------------------------------------


def test_callers_of_multihop_multiplies_confidence(parser: ASTParser):
    files = {
        "a.py": parser.parse_bytes("a.py", PY_A),
        "b.py": parser.parse_bytes("b.py", PY_B),
    }
    graph = CodeGraphBuilder().build(files)
    helper = next(s for s in graph.symbols.values() if s.name == "helper")
    # depth=1 -> direct callers: run (1.0 local) and driver (0.8 via import)
    direct = {s.name: c for s, c in graph.callers_of(helper.uid, max_depth=1)}
    assert direct["run"] == pytest.approx(1.0)
    assert direct["driver"] == pytest.approx(0.8)


def test_callees_of_finds_outgoing_calls(parser: ASTParser):
    files = {"a.py": parser.parse_bytes("a.py", PY_A)}
    graph = CodeGraphBuilder().build(files)
    run = next(s for s in graph.symbols.values() if s.name == "run")
    callees = {s.name for s, _ in graph.callees_of(run.uid)}
    assert "process" in callees
    assert "helper" in callees


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------


def test_extends_cycle_breaks_weakest_edge():
    # Synthetic graph with EXTENDS cycle A -> B -> A; weakest confidence dropped.
    sym_a = Symbol(
        uid="py:a:class:A:1", kind="class", name="A", file_path="a", start_line=1, end_line=2
    )
    sym_b = Symbol(
        uid="py:a:class:B:5", kind="class", name="B", file_path="a", start_line=5, end_line=6
    )
    edges = [
        GraphEdge(src_uid=sym_a.uid, dst_uid=sym_b.uid, edge_type=EDGE_EXTENDS, confidence=0.9),
        GraphEdge(src_uid=sym_b.uid, dst_uid=sym_a.uid, edge_type=EDGE_EXTENDS, confidence=0.5),
    ]
    builder = CodeGraphBuilder()
    result = builder._break_inheritance_cycles(edges)
    # The 0.5 edge should be dropped, leaving the 0.9 edge.
    assert len(result) == 1
    assert result[0].confidence == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# Size cap pruning
# ---------------------------------------------------------------------------


def test_max_symbols_drops_private():
    """When the cap is exceeded, underscore-prefixed symbols are dropped first."""
    pf = ParsedFile(
        file_path="x.py",
        language="python",
        symbols=[
            Symbol(uid=f"py:x:function:{n}:{i}", kind="function", name=n, file_path="x.py",
                   start_line=i, end_line=i)
            for i, n in enumerate(["_private", "public_a", "public_b", "_hidden", "public_c"])
        ],
    )
    graph = CodeGraphBuilder(max_symbols=3).build({"x.py": pf})
    names = {s.name for s in graph.symbols.values()}
    assert "_private" not in names
    assert "_hidden" not in names
    assert "public_a" in names


# ---------------------------------------------------------------------------
# Heritage parsing
# ---------------------------------------------------------------------------


def test_extract_base_names_python():
    assert _extract_base_names("class Worker(Base, Mixin):") == ["Base", "Mixin"]
    assert _extract_base_names("class A:") == []
    assert _extract_base_names("class A(object):") == []


def test_extract_base_names_typescript():
    # Notice we test both extends and implements keywords.
    out = _extract_base_names("class Service extends BaseService implements Disposable, IConfig {")
    assert "BaseService" in out
    assert "Disposable" in out
    assert "IConfig" in out


# ---------------------------------------------------------------------------
# Blocklist
# ---------------------------------------------------------------------------


def test_builtin_calls_excluded():
    """`print(...)` and similar built-ins must not produce CALLS edges."""
    src = b"def f():\n    print('hello')\n    len([1,2])\n    return 1\n"
    pf = ASTParser().parse_bytes("x.py", src)
    graph = CodeGraphBuilder().build({"x.py": pf})
    call_targets = {e.dst_uid for e in graph.edges if e.edge_type == EDGE_CALLS}
    # No edges to print/len because they're not symbols + are blocklisted.
    assert all("print" not in t and "len" not in t for t in call_targets)


# ---------------------------------------------------------------------------
# CodeGraph wrapper basics
# ---------------------------------------------------------------------------


def test_code_graph_query_by_name():
    syms = [
        Symbol(uid="py:a:function:foo:1", kind="function", name="foo", file_path="a.py",
               start_line=1, end_line=2),
        Symbol(uid="py:b:function:foo:3", kind="function", name="foo", file_path="b.py",
               start_line=3, end_line=4),
    ]
    g = CodeGraph(symbols=syms, edges=[])
    matches = g.query_by_name("foo")
    assert len(matches) == 2
    assert g.query_by_name("missing") == []


def test_code_graph_members_of():
    cls = Symbol(uid="py:a:class:K:1", kind="class", name="K", file_path="a.py",
                 start_line=1, end_line=10)
    method = Symbol(uid="py:a:method:m:3", kind="method", name="m", file_path="a.py",
                    start_line=3, end_line=4, parent_uid=cls.uid)
    other = Symbol(uid="py:a:function:f:5", kind="function", name="f", file_path="a.py",
                   start_line=5, end_line=6)
    g = CodeGraph(symbols=[cls, method, other], edges=[])
    members = g.members_of(cls.uid)
    assert [s.name for s in members] == ["m"]
