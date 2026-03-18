"""Tests for MCPSourceAgent — MCP server interaction loop.

Verifies tool discovery, LLM-driven tool calling, iteration limits,
adapter management, token accumulation, and error handling.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.base import AgentContext
from app.agents.mcp_source_agent import MAX_MCP_ITERATIONS, MCPSourceAgent, MCPSourceResult
from app.connectors.mcp_client import MCPClientAdapter
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import LLMResponse, ToolCall

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_tool_schema(
    name: str = "get_data",
    description: str = "Fetches data",
    properties: dict | None = None,
    required: list[str] | None = None,
) -> dict:
    """Helper to build a single MCP tool schema dict."""
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties
            or {"query": {"type": "string", "description": "search query"}},
            "required": required or ["query"],
        },
    }


@pytest.fixture
def mock_adapter():
    adapter = MagicMock(spec=MCPClientAdapter)
    adapter.get_tool_schemas = MagicMock(return_value=[_make_tool_schema()])
    adapter.call_tool = AsyncMock(return_value='{"rows": [1, 2, 3]}')
    return adapter


@pytest.fixture
def mock_llm():
    router = MagicMock()
    router.complete = AsyncMock(
        return_value=LLMResponse(
            content="Here is the answer.",
            tool_calls=[],
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
    )
    return router


@pytest.fixture
def mock_tracker():
    t = MagicMock(spec=WorkflowTracker)
    t.begin = AsyncMock(return_value="wf-1")
    t.end = AsyncMock()
    t.emit = AsyncMock()

    @asynccontextmanager
    async def fake_step(wf_id, step, detail=""):
        yield

    t.step = MagicMock(side_effect=fake_step)
    return t


@pytest.fixture
def context(mock_llm, mock_tracker):
    return AgentContext(
        project_id="proj-1",
        connection_config=None,
        user_question="What are the latest metrics?",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-1",
    )


@pytest.fixture
def agent(mock_llm, mock_adapter):
    return MCPSourceAgent(llm_router=mock_llm, adapter=mock_adapter)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMCPSourceAgent:
    """Comprehensive unit tests for MCPSourceAgent."""

    # 1. name property --------------------------------------------------

    def test_name_property(self, agent: MCPSourceAgent):
        assert agent.name == "mcp_source"

    # 2. no adapter configured ------------------------------------------

    @pytest.mark.asyncio
    async def test_no_adapter(self, mock_llm, context: AgentContext):
        agent = MCPSourceAgent(llm_router=mock_llm, adapter=None)
        result = await agent.run(context)

        assert isinstance(result, MCPSourceResult)
        assert result.status == "error"
        assert result.error == "No MCP adapter configured"
        assert "no adapter" in result.answer.lower()

    # 3. adapter with no tools ------------------------------------------

    @pytest.mark.asyncio
    async def test_no_tools_available(self, mock_llm, mock_adapter, context: AgentContext):
        mock_adapter.get_tool_schemas.return_value = []
        agent = MCPSourceAgent(llm_router=mock_llm, adapter=mock_adapter)

        result = await agent.run(context)

        assert result.status == "no_result"
        assert "no tools" in result.answer.lower()
        mock_llm.complete.assert_not_called()

    # 4. text response without tool calls --------------------------------

    @pytest.mark.asyncio
    async def test_text_response_no_tools(
        self, agent: MCPSourceAgent, mock_llm, context: AgentContext
    ):
        mock_llm.complete.return_value = LLMResponse(
            content="The answer is 42.",
            tool_calls=[],
            usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        )

        result = await agent.run(context)

        assert result.status == "success"
        assert result.answer == "The answer is 42."
        assert result.tool_calls_made == []
        assert result.raw_results == []
        mock_llm.complete.assert_awaited_once()

    # 5. single tool call success ----------------------------------------

    @pytest.mark.asyncio
    async def test_tool_call_success(
        self, agent: MCPSourceAgent, mock_llm, mock_adapter, context: AgentContext
    ):
        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc-1", name="get_data", arguments={"query": "metrics"}),
                    ],
                    usage={"prompt_tokens": 30, "completion_tokens": 15, "total_tokens": 45},
                )
            return LLMResponse(
                content="Based on the data, here are the metrics.",
                tool_calls=[],
                usage={"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)
        mock_adapter.call_tool.return_value = '{"metric": "revenue", "value": 1000}'

        result = await agent.run(context)

        assert result.status == "success"
        assert "metrics" in result.answer.lower()
        assert len(result.tool_calls_made) == 1
        assert result.tool_calls_made[0]["tool"] == "get_data"
        assert result.tool_calls_made[0]["arguments"] == {"query": "metrics"}
        mock_adapter.call_tool.assert_awaited_once_with("get_data", {"query": "metrics"})

    # 6. multiple tool calls in sequence ---------------------------------

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self, mock_llm, mock_adapter, context: AgentContext):
        mock_adapter.get_tool_schemas.return_value = [
            _make_tool_schema("get_users", "List users"),
            _make_tool_schema("get_orders", "List orders"),
        ]
        agent = MCPSourceAgent(llm_router=mock_llm, adapter=mock_adapter)
        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc-1", name="get_users", arguments={"query": "all"}),
                    ],
                    usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
                )
            if call_count == 2:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc-2", name="get_orders", arguments={"query": "recent"}),
                    ],
                    usage={"prompt_tokens": 40, "completion_tokens": 15, "total_tokens": 55},
                )
            return LLMResponse(
                content="Found 5 users and 12 recent orders.",
                tool_calls=[],
                usage={"prompt_tokens": 60, "completion_tokens": 25, "total_tokens": 85},
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)
        mock_adapter.call_tool.side_effect = [
            '[{"id": 1, "name": "Alice"}]',
            '[{"id": 101, "total": 99.9}]',
        ]

        result = await agent.run(context)

        assert result.status == "success"
        assert len(result.tool_calls_made) == 2
        assert result.tool_calls_made[0]["tool"] == "get_users"
        assert result.tool_calls_made[1]["tool"] == "get_orders"
        assert len(result.raw_results) == 2

    # 7. tool call raises exception → handled gracefully -----------------

    @pytest.mark.asyncio
    async def test_tool_call_error(
        self, agent: MCPSourceAgent, mock_llm, mock_adapter, context: AgentContext
    ):
        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc-err", name="get_data", arguments={"query": "broken"}),
                    ],
                    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                )
            return LLMResponse(
                content="Sorry, the tool encountered an error.",
                tool_calls=[],
                usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)
        mock_adapter.call_tool.side_effect = RuntimeError("connection reset")

        with pytest.raises(RuntimeError, match="connection reset"):
            await agent.run(context)

    # 8. max iterations --------------------------------------------------

    @pytest.mark.asyncio
    async def test_max_iterations(
        self, agent: MCPSourceAgent, mock_llm, mock_adapter, context: AgentContext
    ):
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(id="tc-loop", name="get_data", arguments={"query": "loop"}),
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
        )
        mock_adapter.call_tool.return_value = '{"status": "more data needed"}'

        result = await agent.run(context)

        assert result.status == "success"
        assert "maximum iterations" in result.answer.lower()
        assert mock_llm.complete.await_count == MAX_MCP_ITERATIONS
        assert len(result.tool_calls_made) == MAX_MCP_ITERATIONS

    # 9. set_adapter updates the adapter ---------------------------------

    def test_set_adapter(self, mock_llm):
        agent = MCPSourceAgent(llm_router=mock_llm, adapter=None)
        assert agent._adapter is None

        new_adapter = MagicMock(spec=MCPClientAdapter)
        agent.set_adapter(new_adapter)

        assert agent._adapter is new_adapter

    # 10. token usage accumulated across LLM calls -----------------------

    @pytest.mark.asyncio
    async def test_token_usage(
        self, agent: MCPSourceAgent, mock_llm, mock_adapter, context: AgentContext
    ):
        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc-1", name="get_data", arguments={"query": "a"}),
                    ],
                    usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                )
            if call_count == 2:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc-2", name="get_data", arguments={"query": "b"}),
                    ],
                    usage={"prompt_tokens": 200, "completion_tokens": 40, "total_tokens": 240},
                )
            return LLMResponse(
                content="Done.",
                tool_calls=[],
                usage={"prompt_tokens": 150, "completion_tokens": 30, "total_tokens": 180},
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)
        mock_adapter.call_tool.return_value = '{"ok": true}'

        result = await agent.run(context)

        assert result.token_usage["prompt_tokens"] == 100 + 200 + 150
        assert result.token_usage["completion_tokens"] == 20 + 40 + 30
        assert result.token_usage["total_tokens"] == 120 + 240 + 180
