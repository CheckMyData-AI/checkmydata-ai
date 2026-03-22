"""Integration tests for /api/notifications."""

import pytest


@pytest.mark.asyncio
async def test_list_notifications_empty(auth_client):
    resp = await auth_client.get("/api/notifications?unread_only=true&limit=50")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_unread_count_zero(auth_client):
    resp = await auth_client.get("/api/notifications/count")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


@pytest.mark.asyncio
async def test_mark_all_read(auth_client):
    resp = await auth_client.post("/api/notifications/read-all")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_list_notifications_no_auth(client):
    resp = await client.get("/api/notifications")
    assert resp.status_code == 401
