"""Business logic tests: data validation, benchmarks, scheduling, notifications.

Covers the learning lifecycle, data validation feedback, benchmark creation/confirmation,
schedule CRUD, and notification flow.
"""

import uuid

import pytest

from tests.integration.conftest import auth_headers, register_user


def _email():
    return f"biz-{uuid.uuid4().hex[:8]}@test.com"


async def _setup_project_connection(client):
    """Create a user, project, and connection."""
    reg = await register_user(client)
    headers = auth_headers(reg["token"])
    proj = await client.post(
        "/api/projects", json={"name": f"biz-{uuid.uuid4().hex[:6]}"}, headers=headers
    )
    project_id = proj.json()["id"]
    conn = await client.post(
        "/api/connections",
        json={
            "project_id": project_id,
            "name": "test-conn",
            "db_type": "postgres",
            "db_host": "localhost",
            "db_port": 5432,
            "db_name": "test",
            "db_user": "user",
            "db_password": "pass",
        },
        headers=headers,
    )
    connection_id = conn.json()["id"]
    return {
        "token": reg["token"],
        "headers": headers,
        "project_id": project_id,
        "connection_id": connection_id,
        "user_id": reg["user_id"],
    }


@pytest.mark.asyncio
class TestScheduleCRUD:
    async def test_create_schedule(self, client):
        ctx = await _setup_project_connection(client)
        resp = await client.post(
            "/api/schedules",
            json={
                "project_id": ctx["project_id"],
                "connection_id": ctx["connection_id"],
                "title": "Daily users",
                "sql_query": "SELECT COUNT(*) FROM users",
                "cron_expression": "0 9 * * *",
            },
            headers=ctx["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Daily users"
        assert data["cron_expression"] == "0 9 * * *"
        assert data["is_active"] is True
        assert data["next_run_at"] is not None

    async def test_list_schedules(self, client):
        ctx = await _setup_project_connection(client)
        await client.post(
            "/api/schedules",
            json={
                "project_id": ctx["project_id"],
                "connection_id": ctx["connection_id"],
                "title": "Sched 1",
                "sql_query": "SELECT 1",
                "cron_expression": "0 * * * *",
            },
            headers=ctx["headers"],
        )
        resp = await client.get(
            "/api/schedules",
            params={"project_id": ctx["project_id"]},
            headers=ctx["headers"],
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_update_schedule(self, client):
        ctx = await _setup_project_connection(client)
        create_resp = await client.post(
            "/api/schedules",
            json={
                "project_id": ctx["project_id"],
                "connection_id": ctx["connection_id"],
                "title": "Before",
                "sql_query": "SELECT 1",
                "cron_expression": "0 * * * *",
            },
            headers=ctx["headers"],
        )
        schedule_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/api/schedules/{schedule_id}",
            json={"title": "After", "cron_expression": "0 */6 * * *"},
            headers=ctx["headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "After"

    async def test_delete_schedule(self, client):
        ctx = await _setup_project_connection(client)
        create_resp = await client.post(
            "/api/schedules",
            json={
                "project_id": ctx["project_id"],
                "connection_id": ctx["connection_id"],
                "title": "To delete",
                "sql_query": "SELECT 1",
                "cron_expression": "0 * * * *",
            },
            headers=ctx["headers"],
        )
        schedule_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/schedules/{schedule_id}", headers=ctx["headers"])
        assert resp.status_code == 200

    async def test_invalid_cron_rejected(self, client):
        ctx = await _setup_project_connection(client)
        resp = await client.post(
            "/api/schedules",
            json={
                "project_id": ctx["project_id"],
                "connection_id": ctx["connection_id"],
                "title": "Bad cron",
                "sql_query": "SELECT 1",
                "cron_expression": "not a cron",
            },
            headers=ctx["headers"],
        )
        assert resp.status_code in (400, 422)


@pytest.mark.asyncio
class TestNotifications:
    async def test_list_notifications(self, client):
        reg = await register_user(client)
        resp = await client.get("/api/notifications", headers=auth_headers(reg["token"]))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_mark_notification_read(self, client):
        reg = await register_user(client)
        resp = await client.post("/api/notifications/read-all", headers=auth_headers(reg["token"]))
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestNotesCRUD:
    async def test_save_and_list_notes(self, client):
        ctx = await _setup_project_connection(client)
        resp = await client.post(
            "/api/notes",
            json={
                "project_id": ctx["project_id"],
                "connection_id": ctx["connection_id"],
                "title": "Test Note",
                "sql_query": "SELECT 1",
                "result_json": '{"columns": ["?column?"], "rows": [[1]]}',
            },
            headers=ctx["headers"],
        )
        assert resp.status_code == 200
        note_id = resp.json()["id"]

        list_resp = await client.get(
            "/api/notes",
            params={"project_id": ctx["project_id"]},
            headers=ctx["headers"],
        )
        assert list_resp.status_code == 200
        assert any(n["id"] == note_id for n in list_resp.json())

    async def test_delete_note(self, client):
        ctx = await _setup_project_connection(client)
        create_resp = await client.post(
            "/api/notes",
            json={
                "project_id": ctx["project_id"],
                "connection_id": ctx["connection_id"],
                "title": "To Delete",
                "sql_query": "SELECT 1",
                "result_json": "{}",
            },
            headers=ctx["headers"],
        )
        note_id = create_resp.json()["id"]
        resp = await client.delete(f"/api/notes/{note_id}", headers=ctx["headers"])
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestDashboardCRUD:
    async def test_create_and_list(self, client):
        ctx = await _setup_project_connection(client)
        resp = await client.post(
            "/api/dashboards",
            json={
                "project_id": ctx["project_id"],
                "title": "Test Dashboard",
            },
            headers=ctx["headers"],
        )
        assert resp.status_code == 200
        dashboard_id = resp.json()["id"]

        list_resp = await client.get(
            "/api/dashboards",
            params={"project_id": ctx["project_id"]},
            headers=ctx["headers"],
        )
        assert list_resp.status_code == 200
        assert any(d["id"] == dashboard_id for d in list_resp.json())

    async def test_delete_dashboard(self, client):
        ctx = await _setup_project_connection(client)
        create_resp = await client.post(
            "/api/dashboards",
            json={
                "project_id": ctx["project_id"],
                "title": "To Delete",
            },
            headers=ctx["headers"],
        )
        assert create_resp.status_code == 200
        dash_id = create_resp.json()["id"]
        resp = await client.delete(f"/api/dashboards/{dash_id}", headers=ctx["headers"])
        assert resp.status_code == 200
