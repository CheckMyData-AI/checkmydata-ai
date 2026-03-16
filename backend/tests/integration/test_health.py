"""Integration tests for health endpoints."""

import pytest


@pytest.mark.asyncio
class TestHealth:
    async def test_health_ok(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    async def test_module_health_returns_structure(self, client):
        resp = await client.get("/api/health/modules")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "modules" in data
        assert "database" in data["modules"]
