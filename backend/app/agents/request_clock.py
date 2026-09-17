"""The request's clock: one start, one hard deadline, one way to be cut off (PRJ-03).

Lives apart from the orchestrator so the stage executor can bound its stages with the
same clock without importing the module that imports it.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.agents.base import AgentContext

#: Where a request's clock is kept. On `context.extra`, mutated in place and never
#: rebuilt, because `dataclasses.replace` copies the dict's REFERENCE and every
#: sub-agent copy downstream therefore reads the same start (the B-04 lesson).
_REQUEST_START_KEY = "_request_started_at"


def request_started_at(context: AgentContext) -> float:
    """When this request began, established once, at the first reader.

    PRJ-03. The tool loop measured its wall clock from the loop's own first line, so the
    router call, context loading and capability probes that precede it were free — and
    the pipeline path computed a fresh deadline at the start of its stages, so the same
    pre-work was free there too. Measured on production over 30 days: 6 of 23 traces
    exceeded 1.2x the 180 s limit, and failed requests ran a median of 283 s. One start,
    set once, is the precondition for the limit meaning what it says.
    """
    started = context.extra.get(_REQUEST_START_KEY)
    if not isinstance(started, int | float):
        started = time.monotonic()
        context.extra[_REQUEST_START_KEY] = started
    return float(started)


def hard_remaining_seconds(context: AgentContext, limit: float) -> float:
    """Seconds left before the hard cutoff, ``limit x 1.2`` from the request's start.

    The 1.2 is the tool loop's existing hard cutoff, kept rather than reinvented: it is
    the margin between "enter wrap-up" and "stop regardless" that the loop already
    documents, and a second, different margin here would make the two disagree.
    """
    return max(0.0, request_started_at(context) + limit * 1.2 - time.monotonic())


#: How long a fallback answer may still spend becoming the reader's language once the
#: request's deadline is spent. Short and explicit rather than the translator's own 12 s:
#: a readable answer is worth a moment, not another request's worth of waiting.
LOCALIZE_GRACE_SECONDS = 3.0


class WallClockExceeded(BaseException):  # noqa: N818 - control flow, like CancelledError
    """A bounded await ran past the request's hard deadline.

    A ``BaseException`` for the reason ``asyncio.CancelledError`` is one: the tool loop
    wraps its dispatches in ``except Exception`` to turn tool failures into directives
    for the model, and a deadline caught there becomes "the tool failed, try again" —
    which spends the time the deadline exists to stop spending.
    """


async def bounded(awaitable: Any, context: AgentContext, limit: float) -> Any:
    """Await *awaitable*, cutting it off at the request's hard deadline.

    The tool loop checked its wall clock only BETWEEN iterations, so one iteration — a
    single orchestrator LLM call, or one dispatch that runs the whole SQL agent — could
    run past the limit by its entire duration, and nothing could interrupt it. This is
    the interrupt. On expiry the awaitable is cancelled (``asyncio.wait_for`` does that)
    and `WallClockExceeded` is raised for the loop to turn into its timeout answer.
    """
    remaining = hard_remaining_seconds(context, limit)
    if remaining <= 0:
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()  # never awaited: close it so no "was never awaited" warning leaks
        raise WallClockExceeded
    try:
        return await asyncio.wait_for(awaitable, timeout=remaining)
    except TimeoutError as exc:
        raise WallClockExceeded from exc
