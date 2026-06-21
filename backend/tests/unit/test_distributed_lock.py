from app.core.distributed_lock import redis_lock


async def test_no_redis_yields_true(monkeypatch):
    monkeypatch.setattr("app.core.distributed_lock.get_redis", lambda: None)
    async with redis_lock("k", ttl_seconds=10) as acquired:
        assert acquired is True


async def test_second_holder_is_denied(monkeypatch):
    store: dict = {}

    class FakeRedis:
        async def set(self, key, value, *, nx=False, ex=None):
            if nx and key in store:
                return None
            store[key] = value
            return True

        async def get(self, key):
            return store.get(key)

        async def delete(self, key):
            store.pop(key, None)

    fake = FakeRedis()
    monkeypatch.setattr("app.core.distributed_lock.get_redis", lambda: fake)

    async with redis_lock("dup", ttl_seconds=10) as first:
        assert first is True
        async with redis_lock("dup", ttl_seconds=10) as second:
            assert second is False
    # released after the outer block
    async with redis_lock("dup", ttl_seconds=10) as again:
        assert again is True


async def test_redis_error_on_acquire_yields_false(monkeypatch):
    class BrokenRedis:
        async def set(self, key, value, *, nx=False, ex=None):
            raise RuntimeError("connection refused")

        async def get(self, key):
            return None

        async def delete(self, key):
            pass

    monkeypatch.setattr("app.core.distributed_lock.get_redis", lambda: BrokenRedis())
    async with redis_lock("err", ttl_seconds=5) as acquired:
        assert acquired is False
