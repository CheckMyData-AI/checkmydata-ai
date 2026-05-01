"""Integration tests for /api/backup routes (admin-only)."""

import pytest

from app.api.routes import backup as backup_routes
from app.config import settings


@pytest.fixture()
def _admin_client(auth_client, monkeypatch):
    """Promote the ``auth_client`` fixture user to admin for the test scope."""
    email = auth_client.headers.get("X-Test-User-Email")
    # Fall back: decode from the fact that auth_client already set the Bearer
    # token. We don't need to parse: just allow the current logged-in user's
    # email address to be in admin_emails for all backup tests by pulling it
    # from the token via /api/auth/me.
    if not email:
        # Use a sync-like trick: hit /api/auth/me through the same client.
        async def _get_email():
            r = await auth_client.get("/api/auth/me")
            return r.json()["email"]

        import asyncio

        email = asyncio.get_event_loop().run_until_complete(_get_email())  # noqa: F841
    monkeypatch.setattr(settings, "admin_emails", [email])
    yield auth_client


@pytest.mark.asyncio
async def test_backup_history_forbidden_for_non_admin(auth_client):
    resp = await auth_client.get("/api/backup/history")
    assert resp.status_code == 403
    assert "Admin" in resp.json()["detail"] or "admin" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_backup_list_forbidden_for_non_admin(auth_client):
    resp = await auth_client.get("/api/backup/list")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_backup_trigger_forbidden_for_non_admin(auth_client):
    resp = await auth_client.post("/api/backup/trigger")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_backup_history_empty_for_admin(auth_client, monkeypatch):
    me = (await auth_client.get("/api/auth/me")).json()
    monkeypatch.setattr(settings, "admin_emails", [me["email"]])
    resp = await auth_client.get("/api/backup/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "records" in data
    assert data["records"] == []


@pytest.mark.asyncio
async def test_backup_list_ok_for_admin(auth_client, monkeypatch):
    me = (await auth_client.get("/api/auth/me")).json()
    monkeypatch.setattr(settings, "admin_emails", [me["email"]])
    resp = await auth_client.get("/api/backup/list")
    assert resp.status_code == 200
    data = resp.json()
    assert "backups" in data
    assert isinstance(data["backups"], list)


@pytest.mark.asyncio
async def test_backup_trigger_disabled_for_admin(auth_client, monkeypatch):
    me = (await auth_client.get("/api/auth/me")).json()
    monkeypatch.setattr(settings, "admin_emails", [me["email"]])
    monkeypatch.setattr(backup_routes.settings, "backup_enabled", False)
    resp = await auth_client.post("/api/backup/trigger")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Backups are disabled"


@pytest.mark.asyncio
async def test_backup_no_auth(client):
    assert (await client.get("/api/backup/history")).status_code == 401
    assert (await client.get("/api/backup/list")).status_code == 401
    assert (await client.post("/api/backup/trigger")).status_code == 401
