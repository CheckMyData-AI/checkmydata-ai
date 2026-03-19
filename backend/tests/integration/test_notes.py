"""Integration tests for /api/notes endpoints."""

import pytest

from tests.integration.conftest import auth_headers, register_user


async def _create_project(client, token: str, name: str = "Notes Project") -> str:
    resp = await client.post(
        "/api/projects",
        json={"name": name},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    return resp.json()["id"]


async def _create_connection(client, token: str, project_id: str) -> str:
    resp = await client.post(
        "/api/connections",
        json={
            "project_id": project_id,
            "name": "Test DB",
            "db_type": "postgres",
            "db_host": "127.0.0.1",
            "db_port": 5432,
            "db_name": "testdb",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, f"Connection creation failed: {resp.text}"
    return resp.json()["id"]


async def _create_note(
    client,
    token: str,
    project_id: str,
    connection_id: str | None = None,
    title: str = "Test Query",
    sql_query: str = "SELECT 1",
) -> dict:
    resp = await client.post(
        "/api/notes",
        json={
            "project_id": project_id,
            "connection_id": connection_id,
            "title": title,
            "sql_query": sql_query,
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.asyncio
class TestNotesCrud:
    async def test_create_and_list(self, client):
        user = await register_user(client)
        pid = await _create_project(client, user["token"])

        note = await _create_note(client, user["token"], pid, title="My Saved Query")
        assert note["title"] == "My Saved Query"
        assert note["sql_query"] == "SELECT 1"
        assert note["project_id"] == pid
        assert note["id"] is not None
        assert note["created_at"] is not None
        assert note["updated_at"] is not None

        resp = await client.get(
            f"/api/notes?project_id={pid}",
            headers=auth_headers(user["token"]),
        )
        assert resp.status_code == 200
        notes = resp.json()
        assert len(notes) == 1
        assert notes[0]["title"] == "My Saved Query"

    async def test_get_single(self, client):
        user = await register_user(client)
        pid = await _create_project(client, user["token"])
        note = await _create_note(client, user["token"], pid)

        resp = await client.get(
            f"/api/notes/{note['id']}",
            headers=auth_headers(user["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == note["id"]

    async def test_update_note(self, client):
        user = await register_user(client)
        pid = await _create_project(client, user["token"])
        note = await _create_note(client, user["token"], pid)

        resp = await client.patch(
            f"/api/notes/{note['id']}",
            json={"title": "Renamed", "comment": "Important"},
            headers=auth_headers(user["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Renamed"
        assert data["comment"] == "Important"

    async def test_delete_note(self, client):
        user = await register_user(client)
        pid = await _create_project(client, user["token"])
        note = await _create_note(client, user["token"], pid)

        resp = await client.delete(
            f"/api/notes/{note['id']}",
            headers=auth_headers(user["token"]),
        )
        assert resp.status_code == 200

        resp = await client.get(
            f"/api/notes/{note['id']}",
            headers=auth_headers(user["token"]),
        )
        assert resp.status_code == 404

    async def test_get_not_found(self, client):
        user = await register_user(client)
        resp = await client.get(
            "/api/notes/nonexistent",
            headers=auth_headers(user["token"]),
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestNotesAuth:
    async def test_unauthenticated_request_rejected(self, client):
        resp = await client.get("/api/notes?project_id=any")
        assert resp.status_code in (401, 403)

    async def test_other_user_cannot_access_note(self, client):
        owner = await register_user(client)
        other = await register_user(client)
        pid = await _create_project(client, owner["token"])
        note = await _create_note(client, owner["token"], pid)

        resp = await client.get(
            f"/api/notes/{note['id']}",
            headers=auth_headers(other["token"]),
        )
        assert resp.status_code in (403, 404)

    async def test_other_user_cannot_delete_note(self, client):
        owner = await register_user(client)
        other = await register_user(client)
        pid = await _create_project(client, owner["token"])
        note = await _create_note(client, owner["token"], pid)

        resp = await client.delete(
            f"/api/notes/{note['id']}",
            headers=auth_headers(other["token"]),
        )
        assert resp.status_code in (403, 404)


@pytest.mark.asyncio
class TestNotesConnectionValidation:
    async def test_create_with_valid_connection(self, client):
        user = await register_user(client)
        pid = await _create_project(client, user["token"])
        cid = await _create_connection(client, user["token"], pid)

        note = await _create_note(client, user["token"], pid, connection_id=cid)
        assert note["connection_id"] == cid

    async def test_create_with_nonexistent_connection_fails(self, client):
        user = await register_user(client)
        pid = await _create_project(client, user["token"])

        resp = await client.post(
            "/api/notes",
            json={
                "project_id": pid,
                "connection_id": "nonexistent-conn-id",
                "title": "Bad",
                "sql_query": "SELECT 1",
            },
            headers=auth_headers(user["token"]),
        )
        assert resp.status_code == 404

    async def test_create_with_wrong_project_connection_fails(self, client):
        user = await register_user(client)
        p1 = await _create_project(client, user["token"], "P1")
        p2 = await _create_project(client, user["token"], "P2")
        c1 = await _create_connection(client, user["token"], p1)

        resp = await client.post(
            "/api/notes",
            json={
                "project_id": p2,
                "connection_id": c1,
                "title": "Cross-project",
                "sql_query": "SELECT 1",
            },
            headers=auth_headers(user["token"]),
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestNotesMembership:
    async def test_viewer_can_create_notes(self, client):
        owner = await register_user(client)
        viewer = await register_user(client)
        pid = await _create_project(client, owner["token"])

        resp = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": viewer["email"], "role": "viewer"},
            headers=auth_headers(owner["token"]),
        )
        invite_id = resp.json()["id"]
        await client.post(
            f"/api/invites/accept/{invite_id}",
            headers=auth_headers(viewer["token"]),
        )

        note = await _create_note(client, viewer["token"], pid)
        assert note["project_id"] == pid

    async def test_non_member_cannot_create_notes(self, client):
        owner = await register_user(client)
        outsider = await register_user(client)
        pid = await _create_project(client, owner["token"])

        resp = await client.post(
            "/api/notes",
            json={
                "project_id": pid,
                "title": "Blocked",
                "sql_query": "SELECT 1",
            },
            headers=auth_headers(outsider["token"]),
        )
        assert resp.status_code == 403

    async def test_non_member_cannot_list_notes(self, client):
        owner = await register_user(client)
        outsider = await register_user(client)
        pid = await _create_project(client, owner["token"])

        resp = await client.get(
            f"/api/notes?project_id={pid}",
            headers=auth_headers(outsider["token"]),
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestNotesUserScoping:
    async def test_notes_are_user_scoped(self, client):
        owner = await register_user(client)
        viewer = await register_user(client)
        pid = await _create_project(client, owner["token"])

        resp = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": viewer["email"], "role": "viewer"},
            headers=auth_headers(owner["token"]),
        )
        invite_id = resp.json()["id"]
        await client.post(
            f"/api/invites/accept/{invite_id}",
            headers=auth_headers(viewer["token"]),
        )

        await _create_note(client, owner["token"], pid, title="Owner Note")
        await _create_note(client, viewer["token"], pid, title="Viewer Note")

        resp = await client.get(
            f"/api/notes?project_id={pid}",
            headers=auth_headers(owner["token"]),
        )
        assert resp.status_code == 200
        owner_notes = resp.json()
        assert len(owner_notes) == 1
        assert owner_notes[0]["title"] == "Owner Note"

        resp = await client.get(
            f"/api/notes?project_id={pid}",
            headers=auth_headers(viewer["token"]),
        )
        assert resp.status_code == 200
        viewer_notes = resp.json()
        assert len(viewer_notes) == 1
        assert viewer_notes[0]["title"] == "Viewer Note"
