"""Integration tests for batch execution routes."""

import uuid

import pytest
from httpx import AsyncClient

from tests.integration.conftest import auth_headers, register_user


async def _setup_project_and_connection(
    client: AsyncClient,
):
    reg = await register_user(client)
    headers = auth_headers(reg["token"])
    proj_resp = await client.post(
        "/api/projects",
        json={"name": f"batch-proj-{uuid.uuid4().hex[:6]}"},
        headers=headers,
    )
    pid = proj_resp.json()["id"]
    conn_resp = await client.post(
        "/api/connections",
        json={
            "project_id": pid,
            "name": "batch-conn",
            "db_type": "postgres",
            "db_host": "localhost",
            "db_port": 5432,
            "db_name": "testdb",
            "db_user": "user",
            "db_password": "pass",
        },
        headers=headers,
    )
    cid = conn_resp.json()["id"]
    return headers, pid, cid, reg


@pytest.mark.asyncio
class TestBatchExecute:
    async def test_execute_returns_202(self, client: AsyncClient):
        headers, pid, cid, _ = await _setup_project_and_connection(client)
        resp = await client.post(
            "/api/batch/execute",
            json={
                "project_id": pid,
                "connection_id": cid,
                "title": "Test batch",
                "queries": [{"sql": "SELECT 1", "title": "q1"}],
            },
            headers=headers,
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "batch_id" in data
        assert data["status"] == "pending"

    async def test_execute_no_queries_returns_400(self, client: AsyncClient):
        headers, pid, cid, _ = await _setup_project_and_connection(client)
        resp = await client.post(
            "/api/batch/execute",
            json={
                "project_id": pid,
                "connection_id": cid,
                "title": "Empty",
                "queries": [],
            },
            headers=headers,
        )
        assert resp.status_code == 400

    async def test_execute_wrong_connection(self, client: AsyncClient):
        headers, pid, cid, _ = await _setup_project_and_connection(client)
        h2, pid2, cid2, _ = await _setup_project_and_connection(client)
        resp = await client.post(
            "/api/batch/execute",
            json={
                "project_id": pid,
                "connection_id": cid2,
                "title": "Cross-project",
                "queries": [{"sql": "SELECT 1", "title": "q1"}],
            },
            headers=headers,
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestBatchCRUD:
    async def test_get_batch_404(self, client: AsyncClient):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        resp = await client.get(f"/api/batch/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404

    async def test_list_and_delete(self, client: AsyncClient):
        headers, pid, cid, _ = await _setup_project_and_connection(client)
        cr = await client.post(
            "/api/batch/execute",
            json={
                "project_id": pid,
                "connection_id": cid,
                "title": "To delete",
                "queries": [{"sql": "SELECT 1", "title": "q1"}],
            },
            headers=headers,
        )
        bid = cr.json()["batch_id"]

        lst = await client.get(f"/api/batch?project_id={pid}", headers=headers)
        assert lst.status_code == 200
        assert any(b["id"] == bid for b in lst.json())

        get = await client.get(f"/api/batch/{bid}", headers=headers)
        assert get.status_code == 200
        assert get.json()["id"] == bid

        dl = await client.delete(f"/api/batch/{bid}", headers=headers)
        assert dl.status_code == 200

    async def test_export_no_results_400(self, client: AsyncClient):
        headers, pid, cid, _ = await _setup_project_and_connection(client)
        cr = await client.post(
            "/api/batch/execute",
            json={
                "project_id": pid,
                "connection_id": cid,
                "title": "No results",
                "queries": [{"sql": "SELECT 1", "title": "q1"}],
            },
            headers=headers,
        )
        bid = cr.json()["batch_id"]

        resp = await client.post(f"/api/batch/{bid}/export", headers=headers)
        assert resp.status_code == 400

    async def test_delete_nonexistent_404(self, client: AsyncClient):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        resp = await client.delete(f"/api/batch/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestBatchAuth:
    async def test_execute_requires_auth(self, client: AsyncClient):
        resp = await client.post("/api/batch/execute", json={})
        assert resp.status_code in (401, 403, 422)

    async def test_other_user_cannot_get(self, client: AsyncClient):
        h1, pid, cid, _ = await _setup_project_and_connection(client)
        cr = await client.post(
            "/api/batch/execute",
            json={
                "project_id": pid,
                "connection_id": cid,
                "title": "mine",
                "queries": [{"sql": "SELECT 1", "title": "q1"}],
            },
            headers=h1,
        )
        bid = cr.json()["batch_id"]

        other = await register_user(client)
        h2 = auth_headers(other["token"])
        resp = await client.get(f"/api/batch/{bid}", headers=h2)
        assert resp.status_code == 403
