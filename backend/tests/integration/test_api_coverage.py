"""Additional API endpoint tests to boost route coverage.

Exercises routes and flows that exist but didn't have dedicated tests,
improving coverage for chat.py, main.py, and data_validation routes.
"""

import uuid

import pytest

from tests.integration.conftest import auth_headers, register_user


def _email():
    return f"cov-{uuid.uuid4().hex[:8]}@test.com"


async def _setup(client):
    reg = await register_user(client)
    headers = auth_headers(reg["token"])
    proj = await client.post(
        "/api/projects", json={"name": f"cov-{uuid.uuid4().hex[:6]}"}, headers=headers
    )
    pid = proj.json()["id"]
    conn = await client.post(
        "/api/connections",
        json={
            "project_id": pid,
            "name": "cov-conn",
            "db_type": "postgres",
            "db_host": "localhost",
            "db_port": 5432,
            "db_name": "test",
            "db_user": "user",
            "db_password": "pass",
        },
        headers=headers,
    )
    cid = conn.json()["id"]
    return {
        "token": reg["token"],
        "headers": headers,
        "pid": pid,
        "cid": cid,
        "uid": reg["user_id"],
    }


@pytest.mark.asyncio
class TestChatSessionCoverage:
    async def test_list_sessions_empty(self, client):
        ctx = await _setup(client)
        resp = await client.get(
            f"/api/chat/sessions/{ctx['pid']}",
            headers=ctx["headers"],
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_and_delete_session(self, client):
        ctx = await _setup(client)
        create = await client.post(
            "/api/chat/sessions",
            json={"project_id": ctx["pid"]},
            headers=ctx["headers"],
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        msgs = await client.get(
            f"/api/chat/sessions/{sid}/messages",
            headers=ctx["headers"],
        )
        assert msgs.status_code == 200

        delete = await client.delete(
            f"/api/chat/sessions/{sid}",
            headers=ctx["headers"],
        )
        assert delete.status_code == 200


@pytest.mark.asyncio
class TestDataValidationCoverage:
    async def test_submit_validation(self, client):
        ctx = await _setup(client)
        resp = await client.post(
            "/api/data-validation/validate-data",
            json={
                "connection_id": ctx["cid"],
                "project_id": ctx["pid"],
                "session_id": str(uuid.uuid4()),
                "message_id": str(uuid.uuid4()),
                "query": "SELECT COUNT(*) FROM users",
                "verdict": "confirmed",
                "metric_description": "total users",
                "agent_value": "1000",
            },
            headers=ctx["headers"],
        )
        assert resp.status_code == 200

    async def test_validation_stats(self, client):
        ctx = await _setup(client)
        resp = await client.get(
            f"/api/data-validation/validation-stats/{ctx['cid']}",
            params={"project_id": ctx["pid"]},
            headers=ctx["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data

    async def test_benchmarks(self, client):
        ctx = await _setup(client)
        resp = await client.get(
            f"/api/data-validation/benchmarks/{ctx['cid']}",
            params={"project_id": ctx["pid"]},
            headers=ctx["headers"],
        )
        assert resp.status_code == 200

    async def test_analytics_summary(self, client):
        ctx = await _setup(client)
        resp = await client.get(
            f"/api/data-validation/summary/{ctx['pid']}",
            headers=ctx["headers"],
        )
        assert resp.status_code == 200

    async def test_analytics(self, client):
        ctx = await _setup(client)
        resp = await client.get(
            f"/api/data-validation/analytics/{ctx['pid']}",
            headers=ctx["headers"],
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestBatchRoutes:
    async def test_list_batches(self, client):
        ctx = await _setup(client)
        list_resp = await client.get(
            "/api/batch",
            params={"project_id": ctx["pid"]},
            headers=ctx["headers"],
        )
        assert list_resp.status_code == 200


@pytest.mark.asyncio
class TestUsageRoutes:
    async def test_get_usage_stats(self, client):
        ctx = await _setup(client)
        resp = await client.get(
            "/api/usage/stats",
            headers=ctx["headers"],
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestMiscRoutes:
    async def test_task_active_empty(self, client):
        ctx = await _setup(client)
        resp = await client.get("/api/tasks/active", headers=ctx["headers"])
        assert resp.status_code == 200

    async def test_llm_models(self, client):
        ctx = await _setup(client)
        resp = await client.get("/api/models", headers=ctx["headers"])
        assert resp.status_code == 200

    async def test_legal_pages(self, client):
        for page in ["privacy", "terms", "cookies"]:
            resp = await client.get(f"/api/legal/{page}")
            assert resp.status_code in (200, 404)
