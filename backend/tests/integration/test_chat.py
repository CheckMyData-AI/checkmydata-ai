"""Integration tests for /api/chat session management endpoints."""

import pytest

from tests.integration.conftest import auth_headers, register_user


@pytest.mark.asyncio
class TestChatSessions:
    async def _create_project(self, auth_client) -> str:
        resp = await auth_client.post("/api/projects", json={"name": "Chat Proj"})
        return resp.json()["id"]

    async def test_create_and_list_sessions(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.post(
            "/api/chat/sessions",
            json={
                "project_id": pid,
                "title": "Test Session",
            },
        )
        assert resp.status_code == 200
        sid = resp.json()["id"]
        assert resp.json()["title"] == "Test Session"

        resp = await auth_client.get(f"/api/chat/sessions/{pid}")
        assert resp.status_code == 200
        ids = [s["id"] for s in resp.json()]
        assert sid in ids

    async def test_create_session_with_connection_id(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.post(
            "/api/chat/sessions",
            json={
                "project_id": pid,
                "title": "With Conn",
                "connection_id": None,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["connection_id"] is None

    async def test_session_response_includes_connection_id(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.post(
            "/api/chat/sessions",
            json={"project_id": pid, "title": "Sess"},
        )
        assert resp.status_code == 200
        assert "connection_id" in resp.json()

    async def test_delete_session(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.post(
            "/api/chat/sessions",
            json={
                "project_id": pid,
                "title": "Temp",
            },
        )
        sid = resp.json()["id"]

        resp = await auth_client.delete(f"/api/chat/sessions/{sid}")
        assert resp.status_code == 200

    async def test_delete_session_not_found(self, auth_client):
        resp = await auth_client.delete("/api/chat/sessions/nonexistent")
        assert resp.status_code == 404

    async def test_messages_include_tool_calls_json(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.post(
            "/api/chat/sessions",
            json={"project_id": pid, "title": "MsgTest"},
        )
        sid = resp.json()["id"]
        resp = await auth_client.get(f"/api/chat/sessions/{sid}/messages")
        assert resp.status_code == 200
        for msg in resp.json():
            assert "tool_calls_json" in msg


@pytest.mark.asyncio
class TestChatSessionIsolation:
    async def test_list_sessions_shows_only_own(self, client):
        user_a = await register_user(client)
        user_b = await register_user(client)

        resp = await client.post(
            "/api/projects",
            json={"name": "Shared Proj"},
            headers=auth_headers(user_a["token"]),
        )
        pid = resp.json()["id"]

        resp = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": user_b["email"], "role": "editor"},
            headers=auth_headers(user_a["token"]),
        )
        await client.post(
            f"/api/invites/accept/{resp.json()['id']}",
            headers=auth_headers(user_b["token"]),
        )

        resp = await client.post(
            "/api/chat/sessions",
            json={"project_id": pid, "title": "A's Session"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        sid_a = resp.json()["id"]

        resp = await client.post(
            "/api/chat/sessions",
            json={"project_id": pid, "title": "B's Session"},
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 200
        sid_b = resp.json()["id"]

        resp = await client.get(
            f"/api/chat/sessions/{pid}",
            headers=auth_headers(user_a["token"]),
        )
        a_ids = [s["id"] for s in resp.json()]
        assert sid_a in a_ids
        assert sid_b not in a_ids

        resp = await client.get(
            f"/api/chat/sessions/{pid}",
            headers=auth_headers(user_b["token"]),
        )
        b_ids = [s["id"] for s in resp.json()]
        assert sid_b in b_ids
        assert sid_a not in b_ids

    async def test_user_cannot_delete_others_session(self, client):
        user_a = await register_user(client)
        user_b = await register_user(client)

        resp = await client.post(
            "/api/projects",
            json={"name": "Isolation Proj"},
            headers=auth_headers(user_a["token"]),
        )
        pid = resp.json()["id"]
        resp = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": user_b["email"], "role": "editor"},
            headers=auth_headers(user_a["token"]),
        )
        await client.post(
            f"/api/invites/accept/{resp.json()['id']}",
            headers=auth_headers(user_b["token"]),
        )

        resp = await client.post(
            "/api/chat/sessions",
            json={"project_id": pid, "title": "A's Session"},
            headers=auth_headers(user_a["token"]),
        )
        sid_a = resp.json()["id"]

        resp = await client.delete(
            f"/api/chat/sessions/{sid_a}",
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code in (403, 404)


@pytest.mark.asyncio
class TestEnsureWelcomeSession:
    async def _create_project(self, auth_client) -> str:
        resp = await auth_client.post("/api/projects", json={"name": "Welcome Proj"})
        return resp.json()["id"]

    async def test_creates_welcome_session_when_empty(self, auth_client):
        pid = await self._create_project(auth_client)

        resp = await auth_client.post(
            "/api/chat/sessions/ensure-welcome",
            json={"project_id": pid},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] is True
        assert data["title"] == "Welcome"
        assert data["project_id"] == pid

        msg_resp = await auth_client.get(f"/api/chat/sessions/{data['id']}/messages")
        assert msg_resp.status_code == 200
        msgs = msg_resp.json()
        assert len(msgs) == 1
        assert msgs[0]["role"] == "assistant"
        assert "data assistant" in msgs[0]["content"]

    async def test_idempotent_returns_existing(self, auth_client):
        pid = await self._create_project(auth_client)

        resp1 = await auth_client.post(
            "/api/chat/sessions/ensure-welcome",
            json={"project_id": pid},
        )
        assert resp1.status_code == 200
        sid1 = resp1.json()["id"]

        resp2 = await auth_client.post(
            "/api/chat/sessions/ensure-welcome",
            json={"project_id": pid},
        )
        assert resp2.status_code == 200
        assert resp2.json()["created"] is False
        assert resp2.json()["id"] == sid1

    async def test_returns_existing_when_chats_present(self, auth_client):
        pid = await self._create_project(auth_client)

        await auth_client.post(
            "/api/chat/sessions",
            json={"project_id": pid, "title": "Already Here"},
        )

        resp = await auth_client.post(
            "/api/chat/sessions/ensure-welcome",
            json={"project_id": pid},
        )
        assert resp.status_code == 200
        assert resp.json()["created"] is False
        assert resp.json()["title"] == "Already Here"
