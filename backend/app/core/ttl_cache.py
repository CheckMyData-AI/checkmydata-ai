"""Generic TTL + LRU cache with bounded size."""

from __future__ import annotations

import time
from collections import OrderedDict


class TTLCache[V]:
    """In-memory cache with time-to-live and LRU eviction at max_size."""

    def __init__(self, ttl: float = 300.0, max_size: int = 128) -> None:
        self._ttl = ttl
        self._max_size = max_size
        self._data: OrderedDict[str, tuple[float, V]] = OrderedDict()

    def get(self, key: str) -> V | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        ts, value = entry
        if (time.monotonic() - ts) >= self._ttl:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def put(self, key: str, value: V) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = (time.monotonic(), value)
        while len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def invalidate(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)
