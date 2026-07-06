"""End-to-end integration test: full graph over a fixture repo with all W6 fixes composed.

Verifies that fixes T1-T9 work together:
  - T2 (UID format): symbols have stable ``{lang}:{file}:{kind}:{name}`` UIDs.
  - T3 (EXTENDS multi-base heritage): Worker EXTENDS Base edge present.
  - T4 (JS/TS arrow component + module var): Btn (function) and MAX (variable) extracted.
  - T7 (shared ignore): ``tests/`` directory files are excluded from the graph.
  - T1 (cross-file CALLS resolution): run() calls helper() across the file boundary.
  - T4 (reverse-dep incremental relink): reverse_dependents returns worker.py when base.py changes.

This module also exports ``_write_fixture_repo`` and ``EXPECTED_SYMBOLS`` /
``EXPECTED_EXTENDS`` constants for the Task 11 graph benchmark.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.knowledge.ast_parser import ASTParser
from app.knowledge.code_graph import (
    EDGE_CALLS,
    EDGE_EXTENDS,
    EDGE_IMPORTS,
    CodeGraph,
    CodeGraphBuilder,
)
from app.knowledge.shared_ignore import is_ignored_path

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Fixture repo (reused by the Task 11 benchmark)
# ---------------------------------------------------------------------------

_FILES: dict[str, str] = {
    "svc/base.py": "class Base:\n    def ping(self):\n        return 1\n",
    "svc/worker.py": (
        "from svc.base import Base\n\n"
        "def helper():\n    return 2\n\n"
        "class Worker(Base):\n"
        "    def run(self):\n        helper()\n        self.ping()\n"
    ),
    "web/app.ts": "export const MAX = 5;\nexport const Btn = () => { return null; };\n",
    "tests/test_worker.py": "def test_x():\n    assert True\n",  # must be ignored
}

EXPECTED_SYMBOLS: frozenset[str] = frozenset(
    {
        "python:svc/base.py:class:Base",
        "python:svc/base.py:method:ping",
        "python:svc/worker.py:function:helper",
        "python:svc/worker.py:class:Worker",
        "python:svc/worker.py:method:run",
        "typescript:web/app.ts:variable:MAX",
        "typescript:web/app.ts:function:Btn",
    }
)

EXPECTED_EXTENDS: frozenset[tuple[str, str]] = frozenset(
    {("python:svc/worker.py:class:Worker", "python:svc/base.py:class:Base")}
)


def _write_fixture_repo(root: Path) -> None:
    """Write all fixture files into *root* (creates parent dirs as needed)."""
    for rel, content in _FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def _build_from_repo(root: Path) -> CodeGraph:
    """Parse the fixture repo with the real ASTParser, honouring shared ignore rules."""
    parser = ASTParser()
    parsed: dict[str, object] = {}
    for rel in _FILES:
        if is_ignored_path(rel):
            continue
        pf = parser.parse_file(root, rel)
        if pf is not None:
            parsed[rel] = pf
    return CodeGraphBuilder().build(parsed)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_fixture_symbol_and_edge_sets(tmp_path: Path) -> None:
    """T2 + T3 + T4 + T7: symbols, EXTENDS, TS kinds, and tests/ exclusion."""
    _write_fixture_repo(tmp_path)
    graph = _build_from_repo(tmp_path)

    # T7: tests/ dir excluded — test_x must not appear.
    assert not any(s.name == "test_x" for s in graph.symbols.values()), (
        "T7 (shared_ignore): tests/test_worker.py must be excluded from the graph"
    )

    # T2: UID stable format — exact set matches.
    assert set(graph.symbols.keys()) == EXPECTED_SYMBOLS, (
        f"T2 (UID format): symbol set mismatch.\n"
        f"  extra={set(graph.symbols.keys()) - EXPECTED_SYMBOLS}\n"
        f"  missing={EXPECTED_SYMBOLS - set(graph.symbols.keys())}"
    )

    # T3: Worker EXTENDS Base edge present (confidence >= 0.7 is fine).
    extends = {(e.src_uid, e.dst_uid) for e in graph.edges if e.edge_type == EDGE_EXTENDS}
    assert EXPECTED_EXTENDS <= extends, (
        f"T3 (EXTENDS multi-base heritage): Worker->Base edge missing. Got: {extends}"
    )

    # T4: TS arrow component extracted as kind='function', module var as kind='variable'.
    kinds = {s.name: s.kind for s in graph.symbols.values()}
    assert kinds.get("Btn") == "function", (
        f"T4 (TS arrow component): Btn kind={kinds.get('Btn')!r}, expected 'function'"
    )
    assert kinds.get("MAX") == "variable", (
        f"T4 (TS module var): MAX kind={kinds.get('MAX')!r}, expected 'variable'"
    )


def test_cross_file_calls_resolved(tmp_path: Path) -> None:
    """T1: run() calls helper() across file boundary."""
    _write_fixture_repo(tmp_path)
    graph = _build_from_repo(tmp_path)

    calls_by_name = {
        (graph.symbols[e.src_uid].name, graph.symbols[e.dst_uid].name)
        for e in graph.edges
        if e.edge_type == EDGE_CALLS and e.dst_uid in graph.symbols
    }
    assert ("run", "helper") in calls_by_name, (
        f"T1 (cross-file CALLS): run->helper edge missing. Resolved calls: {calls_by_name}"
    )


def test_imports_edge_from_worker_to_base(tmp_path: Path) -> None:
    """IMPORTS edge: svc/worker.py declares import of Base from svc/base.py."""
    _write_fixture_repo(tmp_path)
    graph = _build_from_repo(tmp_path)

    imports = {
        (e.src_uid, graph.symbols[e.dst_uid].name)
        for e in graph.edges
        if e.edge_type == EDGE_IMPORTS and e.dst_uid in graph.symbols
    }
    assert ("file:svc/worker.py", "Base") in imports, (
        f"IMPORTS: worker.py->Base edge missing. Got: {imports}"
    )


def test_incremental_reverse_dep_relinks_caller(tmp_path: Path) -> None:
    """T4 + T2: reverse_dependents finds worker.py when base.py changes; UID stays stable."""
    _write_fixture_repo(tmp_path)
    full = _build_from_repo(tmp_path)

    # Mutate base.py (insert a comment); worker.py unchanged.
    (tmp_path / "svc/base.py").write_text(
        "# added comment\nclass Base:\n    def ping(self):\n        return 1\n"
    )
    deps = CodeGraphBuilder.reverse_dependents(full, {"svc/base.py"})
    assert "svc/worker.py" in deps, (
        f"T4 + T2 (incremental relink): worker.py not in reverse_dependents. Got: {deps}"
    )
