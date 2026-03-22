"""Unit tests for ConnectionHealthMonitor and HealthState."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.core.health_monitor import (
    CHECK_TIMEOUT_SECONDS,
    DEGRADED_LATENCY_MS,
    MAX_CONSECUTIVE_FAILURES,
    ConnectionHealthMonitor,
    HealthState,
)


class _FastConnector:
    async def test_connection(self) -> bool:
        return True


class _FailingConnector:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def test_connection(self) -> None:
        raise self._exc


@pytest.mark.asyncio
async def test_healthy_connection() -> None:
    monitor = ConnectionHealthMonitor()
    result = await monitor.check_connection("c1", _FastConnector())
    assert result["status"] == "healthy"
    assert result["consecutive_failures"] == 0
    assert result["last_error"] is None


@pytest.mark.asyncio
async def test_degraded_latency() -> None:
    """Latency above DEGRADED_LATENCY_MS yields degraded while connection succeeds."""
    monitor = ConnectionHealthMonitor()

    # asyncio.wait_for may call time.monotonic internally; bypass it so only t0/t1 remain.
    async def immediate_wait_for(coro, timeout=None):  # noqa: ANN001
        return await coro

    t1 = (DEGRADED_LATENCY_MS + 500) / 1000.0
    mono_seq = [0.0, t1]

    def fake_monotonic() -> float:
        return mono_seq.pop(0) if mono_seq else t1

    with (
        patch("app.core.health_monitor.asyncio.wait_for", immediate_wait_for),
        patch("app.core.health_monitor.time.monotonic", side_effect=fake_monotonic),
    ):
        result = await monitor.check_connection("c-slow", _FastConnector())

    assert result["status"] == "degraded"
    assert result["latency_ms"] > DEGRADED_LATENCY_MS


@pytest.mark.asyncio
async def test_single_failure_degrades() -> None:
    monitor = ConnectionHealthMonitor()
    result = await monitor.check_connection(
        "c-fail",
        _FailingConnector(RuntimeError("boom")),
    )
    assert result["status"] == "degraded"
    assert result["consecutive_failures"] == 1
    assert result["last_error"] == "boom"


@pytest.mark.asyncio
async def test_consecutive_failures_mark_down() -> None:
    monitor = ConnectionHealthMonitor()
    conn = _FailingConnector(ConnectionError("down"))
    await monitor.check_connection("c-down", conn)
    result = await monitor.check_connection("c-down", conn)
    assert result["status"] == "down"
    assert result["consecutive_failures"] >= MAX_CONSECUTIVE_FAILURES


@pytest.mark.asyncio
async def test_recovery_after_failure() -> None:
    monitor = ConnectionHealthMonitor()
    await monitor.check_connection("c-rec", _FailingConnector(RuntimeError("once")))
    degraded = monitor.get_health("c-rec")
    assert degraded is not None
    assert degraded["consecutive_failures"] == 1

    result = await monitor.check_connection("c-rec", _FastConnector())
    assert result["status"] == "healthy"
    assert result["consecutive_failures"] == 0


def test_get_health_unknown_connection() -> None:
    monitor = ConnectionHealthMonitor()
    assert monitor.get_health("no-such-id") is None


def test_get_all_health_empty() -> None:
    monitor = ConnectionHealthMonitor()
    assert monitor.get_all_health() == {}


@pytest.mark.asyncio
async def test_clear_removes_state() -> None:
    monitor = ConnectionHealthMonitor()
    await monitor.check_connection("c-clear", _FastConnector())
    assert monitor.get_health("c-clear") is not None
    monitor.clear("c-clear")
    assert monitor.get_health("c-clear") is None


def test_to_dict_format() -> None:
    fixed = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
    state = HealthState(
        status="healthy",
        latency_ms=10,
        last_check=fixed,
        consecutive_failures=0,
        last_error=None,
    )
    d = state.to_dict()
    assert set(d.keys()) == {
        "status",
        "latency_ms",
        "last_check",
        "consecutive_failures",
        "last_error",
    }
    assert d["status"] == "healthy"
    assert d["last_check"] == fixed.isoformat()


@pytest.mark.asyncio
async def test_false_return_from_test_connection_is_failure() -> None:
    class _FalseConnector:
        async def test_connection(self) -> bool:
            return False

    monitor = ConnectionHealthMonitor()
    result = await monitor.check_connection("c-false", _FalseConnector())
    assert result["status"] == "degraded"
    assert "returned False" in (result["last_error"] or "")


def test_constants_match_implementation() -> None:
    assert DEGRADED_LATENCY_MS == 3000
    assert MAX_CONSECUTIVE_FAILURES == 2
    assert CHECK_TIMEOUT_SECONDS == 10
