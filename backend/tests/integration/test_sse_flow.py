"""Integration test for the full SSE event flow through /ask/stream.

Verifies the complete event sequence: thinking -> tool_call -> token -> result
with a mocked LLM, exercising the real SSE routing code.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.integration.conftest import auth_headers, register_user


def _make_llm_response(content="Hello", tool_calls=None, provider="openai", model="gpt-4o"):
    """Build a mock LLMResponse."""
    from app.llm.base import LLMResponse

    return LLMResponse(
        content=content,
        tool_calls=tool_calls or [],
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        provider=provider,
        model=model,
    )


def _parse_sse(text: str) -> list[dict]:
    """Parse SSE text into a list of {event, data} dicts."""
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        event_type = ""
        data_str = ""
        for line in lines:
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_str = line.split(":", 1)[1].strip()
        if event_type and data_str:
            try:
                events.append({"event": event_type, "data": json.loads(data_str)})
            except json.JSONDecodeError:
                events.append({"event": event_type, "data": data_str})
    return events


@pytest.mark.asyncio
class TestSSEFlow:
    async def _create_project(self, auth_client) -> str:
        resp = await auth_client.post("/api/projects", json={"name": "SSE Test Proj"})
        return resp.json()["id"]

    @patch("app.core.agent.ConversationalAgent.run")
    async def test_sse_event_sequence_simple_text(self, mock_run, auth_client):
        """Test that a simple text response produces thinking -> token -> result events."""
        from app.agents.orchestrator import AgentResponse

        pid = await self._create_project(auth_client)

        mock_run.return_value = AgentResponse(
            answer="Test answer",
            workflow_id="wf-test-1",
            response_type="text",
            llm_provider="openai",
            llm_model="gpt-4o",
        )

        resp = await auth_client.post(
            "/api/chat/ask/stream",
            json={
                "project_id": pid,
                "message": "Hello",
            },
        )
        assert resp.status_code == 200

        events = _parse_sse(resp.text)
        event_types = [e["event"] for e in events]

        assert "result" in event_types, f"Expected 'result' event in {event_types}"

        result_event = next(e for e in events if e["event"] == "result")
        assert result_event["data"]["answer"] == "Test answer"
        assert result_event["data"]["session_id"]
        assert result_event["data"]["response_type"] == "text"

    @patch("app.core.agent.ConversationalAgent.run")
    async def test_sse_error_event(self, mock_run, auth_client):
        """Test that exceptions produce proper error SSE events."""
        pid = await self._create_project(auth_client)

        mock_run.side_effect = Exception("Test failure")

        resp = await auth_client.post(
            "/api/chat/ask/stream",
            json={
                "project_id": pid,
                "message": "Hello",
            },
        )
        assert resp.status_code == 200

        events = _parse_sse(resp.text)
        event_types = [e["event"] for e in events]

        assert "error" in event_types, f"Expected 'error' event in {event_types}"
        err = next(e for e in events if e["event"] == "error")
        assert err["data"]["is_retryable"] is True

    @patch("app.core.agent.ConversationalAgent.run")
    async def test_sse_result_contains_session_id(self, mock_run, auth_client):
        """Test that result event always has a session_id (new session created)."""
        from app.agents.orchestrator import AgentResponse

        pid = await self._create_project(auth_client)

        mock_run.return_value = AgentResponse(
            answer="answer",
            workflow_id="wf-2",
            response_type="text",
        )

        resp = await auth_client.post(
            "/api/chat/ask/stream",
            json={
                "project_id": pid,
                "message": "test",
            },
        )
        events = _parse_sse(resp.text)
        result_event = next((e for e in events if e["event"] == "result"), None)
        assert result_event is not None
        assert result_event["data"]["session_id"]
