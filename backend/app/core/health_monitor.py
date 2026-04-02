"""Connection health monitoring with lightweight periodic checks.

Tracks per-connection health state (healthy / degraded / down) based on
latency measurements and consecutive failure counts.  Broadcasts state
changes via WorkflowTracker SSE events.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app.config import settings

logger = logging.getLogger(__name__)

HealthStatus = Literal["healthy", "degraded", "down"]

DEGRADED_LATENCY_MS = settings.health_degraded_latency_ms
MAX_CONSECUTIVE_FAILURES = 2
CHECK_TIMEOUT_SECONDS = 10


@dataclass
class HealthState:
    status: HealthStatus = "healthy"
    latency_ms: int = 0
    last_check: datetime = field(default_factory=lambda: datetime.now(UTC))
    consecutive_failures: int = 0
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "latency_ms": self.latency_ms,
            "last_check": self.last_check.isoformat(),
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
        }


class ConnectionHealthMonitor:
    def __init__(self) -> None:
        self._health_state: dict[str, HealthState] = {}
        self._lock = asyncio.Lock()

    async def check_connection(
        self,
        connection_id: str,
        connector: Any,
    ) -> dict[str, Any]:
        state = self._health_state.get(connection_id, HealthState())
        t0 = time.monotonic()

        try:
            alive = await asyncio.wait_for(
                connector.test_connection(),
                timeout=CHECK_TIMEOUT_SECONDS,
            )
            latency_ms = int((time.monotonic() - t0) * 1000)

            if not alive:
                raise ConnectionError("test_connection returned False")

            state.latency_ms = latency_ms
            state.last_check = datetime.now(UTC)
            state.last_error = None
            state.consecutive_failures = 0

            if latency_ms > DEGRADED_LATENCY_MS:
                state.status = "degraded"
            else:
                state.status = "healthy"

        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            state.latency_ms = latency_ms
            state.last_check = datetime.now(UTC)
            state.consecutive_failures += 1
            state.last_error = str(exc)

            if state.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                state.status = "down"
            else:
                state.status = "degraded"

            _QUIET_AFTER = 3
            if state.consecutive_failures <= _QUIET_AFTER:
                logger.warning(
                    "Health check failed for connection %s (attempt %d): %s",
                    connection_id,
                    state.consecutive_failures,
                    exc,
                )
            else:
                logger.debug(
                    "Health check failed for connection %s (attempt %d, suppressed): %s",
                    connection_id,
                    state.consecutive_failures,
                    exc,
                )

        async with self._lock:
            self._health_state[connection_id] = state

        return state.to_dict()

    def get_health(self, connection_id: str) -> dict[str, Any] | None:
        state = self._health_state.get(connection_id)
        return state.to_dict() if state else None

    def get_all_health(self) -> dict[str, dict[str, Any]]:
        return {cid: s.to_dict() for cid, s in self._health_state.items()}

    def clear(self, connection_id: str) -> None:
        self._health_state.pop(connection_id, None)


health_monitor = ConnectionHealthMonitor()
