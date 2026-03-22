"""Integration tests for /api/demo/setup."""

import pytest


@pytest.mark.asyncio
async def test_demo_setup(auth_client):
    resp = await auth_client.post("/api/demo/setup")
    assert resp.status_code == 200
    data = resp.json()
    assert "project_id" in data
    assert "connection_id" in data
    assert isinstance(data["project_id"], str)
    assert isinstance(data["connection_id"], str)
    assert len(data["project_id"]) > 0
    assert len(data["connection_id"]) > 0


@pytest.mark.asyncio
async def test_demo_setup_no_auth(client):
    resp = await client.post("/api/demo/setup")
    assert resp.status_code == 401
