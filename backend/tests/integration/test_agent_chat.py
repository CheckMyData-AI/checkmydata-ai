"""Integration tests for the conversational agent chat routes.

These tests verify that the /api/chat/ask endpoint correctly delegates
to the ConversationalAgent with optional connection_id and returns
responses with the new response_type field.
"""

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.integration.conftest import auth_headers, register_user


@pytest_asyncio.fixture()
async def project_id(auth_client: AsyncClient) -> str:
    resp = await auth_client.post(
        "/api/projects",
        json={
            "name": "Agent Test Project",
            "description": "testing",
        },
    )
    assert resp.status_code == 200
    return resp.json()["id"]


@pytest_asyncio.fixture()
async def connection_id(auth_client: AsyncClient, project_id: str) -> str:
    resp = await auth_client.post(
        "/api/connections",
        json={
            "project_id": project_id,
            "name": "Test Conn",
            "db_type": "postgres",
            "db_host": "localhost",
            "db_port": 5432,
            "db_name": "testdb",
            "db_user": "user",
            "db_password": "pass",
        },
    )
    assert resp.status_code == 200
    return resp.json()["id"]


class TestAskEndpointAgent:
    """Tests for POST /api/chat/ask using the ConversationalAgent."""

    @pytest.mark.asyncio
    @patch("app.api.routes.chat._agent")
    async def test_ask_conversational_response(
        self, mock_agent, auth_client, project_id, connection_id
    ):
        from app.core.agent import AgentResponse

        mock_agent.run = AsyncMock(
            return_value=AgentResponse(
                answer="Hello! I can help with your data.",
                response_type="text",
                workflow_id="wf-test",
                token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
        )

        resp = await auth_client.post(
            "/api/chat/ask",
            json={
                "project_id": project_id,
                "connection_id": connection_id,
                "message": "Hello!",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"] == "Hello! I can help with your data."
        assert data["response_type"] == "text"
        assert data["query"] is None
        assert data["visualization"] is None

    @pytest.mark.asyncio
    @patch("app.api.routes.chat._agent")
    async def test_ask_without_connection_id(self, mock_agent, auth_client, project_id):
        from app.core.agent import AgentResponse

        mock_agent.run = AsyncMock(
            return_value=AgentResponse(
                answer="Based on the project docs, here is what I found...",
                response_type="knowledge",
                workflow_id="wf-kb",
            )
        )

        resp = await auth_client.post(
            "/api/chat/ask",
            json={
                "project_id": project_id,
                "message": "What is the project about?",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["response_type"] == "knowledge"
        assert data["session_id"]

    @pytest.mark.asyncio
    @patch("app.api.routes.chat._agent")
    async def test_ask_sql_result_response(
        self, mock_agent, auth_client, project_id, connection_id
    ):
        from app.connectors.base import QueryResult
        from app.core.agent import AgentResponse

        mock_agent.run = AsyncMock(
            return_value=AgentResponse(
                answer="There are 42 users in the database.",
                query="SELECT COUNT(*) FROM users",
                query_explanation="Count all users",
                results=QueryResult(
                    columns=["count"],
                    rows=[[42]],
                    row_count=1,
                    execution_time_ms=5.0,
                ),
                viz_type="number",
                viz_config={},
                response_type="sql_result",
                workflow_id="wf-sql",
            )
        )

        resp = await auth_client.post(
            "/api/chat/ask",
            json={
                "project_id": project_id,
                "connection_id": connection_id,
                "message": "How many users?",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["response_type"] == "sql_result"
        assert data["query"] == "SELECT COUNT(*) FROM users"
        assert data["visualization"] is not None

    @pytest.mark.asyncio
    @patch("app.api.routes.chat._agent")
    async def test_ask_creates_session(self, mock_agent, auth_client, project_id):
        from app.core.agent import AgentResponse

        mock_agent.run = AsyncMock(
            return_value=AgentResponse(
                answer="Hi!",
                response_type="text",
            )
        )

        resp = await auth_client.post(
            "/api/chat/ask",
            json={
                "project_id": project_id,
                "message": "Hi!",
            },
        )
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]
        assert session_id

        mock_agent.run = AsyncMock(
            return_value=AgentResponse(
                answer="Sure!",
                response_type="text",
            )
        )
        resp2 = await auth_client.post(
            "/api/chat/ask",
            json={
                "project_id": project_id,
                "session_id": session_id,
                "message": "Follow-up question",
            },
        )
        assert resp2.status_code == 200
        assert resp2.json()["session_id"] == session_id


class TestAskEndpointAuth:
    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        resp = await client.post(
            "/api/chat/ask",
            json={
                "project_id": "abc",
                "message": "test",
            },
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    @patch("app.api.routes.chat._agent")
    async def test_non_member_returns_403(self, mock_agent, auth_client, project_id):

        other = await register_user(auth_client)
        resp = await auth_client.post(
            "/api/chat/ask",
            json={"project_id": project_id, "message": "test"},
            headers=auth_headers(other["token"]),
        )
        assert resp.status_code in (403, 404)


class TestStreamEndpointAgent:
    """Smoke test for POST /api/chat/ask/stream."""

    @pytest.mark.asyncio
    @patch("app.api.routes.chat._agent")
    async def test_stream_without_connection(self, mock_agent, auth_client, project_id):
        from app.core.agent import AgentResponse

        mock_agent.run = AsyncMock(
            return_value=AgentResponse(
                answer="Streamed answer",
                response_type="text",
            )
        )

        resp = await auth_client.post(
            "/api/chat/ask/stream",
            json={
                "project_id": project_id,
                "message": "Hello stream",
            },
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
