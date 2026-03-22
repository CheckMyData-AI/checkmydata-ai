"""Edge-case integration tests for demo, dashboard, and notification flows."""

import uuid

import pytest
from httpx import AsyncClient

from tests.integration.conftest import auth_headers, register_user


@pytest.mark.asyncio
class TestDemoIdempotency:
    async def test_demo_setup_twice_creates_two_projects(self, client: AsyncClient):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])

        r1 = await client.post("/api/demo/setup", headers=headers)
        assert r1.status_code == 200
        p1 = r1.json()["project_id"]

        r2 = await client.post("/api/demo/setup", headers=headers)
        assert r2.status_code == 200
        p2 = r2.json()["project_id"]

        assert p1 != p2

    async def test_demo_requires_auth(self, client: AsyncClient):
        resp = await client.post("/api/demo/setup")
        assert resp.status_code in (401, 403)


@pytest.mark.asyncio
class TestDashboardEdgeCases:
    async def _setup(self, client: AsyncClient):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        proj = await client.post(
            "/api/projects",
            json={"name": f"dash-proj-{uuid.uuid4().hex[:6]}"},
            headers=headers,
        )
        pid = proj.json()["id"]
        return headers, pid, reg

    async def test_update_nonexistent_dashboard_404(self, client: AsyncClient):
        headers, pid, _ = await self._setup(client)
        resp = await client.patch(
            f"/api/dashboards/{uuid.uuid4()}",
            json={"title": "Updated"},
            headers=headers,
        )
        assert resp.status_code == 404

    async def test_delete_nonexistent_dashboard_404(self, client: AsyncClient):
        headers, pid, _ = await self._setup(client)
        resp = await client.delete(f"/api/dashboards/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404

    async def test_private_dashboard_not_in_list_for_others(self, client: AsyncClient):
        h_owner, pid, owner = await self._setup(client)
        viewer = await register_user(client)
        h_viewer = auth_headers(viewer["token"])

        await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": viewer["email"], "role": "viewer"},
            headers=h_owner,
        )
        invites = await client.get("/api/invites/pending", headers=h_viewer)
        if invites.status_code == 200 and invites.json():
            inv_id = invites.json()[0]["id"]
            await client.post(f"/api/invites/accept/{inv_id}", headers=h_viewer)

        await client.post(
            "/api/dashboards",
            json={
                "project_id": pid,
                "title": "Private",
                "is_shared": False,
            },
            headers=h_owner,
        )

        resp = await client.get(f"/api/dashboards?project_id={pid}", headers=h_viewer)
        assert resp.status_code == 200
        titles = [d["title"] for d in resp.json()]
        assert "Private" not in titles


@pytest.mark.asyncio
class TestNotificationEdgeCases:
    async def test_read_all_with_no_notifications(self, client: AsyncClient):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])

        resp = await client.post("/api/notifications/read-all", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_count_returns_zero_for_new_user(self, client: AsyncClient):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])

        resp = await client.get("/api/notifications/count", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    async def test_mark_nonexistent_notification_404(self, client: AsyncClient):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])

        resp = await client.patch(f"/api/notifications/{uuid.uuid4()}/read", headers=headers)
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestMetricsEdgeCases:
    async def test_metrics_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/metrics")
        assert resp.status_code in (401, 403)

    async def test_metrics_has_uptime(self, auth_client: AsyncClient):
        resp = await auth_client.get("/api/metrics")
        assert resp.status_code == 200
        assert resp.json()["uptime_seconds"] > 0


@pytest.mark.asyncio
class TestBackupEdgeCases:
    async def test_backup_requires_auth(self, client: AsyncClient):
        resp = await client.post("/api/backup/trigger")
        assert resp.status_code in (401, 403)

    async def test_backup_history_empty_for_new_db(self, auth_client: AsyncClient):
        resp = await auth_client.get("/api/backup/history")
        assert resp.status_code == 200
        assert isinstance(resp.json()["records"], list)
