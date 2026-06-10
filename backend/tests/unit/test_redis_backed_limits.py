"""Redis-backed paths of AgentLimiter and WsTicketStore (T-SCALE-1 / T-SEC-7)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.core.agent_limiter import AgentLimiter
from app.core.ws_tickets import WsTicketStore


class _FakeRedisTickets:
    """Minimal fake supporting set(nx, ex) + getdel."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def getdel(self, key):
        return self.store.pop(key, None)


class TestWsTicketStoreRedis:
    @pytest.mark.asyncio
    async def test_issue_and_redeem_via_redis(self):
        fake = _FakeRedisTickets()
        store = WsTicketStore()
        with patch("app.core.ws_tickets.get_redis", return_value=fake):
            ticket, ttl = await store.issue("u1", "p1", "c1")
            assert ttl > 0
            assert len(fake.store) == 1
            user = await store.redeem(ticket, "p1", "c1")
        assert user == "u1"
        assert fake.store == {}  # consumed

    @pytest.mark.asyncio
    async def test_redeem_is_single_use(self):
        fake = _FakeRedisTickets()
        store = WsTicketStore()
        with patch("app.core.ws_tickets.get_redis", return_value=fake):
            ticket, _ = await store.issue("u1", "p1", "c1")
            assert await store.redeem(ticket, "p1", "c1") == "u1"
            assert await store.redeem(ticket, "p1", "c1") is None

    @pytest.mark.asyncio
    async def test_redeem_wrong_binding_denied(self):
        fake = _FakeRedisTickets()
        store = WsTicketStore()
        with patch("app.core.ws_tickets.get_redis", return_value=fake):
            ticket, _ = await store.issue("u1", "p1", "c1")
            assert await store.redeem(ticket, "p2", "c1") is None
        # consumed even on a failed attempt — no replay
        assert fake.store == {}

    @pytest.mark.asyncio
    async def test_corrupt_payload_denied(self):
        fake = _FakeRedisTickets()
        store = WsTicketStore()
        fake.store["cmd:wsticket:bad"] = "{not json"
        with patch("app.core.ws_tickets.get_redis", return_value=fake):
            assert await store.redeem("bad", "p1", "c1") is None

    @pytest.mark.asyncio
    async def test_redis_error_falls_back_to_memory(self):
        broken = AsyncMock()
        broken.set = AsyncMock(side_effect=RuntimeError("redis down"))
        broken.getdel = AsyncMock(side_effect=RuntimeError("redis down"))
        store = WsTicketStore()
        with patch("app.core.ws_tickets.get_redis", return_value=broken):
            ticket, _ = await store.issue("u1", "p1", "c1")
            assert await store.redeem(ticket, "p1", "c1") == "u1"

    @pytest.mark.asyncio
    async def test_payload_binds_all_fields(self):
        fake = _FakeRedisTickets()
        store = WsTicketStore()
        with patch("app.core.ws_tickets.get_redis", return_value=fake):
            ticket, _ = await store.issue("u1", "p1", "c1")
        entry = json.loads(fake.store[f"cmd:wsticket:{ticket}"])
        assert entry == {"user_id": "u1", "project_id": "p1", "connection_id": "c1"}


class TestAgentLimiterRedis:
    @pytest.mark.asyncio
    async def test_acquire_ok(self):
        fake = AsyncMock()
        fake.eval = AsyncMock(return_value=0)
        limiter = AgentLimiter()
        with patch("app.core.agent_limiter.get_redis", return_value=fake):
            assert await limiter.acquire("u1") is None
        fake.eval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_acquire_concurrency_limit(self):
        fake = AsyncMock()
        fake.eval = AsyncMock(return_value=1)
        limiter = AgentLimiter()
        with patch("app.core.agent_limiter.get_redis", return_value=fake):
            err = await limiter.acquire("u1")
        assert err is not None and "concurrent" in err

    @pytest.mark.asyncio
    async def test_acquire_hourly_limit(self):
        fake = AsyncMock()
        fake.eval = AsyncMock(return_value=2)
        limiter = AgentLimiter()
        with patch("app.core.agent_limiter.get_redis", return_value=fake):
            err = await limiter.acquire("u1")
        assert err is not None and "Hourly" in err

    @pytest.mark.asyncio
    async def test_release_uses_redis(self):
        fake = AsyncMock()
        fake.eval = AsyncMock(return_value=0)
        limiter = AgentLimiter()
        with patch("app.core.agent_limiter.get_redis", return_value=fake):
            await limiter.release("u1")
        fake.eval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_redis_error_falls_back_to_memory(self):
        fake = AsyncMock()
        fake.eval = AsyncMock(side_effect=RuntimeError("redis down"))
        limiter = AgentLimiter()
        with patch("app.core.agent_limiter.get_redis", return_value=fake):
            assert await limiter.acquire("u1") is None  # memory path allowed
            await limiter.release("u1")
        assert limiter._concurrent["u1"] == 0
