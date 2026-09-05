"""Synchronous vector-store calls sat on four async paths (row 2.20).

`VectorStore` and `PgVectorStore` are entirely synchronous — `chromadb` and
`psycopg` both block — which is why `HybridRetriever` wraps every call in
`asyncio.to_thread`. Four other call sites, all inside `async def`, did not:

    context_loader.py:432            dense-only fallback
    knowledge_catalog_service.py:570 the ContextPack RAG leg
    mcp_server/resources.py:140      the MCP knowledge resource
    pipeline_runner.py:447           the worker's step loop

Two of them matter more than "blocking is untidy".

**The first is the documented graceful-degradation path.** It runs when
`hybrid_retrieval_enabled` is off or the hybrid leg returns nothing — so the
worse retrieval health gets, the harder the event loop freezes, and it embeds the
question through the bundled ONNX model while it holds the loop. Every concurrent
request waits.

**The fourth blocks the worker's heartbeat.** `_run_steps` is what writes
`heartbeat_at`, and `StaleRunReaper` kills a run whose beat stops. This programme
has already recorded exactly that outcome in production — a live repo index
reaped at 22:07 while it was still working, then a second copy started beside it.
A synchronous `collection.count()` over a large collection is precisely the kind
of pause that produces it.

`make_vector_store()` at the MCP site is blocking too on pgvector: it opens a
psycopg connection pool.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

#: (module, function) pairs that must not call the vector store synchronously.
_ASYNC_SITES = [
    ("app/agents/context_loader.py", "load_relevant_knowledge"),
    ("app/services/knowledge_catalog_service.py", "_rag_artifacts_async"),
    ("app/mcp_server/resources.py", "get_project_knowledge"),
    ("app/knowledge/pipeline_runner.py", "_run_steps"),
]

#: Vector-store methods that block: they reach chromadb or psycopg directly.
_BLOCKING = {"query", "get_or_create_collection", "count", "add_documents", "delete_by_source_path"}


def _function(tree: ast.AST, name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not an async function any more — check the premise")


def _bare_blocking_calls(fn: ast.AST) -> list[tuple[int, str]]:
    """Blocking vector-store calls that are NOT handed to a worker thread.

    Three legitimate shapes reach `to_thread`, and the check has to know all
    three or it reports a fix as a defect (which it did on the first draft):

    * the bound method as a value — ``to_thread(store.query, …)``
    * a lambda — ``to_thread(lambda: store.get_or_create_collection(p).count())``
    * a local helper by name — ``def _count(): …`` then ``to_thread(_count)``

    Excluding the bodies of *exactly* those, rather than every nested function,
    is deliberate: "anything inside a nested def is fine" would stop catching the
    thing this exists for.
    """
    wrapped_attrs: set[int] = set()
    exempt_bodies: list[ast.AST] = []
    thread_targets: set[str] = set()

    for node in ast.walk(fn):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "to_thread"
        ):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Attribute):
                wrapped_attrs.add(id(arg))
            elif isinstance(arg, ast.Lambda):
                exempt_bodies.append(arg)
            elif isinstance(arg, ast.Name):
                thread_targets.add(arg.id)

    for node in ast.walk(fn):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in thread_targets
        ):
            exempt_bodies.append(node)

    exempt_calls = {
        id(inner)
        for body in exempt_bodies
        for inner in ast.walk(body)
        if isinstance(inner, ast.Call)
    }

    out = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in _BLOCKING:
            continue
        receiver = ast.unparse(node.func.value)
        if "vector_store" not in receiver and receiver != "vs" and "col" not in receiver:
            continue
        if id(node.func) in wrapped_attrs or id(node) in exempt_calls:
            continue
        out.append((node.lineno, f"{receiver}.{node.func.attr}()"))
    return out


class TestNoAsyncPathBlocksOnTheVectorStore:
    @pytest.mark.parametrize(("module", "func"), _ASYNC_SITES)
    def test_the_call_is_off_the_loop(self, module, func):
        tree = ast.parse(Path(module).read_text(encoding="utf-8"))
        offenders = _bare_blocking_calls(_function(tree, func))
        assert not offenders, (
            f"{module}::{func} calls the synchronous vector store on the event loop "
            f"at {offenders}. `HybridRetriever` wraps the same calls in `to_thread`; "
            "these hold the loop for every concurrent request."
        )


class TestTheDetectorWouldSeeAViolation:
    """A structural check that cannot fail is a green that proves nothing — the
    shape this programme has now hit three times."""

    def test_a_bare_call_is_reported(self):
        tree = ast.parse(
            "import asyncio\nasync def f(self):\n    return self._vector_store.query('p', 'q')\n"
        )
        assert _bare_blocking_calls(_function(tree, "f"))

    def test_a_lambda_handed_to_a_thread_is_not(self):
        """The shape `pipeline_runner` uses. The first draft of this detector did
        not know it and reported the fix as the defect."""
        tree = ast.parse(
            "import asyncio\n"
            "async def f(self):\n"
            "    return await asyncio.to_thread(\n"
            "        lambda: self._vector_store.get_or_create_collection('p').count()\n"
            "    )\n"
        )
        assert not _bare_blocking_calls(_function(tree, "f"))

    def test_a_local_helper_handed_to_a_thread_is_not(self):
        """The shape `mcp_server/resources` uses: three blocking calls, one hop."""
        tree = ast.parse(
            "import asyncio\n"
            "async def f(self):\n"
            "    def _count():\n"
            "        vs = make_vector_store()\n"
            "        return vs.get_or_create_collection('p').count()\n"
            "    return await asyncio.to_thread(_count)\n"
        )
        assert not _bare_blocking_calls(_function(tree, "f"))

    def test_a_nested_def_that_is_not_threaded_is_still_reported(self):
        """The loosening has a floor. Exempting every nested function would stop
        the check catching what it exists for."""
        tree = ast.parse(
            "async def f(self):\n"
            "    def _inline():\n"
            "        return self._vector_store.query('p', 'q')\n"
            "    return _inline()\n"
        )
        assert _bare_blocking_calls(_function(tree, "f"))

    def test_a_wrapped_call_is_not(self):
        tree = ast.parse(
            "import asyncio\n"
            "async def f(self):\n"
            "    return await asyncio.to_thread(self._vector_store.query, 'p', 'q')\n"
        )
        assert not _bare_blocking_calls(_function(tree, "f"))


class TestTheHybridRetrieverStaysTheReference:
    """It is the site that got this right, and the reason the others read as
    oversights rather than a house style."""

    def test_it_wraps_both_legs(self):
        src = Path("app/knowledge/hybrid_retriever.py").read_text(encoding="utf-8")
        assert src.count("to_thread") >= 2
