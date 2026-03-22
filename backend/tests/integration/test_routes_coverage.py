"""Integration tests for backup, demo, metrics, health monitor, notifications, and dashboards."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from tests.integration.conftest import auth_headers, register_user


async def _create_project(client, token: str) -> str:
    resp = await client.post(
        "/api/projects",
        json={"name": f"rt-{uuid.uuid4().hex[:6]}"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    return resp.json()["id"]


async def _create_connection(client, token: str, project_id: str) -> str:
    resp = await client.post(
        "/api/connections",
        json={
            "project_id": project_id,
            "name": f"conn-{uuid.uuid4().hex[:6]}",
            "db_type": "postgres",
            "db_host": "localhost",
            "db_port": 5432,
            "db_name": "test",
            "db_user": "user",
            "db_password": "pass",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    return resp.json()["id"]


@pytest.mark.asyncio
class TestBackupRoutes:
    async def test_trigger_disabled_returns_400(self, auth_client):
        with patch("app.config.settings.backup_enabled", False):
            resp = await auth_client.post("/api/backup/trigger")
        assert resp.status_code == 400

    async def test_trigger_list_history(self, auth_client):
        with patch("app.config.settings.backup_enabled", True):
            with patch("app.api.routes.backup._mgr") as mock_mgr:
                mock_mgr.run_backup = AsyncMock(
                    return_value={
                        "timestamp": "20250101_120000",
                        "total_size_bytes": 0,
                        "errors": [],
                        "backup_path": None,
                    }
                )
                mock_mgr.list_backups = AsyncMock(return_value=[{"id": "b1", "path": "/tmp/x"}])

                trig = await auth_client.post("/api/backup/trigger")
                assert trig.status_code == 200
                assert trig.json()["ok"] is True

                lst = await auth_client.get("/api/backup/list")
                assert lst.status_code == 200
                assert "backups" in lst.json()
                assert isinstance(lst.json()["backups"], list)

        hist = await auth_client.get("/api/backup/history")
        assert hist.status_code == 200
        assert "records" in hist.json()
        assert isinstance(hist.json()["records"], list)


@pytest.mark.asyncio
class TestDemoRoutes:
    async def test_setup_returns_ids(self, auth_client):
        resp = await auth_client.post("/api/demo/setup")
        assert resp.status_code == 200
        data = resp.json()
        assert "project_id" in data and "connection_id" in data


@pytest.mark.asyncio
class TestMetricsRoute:
    async def test_metrics_shape(self, auth_client):
        resp = await auth_client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["active_workflows"], int)
        assert isinstance(data["request_stats"], dict)
        assert isinstance(data["uptime_seconds"], float)


@pytest.mark.asyncio
class TestHealthMonitorRoutes:
    async def test_connection_and_project_health(self, client):
        u = await register_user(client)
        pid = await _create_project(client, u["token"])
        cid = await _create_connection(client, u["token"], pid)

        h1 = await client.get(
            f"/api/connections/{cid}/health",
            headers=auth_headers(u["token"]),
        )
        assert h1.status_code == 200
        body = h1.json()
        assert body.get("status") == "unknown"

        h2 = await client.get(
            "/api/connections/health",
            params={"project_id": pid},
            headers=auth_headers(u["token"]),
        )
        assert h2.status_code == 200
        assert cid in h2.json()
        assert h2.json()[cid].get("status") == "unknown"

    async def test_reconnect_no_500(self, client):
        u = await register_user(client)
        pid = await _create_project(client, u["token"])
        cid = await _create_connection(client, u["token"], pid)

        resp = await client.post(
            f"/api/connections/{cid}/reconnect",
            headers=auth_headers(u["token"]),
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestNotificationRoutes:
    async def test_list_count_read_all(self, auth_client):
        lst = await auth_client.get("/api/notifications")
        assert lst.status_code == 200
        assert isinstance(lst.json(), list)

        cnt = await auth_client.get("/api/notifications/count")
        assert cnt.status_code == 200
        assert "count" in cnt.json()
        assert isinstance(cnt.json()["count"], int)

        ra = await auth_client.post("/api/notifications/read-all")
        assert ra.status_code == 200
        assert ra.json().get("ok") is True


@pytest.mark.asyncio
class TestDashboardRoutes:
    async def test_crud_and_rbac(self, client):
        owner = await register_user(client)
        viewer_email = f"vw-{uuid.uuid4().hex[:8]}@test.com"
        viewer = await register_user(client, viewer_email)

        pid = await _create_project(client, owner["token"])
        inv = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": viewer_email, "role": "viewer"},
            headers=auth_headers(owner["token"]),
        )
        assert inv.status_code == 200
        await client.post(
            f"/api/invites/accept/{inv.json()['id']}",
            headers=auth_headers(viewer["token"]),
        )

        create = await client.post(
            "/api/dashboards",
            json={
                "project_id": pid,
                "title": "Owner dash",
                "is_shared": True,
            },
            headers=auth_headers(owner["token"]),
        )
        assert create.status_code == 200
        did = create.json()["id"]

        private = await client.post(
            "/api/dashboards",
            json={
                "project_id": pid,
                "title": "Secret",
                "is_shared": False,
            },
            headers=auth_headers(owner["token"]),
        )
        assert private.status_code == 200
        priv_id = private.json()["id"]

        vlist = await client.get(
            "/api/dashboards",
            params={"project_id": pid},
            headers=auth_headers(viewer["token"]),
        )
        assert vlist.status_code == 200
        vids = {d["id"] for d in vlist.json()}
        assert did in vids
        assert priv_id not in vids

        vget = await client.get(
            f"/api/dashboards/{priv_id}",
            headers=auth_headers(viewer["token"]),
        )
        assert vget.status_code == 403

        bad_patch = await client.patch(
            f"/api/dashboards/{did}",
            json={"title": "Hacked"},
            headers=auth_headers(viewer["token"]),
        )
        assert bad_patch.status_code == 403

        bad_del = await client.delete(
            f"/api/dashboards/{did}",
            headers=auth_headers(viewer["token"]),
        )
        assert bad_del.status_code == 403

        ok_patch = await client.patch(
            f"/api/dashboards/{did}",
            json={"title": "Updated"},
            headers=auth_headers(owner["token"]),
        )
        assert ok_patch.status_code == 200
        assert ok_patch.json()["title"] == "Updated"

        one = await client.get(
            f"/api/dashboards/{did}",
            headers=auth_headers(owner["token"]),
        )
        assert one.status_code == 200

        deleted = await client.delete(
            f"/api/dashboards/{did}",
            headers=auth_headers(owner["token"]),
        )
        assert deleted.status_code == 200

        await client.delete(
            f"/api/dashboards/{priv_id}",
            headers=auth_headers(owner["token"]),
        )
