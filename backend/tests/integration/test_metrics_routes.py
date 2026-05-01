"""Integration tests for /api/metrics (admin-only)."""

import pytest

from app.config import settings


@pytest.mark.asyncio
async def test_get_metrics_forbidden_for_non_admin(auth_client):
    resp = await auth_client.get("/api/metrics")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_metrics_admin(auth_client, monkeypatch):
    me = (await auth_client.get("/api/auth/me")).json()
    monkeypatch.setattr(settings, "admin_emails", [me["email"]])
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
async def test_prometheus_forbidden_for_non_admin(auth_client):
    resp = await auth_client.get("/api/metrics/prometheus")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_prometheus_admin_ok(auth_client, monkeypatch):
    me = (await auth_client.get("/api/auth/me")).json()
    monkeypatch.setattr(settings, "admin_emails", [me["email"]])
    resp = await auth_client.get("/api/metrics/prometheus")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")


@pytest.mark.asyncio
async def test_get_metrics_no_auth(client):
    resp = await client.get("/api/metrics")
    assert resp.status_code == 401
