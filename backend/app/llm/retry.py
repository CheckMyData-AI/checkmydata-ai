"""Shared retry wrapper for LLM calls used across orchestrator and sub-agents.

Provides ``llm_call_with_retry`` so SQL/Knowledge/MCP sub-agents share the
same exponential backoff and error semantics as the orchestrator. Keeping
retry logic centralized prevents inconsistent behaviour between agents.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from app.llm.errors import RETRYABLE_LLM_ERRORS, LLMAllProvidersFailedError

if TYPE_CHECKING:
    from app.llm.base import LLMResponse, Message
    from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)


_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BASE_BACKOFF_SECONDS = 0.5


async def llm_call_with_retry(
    llm: LLMRouter,
    *,
    messages: list[Message],
    tools: list | None,
    preferred_provider: str | None,
    model: str | None,
    component: str = "agent",
    max_retries: int = _DEFAULT_MAX_RETRIES,
    base_backoff: float = _DEFAULT_BASE_BACKOFF_SECONDS,
    on_retry: Any = None,
) -> LLMResponse:
    """Call ``llm.complete`` with exponential backoff on transient failures.

    Parameters
    ----------
    component:
        Used in log messages so we can tell which agent retried.
    on_retry:
        Optional ``async`` callable ``(attempt, exception, wait)`` invoked
        before sleeping. Use this to emit progress events to the workflow
        tracker.
    """
    delay = base_backoff
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return await llm.complete(
                messages=messages,
                tools=tools,
                preferred_provider=preferred_provider,
                model=model,
            )
        except RETRYABLE_LLM_ERRORS as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            wait = exc.retry_after_seconds or delay
            logger.warning(
                "%s LLM retryable error (attempt %d/%d), retrying in %.1fs: [%s] %s",
                component,
                attempt,
                max_retries,
                wait,
                type(exc).__name__,
                exc,
            )
            if on_retry is not None:
                try:
                    await on_retry(attempt, exc, wait)
                except Exception:
                    logger.debug("on_retry callback failed", exc_info=True)
            await asyncio.sleep(wait)
            delay *= 2.0
        except LLMAllProvidersFailedError:
            raise

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("LLM call failed without exception")
