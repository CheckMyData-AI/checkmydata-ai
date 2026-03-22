"""Integration tests for /api/tasks/active."""

import pytest


@pytest.mark.asyncio
async def test_get_active_tasks(auth_client):
    resp = await auth_client.get("/api/tasks/active")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_active_tasks_no_auth(client):
    resp = await client.get("/api/tasks/active")
    assert resp.status_code == 401
