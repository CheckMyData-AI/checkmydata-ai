"""Cross-tenant isolation tests for the /investigate endpoint (F-DG-07/09, R3 C3).

`POST /api/data-validation/investigate` only checked project membership via
``require_role`` and then trusted the caller-supplied ``connection_id`` /
``session_id`` / ``message_id``. A viewer of project A could pass ids belonging
to project B and leak / act on another tenant's data. These tests pin the
ownership re-scoping: a same-project request still starts an investigation, but
any id that belongs to a different project (or a message that belongs to a
different session) is rejected with 404.

Project/connection rows are created through the public API (the proven-working
``client`` path) rather than the ``db_session`` seed helpers, because the shared
in-memory SQLite engine used by the integration suite is not safe to seed
``users``/``projects`` from a second connection mid-test. Chat sessions and
messages (no extra user rows) are seeded directly via ``db_session``.
"""

import json
import uuid

import pytest

from tests.integration.conftest import auth_headers, make_chat_session, register_user


def _email() -> str:
    return f"iso-{uuid.uuid4().hex[:8]}@test.com"


async def _create_project(client, token: str) -> str:
    resp = await client.post(
        "/api/projects",
        json={"name": f"proj-{uuid.uuid4().hex[:6]}"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _create_connection(client, token: str, project_id: str) -> str:
    resp = await client.post(
        "/api/connections",
        json={
            "project_id": project_id,
            "name": f"conn-{uuid.uuid4().hex[:6]}",
            "db_type": "postgres",
            "db_host": "localhost",
            "db_port": 5432,
            "db_name": "test",
            "db_user": "user",
            "db_password": "pass",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _invite_viewer(client, owner_token: str, project_id: str, email: str) -> None:
    resp = await client.post(
        f"/api/invites/{project_id}/invites",
        json={"email": email, "role": "viewer"},
        headers=auth_headers(owner_token),
    )
    assert resp.status_code == 200, resp.text


async def _accept_invites(client, token: str) -> None:
    pending = await client.get("/api/invites/pending", headers=auth_headers(token))
    for inv in pending.json():
        await client.post(f"/api/invites/accept/{inv['id']}", headers=auth_headers(token))


async def _seed_message(db_session, *, session_id: str, message_id: str) -> None:
    """Insert a real chat message carrying investigation metadata."""
    from app.models.chat_session import ChatMessage

    db_session.add(
        ChatMessage(
            id=message_id,
            session_id=session_id,
            role="assistant",
            content="seed",
            metadata_json=json.dumps({"query": "SELECT 1", "raw_result": {"rows": [[1]]}}),
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
class TestInvestigateTenantIsolation:
    """A viewer of project A must not investigate resources from project B."""

    async def _setup(self, client):
        """Owner+viewer on project A, plus a separate owner with project B."""
        owner_a = await register_user(client)
        viewer_email = _email()
        project_a = await _create_project(client, owner_a["token"])
        conn_a = await _create_connection(client, owner_a["token"], project_a)
        await _invite_viewer(client, owner_a["token"], project_a, viewer_email)
        viewer = await register_user(client, viewer_email)
        await _accept_invites(client, viewer["token"])

        owner_b = await register_user(client)
        project_b = await _create_project(client, owner_b["token"])
        conn_b = await _create_connection(client, owner_b["token"], project_b)

        return {
            "viewer": viewer,
            "project_a": project_a,
            "conn_a": conn_a,
            "project_b": project_b,
            "conn_b": conn_b,
        }

    async def test_same_project_investigation_starts(self, client, db_session, monkeypatch):
        """Sanity: a viewer using ids that all belong to project A gets a 200."""
        ctx = await self._setup(client)
        session_id = await make_chat_session(db_session, project_id=ctx["project_a"])
        message_id = str(uuid.uuid4())
        await _seed_message(db_session, session_id=session_id, message_id=message_id)

        # The endpoint fire-and-forgets a background InvestigationAgent task that
        # opens its own DB session. Against the shared in-memory SQLite engine
        # that rogue connection corrupts the pool for later tests, so stub it
        # (mirrors tests/unit/test_validation_learning_credit.py).
        async def _noop_bg(**kwargs):
            return None

        monkeypatch.setattr(
            "app.api.routes.data_investigations._run_investigation_background",
            _noop_bg,
            raising=False,
        )

        resp = await client.post(
            "/api/data-validation/investigate",
            json={
                "project_id": ctx["project_a"],
                "connection_id": ctx["conn_a"],
                "session_id": session_id,
                "message_id": message_id,
                "complaint_type": "numbers_too_high",
            },
            headers=auth_headers(ctx["viewer"]["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["ok"] is True

    async def test_connection_from_other_project_rejected(self, client, db_session):
        ctx = await self._setup(client)
        session_id = await make_chat_session(db_session, project_id=ctx["project_a"])
        message_id = str(uuid.uuid4())
        await _seed_message(db_session, session_id=session_id, message_id=message_id)

        resp = await client.post(
            "/api/data-validation/investigate",
            json={
                "project_id": ctx["project_a"],
                "connection_id": ctx["conn_b"],  # belongs to project B
                "session_id": session_id,
                "message_id": message_id,
                "complaint_type": "numbers_too_high",
            },
            headers=auth_headers(ctx["viewer"]["token"]),
        )
        assert resp.status_code == 404, resp.text

    async def test_session_from_other_project_rejected(self, client, db_session):
        ctx = await self._setup(client)
        # Session (and its message) belong to project B.
        foreign_session = await make_chat_session(db_session, project_id=ctx["project_b"])
        message_id = str(uuid.uuid4())
        await _seed_message(db_session, session_id=foreign_session, message_id=message_id)

        resp = await client.post(
            "/api/data-validation/investigate",
            json={
                "project_id": ctx["project_a"],
                "connection_id": ctx["conn_a"],
                "session_id": foreign_session,  # belongs to project B
                "message_id": message_id,
                "complaint_type": "numbers_too_high",
            },
            headers=auth_headers(ctx["viewer"]["token"]),
        )
        assert resp.status_code == 404, resp.text

    async def test_message_from_other_session_rejected(self, client, db_session):
        ctx = await self._setup(client)
        session_id = await make_chat_session(db_session, project_id=ctx["project_a"])
        # A different (also project-A) session owns the message.
        other_session = await make_chat_session(db_session, project_id=ctx["project_a"])
        foreign_message = str(uuid.uuid4())
        await _seed_message(db_session, session_id=other_session, message_id=foreign_message)

        resp = await client.post(
            "/api/data-validation/investigate",
            json={
                "project_id": ctx["project_a"],
                "connection_id": ctx["conn_a"],
                "session_id": session_id,
                "message_id": foreign_message,  # belongs to other_session
                "complaint_type": "numbers_too_high",
            },
            headers=auth_headers(ctx["viewer"]["token"]),
        )
        assert resp.status_code == 404, resp.text
