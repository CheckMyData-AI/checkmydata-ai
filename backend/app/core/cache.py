"""Shared cache layer: Redis when available, in-memory TTLCache fallback.

All cache operations are async-safe.  Callers import ``shared_cache`` and
use ``get`` / ``put`` / ``invalidate`` without caring about the backend.
"""

from __future__ import annotations

import importlib
import json
import logging
from typing import Any

from app.core.ttl_cache import TTLCache

logger = logging.getLogger(__name__)


class SharedCache:
    """Dual-backend cache with automatic Redis → in-memory fallback."""

    def __init__(self, prefix: str = "cmd", ttl: float = 600, max_local_size: int = 512) -> None:
        self._prefix = prefix
        self._ttl = ttl
        self._local: TTLCache[str] = TTLCache(ttl=ttl, max_size=max_local_size)
        self._redis: Any | None = None

    async def connect(self, redis_url: str | None = None) -> None:
        if not redis_url:
            logger.info("SharedCache[%s]: in-memory only (no REDIS_URL)", self._prefix)
            return
        try:
            redis_mod = importlib.import_module("redis.asyncio")
            self._redis = redis_mod.from_url(redis_url, decode_responses=True)
            await self._redis.ping()
            logger.info("SharedCache[%s]: connected to Redis", self._prefix)
        except Exception:
            logger.warning(
                "SharedCache[%s]: Redis unavailable, using in-memory fallback",
                self._prefix,
                exc_info=True,
            )
            self._redis = None

    async def close(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                logger.debug("Error closing Redis connection", exc_info=True)
            self._redis = None

    def _rkey(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def get(self, key: str) -> Any | None:
        local = self._local.get(key)
        if local is not None:
            return json.loads(local)

        if self._redis is not None:
            try:
                raw = await self._redis.get(self._rkey(key))
                if raw is not None:
                    self._local.put(key, raw)
                    return json.loads(raw)
            except Exception:
                logger.debug("Redis GET failed for %s", key, exc_info=True)

        return None

    async def put(self, key: str, value: Any, ttl: float | None = None) -> None:
        raw = json.dumps(value, default=str)
        self._local.put(key, raw)

        if self._redis is not None:
            try:
                await self._redis.set(
                    self._rkey(key), raw, ex=int(ttl or self._ttl),
                )
            except Exception:
                logger.debug("Redis SET failed for %s", key, exc_info=True)

    async def invalidate(self, key: str) -> None:
        self._local.invalidate(key)
        if self._redis is not None:
            try:
                await self._redis.delete(self._rkey(key))
            except Exception:
                logger.debug("Redis DEL failed for %s", key, exc_info=True)

    async def invalidate_prefix(self, prefix: str) -> None:
        """Remove all keys matching ``<cache_prefix>:<prefix>*``."""
        self._local.clear()
        if self._redis is not None:
            try:
                pattern = f"{self._prefix}:{prefix}*"
                cursor: int | bytes = 0
                while True:
                    cursor, keys = await self._redis.scan(cursor, match=pattern, count=200)
                    if keys:
                        await self._redis.delete(*keys)
                    if not cursor:
                        break
            except Exception:
                logger.debug("Redis SCAN/DEL failed for prefix %s", prefix, exc_info=True)

    @property
    def is_redis_connected(self) -> bool:
        return self._redis is not None


shared_cache = SharedCache()
