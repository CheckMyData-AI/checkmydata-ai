"""The health probe must heal a dead tunnel, not just report it dead.

Production, 2026-08-07: connection `db-esim` (mysql, over an SSH tunnel to
64.188.10.62) reported `Can't connect to MySQL server on '127.0.0.1'` every five
minutes from 03:07 until the 04:44 dyno restart. `127.0.0.1` is the tunnel's local
endpoint and the configuration is correct — the tunnel was down.

Every piece needed to recover already existed and none of them ran:

* `SSHTunnelManager.get_or_create` checks `is_alive()` and reconnects with retries;
* `MySQLConnector._reconnect` closes the stale pool and reconnects, its own docstring
  saying it "picks up a new tunnel port".

But the health path never asks. `_health_check_loop` → `all_connectors()` →
`health_monitor.check_connection` → `connector.test_connection()`, and
`test_connection` uses `self._pool`, built at first connect against the *old* tunnel
port. So the probe observed the failure it was designed to observe and did nothing
about it, while the repair sat one call away.

Only a user query would have healed it, because that path goes through
`get_or_create` — and there was no traffic. A monitor that can only report is a
monitor that watches a recoverable outage persist.
"""

from __future__ import annotations

import pytest

from app.core.health_monitor import ConnectionHealthMonitor


class _TunnelledConnector:
    """Fails until reconnected — the shape of a connector holding a stale pool."""

    def __init__(self) -> None:
        self.reconnects = 0
        self._healthy = False

    async def test_connection(self) -> bool:
        return self._healthy

    async def reconnect(self) -> bool:
        self.reconnects += 1
        self._healthy = True  # a fresh pool on the new tunnel port
        return True


class _PlainConnector:
    """No tunnel, no recovery to attempt."""

    def __init__(self) -> None:
        self.calls = 0

    async def test_connection(self) -> bool:
        self.calls += 1
        return False


@pytest.mark.asyncio
async def test_a_failed_probe_tries_to_reconnect_and_reports_healthy():
    c = _TunnelledConnector()
    out = await ConnectionHealthMonitor().check_connection("conn-1", c)

    assert c.reconnects == 1, "the probe must attempt the repair that sits one call away"
    assert out["status"] in ("healthy", "degraded"), (
        f"a connection healed by reconnecting must not be reported down: {out}"
    )


@pytest.mark.asyncio
async def test_a_connector_without_reconnect_is_reported_down_as_before():
    c = _PlainConnector()
    out = await ConnectionHealthMonitor().check_connection("conn-2", c)

    # A single failure is `degraded`; `down` needs MAX_CONSECUTIVE_FAILURES. The point
    # here is that nothing was healed and nothing extra was probed.
    assert out["status"] != "healthy"
    assert out["consecutive_failures"] == 1
    assert c.calls == 1, "no reconnect support means no second probe, and no extra load"


@pytest.mark.asyncio
async def test_a_reconnect_that_fails_does_not_mask_the_outage():
    """Healing is best-effort; it must never turn a real outage into a green light."""

    class _Stubborn(_TunnelledConnector):
        async def reconnect(self) -> bool:
            self.reconnects += 1
            return False  # tunnel host really is unreachable

    c = _Stubborn()
    out = await ConnectionHealthMonitor().check_connection("conn-3", c)

    assert c.reconnects == 1
    assert out["status"] != "healthy"
    assert out["consecutive_failures"] == 1, "a failed repair must still count as a failure"


@pytest.mark.asyncio
async def test_a_raising_reconnect_is_survivable():
    class _Explodes(_TunnelledConnector):
        async def reconnect(self) -> bool:
            self.reconnects += 1
            raise RuntimeError("ssh handshake failed")

    c = _Explodes()
    out = await ConnectionHealthMonitor().check_connection("conn-4", c)

    assert out["status"] != "healthy", "a failed repair is still just a failed probe"
    assert out["consecutive_failures"] == 1
