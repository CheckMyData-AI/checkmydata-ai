"""Tests for :mod:`app.core.ttl_cache` (T20)."""

from __future__ import annotations

import time

from app.core.ttl_cache import TTLCache


class TestTTLCache:
    def test_set_and_get(self):
        c: TTLCache[str, int] = TTLCache(max_size=10, ttl=60.0)
        c.set("a", 1)
        assert c.get("a") == 1

    def test_lru_eviction(self):
        c: TTLCache[str, int] = TTLCache(max_size=2, ttl=60.0)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)  # evicts 'a'
        assert c.get("a") is None
        assert c.get("b") == 2
        assert c.get("c") == 3

    def test_get_refreshes_recency(self):
        c: TTLCache[str, int] = TTLCache(max_size=2, ttl=60.0)
        c.set("a", 1)
        c.set("b", 2)
        c.get("a")  # touch 'a'
        c.set("c", 3)  # should evict 'b', not 'a'
        assert c.get("a") == 1
        assert c.get("b") is None

    def test_ttl_expiry(self):
        c: TTLCache[str, int] = TTLCache(max_size=10, ttl=0.05)
        c.set("a", 1)
        time.sleep(0.1)
        assert c.get("a") is None

    def test_ttl_zero_means_no_expiry(self):
        c: TTLCache[str, int] = TTLCache(max_size=10, ttl=0.0)
        c.set("a", 1)
        time.sleep(0.05)
        assert c.get("a") == 1

    def test_pop(self):
        c: TTLCache[str, int] = TTLCache(max_size=10, ttl=60.0)
        c.set("a", 1)
        assert c.pop("a") == 1
        assert c.get("a") is None

    def test_get_or_set_caches(self):
        c: TTLCache[str, int] = TTLCache(max_size=10, ttl=60.0)
        calls = {"n": 0}

        def factory():
            calls["n"] += 1
            return 42

        v1 = c.get_or_set("k", factory)
        v2 = c.get_or_set("k", factory)
        assert v1 == v2 == 42
        assert calls["n"] == 1

    def test_len_and_contains(self):
        c: TTLCache[str, int] = TTLCache(max_size=10, ttl=60.0)
        c.set("a", 1)
        assert "a" in c
        assert len(c) == 1

    def test_clear(self):
        c: TTLCache[str, int] = TTLCache(max_size=10, ttl=60.0)
        c.set("a", 1)
        c.clear()
        assert len(c) == 0
