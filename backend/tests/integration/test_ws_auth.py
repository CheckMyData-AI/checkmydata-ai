"""WebSocket authentication tests for the chat endpoint (T-SEC-2).

Authentication moved from a JWT in the URL query string to a single-use ticket
carried in ``Sec-WebSocket-Protocol``. These tests verify the handshake rejects
unauthenticated connects and that the ticket store gates redemption.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.ws_tickets import TICKET_SUBPROTOCOL_PREFIX, ws_ticket_store
from app.main import app


class TestWebSocketTicketAuth:
    def test_connect_without_ticket_is_rejected(self):
        client = TestClient(app)
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/chat/ws/proj-1/conn-1"):
                pass
        # 4001 == authentication required (handler closes before accept).
        assert exc_info.value.code == 4001

    def test_connect_with_unknown_ticket_is_rejected(self):
        client = TestClient(app)
        sub = f"{TICKET_SUBPROTOCOL_PREFIX}bogus-ticket"
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/chat/ws/proj-1/conn-1", subprotocols=[sub]):
                pass
        assert exc_info.value.code == 4001

    @pytest.mark.asyncio
    async def test_ticket_is_consumed_on_redeem(self):
        # A ticket issued for one route cannot be replayed or used elsewhere.
        ticket, _ = await ws_ticket_store.issue("user-1", "proj-1", "conn-1")
        assert await ws_ticket_store.redeem(ticket, "proj-1", "conn-1") == "user-1"
        assert await ws_ticket_store.redeem(ticket, "proj-1", "conn-1") is None

    @pytest.mark.asyncio
    async def test_ticket_bound_to_route(self):
        ticket, _ = await ws_ticket_store.issue("user-1", "proj-1", "conn-1")
        # Wrong connection id must not redeem (and must consume the ticket).
        assert await ws_ticket_store.redeem(ticket, "proj-1", "WRONG") is None
