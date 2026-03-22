"""Unit tests for QueryCache."""

from unittest.mock import patch

from app.connectors.base import QueryResult
from app.core.query_cache import QueryCache


def _ok_result(**overrides):
    defaults = dict(columns=["a"], rows=[[1]], row_count=1, execution_time_ms=10)
    defaults.update(overrides)
    return QueryResult(**defaults)


def _err_result():
    return QueryResult(columns=[], rows=[], row_count=0, execution_time_ms=0, error="fail")


# ── _make_key ──────────────────────────────────────────────────────────


class TestMakeKey:
    def test_normalizes_whitespace(self):
        k1 = QueryCache._make_key("c", "SELECT   1  FROM   t")
        k2 = QueryCache._make_key("c", "SELECT 1 FROM t")
        assert k1 == k2

    def test_lowercases(self):
        k1 = QueryCache._make_key("c", "SELECT 1")
        k2 = QueryCache._make_key("c", "select 1")
        assert k1 == k2

    def test_includes_connection_key(self):
        k1 = QueryCache._make_key("conn_a", "SELECT 1")
        k2 = QueryCache._make_key("conn_b", "SELECT 1")
        assert k1 != k2
        assert k1.startswith("conn_a:")
        assert k2.startswith("conn_b:")

    def test_includes_schema_version(self):
        k1 = QueryCache._make_key("c", "SELECT 1", schema_version="v1")
        k2 = QueryCache._make_key("c", "SELECT 1", schema_version="v2")
        assert k1 != k2
        assert ":v1:" in k1
        assert ":v2:" in k2

    def test_no_schema_version_uses_underscore(self):
        key = QueryCache._make_key("c", "SELECT 1")
        assert ":_:" in key

    def test_same_query_different_schema_version_different_keys(self):
        k_none = QueryCache._make_key("c", "SELECT 1")
        k_v1 = QueryCache._make_key("c", "SELECT 1", schema_version="v1")
        assert k_none != k_v1


# ── get / put ──────────────────────────────────────────────────────────


class TestGetPut:
    def test_put_then_get_returns_result(self):
        cache = QueryCache()
        r = _ok_result()
        cache.put("c", "SELECT 1", r)
        assert cache.get("c", "SELECT 1") is r

    def test_get_missing_returns_none(self):
        cache = QueryCache()
        assert cache.get("c", "SELECT 1") is None

    def test_get_expired_returns_none(self):
        cache = QueryCache(ttl_seconds=60)
        r = _ok_result()
        with patch("time.monotonic", return_value=1000.0):
            cache.put("c", "SELECT 1", r)
        with patch("time.monotonic", return_value=1061.0):
            assert cache.get("c", "SELECT 1") is None
        assert cache.size == 0

    def test_put_skips_error_result(self):
        cache = QueryCache()
        cache.put("c", "SELECT 1", _err_result())
        assert cache.size == 0
        assert cache.get("c", "SELECT 1") is None

    def test_evicts_oldest_when_max_size_exceeded(self):
        cache = QueryCache(max_size=2)
        cache.put("c", "q1", _ok_result())
        cache.put("c", "q2", _ok_result())
        cache.put("c", "q3", _ok_result())
        assert cache.size == 2
        assert cache.get("c", "q1") is None
        assert cache.get("c", "q2") is not None

    def test_lru_get_prevents_eviction(self):
        cache = QueryCache(max_size=2)
        r1 = _ok_result()
        cache.put("c", "q1", r1)
        cache.put("c", "q2", _ok_result())
        cache.get("c", "q1")
        cache.put("c", "q3", _ok_result())
        assert cache.size == 2
        assert cache.get("c", "q1") is r1
        assert cache.get("c", "q2") is None


# ── invalidate ─────────────────────────────────────────────────────────


class TestInvalidate:
    def test_removes_all_entries_for_connection(self):
        cache = QueryCache()
        cache.put("c1", "q1", _ok_result())
        cache.put("c1", "q2", _ok_result())
        cache.invalidate("c1")
        assert cache.size == 0

    def test_does_not_remove_other_connections(self):
        cache = QueryCache()
        cache.put("c1", "q1", _ok_result())
        cache.put("c2", "q1", _ok_result())
        cache.invalidate("c1")
        assert cache.size == 1
        assert cache.get("c2", "q1") is not None


# ── invalidate_schema ──────────────────────────────────────────────────


class TestInvalidateSchema:
    def test_removes_stale_schema_entries(self):
        cache = QueryCache()
        cache.put("c", "q1", _ok_result(), schema_version="v1")
        cache.put("c", "q2", _ok_result(), schema_version="v2")
        cache.invalidate_schema("c", "v2")
        assert cache.size == 1
        assert cache.get("c", "q1", schema_version="v1") is None
        assert cache.get("c", "q2", schema_version="v2") is not None

    def test_keeps_current_schema_entries(self):
        cache = QueryCache()
        cache.put("c", "q1", _ok_result(), schema_version="v3")
        cache.put("c", "q2", _ok_result(), schema_version="v3")
        cache.invalidate_schema("c", "v3")
        assert cache.size == 2


# ── clear / size ───────────────────────────────────────────────────────


class TestClearAndSize:
    def test_clear_removes_all(self):
        cache = QueryCache()
        cache.put("c1", "q1", _ok_result())
        cache.put("c2", "q2", _ok_result())
        cache.clear()
        assert cache.size == 0

    def test_size_reflects_entries(self):
        cache = QueryCache()
        assert cache.size == 0
        cache.put("c", "q1", _ok_result())
        assert cache.size == 1
        cache.put("c", "q2", _ok_result())
        assert cache.size == 2
