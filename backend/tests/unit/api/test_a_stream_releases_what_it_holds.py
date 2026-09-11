"""A stream held a session lock and a database connection it had stopped using.

P1 row 13, the backend half; API-01 and API-02. Both are resource leaks whose
symptom is somebody else's failure, which is why neither shows up where it is caused.

**API-01 — a routine 429 wedges the chat session for an hour.** `/ask/stream` enters
the per-session lock by hand (`await cm.__aenter__()`) and the matching `__aexit__`
lives only in the streaming generator's `finally`, created ~110 lines later. Three
things can raise in between, and the author guarded exactly one of them — the comment
on that guard says *"otherwise the session is wedged 'busy'"*. The limiter refusal, the
most frequently taken of the three, sits outside it. The lock then survives until its
`TTLCache` entry expires, and `TTLCache.get` refreshes LRU position but not
`expires_at`, so the ceiling is a full hour of `409 "currently processing another
request"` on a session where nothing is processing. The non-streaming `/ask` gets this
right.

**API-02 — a streaming response pins its request-scoped database connection for the
whole stream.** FastAPI closes yield-dependency exit stacks *after* the response is
sent, and for a `StreamingResponse` "sent" means "the generator finished". Both routes
run a bare `SELECT` first, which autobegins a transaction and checks a connection out
of the pool; it then sits idle-in-transaction for the run. `/workflows/events` has no
maximum duration at all, so four browser tabs hold four connections indefinitely —
against a Supavisor ceiling this deployment's own notes record as saturated at 14 of 15
at rest.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from app.api.routes import chat as chat_mod
from app.api.routes import workflows as wf_mod


def _tree(fn) -> ast.AST:
    return ast.parse(textwrap.dedent(inspect.getsource(fn)).replace("async def", "def", 1))


class TestTheSessionLockOutlivesNothing:
    """API-01."""

    def test_the_limiter_refusal_is_inside_a_release_path(self) -> None:
        """Every raise between the acquire and the hand-off, not just the first one.

        A guard naming `agent_limiter` specifically would pass while
        `update_session_status` — the third raising call in the same window — still
        leaked. The property is structural: after `__aenter__`, nothing may raise
        outside a handler that releases.
        """
        tree = _tree(chat_mod.ask_stream)
        fn = tree.body[0]

        enter_index = next(
            i
            for i, stmt in enumerate(fn.body)
            if "__aenter__" in ast.unparse(stmt) or "_stream_lock_cm" in ast.unparse(stmt)
        )
        tail = fn.body[enter_index + 1 :]

        # Statements that are not inside SOME try. A `return` of the streaming
        # response is the hand-off and is allowed to be bare.
        unprotected: list[str] = []
        for stmt in tail:
            if isinstance(stmt, ast.Try | ast.Return):
                continue
            text = ast.unparse(stmt)
            if "raise" in text or "acquire" in text or "HTTPException" in text:
                unprotected.append(text[:80])

        assert not unprotected, (
            "these can raise after the per-session lock is held and before the "
            f"generator that releases it exists: {unprotected}. A 429 from the agent "
            "limiter — the expected outcome when three streams are already running — "
            "then leaves the session answering 409 'currently processing another "
            "request' for up to an hour, indistinguishable from the honest 409 (API-01)"
        )

    def test_the_release_actually_runs_on_the_way_out(self) -> None:
        """A `try` that exists is not a release that happens.

        The first draft of this class checked only that the raising statements sat
        inside *some* try. Replacing the finally's condition with `if False:` left
        every statement where it was and passed — so the guard proved the shape of
        the code and nothing about the lock.
        """
        tree = _tree(chat_mod.ask_stream)
        fn = tree.body[0]

        # The handler's OWN try, not the generator's — that one has its own release
        # and its own guards, and walking the whole tree cannot tell them apart.
        finallies = [
            node
            for node in fn.body
            if isinstance(node, ast.Try) and node.finalbody and "__aexit__" in ast.unparse(node)
        ]
        assert finallies, (
            "no `finally` releases the per-session lock; the only release lives in the "
            "streaming generator, which is created ~700 lines after the lock is taken"
        )

        # The release must be conditional on the hand-off, and on nothing else — a
        # constant-false guard is the planted defect this catches, and a constant-true
        # one would release a lock the generator now owns.
        guards = [
            ast.unparse(node.test)
            for f in finallies
            for node in f.finalbody
            if isinstance(node, ast.If) and "__aexit__" in ast.unparse(node)
        ]
        assert guards, "the release is unconditional; it would run after the hand-off too"
        assert all(g not in ("False", "True") and "lock_handed_off" in g for g in guards), (
            f"the release is guarded on something other than the hand-off: {guards}"
        )
        assert "lock_handed_off = True" in ast.unparse(fn), (
            "nothing marks the hand-off, so the guard above can never be satisfied"
        )


class TestAStreamDoesNotSitOnAConnection:
    """API-02."""

    def test_the_workflow_stream_returns_its_connection_first(self) -> None:
        tree = _tree(wf_mod.workflow_events)
        commits = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Await) and ".commit()" in ast.unparse(node)
        ]
        assert commits, (
            "`get_accessible_projects` is a bare SELECT: it autobegins a transaction "
            "and checks a connection out of the pool, and FastAPI closes the "
            "dependency's exit stack only after the generator finishes. Four tabs on "
            "this endpoint hold four connections for as long as they stay open, "
            "against a pooler this deployment records as saturated at 14 of 15 at "
            "rest (API-02)"
        )

    @pytest.mark.asyncio
    async def test_the_workflow_stream_has_a_maximum_duration(self) -> None:
        """The generator stops, rather than the name of a setting appearing.

        A name check passes for a hardcoded ceiling and for a parameter nobody
        consults; driving the generator to its deadline does not.
        """
        import asyncio

        queue: asyncio.Queue = asyncio.Queue()
        chunks: list[str] = []
        # Capped, because the defect is an endless loop: collecting without a bound
        # would hang the suite instead of failing it.
        agen = wf_mod._event_generator(queue, None, max_seconds=0.0)
        try:
            async for chunk in agen:
                chunks.append(chunk)
                if len(chunks) > 3:
                    break
        finally:
            await agen.aclose()

        assert chunks, "the stream ended without telling the client why"
        assert len(chunks) <= 3, f"the generator kept going past its deadline: {chunks[:4]}"
        assert "reconnect" in chunks[-1], (
            "the SSE loop is `while True` with a 30 s keepalive and no ceiling, and the "
            "route carries no rate limit — so a caller decides how long the server holds "
            f"a pooled connection. Yielded: {chunks} (API-02)"
        )

    def test_the_ceiling_is_configurable_and_refused_when_absent(self) -> None:
        from app.config import Settings

        assert Settings().sse_max_stream_seconds > 0
        try:
            Settings(sse_max_stream_seconds=0)
        except Exception as exc:
            assert "SSE_MAX_STREAM_SECONDS" in str(exc)
        else:  # pragma: no cover - the assertion above is the point
            raise AssertionError(
                "a 0 that reads as configured and behaves as absent is the shape this "
                "whole finding is about"
            )

    def test_the_chat_stream_returns_its_connection_before_the_agent_runs(self) -> None:
        tree = _tree(chat_mod.ask_stream)
        fn = tree.body[0]

        # In the handler's OWN body, before the response is returned — not inside the
        # generator, where it would run only once the work is already done.
        def _own(node):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                    continue
                yield child
                yield from _own(child)

        commits = [
            ast.unparse(n)
            for n in _own(fn)
            if isinstance(n, ast.Await) and ".commit()" in ast.unparse(n)
        ]
        assert commits, (
            "the session sits idle-in-transaction for the whole run — up to "
            "`stream_timeout_seconds` (360) — holding one of the deployment's scarcest "
            "resources while doing nothing with it (API-02)"
        )
