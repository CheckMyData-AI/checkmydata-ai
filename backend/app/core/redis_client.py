"""Process-wide async Redis client (T-SCALE-1 / T-SEC-7).

One connection pool shared by the rate limiters and the WS ticket store so
multi-dyno deployments enforce limits globally instead of per process.
``get_redis()`` returns ``None`` when Redis is not configured or unreachable —
callers must degrade to their in-memory fallback.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

_client: Any | None = None


async def connect(redis_url: str | None) -> None:
    """Connect the shared client. Safe to call when Redis is not configured."""
    global _client  # noqa: PLW0603
    if not redis_url:
        logger.info("redis_client: no REDIS_URL — in-memory fallbacks in effect")
        return
    try:
        redis_mod = importlib.import_module("redis.asyncio")
        from app.core.redis_tls import redis_connect_kwargs

        client = redis_mod.from_url(
            redis_url, decode_responses=True, **redis_connect_kwargs(redis_url)
        )
        await client.ping()
        _client = client
        logger.info("redis_client: connected")
    except Exception:
        logger.warning("redis_client: Redis unavailable, using in-memory fallbacks", exc_info=True)
        _client = None


async def close() -> None:
    global _client  # noqa: PLW0603
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:
            logger.debug("redis_client: error on close", exc_info=True)
        _client = None


def get_redis() -> Any | None:
    """The shared client, or ``None`` when Redis is not available."""
    return _client
