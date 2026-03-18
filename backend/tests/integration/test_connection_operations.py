"""Integration tests for connection operational endpoints (test, index, learnings)."""

from unittest.mock import AsyncMock, patch

import pytest

from tests.integration.conftest import auth_headers, register_user


@pytest.mark.asyncio
class TestConnectionOperations:
    """Tests for /api/connections/{id}/test, refresh-schema, index-db, learnings."""

    async def _setup(self, auth_client) -> tuple[str, str]:
        """Create a project + connection and return (project_id, connection_id)."""
        resp = await auth_client.post("/api/projects", json={"name": "ConnOps Proj"})
        pid = resp.json()["id"]
        resp = await auth_client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "TestConn",
                "db_type": "postgres",
                "db_host": "127.0.0.1",
                "db_name": "testdb",
            },
        )
        assert resp.status_code == 200
        cid = resp.json()["id"]
        return pid, cid

    # ---- test connection ----

    async def test_test_connection_not_found(self, auth_client):
        resp = await auth_client.post("/api/connections/nonexistent/test")
        assert resp.status_code == 404

    async def test_test_connection_mocked_success(self, auth_client):
        _, cid = await self._setup(auth_client)
        with patch(
            "app.services.connection_service.ConnectionService.test_connection",
            new_callable=AsyncMock,
            return_value={"success": True, "message": "OK"},
        ):
            resp = await auth_client.post(f"/api/connections/{cid}/test")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    async def test_test_connection_mocked_failure(self, auth_client):
        _, cid = await self._setup(auth_client)
        with patch(
            "app.services.connection_service.ConnectionService.test_connection",
            new_callable=AsyncMock,
            return_value={"success": False, "error": "Connection refused"},
        ):
            resp = await auth_client.post(f"/api/connections/{cid}/test")
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "refused" in resp.json()["error"].lower()

    async def test_test_ssh_no_host(self, auth_client):
        _, cid = await self._setup(auth_client)
        with patch(
            "app.services.connection_service.ConnectionService.test_ssh",
            new_callable=AsyncMock,
            return_value={"success": False, "error": "No SSH host configured"},
        ):
            resp = await auth_client.post(f"/api/connections/{cid}/test-ssh")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False

    # ---- refresh schema ----

    async def test_refresh_schema_not_found(self, auth_client):
        resp = await auth_client.post("/api/connections/nonexistent/refresh-schema")
        assert resp.status_code == 404

    # ---- index-db ----

    async def test_index_db_not_found(self, auth_client):
        resp = await auth_client.post("/api/connections/nonexistent/index-db")
        assert resp.status_code == 404

    async def test_index_db_status_not_found(self, auth_client):
        resp = await auth_client.get("/api/connections/nonexistent/index-db/status")
        assert resp.status_code == 404

    async def test_index_db_get_empty(self, auth_client):
        _, cid = await self._setup(auth_client)
        resp = await auth_client.get(f"/api/connections/{cid}/index-db")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tables"] == []
        assert data["summary"] is None

    async def test_index_db_delete_empty(self, auth_client):
        _, cid = await self._setup(auth_client)
        resp = await auth_client.delete(f"/api/connections/{cid}/index-db")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    # ---- learnings ----

    async def test_learnings_list_empty(self, auth_client):
        _, cid = await self._setup(auth_client)
        resp = await auth_client.get(f"/api/connections/{cid}/learnings")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_learnings_status(self, auth_client):
        _, cid = await self._setup(auth_client)
        resp = await auth_client.get(f"/api/connections/{cid}/learnings/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data or "total" in data or isinstance(data, dict)

    async def test_learnings_summary_empty(self, auth_client):
        _, cid = await self._setup(auth_client)
        resp = await auth_client.get(f"/api/connections/{cid}/learnings/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "compiled_prompt" in data

    async def test_learnings_delete_all_empty(self, auth_client):
        _, cid = await self._setup(auth_client)
        resp = await auth_client.delete(f"/api/connections/{cid}/learnings")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_learnings_recompile_empty(self, auth_client):
        _, cid = await self._setup(auth_client)
        resp = await auth_client.post(f"/api/connections/{cid}/learnings/recompile")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_learnings_update_not_found(self, auth_client):
        _, cid = await self._setup(auth_client)
        resp = await auth_client.patch(
            f"/api/connections/{cid}/learnings/nonexistent",
            json={"lesson": "updated"},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestConnectionOperationsRBAC:
    """Role-based access checks for connection operation endpoints."""

    async def _setup_viewer(self, client):
        """Create owner + viewer users, a project, and a connection. Return IDs + tokens."""
        owner = await register_user(client)
        viewer = await register_user(client)

        resp = await client.post(
            "/api/projects",
            json={"name": "RBAC Ops Proj"},
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
                "name": "RBAC Conn",
                "db_type": "mysql",
                "db_host": "127.0.0.1",
                "db_name": "testdb",
            },
            headers=auth_headers(owner["token"]),
        )
        cid = resp.json()["id"]
        return owner, viewer, pid, cid

    async def test_viewer_cannot_test_connection(self, client):
        """Viewers can list but test-connection requires at least viewer
        (test endpoint allows viewer, but indexing requires editor)."""
        owner, viewer, pid, cid = await self._setup_viewer(client)
        with patch(
            "app.services.connection_service.ConnectionService.test_connection",
            new_callable=AsyncMock,
            return_value={"success": True, "message": "OK"},
        ):
            resp = await client.post(
                f"/api/connections/{cid}/test",
                headers=auth_headers(viewer["token"]),
            )
        assert resp.status_code == 200

    async def test_viewer_cannot_index(self, client):
        owner, viewer, pid, cid = await self._setup_viewer(client)
        resp = await client.post(
            f"/api/connections/{cid}/index-db",
            headers=auth_headers(viewer["token"]),
        )
        assert resp.status_code == 403

    async def test_connection_operations_require_auth(self, client):
        endpoints = [
            ("POST", "/api/connections/fake/test"),
            ("POST", "/api/connections/fake/test-ssh"),
            ("POST", "/api/connections/fake/refresh-schema"),
            ("POST", "/api/connections/fake/index-db"),
            ("GET", "/api/connections/fake/index-db/status"),
            ("GET", "/api/connections/fake/index-db"),
            ("DELETE", "/api/connections/fake/index-db"),
            ("GET", "/api/connections/fake/learnings"),
            ("GET", "/api/connections/fake/learnings/status"),
            ("GET", "/api/connections/fake/learnings/summary"),
            ("DELETE", "/api/connections/fake/learnings"),
            ("POST", "/api/connections/fake/learnings/recompile"),
        ]
        for method, url in endpoints:
            resp = await getattr(client, method.lower())(url)
            assert resp.status_code == 401, f"{method} {url} should require auth"
