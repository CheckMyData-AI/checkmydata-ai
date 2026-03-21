"""Performance smoke tests.

Verify that critical API endpoints respond within acceptable latency
budgets under no-load conditions. These are NOT load tests — they
catch regressions where an endpoint becomes accidentally O(n²) or
acquires a blocking call on the hot path.
"""

import time
import uuid

import pytest
from httpx import AsyncClient

from tests.integration.conftest import auth_headers, register_user

MAX_HEALTH_MS = 200
MAX_AUTH_MS = 500
MAX_CRUD_MS = 300
MAX_LIST_MS = 300


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


@pytest.mark.asyncio
class TestHealthPerformance:
    async def test_health_endpoint_fast(self, client: AsyncClient):
        t0 = time.perf_counter()
        resp = await client.get("/api/health")
        ms = _elapsed_ms(t0)
        assert resp.status_code == 200
        assert ms < MAX_HEALTH_MS, f"/api/health took {ms:.0f}ms (limit {MAX_HEALTH_MS}ms)"

    async def test_modules_health_responds(self, client: AsyncClient):
        """Modules health may probe connectors; just verify it completes under 5s."""
        t0 = time.perf_counter()
        resp = await client.get("/api/health/modules")
        ms = _elapsed_ms(t0)
        assert resp.status_code == 200
        assert ms < 5000, f"/api/health/modules took {ms:.0f}ms (limit 5000ms)"


@pytest.mark.asyncio
class TestAuthPerformance:
    async def test_register_latency(self, client: AsyncClient):
        t0 = time.perf_counter()
        resp = await client.post(
            "/api/auth/register",
            json={
                "email": f"perf-{uuid.uuid4().hex[:8]}@test.com",
                "password": "testpass123",
            },
        )
        ms = _elapsed_ms(t0)
        assert resp.status_code == 200
        assert ms < MAX_AUTH_MS, f"Register took {ms:.0f}ms (limit {MAX_AUTH_MS}ms)"

    async def test_login_latency(self, client: AsyncClient):
        email = f"perf-login-{uuid.uuid4().hex[:8]}@test.com"
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": "testpass123"},
        )
        t0 = time.perf_counter()
        resp = await client.post(
            "/api/auth/login",
            json={"email": email, "password": "testpass123"},
        )
        ms = _elapsed_ms(t0)
        assert resp.status_code == 200
        assert ms < MAX_AUTH_MS, f"Login took {ms:.0f}ms (limit {MAX_AUTH_MS}ms)"


@pytest.mark.asyncio
class TestCRUDPerformance:
    async def test_create_project_latency(self, client: AsyncClient):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        t0 = time.perf_counter()
        resp = await client.post(
            "/api/projects",
            json={"name": "perf-project", "description": "smoke"},
            headers=headers,
        )
        ms = _elapsed_ms(t0)
        assert resp.status_code == 200
        assert ms < MAX_CRUD_MS, f"Create project took {ms:.0f}ms (limit {MAX_CRUD_MS}ms)"

    async def test_list_projects_latency(self, client: AsyncClient):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        for i in range(5):
            await client.post(
                "/api/projects",
                json={"name": f"perf-proj-{i}"},
                headers=headers,
            )
        t0 = time.perf_counter()
        resp = await client.get("/api/projects", headers=headers)
        ms = _elapsed_ms(t0)
        assert resp.status_code == 200
        assert ms < MAX_LIST_MS, f"List projects took {ms:.0f}ms (limit {MAX_LIST_MS}ms)"

    async def test_create_connection_latency(self, client: AsyncClient):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        proj = await client.post(
            "/api/projects",
            json={"name": "perf-conn-proj"},
            headers=headers,
        )
        pid = proj.json()["id"]
        t0 = time.perf_counter()
        resp = await client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "perf-conn",
                "db_type": "postgres",
                "db_host": "localhost",
                "db_port": 5432,
                "db_name": "perfdb",
                "db_user": "user",
                "db_password": "pass",
            },
            headers=headers,
        )
        ms = _elapsed_ms(t0)
        assert resp.status_code == 200
        assert ms < MAX_CRUD_MS, f"Create connection took {ms:.0f}ms (limit {MAX_CRUD_MS}ms)"


@pytest.mark.asyncio
class TestListEndpointPerformance:
    async def test_models_list_latency(self, auth_client: AsyncClient):
        t0 = time.perf_counter()
        resp = await auth_client.get("/api/models")
        ms = _elapsed_ms(t0)
        assert resp.status_code in (200, 404)
        assert ms < MAX_LIST_MS, f"Models list took {ms:.0f}ms (limit {MAX_LIST_MS}ms)"

    async def test_legal_pages_latency(self, client: AsyncClient):
        for path in ("/api/legal/terms", "/api/legal/privacy"):
            t0 = time.perf_counter()
            resp = await client.get(path)
            ms = _elapsed_ms(t0)
            assert resp.status_code in (200, 404)
            assert ms < MAX_LIST_MS, f"{path} took {ms:.0f}ms (limit {MAX_LIST_MS}ms)"
