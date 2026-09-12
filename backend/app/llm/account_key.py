"""The account whose OpenRouter key should pay for the calls in this request (P0-1c).

A `ContextVar` rather than a constructor argument, because the shape of the chat path
forces it: `chat.py` builds `ConversationalAgent()` **at module level**, so one router
and one set of adapters serve every request in the process. Threading a key through
`complete()` from every call site would touch dozens of them and still miss the next
one. The same mechanism already carries the MCP principal (`mcp_server/runtime.py`) and
the workflow id (`core/workflow_tracker.py`), for the same reason.

`LLMRouter` reads its constructor argument first and this second, so a router built
per request with an explicit key — the background indexing routers — keeps working
exactly as written, and the shared one picks up whoever is asking right now.

**Set it, and always unset it.** `asyncio` copies the context into each task, so a
value left behind is not merely stale: it is the previous customer's key, in the
process that serves the next one. `account_key_scope` exists so no call site can
forget, and every entry point uses it rather than `set()` directly.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar

logger = logging.getLogger(__name__)

current_account_openrouter_key: ContextVar[str | None] = ContextVar(
    "account_openrouter_key", default=None
)


@contextmanager
def account_key_scope(key: str | None) -> Iterator[None]:
    """Bind *key* for the duration of the block, then restore what was there before.

    Restores rather than clears: nesting is legitimate (a request that spawns a
    sub-task which sets its own), and clearing would leave the outer scope keyless for
    the rest of its work.
    """
    token = current_account_openrouter_key.set(key)
    try:
        yield
    finally:
        current_account_openrouter_key.reset(token)


@asynccontextmanager
async def account_key_scope_async(key: str | None) -> AsyncIterator[None]:
    """`account_key_scope` for an `async with`, which most entry points want."""
    with account_key_scope(key):
        yield


async def bind_account_key(db: object, user_id: str | None) -> str | None:
    """Resolve the account's key and return it, or ``None``.

    Thin on purpose: the resolution and its failure policy live in
    `openrouter_credit_service.resolve_account_key`, which is where the decision that
    every failure answers ``None`` is written down and tested.

    **Deliberately UNGUARDED**, and the first draft was not. A broad handler here could
    only catch an ImportError, because the function it calls is documented and tested
    never to raise — a suppression that suppresses nothing, which is exactly what the
    ratchet in `tests/unit/docs/test_suppression_debt_ratchet.py` exists to refuse. The
    `user_id` check is real: the WebSocket path can reach here before a principal is
    resolved, and asking for "the key belonging to nobody" is a database round trip
    with a known answer.
    """
    if not user_id:
        return None
    from app.services.openrouter_credit_service import resolve_account_key

    return await resolve_account_key(db, user_id)  # type: ignore[arg-type]
