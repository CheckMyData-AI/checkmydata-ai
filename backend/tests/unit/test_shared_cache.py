"""Unit tests for the shared cache layer (in-memory fallback path)."""

import pytest

from app.core.cache import SharedCache


@pytest.fixture
def cache():
    return SharedCache(prefix="test", ttl=60, max_local_size=16)


@pytest.mark.asyncio
async def test_connect_without_redis(cache: SharedCache):
    await cache.connect(None)
    assert not cache.is_redis_connected


@pytest.mark.asyncio
async def test_put_and_get(cache: SharedCache):
    await cache.connect(None)
    await cache.put("k1", {"hello": "world"})
    result = await cache.get("k1")
    assert result == {"hello": "world"}


@pytest.mark.asyncio
async def test_get_missing_returns_none(cache: SharedCache):
    await cache.connect(None)
    assert await cache.get("nonexistent") is None


@pytest.mark.asyncio
async def test_invalidate(cache: SharedCache):
    await cache.connect(None)
    await cache.put("k1", "val")
    await cache.invalidate("k1")
    assert await cache.get("k1") is None


@pytest.mark.asyncio
async def test_invalidate_prefix(cache: SharedCache):
    await cache.connect(None)
    await cache.put("conn:a", 1)
    await cache.put("conn:b", 2)
    await cache.put("other", 3)
    await cache.invalidate_prefix("conn:")
    assert await cache.get("conn:a") is None
    assert await cache.get("other") is None


@pytest.mark.asyncio
async def test_close_resets_redis_flag(cache: SharedCache):
    await cache.connect(None)
    await cache.close()
    assert not cache.is_redis_connected


@pytest.mark.asyncio
async def test_serializes_various_types(cache: SharedCache):
    await cache.connect(None)
    await cache.put("int", 42)
    await cache.put("list", [1, 2, 3])
    await cache.put("str", "hello")

    assert await cache.get("int") == 42
    assert await cache.get("list") == [1, 2, 3]
    assert await cache.get("str") == "hello"
