"""COR-06: the lowest role could run DML against the customer's database.

The role ladder gates workspace mutations — a dashboard needs `editor`, a schedule
needs `owner` — and no execution path distinguished a viewer from an owner for SQL
against the CONNECTED database. On a connection with `is_read_only=False` a viewer
could save a note whose `sql_query` is `DELETE FROM orders WHERE 1=1` and execute it:
the guard there is `SafetyLevel.ALLOW_DML`, which blocks DDL and nothing else. Same
shape one route over, in `/api/batch/execute`.

These are behavioural rather than source-shaped on purpose: the earlier draft of this
guard asserted that the string `"viewer"` was absent from the route body, which any
rename satisfies without moving the gate.
"""

import uuid

import pytest
from httpx import AsyncClient

from tests.integration.conftest import auth_headers, register_user

_DML = "DELETE FROM orders WHERE 1=1"


async def _project_with_viewer(client: AsyncClient, *, read_only: bool):
    """An owner, a project, a connection of the requested writability, and a viewer."""
    owner = await register_user(client)
    owner_headers = auth_headers(owner["token"])
    pid = (
        await client.post(
            "/api/projects",
            json={"name": f"cor06-{uuid.uuid4().hex[:6]}"},
            headers=owner_headers,
        )
    ).json()["id"]
    conn = await client.post(
        "/api/connections",
        json={
            "project_id": pid,
            "name": "customer-db",
            "db_type": "postgres",
            "db_host": "127.0.0.1",
            "db_port": 5432,
            "db_name": "testdb",
            "db_user": "user",
            "db_password": "pass",
            "is_read_only": read_only,
        },
        headers=owner_headers,
    )
    assert conn.status_code == 200, conn.text
    assert conn.json()["is_read_only"] is read_only
    cid = conn.json()["id"]

    viewer = await register_user(client)
    invite = await client.post(
        f"/api/invites/{pid}/invites",
        json={"email": viewer["email"], "role": "viewer"},
        headers=owner_headers,
    )
    assert invite.status_code == 200, invite.text
    accepted = await client.post(
        f"/api/invites/accept/{invite.json()['id']}",
        headers=auth_headers(viewer["token"]),
    )
    assert accepted.status_code == 200, accepted.text
    return pid, cid, auth_headers(viewer["token"])


@pytest.mark.asyncio
class TestANoteIsNotAWayAroundTheRoleLadder:
    async def test_a_viewer_cannot_execute_dml_on_a_writable_connection(
        self, client: AsyncClient
    ) -> None:
        pid, cid, viewer_headers = await _project_with_viewer(client, read_only=False)
        note = await client.post(
            "/api/notes",
            json={
                "project_id": pid,
                "connection_id": cid,
                "title": "cleanup",
                "sql_query": _DML,
            },
            headers=viewer_headers,
        )
        assert note.status_code == 200, note.text

        resp = await client.post(
            f"/api/notes/{note.json()['id']}/execute",
            json={},
            headers=viewer_headers,
        )
        assert resp.status_code == 403, (
            "a viewer executed a saved note against a WRITABLE connection: "
            f"{resp.status_code} {resp.text[:200]}. `SafetyLevel.ALLOW_DML` blocks DDL "
            "and nothing else, so the DELETE reaches the customer's database (COR-06)"
        )

    async def test_a_viewer_still_reaches_a_read_only_connection(self, client: AsyncClient) -> None:
        """Running a SELECT is what a viewer is FOR — the gate must not take that away.

        Without this the cheapest way to pass the test above is `require_role(…,
        "editor")` unconditionally, which removes the product's actual function from
        the role most likely to be using it.
        """
        pid, cid, viewer_headers = await _project_with_viewer(client, read_only=True)
        note = await client.post(
            "/api/notes",
            json={
                "project_id": pid,
                "connection_id": cid,
                "title": "count",
                "sql_query": "SELECT 1",
            },
            headers=viewer_headers,
        )
        assert note.status_code == 200, note.text

        resp = await client.post(
            f"/api/notes/{note.json()['id']}/execute",
            json={},
            headers=viewer_headers,
        )
        # The connection points at nothing, so this fails on connecting — never on the
        # role. Any status but 403 proves the gate let it through to the executor.
        assert resp.status_code != 403, (
            "a viewer was refused a SELECT on a READ-ONLY connection: the engine "
            "already answers 'no' to a write there, so the role is not the layer that "
            f"has to. {resp.text[:200]}"
        )


@pytest.mark.asyncio
class TestABatchIsNotEither:
    async def test_a_viewer_cannot_run_a_batch_on_a_writable_connection(
        self, client: AsyncClient
    ) -> None:
        pid, cid, viewer_headers = await _project_with_viewer(client, read_only=False)
        resp = await client.post(
            "/api/batch/execute",
            json={
                "project_id": pid,
                "connection_id": cid,
                "title": "cleanup",
                "queries": [{"sql": _DML, "title": "q1"}],
            },
            headers=viewer_headers,
        )
        assert resp.status_code == 403, (
            "a viewer queued a batch of arbitrary SQL against a WRITABLE connection: "
            f"{resp.status_code} {resp.text[:200]} (COR-06)"
        )

    async def test_a_viewer_still_runs_a_batch_on_a_read_only_connection(
        self, client: AsyncClient
    ) -> None:
        pid, cid, viewer_headers = await _project_with_viewer(client, read_only=True)
        resp = await client.post(
            "/api/batch/execute",
            json={
                "project_id": pid,
                "connection_id": cid,
                "title": "report",
                "queries": [{"sql": "SELECT 1", "title": "q1"}],
            },
            headers=viewer_headers,
        )
        assert resp.status_code == 202, (
            f"a viewer was refused a read-only batch: {resp.status_code} {resp.text[:200]}"
        )
