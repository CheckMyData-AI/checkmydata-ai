"""Integration tests for the conversational agent chat routes.

These tests verify that the /api/chat/ask endpoint correctly delegates
to the ConversationalAgent with optional connection_id and returns
responses with the new response_type field.
"""

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
    async def test_ask_releases_session_lock_when_message_persist_fails(
        self, mock_agent, auth_client, project_id
    ):
        """A DB failure persisting the user message must release the per-session
        lock acquired just before it — otherwise the session is wedged 'busy'
        for the lock TTL window."""
        import contextlib
        from unittest.mock import MagicMock

        from app.api.routes import chat as chat_mod

        fake_cm = MagicMock()
        fake_cm.__aenter__ = AsyncMock(return_value=None)
        fake_cm.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.object(chat_mod, "session_processing_lock", return_value=fake_cm),
            patch.object(
                chat_mod._chat_svc,
                "add_message",
                new=AsyncMock(side_effect=RuntimeError("db down")),
            ),
        ):
            # The test client re-raises server exceptions; we only care that the
            # lock was released on the way out.
            with contextlib.suppress(BaseException):
                await auth_client.post(
                    "/api/chat/ask",
                    json={"project_id": project_id, "message": "hi"},
                )

        # The lock must have been released despite the failure (no wedged session).
        fake_cm.__aexit__.assert_awaited()

    @pytest.mark.asyncio
    @patch("app.api.routes.chat.maybe_auto_investigate")
    @patch("app.api.routes.chat._agent")
    async def test_ask_releases_session_lock_when_postagent_step_fails(
        self, mock_agent, mock_investigate, auth_client, project_id
    ):
        """A failure in post-agent processing (after the agent already ran) must
        also release the lock — the single try/finally covers the whole body,
        closing the gap the interim fix left open."""
        import contextlib
        from unittest.mock import MagicMock

        from app.api.routes import chat as chat_mod
        from app.core.agent import AgentResponse

        mock_agent.run = AsyncMock(
            return_value=AgentResponse(
                answer="ok",
                response_type="text",
                workflow_id="wf-x",
                token_usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            )
        )
        mock_investigate.side_effect = RuntimeError("investigate boom")

        fake_cm = MagicMock()
        fake_cm.__aenter__ = AsyncMock(return_value=None)
        fake_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(chat_mod, "session_processing_lock", return_value=fake_cm):
            with contextlib.suppress(BaseException):
                await auth_client.post(
                    "/api/chat/ask",
                    json={"project_id": project_id, "message": "hi"},
                )

        fake_cm.__aexit__.assert_awaited()

    @pytest.mark.asyncio
    @patch("app.api.routes.chat._agent")
    async def test_ask_acquires_and_releases_agent_limiter(
        self, mock_agent, auth_client, project_id
    ):
        """The non-streaming /ask path must acquire an agent_limiter slot before
        running the agent and release it afterwards — exactly like /ask/stream
        and the WS path. Otherwise /ask bypasses ``max_concurrent_agent_calls``
        and ``max_agent_calls_per_hour`` (audit-High concurrency bypass)."""
        from app.api.routes import chat as chat_mod
        from app.core.agent import AgentResponse

        mock_agent.run = AsyncMock(return_value=AgentResponse(answer="ok", response_type="text"))

        with (
            patch.object(
                chat_mod.agent_limiter, "acquire", new=AsyncMock(return_value=None)
            ) as acq,
            patch.object(
                chat_mod.agent_limiter, "release", new=AsyncMock(return_value=None)
            ) as rel,
        ):
            resp = await auth_client.post(
                "/api/chat/ask",
                json={"project_id": project_id, "message": "Hi"},
            )

        assert resp.status_code == 200
        # Acquired once for this run, with the authenticated user's id.
        acq.assert_awaited_once()
        acquired_user_id = acq.await_args.args[0]
        assert acquired_user_id
        # The agent only ran because the slot was granted.
        mock_agent.run.assert_awaited_once()
        # The slot is returned afterwards, for the same user.
        rel.assert_awaited_once_with(acquired_user_id)

    @pytest.mark.asyncio
    @patch("app.api.routes.chat._agent")
    async def test_ask_over_concurrency_cap_returns_429(self, mock_agent, auth_client, project_id):
        """When the user is over their concurrency/hourly cap, /ask must surface
        the limiter's message as HTTP 429 and never invoke the agent (mirrors the
        stream path's ``raise HTTPException(429, detail=limit_err)``)."""
        from app.api.routes import chat as chat_mod
        from app.core.agent import AgentResponse

        mock_agent.run = AsyncMock(return_value=AgentResponse(answer="ok", response_type="text"))
        deny_msg = "Too many concurrent requests (limit: 3). Please wait."

        with (
            patch.object(
                chat_mod.agent_limiter, "acquire", new=AsyncMock(return_value=deny_msg)
            ) as acq,
            patch.object(
                chat_mod.agent_limiter, "release", new=AsyncMock(return_value=None)
            ) as rel,
        ):
            resp = await auth_client.post(
                "/api/chat/ask",
                json={"project_id": project_id, "message": "Hi"},
            )

        assert resp.status_code == 429
        assert resp.json()["detail"] == deny_msg
        acq.assert_awaited_once()
        # A denied acquire reserves nothing, so there is nothing to release...
        rel.assert_not_called()
        # ...and the agent must not run.
        mock_agent.run.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.api.routes.chat._agent")
    async def test_ask_agent_timeout_returns_504_and_releases_limiter(
        self, mock_agent, auth_client, project_id
    ):
        """A stuck agent run must be bounded by ``stream_timeout_seconds`` so it
        cannot hold the request (and its concurrency slot) open forever. On
        timeout /ask returns 504 and still releases the limiter slot."""
        import asyncio as _asyncio

        from app.api.routes import chat as chat_mod

        async def _hang(*args, **kwargs):
            await _asyncio.sleep(3600)

        mock_agent.run = AsyncMock(side_effect=_hang)

        with (
            patch.object(chat_mod.agent_limiter, "acquire", new=AsyncMock(return_value=None)),
            patch.object(
                chat_mod.agent_limiter, "release", new=AsyncMock(return_value=None)
            ) as rel,
        ):
            # Drive the timeout immediately rather than waiting the real budget.
            from app.config import settings as real_settings

            with patch.object(real_settings, "stream_timeout_seconds", 0.05):
                resp = await auth_client.post(
                    "/api/chat/ask",
                    json={"project_id": project_id, "message": "Hi"},
                )

        assert resp.status_code == 504
        # The slot acquired for this run is returned even on timeout.
        rel.assert_awaited_once()

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
    async def test_ask_checkpoint_returns_viz_config_pipeline_run_id(
        self, mock_agent, auth_client, project_id, connection_id
    ):
        """A stage_checkpoint response must surface ``viz_config.pipeline_run_id``.

        The frontend reads ``result.viz_config.pipeline_run_id`` to enable the
        checkpoint "Continue / Modify / Retry" buttons (``sendPipelineAction``
        early-returns without it). If the route drops ``viz_config`` the buttons
        render but silently no-op.
        """
        from app.connectors.base import QueryResult
        from app.core.agent import AgentResponse

        mock_agent.run = AsyncMock(
            return_value=AgentResponse(
                answer="Found 16 rows. Does this look correct?",
                query="SELECT data_type, payment_type, COUNT(*) FROM t GROUP BY 1, 2",
                results=QueryResult(
                    columns=["data_type", "payment_type", "rows_cnt"],
                    rows=[["Virtual numbers", "apple", 63761]],
                    row_count=16,
                    execution_time_ms=12.0,
                ),
                viz_type="table",
                viz_config={"pipeline_run_id": "run-abc-123", "stage_id": "stage-1"},
                response_type="stage_checkpoint",
                workflow_id="wf-checkpoint",
            )
        )

        resp = await auth_client.post(
            "/api/chat/ask",
            json={
                "project_id": project_id,
                "connection_id": connection_id,
                "message": "Inspect the cohort table",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["response_type"] == "stage_checkpoint"
        assert data.get("viz_config") is not None
        assert data["viz_config"]["pipeline_run_id"] == "run-abc-123"
        assert data["viz_config"]["stage_id"] == "stage-1"

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


class TestProjectLlmConfigUsed:
    """Verify the chat route loads project-level LLM settings."""

    @pytest.mark.asyncio
    @patch("app.api.routes.chat._agent")
    async def test_agent_receives_project_llm_config(self, mock_agent, auth_client):
        from app.core.agent import AgentResponse

        resp = await auth_client.post(
            "/api/projects",
            json={
                "name": "LLM Route Test",
                "agent_llm_provider": "anthropic",
                "agent_llm_model": "claude-3-opus",
                "sql_llm_provider": "openrouter",
                "sql_llm_model": "mixtral-8x7b",
            },
        )
        pid = resp.json()["id"]

        mock_agent.run = AsyncMock(return_value=AgentResponse(answer="ok", response_type="text"))

        resp = await auth_client.post(
            "/api/chat/ask",
            json={"project_id": pid, "message": "Hi"},
        )
        assert resp.status_code == 200

        call_kwargs = mock_agent.run.call_args.kwargs
        assert call_kwargs["preferred_provider"] == "anthropic"
        assert call_kwargs["model"] == "claude-3-opus"
        assert call_kwargs["sql_provider"] == "openrouter"
        assert call_kwargs["sql_model"] == "mixtral-8x7b"

    @pytest.mark.asyncio
    @patch("app.api.routes.chat._agent")
    async def test_request_overrides_project_agent_config(self, mock_agent, auth_client):
        from app.core.agent import AgentResponse

        resp = await auth_client.post(
            "/api/projects",
            json={
                "name": "Override Test",
                "agent_llm_provider": "anthropic",
                "agent_llm_model": "claude-3-opus",
            },
        )
        pid = resp.json()["id"]

        mock_agent.run = AsyncMock(return_value=AgentResponse(answer="ok", response_type="text"))

        resp = await auth_client.post(
            "/api/chat/ask",
            json={
                "project_id": pid,
                "message": "Hi",
                "preferred_provider": "openai",
                "model": "gpt-4o",
            },
        )
        assert resp.status_code == 200

        call_kwargs = mock_agent.run.call_args.kwargs
        assert call_kwargs["preferred_provider"] == "openai"
        assert call_kwargs["model"] == "gpt-4o"


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


class TestRulesChangedFlag:
    """Tests for rules_changed flag in ChatResponse."""

    @pytest.mark.asyncio
    @patch("app.api.routes.chat._agent")
    async def test_rules_changed_true_when_manage_rules_called(
        self,
        mock_agent,
        auth_client,
        project_id,
    ):
        from app.core.agent import AgentResponse

        mock_agent.run = AsyncMock(
            return_value=AgentResponse(
                answer="Rule created!",
                response_type="text",
                tool_call_log=[
                    {"tool": "manage_custom_rules", "arguments": {"action": "create"}},
                ],
            )
        )

        resp = await auth_client.post(
            "/api/chat/ask",
            json={"project_id": project_id, "message": "Remember: amount is cents"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rules_changed"] is True

    @pytest.mark.asyncio
    @patch("app.api.routes.chat._agent")
    async def test_rules_changed_false_for_normal_chat(
        self,
        mock_agent,
        auth_client,
        project_id,
    ):
        from app.core.agent import AgentResponse

        mock_agent.run = AsyncMock(
            return_value=AgentResponse(
                answer="Hello!",
                response_type="text",
                tool_call_log=[],
            )
        )

        resp = await auth_client.post(
            "/api/chat/ask",
            json={"project_id": project_id, "message": "Hi"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rules_changed"] is False

    @pytest.mark.asyncio
    @patch("app.api.routes.chat._agent")
    async def test_user_id_passed_to_agent(
        self,
        mock_agent,
        auth_client,
        project_id,
    ):
        from app.core.agent import AgentResponse

        mock_agent.run = AsyncMock(return_value=AgentResponse(answer="ok", response_type="text"))

        resp = await auth_client.post(
            "/api/chat/ask",
            json={"project_id": project_id, "message": "test"},
        )
        assert resp.status_code == 200

        call_kwargs = mock_agent.run.call_args.kwargs
        assert "user_id" in call_kwargs
        assert call_kwargs["user_id"] is not None


class TestStreamEndpointAgent:
    """Smoke test for POST /api/chat/ask/stream."""

    @pytest.mark.asyncio
    @patch("app.api.routes.chat._agent")
    async def test_stream_without_connection(self, mock_agent, auth_client, project_id, engine):
        from app.core.agent import AgentResponse

        mock_agent.run = AsyncMock(
            return_value=AgentResponse(
                answer="Streamed answer",
                response_type="text",
            )
        )

        test_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        with patch("app.models.base.async_session_factory", test_factory):
            resp = await auth_client.post(
                "/api/chat/ask/stream",
                json={
                    "project_id": project_id,
                    "message": "Hello stream",
                },
            )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
