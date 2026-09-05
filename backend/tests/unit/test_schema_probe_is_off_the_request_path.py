"""The schema snapshot was deserialised on the event loop (row 2.6).

`sql_agent` threads the BM25 *query* — `await retriever.aquery(...)`, with a
comment saying it "offloads BM25 (CPU-bound) off the loop" — and then reaches it
through a probe that is not threaded:

    if not retriever.has_index(connection_id):   # sync

`has_index` is the expensive half. It resolves through `BM25Index.indexed_sha` to
`load()`, which reads and gunzips the whole snapshot and rebuilds `BM25Okapi`
from the tokenised corpus. `aquery` afterwards finds it cached. So the call the
author deliberately moved off the loop was already warm, and the one that does
the work was not.

`bm25_local_reconcile.py:120` wraps the identical call —
`await asyncio.to_thread(retriever.has_index, cid)`. One call, two sites, threaded
in one. Same shape this programme has now found six times: one job with several
implementations, and the wrong one on the path that matters.

It bites hardest right after a deploy, when no snapshot is cached and every
project's first question pays the deserialisation with the loop held.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

#: Call sites that run on a request and must not block the loop on the snapshot.
_REQUEST_PATH = [("app/agents/sql_agent.py", "has_index")]


def _threaded_calls(tree: ast.AST) -> set[str]:
    """Attribute names handed to `to_thread` as a value."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "to_thread"
        ):
            for arg in node.args:
                if isinstance(arg, ast.Attribute):
                    out.add(arg.attr)
    return out


def _bare_calls(tree: ast.AST, name: str) -> list[int]:
    threaded = _threaded_calls(tree)
    if name in threaded:
        return []
    return [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == name
    ]


class TestTheProbeDoesNotBlockTheLoop:
    @pytest.mark.parametrize(("module", "call"), _REQUEST_PATH)
    def test_the_snapshot_probe_is_threaded(self, module, call):
        tree = ast.parse(Path(module).read_text(encoding="utf-8"))
        bare = _bare_calls(tree, call)
        assert not bare, (
            f"{module}:{bare} calls {call}() on the event loop. It resolves through "
            "`BM25Index.load`, which gunzips the snapshot and rebuilds the index — the "
            "expensive half of the work the `aquery` call two lines below was already "
            "threaded to avoid."
        )

    def test_the_boot_reconcile_already_did_it_this_way(self):
        """The reference. It is why the request-path site reads as an oversight
        rather than a house style — and where the shape of the fix comes from."""
        tree = ast.parse(Path("app/ops/bm25_local_reconcile.py").read_text(encoding="utf-8"))
        assert "has_index" in _threaded_calls(tree)


class TestTheDetectorWouldSeeAViolation:
    """A structural check that cannot fail proves nothing — the shape this
    programme has hit four times now."""

    def test_a_bare_call_is_reported(self):
        tree = ast.parse("async def f(r):\n    return r.has_index('c')\n")
        assert _bare_calls(tree, "has_index")

    def test_a_threaded_call_is_not(self):
        tree = ast.parse(
            "import asyncio\n"
            "async def f(r):\n"
            "    return await asyncio.to_thread(r.has_index, 'c')\n"
        )
        assert not _bare_calls(tree, "has_index")
