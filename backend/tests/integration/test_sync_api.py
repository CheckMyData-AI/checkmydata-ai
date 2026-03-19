"""Integration tests for Code-DB Sync API endpoints."""

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest_asyncio.fixture()
async def project_and_connection(auth_client: AsyncClient):
    """Create a project and connection for sync tests."""
    proj = await auth_client.post(
        "/api/projects",
        json={"name": "SyncTestProject", "description": "For sync tests"},
    )
    assert proj.status_code == 200
    project_id = proj.json()["id"]

    conn = await auth_client.post(
        "/api/connections",
        json={
            "project_id": project_id,
            "name": "TestDB",
            "db_type": "postgres",
            "db_host": "127.0.0.1",
            "db_port": 5432,
            "db_name": "testdb",
            "db_user": "user",
            "db_password": "pass",
        },
    )
    assert conn.status_code == 200
    connection_id = conn.json()["id"]

    return project_id, connection_id


class TestSyncStatusEndpoint:
    @pytest.mark.asyncio
    async def test_initial_status(self, auth_client: AsyncClient, project_and_connection):
        _, connection_id = project_and_connection
        resp = await auth_client.get(f"/api/connections/{connection_id}/sync/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_synced"] is False

    @pytest.mark.asyncio
    async def test_trigger_sync_without_index(
        self, auth_client: AsyncClient, project_and_connection
    ):
        """Sync should fail if DB is not indexed."""
        _, connection_id = project_and_connection
        resp = await auth_client.post(f"/api/connections/{connection_id}/sync")
        assert resp.status_code == 400
        assert "indexed" in resp.json()["detail"].lower()


class TestGetSyncEndpoint:
    @pytest.mark.asyncio
    async def test_empty_sync(self, auth_client: AsyncClient, project_and_connection):
        _, connection_id = project_and_connection
        resp = await auth_client.get(f"/api/connections/{connection_id}/sync")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tables"] == []
        assert data["summary"] is None


class TestDeleteSyncEndpoint:
    @pytest.mark.asyncio
    async def test_delete_empty_sync(self, auth_client: AsyncClient, project_and_connection):
        _, connection_id = project_and_connection
        resp = await auth_client.delete(f"/api/connections/{connection_id}/sync")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestReadinessEndpoint:
    @pytest.mark.asyncio
    async def test_project_readiness(self, auth_client: AsyncClient, project_and_connection):
        project_id, _ = project_and_connection
        resp = await auth_client.get(f"/api/projects/{project_id}/readiness")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ready"] is False
        assert data["db_connected"] is True
        assert data["repo_connected"] is False
        assert isinstance(data["missing_steps"], list)
        assert any(s["step"] == "connect_repo" for s in data["missing_steps"])
        assert "last_indexed_at" in data
        assert "commits_behind" in data
        assert "is_stale" in data
        assert data["last_indexed_at"] is None
        assert data["commits_behind"] == 0
        assert data["is_stale"] is False

    @pytest.mark.asyncio
    async def test_readiness_not_found(self, auth_client: AsyncClient):
        resp = await auth_client.get("/api/projects/nonexistent/readiness")
        assert resp.status_code in (403, 404)
