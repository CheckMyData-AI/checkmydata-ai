"""Integration tests for /api/metrics."""

import pytest


@pytest.mark.asyncio
async def test_get_metrics_authenticated(auth_client):
    resp = await auth_client.get("/api/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "active_workflows" in data
    assert "request_stats" in data
    assert "uptime_seconds" in data
    assert isinstance(data["active_workflows"], int)
    assert isinstance(data["request_stats"], dict)
    assert isinstance(data["uptime_seconds"], int | float)


@pytest.mark.asyncio
async def test_get_metrics_no_auth(client):
    resp = await client.get("/api/metrics")
    assert resp.status_code == 401
