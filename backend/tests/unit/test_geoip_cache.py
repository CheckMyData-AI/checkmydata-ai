"""Unit tests for GeoIPCache (two-tier: memory LRU + SQLite)."""

from __future__ import annotations

import os
import threading

import pytest

from app.services.geoip_cache import GeoIPCache
from app.services.geoip_service import GeoIPResult


@pytest.fixture()
def cache(tmp_path):
    """Return a GeoIPCache backed by a temporary SQLite file."""
    db = os.path.join(str(tmp_path), "test_geoip.db")
    c = GeoIPCache(db_path=db, memory_max_size=5)
    yield c
    c.close()


US = GeoIPResult(country_code="US", country_name="United States")
DE = GeoIPResult(country_code="DE", country_name="Germany")
AU = GeoIPResult(country_code="AU", country_name="Australia")
PRIVATE = GeoIPResult(country_code="", country_name="Private Network", is_private=True)
UNKNOWN = GeoIPResult(country_code="", country_name="Unknown")


class TestSingleKey:
    def test_get_miss_returns_none(self, cache: GeoIPCache):
        assert cache.get("1.1.1.1") is None

    def test_put_then_get(self, cache: GeoIPCache):
        cache.put("8.8.8.8", US)
        result = cache.get("8.8.8.8")
        assert result is not None
        assert result.country_code == "US"
        assert result.country_name == "United States"
        assert result.is_private is False

    def test_put_private_ip(self, cache: GeoIPCache):
        cache.put("192.168.1.1", PRIVATE)
        result = cache.get("192.168.1.1")
        assert result is not None
        assert result.is_private is True

    def test_put_overwrites_existing(self, cache: GeoIPCache):
        cache.put("8.8.8.8", US)
        cache.put("8.8.8.8", DE)
        result = cache.get("8.8.8.8")
        assert result is not None
        assert result.country_code == "DE"


class TestBatchOperations:
    def test_get_many_empty(self, cache: GeoIPCache):
        assert cache.get_many([]) == {}

    def test_get_many_all_misses(self, cache: GeoIPCache):
        result = cache.get_many(["1.1.1.1", "2.2.2.2"])
        assert result == {}

    def test_put_many_then_get_many(self, cache: GeoIPCache):
        items = [("1.1.1.1", AU), ("8.8.8.8", US), ("5.5.5.5", DE)]
        cache.put_many(items)

        found = cache.get_many(["1.1.1.1", "8.8.8.8", "9.9.9.9"])
        assert len(found) == 2
        assert found["1.1.1.1"].country_code == "AU"
        assert found["8.8.8.8"].country_code == "US"
        assert "9.9.9.9" not in found

    def test_put_many_empty_list(self, cache: GeoIPCache):
        cache.put_many([])
        assert cache.stats()["sqlite_entries"] == 0

    def test_get_many_large_batch(self, tmp_path):
        """Ensure batched SQL works for >500 IPs."""
        db = os.path.join(str(tmp_path), "large.db")
        c = GeoIPCache(db_path=db, memory_max_size=10)
        try:
            items = [(f"10.0.{i // 256}.{i % 256}", US) for i in range(600)]
            c.put_many(items)
            c._mem.clear()  # force SQLite path

            all_ips = [ip for ip, _ in items]
            found = c.get_many(all_ips)
            assert len(found) == 600
        finally:
            c.close()


class TestLRUEviction:
    def test_memory_eviction_at_max_size(self, cache: GeoIPCache):
        """Cache has memory_max_size=5; inserting 7 should evict the 2 oldest."""
        for i in range(7):
            cache.put(f"10.0.0.{i}", US)

        with cache._lock:
            assert len(cache._mem) == 5
            assert "10.0.0.0" not in cache._mem
            assert "10.0.0.1" not in cache._mem
            assert "10.0.0.6" in cache._mem

    def test_evicted_from_memory_still_in_sqlite(self, cache: GeoIPCache):
        for i in range(7):
            cache.put(f"10.0.0.{i}", US)

        result = cache.get("10.0.0.0")
        assert result is not None
        assert result.country_code == "US"

    def test_access_promotes_in_lru(self, cache: GeoIPCache):
        """Accessing an entry moves it to the end so it survives eviction."""
        for i in range(5):
            cache.put(f"10.0.0.{i}", US)

        cache.get("10.0.0.0")

        cache.put("10.0.0.99", DE)

        with cache._lock:
            assert "10.0.0.0" in cache._mem
            assert "10.0.0.1" not in cache._mem


class TestPersistence:
    def test_survives_close_and_reopen(self, tmp_path):
        db = os.path.join(str(tmp_path), "persist.db")

        c1 = GeoIPCache(db_path=db, memory_max_size=100)
        c1.put("8.8.8.8", US)
        c1.put("1.1.1.1", AU)
        c1.close()

        c2 = GeoIPCache(db_path=db, memory_max_size=100)
        try:
            assert c2.get("8.8.8.8") is not None
            assert c2.get("8.8.8.8").country_code == "US"
            assert c2.get("1.1.1.1").country_code == "AU"
            assert c2.stats()["sqlite_entries"] == 2
        finally:
            c2.close()


class TestStats:
    def test_empty_stats(self, cache: GeoIPCache):
        s = cache.stats()
        assert s["memory_entries"] == 0
        assert s["sqlite_entries"] == 0

    def test_stats_after_inserts(self, cache: GeoIPCache):
        cache.put("1.1.1.1", US)
        cache.put("2.2.2.2", DE)
        s = cache.stats()
        assert s["memory_entries"] == 2
        assert s["sqlite_entries"] == 2


class TestClear:
    def test_clear_wipes_both_tiers(self, cache: GeoIPCache):
        cache.put("8.8.8.8", US)
        cache.put("1.1.1.1", AU)
        assert cache.stats()["sqlite_entries"] == 2

        cache.clear()

        assert cache.stats()["memory_entries"] == 0
        assert cache.stats()["sqlite_entries"] == 0
        assert cache.get("8.8.8.8") is None


class TestThreadSafety:
    def test_concurrent_puts(self, tmp_path):
        db = os.path.join(str(tmp_path), "thread.db")
        c = GeoIPCache(db_path=db, memory_max_size=10_000)
        errors: list[Exception] = []

        def writer(start: int):
            try:
                for i in range(200):
                    ip = f"10.{start}.{i // 256}.{i % 256}"
                    c.put(ip, US)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent writes raised: {errors}"
        assert c.stats()["sqlite_entries"] == 800
        c.close()

    def test_concurrent_reads_and_writes(self, tmp_path):
        db = os.path.join(str(tmp_path), "rw.db")
        c = GeoIPCache(db_path=db, memory_max_size=1_000)
        items = [(f"10.0.{i // 256}.{i % 256}", US) for i in range(100)]
        c.put_many(items)
        errors: list[Exception] = []

        def reader():
            try:
                for ip, _ in items:
                    c.get(ip)
            except Exception as exc:
                errors.append(exc)

        def writer():
            try:
                for i in range(100):
                    c.put(f"20.0.0.{i}", DE)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        c.close()
        assert not errors
