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

When the shared Redis client is connected (T-SCALE-1) tickets live in Redis
(``SET EX`` + atomic ``GETDEL`` redemption) so the WS handshake can land on a
different dyno than the one that minted the ticket. Without Redis the original
in-memory, single-process store applies.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

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


def _rkey(ticket: str) -> str:
    return f"cmd:wsticket:{ticket}"


class WsTicketStore:
    """Async-safe, single-use ticket store with TTL (Redis-backed when available)."""

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

        redis = get_redis()
        if redis is not None:
            try:
                await redis.set(
                    _rkey(ticket),
                    json.dumps(
                        {
                            "user_id": user_id,
                            "project_id": project_id,
                            "connection_id": connection_id,
                        }
                    ),
                    ex=max(1, int(ttl)),
                    nx=True,
                )
                return ticket, ttl
            except Exception:
                logger.warning(
                    "WsTicketStore: Redis issue failed, falling back to memory",
                    exc_info=True,
                )

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

        redis = get_redis()
        if redis is not None:
            try:
                # GETDEL is atomic: one redemption ever sees the value.
                raw = await redis.getdel(_rkey(ticket))
                if raw is not None:
                    try:
                        entry = json.loads(raw)
                    except (TypeError, ValueError):
                        return None
                    if (
                        entry.get("project_id") != project_id
                        or entry.get("connection_id") != connection_id
                    ):
                        return None
                    return entry.get("user_id")
                # Not in Redis — fall through to the in-memory store, which may
                # hold tickets issued before Redis connected.
            except Exception:
                logger.warning(
                    "WsTicketStore: Redis redeem failed, falling back to memory",
                    exc_info=True,
                )

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
