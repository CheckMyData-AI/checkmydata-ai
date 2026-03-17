"""Integration tests for /api/connections endpoints."""

import pytest

from tests.integration.conftest import auth_headers, register_user


@pytest.mark.asyncio
class TestConnectionCrud:
    async def _create_project(self, auth_client) -> str:
        resp = await auth_client.post("/api/projects", json={"name": "Conn Test Proj"})
        return resp.json()["id"]

    async def test_create_and_list(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "My MySQL",
                "db_type": "mysql",
                "db_host": "127.0.0.1",
                "db_port": 3306,
                "db_name": "testdb",
            },
        )
        assert resp.status_code == 200
        conn = resp.json()
        assert conn["name"] == "My MySQL"
        assert conn["db_type"] == "mysql"
        assert conn["is_read_only"] is True

        resp = await auth_client.get(f"/api/connections/project/{pid}")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_update_connection(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "Before",
                "db_type": "postgres",
                "db_host": "127.0.0.1",
                "db_name": "testdb",
            },
        )
        cid = resp.json()["id"]

        resp = await auth_client.patch(f"/api/connections/{cid}", json={"name": "After"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "After"

    async def test_delete_connection(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "Temp",
                "db_type": "postgres",
                "db_host": "127.0.0.1",
                "db_name": "testdb",
            },
        )
        cid = resp.json()["id"]

        resp = await auth_client.delete(f"/api/connections/{cid}")
        assert resp.status_code == 200

        resp = await auth_client.get(f"/api/connections/{cid}")
        assert resp.status_code == 404

    async def test_get_not_found(self, auth_client):
        resp = await auth_client.get("/api/connections/nonexistent")
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestConnectionAccessControl:
    async def test_viewer_can_list_but_not_create(self, client):
        owner = await register_user(client)
        viewer = await register_user(client)
        resp = await client.post(
            "/api/projects",
            json={"name": "Conn RBAC"},
            headers=auth_headers(owner["token"]),
        )
        pid = resp.json()["id"]

        resp = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": viewer["email"], "role": "viewer"},
            headers=auth_headers(owner["token"]),
        )
        await client.post(
            f"/api/invites/accept/{resp.json()['id']}",
            headers=auth_headers(viewer["token"]),
        )

        resp = await client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "Blocked",
                "db_type": "mysql",
                "db_host": "127.0.0.1",
                "db_name": "testdb",
            },
            headers=auth_headers(owner["token"]),
        )
        assert resp.status_code == 200

        resp = await client.get(
            f"/api/connections/project/{pid}",
            headers=auth_headers(viewer["token"]),
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

        resp = await client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "Attempt",
                "db_type": "postgres",
                "db_host": "127.0.0.1",
                "db_name": "testdb",
            },
            headers=auth_headers(viewer["token"]),
        )
        assert resp.status_code == 403
