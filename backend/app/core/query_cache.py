"""LRU query cache with schema-version awareness and optional file persistence.

Uses an in-memory LRU by default.  When *persist_dir* is set, cache entries
are serialized to disk so they survive process restarts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from app.connectors.base import QueryResult

logger = logging.getLogger(__name__)


@dataclass
class CachedResult:
    result: QueryResult
    cached_at: float
    schema_version: str | None = None


class QueryCache:
    """TTL-aware LRU cache keyed on ``(connection_key, query_hash, schema_version)``.

    When *persist_dir* is given, entries are also saved to disk on ``put``
    and loaded lazily on ``get`` if the in-memory entry has expired but the
    file is still within TTL.
    """

    def __init__(
        self,
        max_size: int = 256,
        ttl_seconds: float = 600,
        persist_dir: str | None = None,
    ):
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, CachedResult] = OrderedDict()
        self._persist_dir: Path | None = None
        if persist_dir:
            self._persist_dir = Path(persist_dir)
            self._persist_dir.mkdir(parents=True, exist_ok=True)

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
            disk_result = self._load_from_disk(key)
            if disk_result is not None:
                logger.debug("Cache hit (disk) for key=%s", key[:30])
                return disk_result
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
            evicted_key, _ = self._store.popitem(last=False)
            self._delete_persisted(evicted_key)

        self._persist_to_disk(key, result, schema_version)

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

    # ------------------------------------------------------------------
    # File persistence helpers
    # ------------------------------------------------------------------

    def _persist_to_disk(
        self,
        key: str,
        result: QueryResult,
        schema_version: str | None,
    ) -> None:
        if not self._persist_dir:
            return
        try:
            safe_key = hashlib.sha256(key.encode()).hexdigest()[:24]
            path = self._persist_dir / f"{safe_key}.json"
            data = {
                "key": key,
                "cached_at": time.time(),
                "schema_version": schema_version,
                "columns": result.columns,
                "rows": [[str(v) for v in row] for row in result.rows[:200]],
                "row_count": result.row_count,
                "execution_time_ms": result.execution_time_ms,
            }
            path.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            logger.debug("Failed to persist cache entry %s", key[:30], exc_info=True)

    def _load_from_disk(self, key: str) -> QueryResult | None:
        if not self._persist_dir:
            return None
        try:
            safe_key = hashlib.sha256(key.encode()).hexdigest()[:24]
            path = self._persist_dir / f"{safe_key}.json"
            if not path.exists():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            file_age = time.time() - data.get("cached_at", 0)
            if file_age > self._ttl:
                path.unlink(missing_ok=True)
                return None
            result = QueryResult(
                columns=data["columns"],
                rows=data["rows"],
                row_count=data.get("row_count", len(data["rows"])),
                execution_time_ms=data.get("execution_time_ms", 0),
            )
            self._store[key] = CachedResult(
                result=result,
                cached_at=time.monotonic(),
                schema_version=data.get("schema_version"),
            )
            return result
        except Exception:
            logger.debug("Failed to load persisted cache for %s", key[:30], exc_info=True)
            return None

    def _delete_persisted(self, key: str) -> None:
        if not self._persist_dir:
            return
        try:
            safe_key = hashlib.sha256(key.encode()).hexdigest()[:24]
            path = self._persist_dir / f"{safe_key}.json"
            path.unlink(missing_ok=True)
        except Exception:
            pass
