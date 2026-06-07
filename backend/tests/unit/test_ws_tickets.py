"""Unit tests for the single-use WebSocket ticket store (T-SEC-2)."""

import time

import pytest

from app.core.ws_tickets import (
    TICKET_SUBPROTOCOL_PREFIX,
    WsTicketStore,
)


@pytest.mark.asyncio
class TestWsTicketStore:
    async def test_issue_then_redeem_returns_user(self):
        store = WsTicketStore()
        ticket, ttl = await store.issue("user-1", "proj-1", "conn-1")
        assert ticket
        assert ttl == 30
        assert await store.redeem(ticket, "proj-1", "conn-1") == "user-1"

    async def test_ticket_is_single_use(self):
        store = WsTicketStore()
        ticket, _ = await store.issue("user-1", "proj-1", "conn-1")
        assert await store.redeem(ticket, "proj-1", "conn-1") == "user-1"
        # Second redemption must fail — the ticket was consumed.
        assert await store.redeem(ticket, "proj-1", "conn-1") is None

    async def test_redeem_rejects_wrong_project(self):
        store = WsTicketStore()
        ticket, _ = await store.issue("user-1", "proj-1", "conn-1")
        assert await store.redeem(ticket, "other-proj", "conn-1") is None

    async def test_redeem_rejects_wrong_connection(self):
        store = WsTicketStore()
        ticket, _ = await store.issue("user-1", "proj-1", "conn-1")
        assert await store.redeem(ticket, "proj-1", "other-conn") is None

    async def test_unknown_ticket_returns_none(self):
        store = WsTicketStore()
        assert await store.redeem("nope", "proj-1", "conn-1") is None

    async def test_empty_ticket_returns_none(self):
        store = WsTicketStore()
        assert await store.redeem("", "proj-1", "conn-1") is None

    async def test_expired_ticket_returns_none(self, monkeypatch):
        store = WsTicketStore(ttl_seconds=1)
        ticket, _ = await store.issue("user-1", "proj-1", "conn-1")
        # Advance the monotonic clock past the TTL.
        real_monotonic = time.monotonic
        monkeypatch.setattr("app.core.ws_tickets.time.monotonic", lambda: real_monotonic() + 5)
        assert await store.redeem(ticket, "proj-1", "conn-1") is None

    async def test_custom_ttl_is_reported(self):
        store = WsTicketStore()
        _, ttl = await store.issue("u", "p", "c", ttl_seconds=120)
        assert ttl == 120

    async def test_subprotocol_prefix_constant(self):
        # Guards against accidental rename that would desync client/server.
        assert TICKET_SUBPROTOCOL_PREFIX == "cmd-ticket."
