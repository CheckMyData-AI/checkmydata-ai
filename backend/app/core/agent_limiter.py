"""Per-user rate limiting for agent calls.

Tracks concurrent requests per user and enforces hourly caps.
All mutations are serialized through an asyncio.Lock.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict

from app.config import settings


class AgentLimiter:
    """In-memory per-user concurrent and hourly rate limiter."""

    def __init__(self) -> None:
        self._concurrent: dict[str, int] = defaultdict(int)
        self._hourly_calls: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def acquire(self, user_id: str) -> str | None:
        """Try to acquire a slot. Returns error string or None if OK."""
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

    async def release(self, user_id: str) -> None:
        """Release one concurrent slot."""
        async with self._lock:
            self._concurrent[user_id] = max(0, self._concurrent[user_id] - 1)


agent_limiter = AgentLimiter()
