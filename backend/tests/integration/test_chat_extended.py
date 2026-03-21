"""Extended integration tests for chat sessions, feedback, and messages."""

import pytest


@pytest.mark.asyncio
class TestChatSessionExtended:
    async def _create_project(self, auth_client) -> str:
        resp = await auth_client.post("/api/projects", json={"name": "ChatExt Proj"})
        return resp.json()["id"]

    async def _create_session(self, auth_client, pid: str, title: str = "Sess") -> str:
        resp = await auth_client.post(
            "/api/chat/sessions",
            json={"project_id": pid, "title": title},
        )
        assert resp.status_code == 200
        return resp.json()["id"]

    async def test_update_session_title(self, auth_client):
        pid = await self._create_project(auth_client)
        sid = await self._create_session(auth_client, pid, "Original")
        resp = await auth_client.patch(
            f"/api/chat/sessions/{sid}",
            json={"title": "Renamed"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Renamed"

    async def test_update_session_title_not_found(self, auth_client):
        resp = await auth_client.patch(
            "/api/chat/sessions/nonexistent",
            json={"title": "Nope"},
        )
        assert resp.status_code == 404

    async def test_generate_title_not_found(self, auth_client):
        resp = await auth_client.post("/api/chat/sessions/nonexistent/generate-title")
        assert resp.status_code == 404

    async def test_get_messages_empty(self, auth_client):
        pid = await self._create_project(auth_client)
        sid = await self._create_session(auth_client, pid)
        resp = await auth_client.get(f"/api/chat/sessions/{sid}/messages")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_messages_not_found(self, auth_client):
        resp = await auth_client.get("/api/chat/sessions/nonexistent/messages")
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestFeedback:
    async def _create_project(self, auth_client) -> str:
        resp = await auth_client.post("/api/projects", json={"name": "Feedback Proj"})
        return resp.json()["id"]

    async def test_feedback_submit(self, auth_client):
        resp = await auth_client.post(
            "/api/chat/feedback",
            json={"message_id": "nonexistent", "rating": 1},
        )
        assert resp.status_code == 404

    async def test_feedback_missing_fields(self, auth_client):
        resp = await auth_client.post("/api/chat/feedback", json={})
        assert resp.status_code == 422

    async def test_feedback_analytics_empty(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.get(f"/api/chat/analytics/feedback/{pid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_rated"] == 0
        assert data["positive"] == 0
        assert data["negative"] == 0


@pytest.mark.asyncio
class TestChatSearch:
    async def _create_project(self, auth_client) -> str:
        resp = await auth_client.post("/api/projects", json={"name": "Search Proj"})
        return resp.json()["id"]

    async def _create_session(self, auth_client, pid: str, title: str = "Sess") -> str:
        resp = await auth_client.post(
            "/api/chat/sessions",
            json={"project_id": pid, "title": title},
        )
        assert resp.status_code == 200
        return resp.json()["id"]

    async def test_search_no_results(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.get(f"/api/chat/search?project_id={pid}&q=nonexistent")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_search_finds_message(self, auth_client, db_session):
        pid = await self._create_project(auth_client)
        sid = await self._create_session(auth_client, pid, "Test Search Session")

        from app.services.chat_service import ChatService

        svc = ChatService()
        await svc.add_message(db_session, sid, "user", "Show me all active users by country")
        await svc.add_message(
            db_session,
            sid,
            "assistant",
            "Here are the active users grouped by country.",
            metadata={"query": "SELECT country, COUNT(*) FROM users WHERE active GROUP BY country"},
        )

        resp = await auth_client.get(f"/api/chat/search?project_id={pid}&q=active+users")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1
        assert any("active users" in r["content_snippet"].lower() for r in results)

    async def test_search_finds_sql_in_metadata(self, auth_client, db_session):
        pid = await self._create_project(auth_client)
        sid = await self._create_session(auth_client, pid, "SQL Search Session")

        from app.services.chat_service import ChatService

        svc = ChatService()
        await svc.add_message(
            db_session,
            sid,
            "assistant",
            "Query result below.",
            metadata={"query": "SELECT * FROM orders WHERE total > 1000"},
        )

        resp = await auth_client.get(f"/api/chat/search?project_id={pid}&q=orders+WHERE+total")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1
        assert any(r.get("sql_query") for r in results)

    async def test_search_requires_query(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.get(f"/api/chat/search?project_id={pid}")
        assert resp.status_code == 422

    async def test_search_requires_auth(self, client):
        resp = await client.get("/api/chat/search?project_id=fake&q=test")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestChatAuth:
    async def test_session_requires_auth(self, client):
        endpoints = [
            ("POST", "/api/chat/sessions"),
            ("GET", "/api/chat/sessions/fake"),
            ("PATCH", "/api/chat/sessions/fake"),
            ("DELETE", "/api/chat/sessions/fake"),
            ("POST", "/api/chat/sessions/fake/generate-title"),
            ("GET", "/api/chat/sessions/fake/messages"),
            ("GET", "/api/chat/search?project_id=fake&q=test"),
        ]
        for method, url in endpoints:
            if method == "POST" and url == "/api/chat/sessions":
                resp = await client.post(url, json={"project_id": "x", "title": "t"})
            elif method == "PATCH":
                resp = await client.patch(url, json={"title": "t"})
            else:
                resp = await getattr(client, method.lower())(url)
            assert resp.status_code == 401, f"{method} {url} should require auth"

    async def test_feedback_requires_auth(self, client):
        resp = await client.post(
            "/api/chat/feedback",
            json={"message_id": "x", "rating": 1},
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestExplainSql:
    async def _create_project(self, auth_client) -> str:
        resp = await auth_client.post("/api/projects", json={"name": "Explain Proj"})
        return resp.json()["id"]

    async def test_explain_sql_requires_auth(self, client):
        resp = await client.post(
            "/api/chat/explain-sql",
            json={"sql": "SELECT 1", "project_id": "fake"},
        )
        assert resp.status_code == 401

    async def test_explain_sql_missing_fields(self, auth_client):
        resp = await auth_client.post("/api/chat/explain-sql", json={})
        assert resp.status_code == 422

    async def test_explain_sql_requires_project_access(self, auth_client):
        resp = await auth_client.post(
            "/api/chat/explain-sql",
            json={"sql": "SELECT 1", "project_id": "nonexistent"},
        )
        assert resp.status_code in (403, 404)


@pytest.mark.asyncio
class TestSummarize:
    async def _create_project(self, auth_client) -> str:
        resp = await auth_client.post("/api/projects", json={"name": "Summarize Proj"})
        return resp.json()["id"]

    async def test_summarize_requires_auth(self, client):
        resp = await client.post(
            "/api/chat/summarize",
            json={"message_id": "fake", "project_id": "fake"},
        )
        assert resp.status_code == 401

    async def test_summarize_missing_fields(self, auth_client):
        resp = await auth_client.post("/api/chat/summarize", json={})
        assert resp.status_code == 422

    async def test_summarize_message_not_found(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.post(
            "/api/chat/summarize",
            json={"message_id": "nonexistent", "project_id": pid},
        )
        assert resp.status_code == 404
