"""Persistent LRU query cache with schema-version awareness.

Falls back to an in-memory LRU when no database is available.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass

from app.connectors.base import QueryResult

logger = logging.getLogger(__name__)


@dataclass
class CachedResult:
    result: QueryResult
    cached_at: float
    schema_version: str | None = None


class QueryCache:
    """TTL-aware LRU cache keyed on ``(connection_key, query_hash, schema_version)``."""

    def __init__(
        self,
        max_size: int = 256,
        ttl_seconds: float = 600,
    ):
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, CachedResult] = OrderedDict()

    @staticmethod
    def _make_key(
        connection_key: str,
        query: str,
        schema_version: str | None = None,
    ) -> str:
        normalized = " ".join(query.strip().split()).lower()
        qhash = hashlib.sha256(normalized.encode()).hexdigest()[:16]
        sv = schema_version or "_"
        return f"{connection_key}:{sv}:{qhash}"

    def get(
        self,
        connection_key: str,
        query: str,
        schema_version: str | None = None,
    ) -> QueryResult | None:
        key = self._make_key(connection_key, query, schema_version)
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.monotonic() - entry.cached_at > self._ttl:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        logger.debug("Cache hit for key=%s", key[:30])
        return entry.result

    def put(
        self,
        connection_key: str,
        query: str,
        result: QueryResult,
        schema_version: str | None = None,
    ) -> None:
        if result.error:
            return
        key = self._make_key(connection_key, query, schema_version)
        self._store[key] = CachedResult(
            result=result,
            cached_at=time.monotonic(),
            schema_version=schema_version,
        )
        self._store.move_to_end(key)
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def invalidate(self, connection_key: str) -> None:
        keys_to_remove = [k for k in self._store if k.startswith(f"{connection_key}:")]
        for k in keys_to_remove:
            del self._store[k]

    def invalidate_schema(self, connection_key: str, schema_version: str) -> None:
        """Remove entries whose schema version doesn't match the current one."""
        prefix = f"{connection_key}:"
        keys_to_remove = [
            k
            for k, v in self._store.items()
            if k.startswith(prefix) and v.schema_version != schema_version
        ]
        for k in keys_to_remove:
            del self._store[k]

    def clear(self) -> None:
        self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)
