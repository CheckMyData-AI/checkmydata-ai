"""Best-effort distributed advisory lock via Redis SET NX EX.

Yields True when this process holds the lock, else False. Without Redis the
single-process case yields True. Never raises on Redis errors (yields False).
Releases only if still owned (token compare) to avoid deleting a lock that a
later holder acquired after our TTL expired.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)


@asynccontextmanager
async def redis_lock(key: str, *, ttl_seconds: int) -> AsyncIterator[bool]:
    client = get_redis()
    if client is None:
        yield True
        return

    token = uuid.uuid4().hex
    acquired = False
    try:
        acquired = bool(await client.set(key, token, nx=True, ex=ttl_seconds))
    except Exception:
        logger.warning("redis_lock acquire failed for %s", key, exc_info=True)
        acquired = False

    try:
        yield acquired
    finally:
        if acquired:
            try:
                current = await client.get(key)
                cur = current.decode() if isinstance(current, bytes) else current
                if cur == token:
                    await client.delete(key)
            except Exception:
                logger.debug("redis_lock release failed for %s", key, exc_info=True)
