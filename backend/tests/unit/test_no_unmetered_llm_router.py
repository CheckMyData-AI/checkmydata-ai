"""An LLM call on a path that knows who the user is must be counted against them.

``LLMRouter.__init__`` defaults to ``NullUsageSink``, whose ``observe`` is a no-op
(`app/llm/usage_sink.py`). The codebase names the hazard in its own comment at
`data_investigations.py:408-410` — *"A bare `LLMRouter()` has a `NullUsageSink`, which is
exactly the off-the-books path we must avoid"* — and then four HTTP handlers, the learning
analyzer and the cluster labeller constructed bare ones anyway (API-08, BILL-10, audit
2026-09-09).

What that costs, now that the token ceiling is the layer that binds (D-SPEND-1): tokens
spent through an unmetered router count against no daily limit, no monthly limit and no
plan limit, and appear in no figure on `/api/usage/stats`. The learning-extraction call is
the highest-frequency user-triggered LLM path in the product — `learning_analyzer_mode`
defaults to `llm_first`, so it fires after nearly every question that took more than one
attempt.

**This is a guard, not a unit test.** It reads the AST rather than grepping, because the
previous generation of source-string guards in this repository matched their own comments
(TEST-04). Each allowed exception carries its reason here; a new one has to be argued for
in this file.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

APP = pathlib.Path(__file__).parents[1].parent / "app"

#: Files whose LLM calls are made on behalf of an identified user or project owner. A bare
#: ``LLMRouter()`` in any of them is spend nobody is charged for.
METERED_SURFACES = [
    APP / "api" / "routes",
    APP / "knowledge" / "learning_analyzer.py",
    APP / "knowledge" / "pipeline_runner.py",
    APP / "mcp_server" / "tools.py",
]

#: ``file::function`` sites allowed to build a router with no sink, each with its reason.
ALLOWED_UNMETERED: dict[str, str] = {
    "learning_analyzer.py::_get_shared_router": (
        "the class-level fallback for callers that inject nothing — tests, and any future "
        "caller that genuinely has no user. Every production path passes the request's own "
        "router (SQLAgent._extract_learnings), which is what test_learning_extraction_is_"
        "metered pins."
    ),
}


def _iter_python_files():
    for target in METERED_SURFACES:
        if target.is_dir():
            yield from sorted(p for p in target.rglob("*.py") if p.name != "__init__.py")
        else:
            yield target


def _unmetered_sites(path: pathlib.Path) -> list[str]:
    """`function::line` for every ``LLMRouter(...)`` built without a ``usage_sink``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    enclosing: dict[ast.AST, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for child in ast.walk(node):
                enclosing.setdefault(child, node.name)

    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "LLMRouter"):
            continue
        if any(kw.arg == "usage_sink" for kw in node.keywords):
            continue
        fn = enclosing.get(node, "<module>")
        if f"{path.name}::{fn}" in ALLOWED_UNMETERED:
            continue
        found.append(f"{path.name}::{fn}:{node.lineno}")
    return found


@pytest.mark.parametrize("path", list(_iter_python_files()), ids=lambda p: p.name)
def test_no_unmetered_llm_router_on_a_metered_surface(path: pathlib.Path) -> None:
    sites = _unmetered_sites(path)
    assert not sites, (
        "these build an LLMRouter with no usage_sink, so every token they spend is "
        f"invisible to the budget gate and to the usage display: {sites}"
    )


def test_the_allowlist_entries_still_exist() -> None:
    """An allowance for a site that has been deleted is an allowance nobody reviews."""
    live = set()
    for path in _iter_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                live.add(f"{path.name}::{node.name}")
    stale = [key for key in ALLOWED_UNMETERED if key not in live]
    assert not stale, f"allowlisted sites that no longer exist: {stale}"
