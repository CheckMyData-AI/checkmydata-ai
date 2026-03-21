"""Extended auth integration tests for coverage of auth_service internals."""

import uuid

import pytest

from tests.integration.conftest import auth_headers, register_user


def _email():
    return f"ext-{uuid.uuid4().hex[:8]}@test.com"


@pytest.mark.asyncio
class TestProjectOperationsExtended:
    async def test_create_list_update_delete_project(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])

        create_resp = await client.post(
            "/api/projects", json={"name": "Test Proj"}, headers=headers
        )
        assert create_resp.status_code == 200
        pid = create_resp.json()["id"]

        list_resp = await client.get("/api/projects", headers=headers)
        assert list_resp.status_code == 200
        assert any(p["id"] == pid for p in list_resp.json())

        update_resp = await client.patch(
            f"/api/projects/{pid}", json={"name": "Updated"}, headers=headers
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["name"] == "Updated"

        delete_resp = await client.delete(f"/api/projects/{pid}", headers=headers)
        assert delete_resp.status_code == 200


@pytest.mark.asyncio
class TestConnectionExtended:
    async def test_full_connection_lifecycle(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        proj = await client.post("/api/projects", json={"name": "Conn Test"}, headers=headers)
        pid = proj.json()["id"]

        create = await client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "test-pg",
                "db_type": "postgres",
                "db_host": "localhost",
                "db_port": 5432,
                "db_name": "testdb",
                "db_user": "user",
                "db_password": "pass",
            },
            headers=headers,
        )
        assert create.status_code == 200
        cid = create.json()["id"]

        list_resp = await client.get(f"/api/connections/project/{pid}", headers=headers)
        assert list_resp.status_code == 200
        assert any(c["id"] == cid for c in list_resp.json())

        update = await client.patch(
            f"/api/connections/{cid}",
            json={"name": "updated-pg"},
            headers=headers,
        )
        assert update.status_code == 200
        assert update.json()["name"] == "updated-pg"

        delete = await client.delete(f"/api/connections/{cid}", headers=headers)
        assert delete.status_code == 200

    async def test_create_mysql_connection(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        proj = await client.post("/api/projects", json={"name": "MySQL"}, headers=headers)
        pid = proj.json()["id"]
        resp = await client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "mysql-conn",
                "db_type": "mysql",
                "db_host": "localhost",
                "db_port": 3306,
                "db_name": "mydb",
                "db_user": "root",
                "db_password": "secret",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["db_type"] == "mysql"

    async def test_create_mongodb_connection(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        proj = await client.post("/api/projects", json={"name": "Mongo"}, headers=headers)
        pid = proj.json()["id"]
        resp = await client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "mongo-conn",
                "db_type": "mongodb",
                "db_host": "localhost",
                "db_port": 27017,
                "db_name": "testdb",
                "db_user": "admin",
                "db_password": "pass",
            },
            headers=headers,
        )
        assert resp.status_code == 200

    async def test_create_clickhouse_connection(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        proj = await client.post("/api/projects", json={"name": "CH"}, headers=headers)
        pid = proj.json()["id"]
        resp = await client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "ch-conn",
                "db_type": "clickhouse",
                "db_host": "localhost",
                "db_port": 8123,
                "db_name": "default",
                "db_user": "default",
                "db_password": "",
            },
            headers=headers,
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestHealthEndpoints:
    async def test_health_check(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data

    async def test_health_modules(self, client):
        resp = await client.get("/api/health/modules")
        assert resp.status_code == 200
