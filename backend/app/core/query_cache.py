"""Short-lived LRU cache for query results to avoid duplicate execution."""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass

from app.connectors.base import QueryResult


@dataclass
class CachedResult:
    result: QueryResult
    cached_at: float


class QueryCache:
    """TTL-aware LRU cache keyed on ``(connection_key, query_hash)``."""

    def __init__(self, max_size: int = 64, ttl_seconds: float = 120):
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, CachedResult] = OrderedDict()

    @staticmethod
    def _make_key(connection_key: str, query: str) -> str:
        normalized = " ".join(query.strip().split()).lower()
        qhash = hashlib.sha256(normalized.encode()).hexdigest()[:16]
        return f"{connection_key}:{qhash}"

    def get(self, connection_key: str, query: str) -> QueryResult | None:
        key = self._make_key(connection_key, query)
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.monotonic() - entry.cached_at > self._ttl:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return entry.result

    def put(self, connection_key: str, query: str, result: QueryResult) -> None:
        if result.error:
            return
        key = self._make_key(connection_key, query)
        self._store[key] = CachedResult(result=result, cached_at=time.monotonic())
        self._store.move_to_end(key)
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def invalidate(self, connection_key: str) -> None:
        keys_to_remove = [k for k in self._store if k.startswith(f"{connection_key}:")]
        for k in keys_to_remove:
            del self._store[k]

    def clear(self) -> None:
        self._store.clear()
