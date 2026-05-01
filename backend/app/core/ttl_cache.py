"""Small TTL + LRU caches for in-process memory hygiene.

Used by chat session locks, connector health state, query/schema caches,
and similar singletons that would otherwise grow unbounded over the
lifetime of a process.

These caches are intentionally tiny and synchronous. If you need
per-entry expiration callbacks or distributed eviction, reach for Redis
instead.

Historical note (T20): the original ``TTLCache`` exposed ``put`` /
``invalidate`` for string-keyed values. T20 added ``set`` / ``pop`` /
``get_or_set`` for richer use cases (session locks, health state).
Both APIs are supported — ``put`` and ``invalidate`` remain as aliases
so existing call sites keep working.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class TTLCache(Generic[K, V]):
    """An LRU-capped cache where entries also expire after ``ttl`` seconds.

    Thread-safe within a single process via a simple re-entrant lock —
    good enough for the volumes we handle here (~thousands of entries).
    Not safe for cross-process use.
    """

    def __init__(
        self,
        ttl: float = 300.0,
        max_size: int = 1024,
    ) -> None:
        self._max_size = max(1, max_size)
        self._ttl = max(0.0, ttl)
        self._store: OrderedDict[K, tuple[V, float]] = OrderedDict()
        self._lock = threading.RLock()

    def __len__(self) -> int:
        with self._lock:
            self._purge_expired()
            return len(self._store)

    def __contains__(self, key: K) -> bool:
        return self.get(key) is not None

    def get(self, key: K) -> V | None:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if self._ttl > 0 and expires_at <= now:
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return value

    def set(self, key: K, value: V) -> None:
        with self._lock:
            expires_at = (
                time.monotonic() + self._ttl if self._ttl > 0 else float("inf")
            )
            self._store[key] = (value, expires_at)
            self._store.move_to_end(key)
            while len(self._store) > self._max_size:
                self._store.popitem(last=False)

    # ------------------------------------------------------------------
    # Legacy-compat aliases (pre-T20 call sites use ``put`` / ``invalidate``)
    # ------------------------------------------------------------------

    def put(self, key: K, value: V) -> None:
        """Alias for :meth:`set` — kept for backwards compatibility."""
        self.set(key, value)

    def invalidate(self, key: K) -> None:
        """Alias for :meth:`pop` that does not return anything."""
        self.pop(key)

    def pop(self, key: K, default: V | None = None) -> V | None:
        with self._lock:
            entry = self._store.pop(key, None)
            if entry is None:
                return default
            return entry[0]

    def get_or_set(self, key: K, factory) -> V:
        """Return the cached value or compute + cache it via ``factory()``."""
        existing = self.get(key)
        if existing is not None:
            return existing
        with self._lock:
            existing = self.get(key)
            if existing is not None:
                return existing
            value = factory()
            self.set(key, value)
            return value

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def _purge_expired(self) -> None:
        if self._ttl <= 0:
            return
        now = time.monotonic()
        expired = [k for k, (_, exp) in self._store.items() if exp <= now]
        for k in expired:
            self._store.pop(k, None)
