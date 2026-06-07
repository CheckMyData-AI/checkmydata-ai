"""Short-lived, single-use tickets for authenticating WebSocket connections.

Browsers cannot set ``Authorization`` headers on a WebSocket handshake, so the
legacy implementation passed the JWT in the URL query string. URLs leak into
server logs, proxy logs, browser history and ``Referer`` headers, so a long-
lived bearer credential there is a real exposure (T-SEC-2 / F-SEC-2).

Instead the browser calls an authenticated HTTP endpoint to mint a ticket, then
hands that ticket to the WS handshake via the ``Sec-WebSocket-Protocol`` header
(never the URL). Tickets are:

* random and opaque (``secrets.token_urlsafe``),
* bound to the exact ``user_id`` / ``project_id`` / ``connection_id`` they were
  issued for,
* single-use (consumed atomically on redemption), and
* short-lived (default 30s TTL).

The store is in-memory and therefore single-process. That is acceptable for this
sprint; a Redis-backed store lands with ``T-SCALE-1`` when the app scales out.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass

DEFAULT_TTL_SECONDS = 30
# Carried in Sec-WebSocket-Protocol so the server can pick the ticket out of any
# other subprotocols a client/proxy might offer.
TICKET_SUBPROTOCOL_PREFIX = "cmd-ticket."


@dataclass(frozen=True)
class _Ticket:
    user_id: str
    project_id: str
    connection_id: str
    expires_at: float


class WsTicketStore:
    """Async-safe, in-memory, single-use ticket store with TTL."""

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._tickets: dict[str, _Ticket] = {}
        self._lock = asyncio.Lock()

    def _prune(self, now: float) -> None:
        expired = [k for k, t in self._tickets.items() if t.expires_at <= now]
        for k in expired:
            self._tickets.pop(k, None)

    async def issue(
        self,
        user_id: str,
        project_id: str,
        connection_id: str,
        ttl_seconds: int | None = None,
    ) -> tuple[str, int]:
        """Mint a ticket bound to (user, project, connection). Returns (ticket, ttl)."""
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl
        ticket = secrets.token_urlsafe(32)
        now = time.monotonic()
        async with self._lock:
            self._prune(now)
            self._tickets[ticket] = _Ticket(
                user_id=user_id,
                project_id=project_id,
                connection_id=connection_id,
                expires_at=now + ttl,
            )
        return ticket, ttl

    async def redeem(self, ticket: str, project_id: str, connection_id: str) -> str | None:
        """Consume a ticket and return its ``user_id`` if it is valid for this route.

        Returns ``None`` when the ticket is unknown, expired, already used, or was
        issued for a different project/connection. The ticket is always removed on
        a match attempt so it can never be replayed.
        """
        if not ticket:
            return None
        now = time.monotonic()
        async with self._lock:
            self._prune(now)
            entry = self._tickets.pop(ticket, None)
            if entry is None:
                return None
            if entry.expires_at <= now:
                return None
            if entry.project_id != project_id or entry.connection_id != connection_id:
                return None
            return entry.user_id


# Process-wide singleton used by the chat routes.
ws_ticket_store = WsTicketStore()
