"""Graph-quality benchmark gating the code_graph/lineage flag flip (W6, spec §9).

Builds the code graph from a tiny known fixture repo and asserts minimum
symbol / CALLS / EXTENDS / IMPORTS counts. Deterministic (no LLM, no network).
Run as ``python -m app.eval.graph_benchmark`` — exits non-zero on FAIL so it
can be a CI/rollout gate before flipping the flags.
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.knowledge.ast_parser import ASTParser
from app.knowledge.code_graph import (
    EDGE_CALLS,
    EDGE_EXTENDS,
    EDGE_IMPORTS,
    CodeGraphBuilder,
)
from app.knowledge.shared_ignore import is_ignored_path

_MIN_SYMBOLS = 7
_MIN_CALLS = 1
_MIN_EXTENDS = 1
_MIN_IMPORTS = 1


@dataclass
class GraphBenchmarkResult:
    symbols: int
    calls: int
    extends: int
    imports: int
    passed: bool
    failures: list[str] = field(default_factory=list)


def _fixture(root: Path) -> None:
    """Write the Task-10 fixture repo into *root*; reuses the integration test's source of truth."""
    # Imported lazily to avoid pulling in pytest fixtures at module level.
    from tests.integration.test_code_graph_end_to_end import _write_fixture_repo  # noqa: PLC0415

    _write_fixture_repo(root)


def run_graph_benchmark(*, repo_root: Path | None = None) -> GraphBenchmarkResult:
    """Build the code graph over *repo_root* (or a fresh fixture) and verify thresholds.

    Parameters
    ----------
    repo_root:
        Path to an existing repo to benchmark. If *None*, a temporary directory is created,
        the Task-10 fixture repo is written into it, and it is cleaned up after the run.

    Returns
    -------
    GraphBenchmarkResult
        Counts and pass/fail flag with any failure messages.
    """
    tmp: tempfile.TemporaryDirectory[str] | None = None
    if repo_root is None:
        tmp = tempfile.TemporaryDirectory()
        repo_root = Path(tmp.name)
        _fixture(repo_root)
    try:
        parser = ASTParser()
        parsed: dict[str, object] = {}
        for path in repo_root.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(repo_root)).replace("\\", "/")
            if is_ignored_path(rel):
                continue
            pf = parser.parse_file(repo_root, rel)
            if pf is not None:
                parsed[rel] = pf
        graph = CodeGraphBuilder().build(parsed)  # type: ignore[arg-type]
        n_sym = len(graph.symbols)
        n_calls = sum(1 for e in graph.edges if e.edge_type == EDGE_CALLS)
        n_ext = sum(1 for e in graph.edges if e.edge_type == EDGE_EXTENDS)
        n_imp = sum(1 for e in graph.edges if e.edge_type == EDGE_IMPORTS)
        failures: list[str] = []
        if n_sym < _MIN_SYMBOLS:
            failures.append(f"symbols {n_sym} < {_MIN_SYMBOLS}")
        if n_calls < _MIN_CALLS:
            failures.append(f"CALLS {n_calls} < {_MIN_CALLS}")
        if n_ext < _MIN_EXTENDS:
            failures.append(f"EXTENDS {n_ext} < {_MIN_EXTENDS}")
        if n_imp < _MIN_IMPORTS:
            failures.append(f"IMPORTS {n_imp} < {_MIN_IMPORTS}")
        return GraphBenchmarkResult(
            symbols=n_sym,
            calls=n_calls,
            extends=n_ext,
            imports=n_imp,
            passed=not failures,
            failures=failures,
        )
    finally:
        if tmp is not None:
            tmp.cleanup()


def main() -> int:
    """CLI entry point — prints PASS/FAIL line and exits non-zero on failure."""
    res = run_graph_benchmark()
    status = "PASS" if res.passed else "FAIL"
    print(
        f"graph_benchmark: {status} "
        f"symbols={res.symbols} CALLS={res.calls} EXTENDS={res.extends} IMPORTS={res.imports}"
    )
    for f in res.failures:
        print(f"  - {f}")
    return 0 if res.passed else 1


if __name__ == "__main__":
    sys.exit(main())
