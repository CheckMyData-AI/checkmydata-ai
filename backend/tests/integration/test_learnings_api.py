"""Integration tests for /api/connections/{id}/learnings endpoints."""

import pytest

from app.models.agent_learning import AgentLearning, _lesson_hash


@pytest.mark.asyncio
class TestLearningsApi:
    async def _setup_connection(self, auth_client) -> str:
        resp = await auth_client.post("/api/projects", json={"name": "Learn Test Proj"})
        pid = resp.json()["id"]
        resp = await auth_client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "Learn Conn",
                "db_type": "postgres",
                "db_host": "127.0.0.1",
                "db_name": "testdb",
            },
        )
        return resp.json()["id"]

    async def _seed_learning(self, db_session, connection_id: str, **kw) -> AgentLearning:
        defaults = {
            "connection_id": connection_id,
            "category": "table_preference",
            "subject": "orders",
            "lesson": "Use orders_v2",
            "lesson_hash": _lesson_hash("Use orders_v2"),
            "confidence": 0.7,
        }
        defaults.update(kw)
        entry = AgentLearning(**defaults)
        db_session.add(entry)
        await db_session.flush()
        return entry

    async def test_list_learnings_empty(self, auth_client, db_session):
        cid = await self._setup_connection(auth_client)
        resp = await auth_client.get(f"/api/connections/{cid}/learnings")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_learnings_with_data(self, auth_client, db_session):
        cid = await self._setup_connection(auth_client)
        await self._seed_learning(db_session, cid)
        await db_session.commit()

        resp = await auth_client.get(f"/api/connections/{cid}/learnings")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["subject"] == "orders"

    async def test_get_status_empty(self, auth_client, db_session):
        cid = await self._setup_connection(auth_client)
        resp = await auth_client.get(f"/api/connections/{cid}/learnings/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["has_learnings"] is False
        assert body["total_active"] == 0

    async def test_get_status_with_data(self, auth_client, db_session):
        cid = await self._setup_connection(auth_client)
        await self._seed_learning(db_session, cid)
        await db_session.commit()

        resp = await auth_client.get(f"/api/connections/{cid}/learnings/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["has_learnings"] is True
        assert body["total_active"] == 1

    async def test_get_summary_empty(self, auth_client, db_session):
        cid = await self._setup_connection(auth_client)
        resp = await auth_client.get(f"/api/connections/{cid}/learnings/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["compiled_prompt"] == ""

    async def test_update_learning_lesson(self, auth_client, db_session):
        cid = await self._setup_connection(auth_client)
        entry = await self._seed_learning(db_session, cid)
        await db_session.commit()

        resp = await auth_client.patch(
            f"/api/connections/{cid}/learnings/{entry.id}",
            json={"lesson": "Updated lesson text"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_update_learning_toggle_active(self, auth_client, db_session):
        cid = await self._setup_connection(auth_client)
        entry = await self._seed_learning(db_session, cid)
        await db_session.commit()

        resp = await auth_client.patch(
            f"/api/connections/{cid}/learnings/{entry.id}",
            json={"is_active": False},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_delete_learning(self, auth_client, db_session):
        cid = await self._setup_connection(auth_client)
        entry = await self._seed_learning(db_session, cid)
        await db_session.commit()

        resp = await auth_client.delete(f"/api/connections/{cid}/learnings/{entry.id}")
        assert resp.status_code == 200

        resp2 = await auth_client.get(f"/api/connections/{cid}/learnings")
        assert len(resp2.json()) == 0

    async def test_clear_all_learnings(self, auth_client, db_session):
        cid = await self._setup_connection(auth_client)
        await self._seed_learning(db_session, cid)
        await self._seed_learning(
            db_session,
            cid,
            subject="users",
            lesson="Users table note",
            lesson_hash=_lesson_hash("Users table note"),
        )
        await db_session.commit()

        resp = await auth_client.delete(f"/api/connections/{cid}/learnings")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 2

    async def test_recompile(self, auth_client, db_session):
        cid = await self._setup_connection(auth_client)
        await self._seed_learning(db_session, cid)
        await db_session.commit()

        resp = await auth_client.post(f"/api/connections/{cid}/learnings/recompile")
        assert resp.status_code == 200
        body = resp.json()
        assert "compiled_prompt" in body
        assert "Table Preferences" in body["compiled_prompt"]

    async def test_auth_required(self, client):
        resp = await client.get("/api/connections/fake-id/learnings")
        assert resp.status_code in (401, 403, 422)
