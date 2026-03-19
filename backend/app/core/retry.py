"""Configurable retry decorator with exponential backoff."""

import asyncio
import functools
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def retry(
    max_attempts: int = 2,
    backoff_seconds: float = 1.0,
    backoff_multiplier: float = 2.0,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    non_retryable: tuple[type[BaseException], ...] = (KeyboardInterrupt, SystemExit, GeneratorExit),
    on_retry: Callable[..., Any] | None = None,
):
    """Async retry decorator with exponential backoff.

    Args:
        max_attempts: Total attempts (1 = no retry, 2 = 1 retry).
        backoff_seconds: Initial delay between retries.
        backoff_multiplier: Multiplied each retry iteration.
        retryable_exceptions: Only retry on these exception types.
        on_retry: Optional callback(attempt, exception) called before each retry.
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            delay = backoff_seconds
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except non_retryable:
                    raise
                except retryable_exceptions as exc:
                    last_exc = exc
                    if attempt >= max_attempts:
                        break
                    logger.warning(
                        "Retry %d/%d for %s: %s",
                        attempt,
                        max_attempts,
                        func.__qualname__,
                        exc,
                    )
                    if on_retry:
                        try:
                            on_retry(attempt, exc)
                        except Exception:
                            pass
                    await asyncio.sleep(delay)
                    delay *= backoff_multiplier
            if last_exc is None:  # pragma: no cover
                raise RuntimeError("retry exhausted without exception")
            raise last_exc  # pragma: no cover

        return wrapper

    return decorator
