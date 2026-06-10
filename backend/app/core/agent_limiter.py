"""Per-user rate limiting for agent calls.

Tracks concurrent requests per user and enforces hourly caps. When the shared
Redis client is connected the counters live in Redis (atomic Lua script) so
limits hold across processes (T-SCALE-1); otherwise the original in-memory
implementation applies. A Redis outage mid-flight degrades to in-memory
counting rather than blocking chat.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict

from app.config import settings
from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

# Atomically: enforce the concurrency cap, slide the hourly window, then
# reserve a slot + record the call. Returns 0=ok, 1=concurrency, 2=hourly.
_ACQUIRE_LUA = """
local conc = tonumber(redis.call('GET', KEYS[1]) or '0')
if conc >= tonumber(ARGV[1]) then return 1 end
redis.call('ZREMRANGEBYSCORE', KEYS[2], 0, tonumber(ARGV[3]) - 3600)
if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[2]) then return 2 end
redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], 3600)
redis.call('ZADD', KEYS[2], ARGV[3], ARGV[4])
redis.call('EXPIRE', KEYS[2], 3600)
return 0
"""

# DECR with a floor of zero (a crashed process may have leaked a release).
_RELEASE_LUA = """
local v = redis.call('DECR', KEYS[1])
if v < 0 then redis.call('SET', KEYS[1], '0', 'EX', 3600) end
return 0
"""


def _conc_key(user_id: str) -> str:
    return f"cmd:agentlimit:conc:{user_id}"


def _hour_key(user_id: str) -> str:
    return f"cmd:agentlimit:hour:{user_id}"


class AgentLimiter:
    """Per-user concurrent + hourly rate limiter (Redis-backed when available)."""

    def __init__(self) -> None:
        self._concurrent: dict[str, int] = defaultdict(int)
        self._hourly_calls: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Redis path
    # ------------------------------------------------------------------

    async def _acquire_redis(self, redis, user_id: str) -> str | None:
        code = int(
            await redis.eval(
                _ACQUIRE_LUA,
                2,
                _conc_key(user_id),
                _hour_key(user_id),
                settings.max_concurrent_agent_calls,
                settings.max_agent_calls_per_hour,
                time.time(),
                uuid.uuid4().hex,
            )
        )
        if code == 1:
            return (
                f"Too many concurrent requests "
                f"(limit: {settings.max_concurrent_agent_calls}). "
                "Please wait for a current request to finish."
            )
        if code == 2:
            return (
                f"Hourly request limit reached "
                f"({settings.max_agent_calls_per_hour}/hour). "
                "Please try again later."
            )
        return None

    # ------------------------------------------------------------------
    # In-memory path (single process / Redis unavailable)
    # ------------------------------------------------------------------

    async def _acquire_memory(self, user_id: str) -> str | None:
        async with self._lock:
            now = time.monotonic()

            if self._concurrent[user_id] >= settings.max_concurrent_agent_calls:
                return (
                    f"Too many concurrent requests "
                    f"(limit: {settings.max_concurrent_agent_calls}). "
                    "Please wait for a current request to finish."
                )

            calls = self._hourly_calls[user_id]
            cutoff = now - 3600
            self._hourly_calls[user_id] = [t for t in calls if t > cutoff]

            if len(self._hourly_calls[user_id]) >= settings.max_agent_calls_per_hour:
                return (
                    f"Hourly request limit reached "
                    f"({settings.max_agent_calls_per_hour}/hour). "
                    "Please try again later."
                )

            self._concurrent[user_id] += 1
            self._hourly_calls[user_id].append(now)
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def acquire(self, user_id: str) -> str | None:
        """Try to acquire a slot. Returns error string or None if OK."""
        redis = get_redis()
        if redis is not None:
            try:
                return await self._acquire_redis(redis, user_id)
            except Exception:
                logger.warning(
                    "AgentLimiter: Redis acquire failed, falling back to memory",
                    exc_info=True,
                )
        return await self._acquire_memory(user_id)

    async def release(self, user_id: str) -> None:
        """Release one concurrent slot."""
        redis = get_redis()
        if redis is not None:
            try:
                await redis.eval(_RELEASE_LUA, 1, _conc_key(user_id))
                return
            except Exception:
                logger.warning(
                    "AgentLimiter: Redis release failed, falling back to memory",
                    exc_info=True,
                )
        async with self._lock:
            self._concurrent[user_id] = max(0, self._concurrent[user_id] - 1)


agent_limiter = AgentLimiter()
