"""Integration tests for /api/backup routes."""

import pytest

from app.api.routes import backup as backup_routes


@pytest.mark.asyncio
async def test_backup_history_empty(auth_client):
    resp = await auth_client.get("/api/backup/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "records" in data
    assert data["records"] == []


@pytest.mark.asyncio
async def test_backup_list(auth_client):
    resp = await auth_client.get("/api/backup/list")
    assert resp.status_code == 200
    data = resp.json()
    assert "backups" in data
    assert isinstance(data["backups"], list)


@pytest.mark.asyncio
async def test_backup_trigger_disabled(auth_client, monkeypatch):
    monkeypatch.setattr(backup_routes.settings, "backup_enabled", False)
    resp = await auth_client.post("/api/backup/trigger")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Backups are disabled"


@pytest.mark.asyncio
async def test_backup_no_auth(client):
    assert (await client.get("/api/backup/history")).status_code == 401
    assert (await client.get("/api/backup/list")).status_code == 401
    assert (await client.post("/api/backup/trigger")).status_code == 401
