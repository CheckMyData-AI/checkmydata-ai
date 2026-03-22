"""Integration tests for /api/schedules and /api/notes CRUD routes."""

import uuid

import pytest

from tests.integration.conftest import auth_headers, register_user


def _email():
    return f"sn-{uuid.uuid4().hex[:8]}@test.com"


async def _setup_project_and_connection(client, token: str) -> tuple[str, str]:
    """Create a project + connection, return (project_id, connection_id)."""
    proj_resp = await client.post(
        "/api/projects",
        json={"name": f"TestProject-{uuid.uuid4().hex[:6]}"},
        headers=auth_headers(token),
    )
    assert proj_resp.status_code == 200
    project_id = proj_resp.json()["id"]

    conn_resp = await client.post(
        "/api/connections",
        json={
            "project_id": project_id,
            "name": "test-conn",
            "db_type": "postgres",
            "db_host": "localhost",
            "db_port": 5432,
            "db_name": "testdb",
            "db_user": "user",
            "db_password": "pass",
        },
        headers=auth_headers(token),
    )
    assert conn_resp.status_code == 200
    connection_id = conn_resp.json()["id"]

    return project_id, connection_id


# ---------------------------------------------------------------------------
# Schedules CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestScheduleCreate:
    async def test_create_schedule(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, connection_id = await _setup_project_and_connection(client, reg["token"])

        resp = await client.post(
            "/api/schedules",
            json={
                "project_id": project_id,
                "connection_id": connection_id,
                "title": "Nightly Check",
                "sql_query": "SELECT count(*) FROM orders",
                "cron_expression": "0 0 * * *",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Nightly Check"
        assert data["sql_query"] == "SELECT count(*) FROM orders"
        assert data["cron_expression"] == "0 0 * * *"
        assert data["is_active"] is True
        assert data["project_id"] == project_id
        assert data["connection_id"] == connection_id

    async def test_create_schedule_invalid_cron(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, connection_id = await _setup_project_and_connection(client, reg["token"])

        resp = await client.post(
            "/api/schedules",
            json={
                "project_id": project_id,
                "connection_id": connection_id,
                "title": "Bad Cron",
                "sql_query": "SELECT 1",
                "cron_expression": "not-a-cron",
            },
            headers=headers,
        )
        assert resp.status_code == 400
        assert "cron" in resp.json()["detail"].lower()


@pytest.mark.asyncio
class TestScheduleList:
    async def test_list_schedules_for_project(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, connection_id = await _setup_project_and_connection(client, reg["token"])

        for i in range(3):
            await client.post(
                "/api/schedules",
                json={
                    "project_id": project_id,
                    "connection_id": connection_id,
                    "title": f"Schedule {i}",
                    "sql_query": "SELECT 1",
                    "cron_expression": "0 0 * * *",
                },
                headers=headers,
            )

        resp = await client.get(
            f"/api/schedules?project_id={project_id}",
            headers=headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 3


@pytest.mark.asyncio
class TestScheduleGetSingle:
    async def test_get_single_schedule(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, connection_id = await _setup_project_and_connection(client, reg["token"])

        created = await client.post(
            "/api/schedules",
            json={
                "project_id": project_id,
                "connection_id": connection_id,
                "title": "Get Me",
                "sql_query": "SELECT 1",
                "cron_expression": "0 0 * * *",
            },
            headers=headers,
        )
        sid = created.json()["id"]

        resp = await client.get(f"/api/schedules/{sid}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == sid
        assert resp.json()["title"] == "Get Me"

    async def test_get_nonexistent_schedule(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])

        resp = await client.get("/api/schedules/nonexistent-id", headers=headers)
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestScheduleUpdate:
    async def test_update_schedule(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, connection_id = await _setup_project_and_connection(client, reg["token"])

        created = await client.post(
            "/api/schedules",
            json={
                "project_id": project_id,
                "connection_id": connection_id,
                "title": "Original",
                "sql_query": "SELECT 1",
                "cron_expression": "0 0 * * *",
            },
            headers=headers,
        )
        sid = created.json()["id"]

        resp = await client.patch(
            f"/api/schedules/{sid}",
            json={"title": "Updated Title", "is_active": False},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Updated Title"
        assert data["is_active"] is False

    async def test_update_schedule_invalid_cron(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, connection_id = await _setup_project_and_connection(client, reg["token"])

        created = await client.post(
            "/api/schedules",
            json={
                "project_id": project_id,
                "connection_id": connection_id,
                "title": "Update Cron",
                "sql_query": "SELECT 1",
                "cron_expression": "0 0 * * *",
            },
            headers=headers,
        )
        sid = created.json()["id"]

        resp = await client.patch(
            f"/api/schedules/{sid}",
            json={"cron_expression": "bad-cron"},
            headers=headers,
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestScheduleDelete:
    async def test_delete_schedule(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, connection_id = await _setup_project_and_connection(client, reg["token"])

        created = await client.post(
            "/api/schedules",
            json={
                "project_id": project_id,
                "connection_id": connection_id,
                "title": "Delete Me",
                "sql_query": "SELECT 1",
                "cron_expression": "0 0 * * *",
            },
            headers=headers,
        )
        sid = created.json()["id"]

        resp = await client.delete(f"/api/schedules/{sid}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        get_resp = await client.get(f"/api/schedules/{sid}", headers=headers)
        assert get_resp.status_code == 404


@pytest.mark.asyncio
class TestScheduleRunNow:
    async def test_run_now_returns_run_record(self, client):
        """run-now fails without a real DB; returns a run with status=failed."""
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, connection_id = await _setup_project_and_connection(client, reg["token"])

        created = await client.post(
            "/api/schedules",
            json={
                "project_id": project_id,
                "connection_id": connection_id,
                "title": "Run Now Test",
                "sql_query": "SELECT 1",
                "cron_expression": "0 0 * * *",
            },
            headers=headers,
        )
        sid = created.json()["id"]

        resp = await client.post(f"/api/schedules/{sid}/run-now", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["schedule_id"] == sid
        assert data["status"] in ("success", "failed")
        assert "id" in data


@pytest.mark.asyncio
class TestScheduleHistory:
    async def test_get_history_empty(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, connection_id = await _setup_project_and_connection(client, reg["token"])

        created = await client.post(
            "/api/schedules",
            json={
                "project_id": project_id,
                "connection_id": connection_id,
                "title": "History Test",
                "sql_query": "SELECT 1",
                "cron_expression": "0 0 * * *",
            },
            headers=headers,
        )
        sid = created.json()["id"]

        resp = await client.get(f"/api/schedules/{sid}/history", headers=headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_history_after_run(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, connection_id = await _setup_project_and_connection(client, reg["token"])

        created = await client.post(
            "/api/schedules",
            json={
                "project_id": project_id,
                "connection_id": connection_id,
                "title": "History After Run",
                "sql_query": "SELECT 1",
                "cron_expression": "0 0 * * *",
            },
            headers=headers,
        )
        sid = created.json()["id"]

        await client.post(f"/api/schedules/{sid}/run-now", headers=headers)

        resp = await client.get(f"/api/schedules/{sid}/history", headers=headers)
        assert resp.status_code == 200
        history = resp.json()
        assert len(history) >= 1
        assert history[0]["schedule_id"] == sid


# ---------------------------------------------------------------------------
# Notes CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNoteCreate:
    async def test_create_note(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, connection_id = await _setup_project_and_connection(client, reg["token"])

        resp = await client.post(
            "/api/notes",
            json={
                "project_id": project_id,
                "connection_id": connection_id,
                "title": "Revenue Query",
                "sql_query": "SELECT sum(amount) FROM payments",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Revenue Query"
        assert data["sql_query"] == "SELECT sum(amount) FROM payments"
        assert data["project_id"] == project_id
        assert data["connection_id"] == connection_id
        assert data["user_id"] == reg["user_id"]

    async def test_create_note_without_connection(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, _ = await _setup_project_and_connection(client, reg["token"])

        resp = await client.post(
            "/api/notes",
            json={
                "project_id": project_id,
                "title": "No Connection Note",
                "sql_query": "SELECT 1",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["connection_id"] is None


@pytest.mark.asyncio
class TestNoteList:
    async def test_list_notes_for_project(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, connection_id = await _setup_project_and_connection(client, reg["token"])

        for i in range(2):
            await client.post(
                "/api/notes",
                json={
                    "project_id": project_id,
                    "connection_id": connection_id,
                    "title": f"Note {i}",
                    "sql_query": "SELECT 1",
                },
                headers=headers,
            )

        resp = await client.get(
            f"/api/notes?project_id={project_id}",
            headers=headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2


@pytest.mark.asyncio
class TestNoteGetSingle:
    async def test_get_single_note(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, connection_id = await _setup_project_and_connection(client, reg["token"])

        created = await client.post(
            "/api/notes",
            json={
                "project_id": project_id,
                "connection_id": connection_id,
                "title": "Fetch Me",
                "sql_query": "SELECT 1",
            },
            headers=headers,
        )
        nid = created.json()["id"]

        resp = await client.get(f"/api/notes/{nid}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == nid
        assert resp.json()["title"] == "Fetch Me"

    async def test_get_nonexistent_note(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])

        resp = await client.get("/api/notes/no-such-id", headers=headers)
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestNoteUpdate:
    async def test_update_note(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, connection_id = await _setup_project_and_connection(client, reg["token"])

        created = await client.post(
            "/api/notes",
            json={
                "project_id": project_id,
                "connection_id": connection_id,
                "title": "Before Update",
                "sql_query": "SELECT 1",
            },
            headers=headers,
        )
        nid = created.json()["id"]

        resp = await client.patch(
            f"/api/notes/{nid}",
            json={"title": "After Update", "comment": "Added context"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "After Update"
        assert data["comment"] == "Added context"


@pytest.mark.asyncio
class TestNoteDelete:
    async def test_delete_note(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, connection_id = await _setup_project_and_connection(client, reg["token"])

        created = await client.post(
            "/api/notes",
            json={
                "project_id": project_id,
                "connection_id": connection_id,
                "title": "Delete Me",
                "sql_query": "SELECT 1",
            },
            headers=headers,
        )
        nid = created.json()["id"]

        resp = await client.delete(f"/api/notes/{nid}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        get_resp = await client.get(f"/api/notes/{nid}", headers=headers)
        assert get_resp.status_code == 404


@pytest.mark.asyncio
class TestNoteExecute:
    async def test_execute_note_without_connection_fails(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, _ = await _setup_project_and_connection(client, reg["token"])

        created = await client.post(
            "/api/notes",
            json={
                "project_id": project_id,
                "title": "No Conn Execute",
                "sql_query": "SELECT 1",
            },
            headers=headers,
        )
        nid = created.json()["id"]

        resp = await client.post(f"/api/notes/{nid}/execute", headers=headers)
        assert resp.status_code == 400
        assert "no connection" in resp.json()["detail"].lower()

    async def test_execute_note_with_connection_returns_result(self, client):
        """Execute fails without a real DB; endpoint handles gracefully."""
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id, connection_id = await _setup_project_and_connection(client, reg["token"])

        created = await client.post(
            "/api/notes",
            json={
                "project_id": project_id,
                "connection_id": connection_id,
                "title": "Execute Me",
                "sql_query": "SELECT 1",
            },
            headers=headers,
        )
        nid = created.json()["id"]

        resp = await client.post(f"/api/notes/{nid}/execute", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == nid
        assert "error" in data or "last_result_json" in data


@pytest.mark.asyncio
class TestScheduleAuth:
    async def test_schedule_endpoints_require_auth(self, client):
        resp_list = await client.get("/api/schedules?project_id=any")
        assert resp_list.status_code == 401

        resp_create = await client.post(
            "/api/schedules",
            json={
                "project_id": "x",
                "connection_id": "x",
                "title": "No Auth",
                "sql_query": "SELECT 1",
                "cron_expression": "0 0 * * *",
            },
        )
        assert resp_create.status_code == 401


@pytest.mark.asyncio
class TestNoteAuth:
    async def test_note_endpoints_require_auth(self, client):
        resp_list = await client.get("/api/notes?project_id=any")
        assert resp_list.status_code == 401

        resp_create = await client.post(
            "/api/notes",
            json={
                "project_id": "x",
                "title": "No Auth",
                "sql_query": "SELECT 1",
            },
        )
        assert resp_create.status_code == 401
