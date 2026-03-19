"""Tests for KnowledgeAgent — RAG / codebase specialist.

Covers the full run loop, tool dispatch, entity formatting,
max-iteration guard, and token-usage accumulation.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import AgentContext
from app.agents.knowledge_agent import KnowledgeAgent, KnowledgeResult
from app.config import settings
from app.core.workflow_tracker import WorkflowTracker
from app.knowledge.entity_extractor import (
    ColumnInfo,
    EntityInfo,
    EnumDefinition,
    ProjectKnowledge,
    TableUsage,
)
from app.llm.base import LLMResponse, ToolCall

RAG_RELEVANCE_THRESHOLD = settings.rag_relevance_threshold

# ── fixtures ──────────────────────────────────────────────────────────


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
def mock_llm():
    router = MagicMock()
    router.complete = AsyncMock()
    return router


@pytest.fixture
def mock_vector_store():
    vs = MagicMock()
    vs.query = MagicMock(return_value=[])
    return vs


@pytest.fixture
def context(mock_llm, mock_tracker):
    return AgentContext(
        project_id="proj-1",
        connection_config=None,
        user_question="test question",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-1",
        user_id="user-1",
    )


@pytest.fixture
def agent(mock_vector_store):
    return KnowledgeAgent(vector_store=mock_vector_store)


@pytest.fixture
def sample_knowledge():
    """Minimal ProjectKnowledge with one entity, table, and enum."""
    return ProjectKnowledge(
        entities={
            "User": EntityInfo(
                name="User",
                table_name="users",
                file_path="models/user.py",
                columns=[
                    ColumnInfo(name="id", col_type="Integer", is_pk=True),
                    ColumnInfo(name="org_id", col_type="Integer", is_fk=True, fk_target="orgs.id"),
                ],
                relationships=["Organization"],
                used_in_files=["routes/user.py"],
            ),
        },
        table_usage={
            "users": TableUsage(
                table_name="users",
                readers=["routes/user.py"],
                writers=["services/user_svc.py"],
                orm_refs=["models/user.py"],
            ),
        },
        enums=[
            EnumDefinition(
                name="StatusEnum", values=["active", "inactive"], file_path="models/enums.py"
            ),
        ],
        service_functions=[
            {"name": "get_user", "file_path": "services/user_svc.py", "tables": ["users"]},
        ],
    )


# ── helpers ───────────────────────────────────────────────────────────


def _llm_text(content: str, usage: dict | None = None) -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=[],
        usage=usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )


def _llm_tool(tool_calls: list[ToolCall], usage: dict | None = None) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=tool_calls,
        usage=usage or {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    )


# ── test class ────────────────────────────────────────────────────────


class TestKnowledgeAgent:
    """Comprehensive unit tests for KnowledgeAgent."""

    # 1 ── name property ──────────────────────────────────────────────

    def test_name_property(self, agent):
        assert agent.name == "knowledge"

    # 2 ── plain-text LLM response (no tool calls) ───────────────────

    @pytest.mark.asyncio
    async def test_text_response_no_tools(self, agent, mock_llm, context):
        mock_llm.complete = AsyncMock(
            return_value=_llm_text("This project uses a microservice architecture."),
        )

        result = await agent.run(context, question="What architecture is used?")

        assert isinstance(result, KnowledgeResult)
        assert result.status == "success"
        assert result.answer == "This project uses a microservice architecture."
        assert result.sources == []
        assert result.tool_call_log == []

    # 3 ── search_knowledge returns sources above threshold ───────────

    @pytest.mark.asyncio
    async def test_search_knowledge_returns_sources(
        self,
        agent,
        mock_llm,
        mock_vector_store,
        context,
    ):
        mock_vector_store.query = MagicMock(
            return_value=[
                {
                    "document": "PostgreSQL 15 is used.",
                    "metadata": {"source_path": "README.md", "doc_type": "markdown"},
                    "distance": 0.3,
                },
                {
                    "document": "DB migrations via Alembic.",
                    "metadata": {"source_path": "docs/migrations.md"},
                    "distance": 0.5,
                },
            ]
        )

        call_count = 0

        async def _complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _llm_tool(
                    [
                        ToolCall(
                            id="tc-1",
                            name="search_knowledge",
                            arguments={"query": "database", "max_results": 5},
                        ),
                    ]
                )
            return _llm_text("PostgreSQL 15 with Alembic migrations.")

        mock_llm.complete = AsyncMock(side_effect=_complete)

        result = await agent.run(context, question="What database?")

        assert result.status == "success"
        assert "PostgreSQL" in result.answer
        assert len(result.tool_call_log) == 1
        assert result.tool_call_log[0]["tool"] == "search_knowledge"
        assert "Found 2 relevant" in result.tool_call_log[0]["result_preview"]

    # 4 ── search_knowledge with no results ───────────────────────────

    @pytest.mark.asyncio
    async def test_search_knowledge_no_results(
        self,
        agent,
        mock_llm,
        mock_vector_store,
        context,
    ):
        mock_vector_store.query = MagicMock(return_value=[])

        call_count = 0

        async def _complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _llm_tool(
                    [
                        ToolCall(
                            id="tc-1", name="search_knowledge", arguments={"query": "missing topic"}
                        ),
                    ]
                )
            return _llm_text("I couldn't find relevant info.")

        mock_llm.complete = AsyncMock(side_effect=_complete)

        result = await agent.run(context, question="What about X?")

        assert result.status == "success"
        log_preview = result.tool_call_log[0]["result_preview"]
        assert "No relevant documents" in log_preview

    # 5 ── all results below relevance threshold ──────────────────────

    @pytest.mark.asyncio
    async def test_search_knowledge_below_threshold(
        self,
        agent,
        mock_llm,
        mock_vector_store,
        context,
    ):
        mock_vector_store.query = MagicMock(
            return_value=[
                {
                    "document": "Barely related content",
                    "metadata": {"source_path": "noise.txt"},
                    "distance": RAG_RELEVANCE_THRESHOLD + 0.5,
                },
            ]
        )

        call_count = 0

        async def _complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _llm_tool(
                    [
                        ToolCall(
                            id="tc-1", name="search_knowledge", arguments={"query": "irrelevant"}
                        ),
                    ]
                )
            return _llm_text("Nothing relevant found.")

        mock_llm.complete = AsyncMock(side_effect=_complete)

        result = await agent.run(context, question="Something?")

        log_preview = result.tool_call_log[0]["result_preview"]
        assert "No sufficiently relevant" in log_preview

    # 6 ── get_entity_info scope=list ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_entity_info_list(
        self,
        agent,
        mock_llm,
        context,
        sample_knowledge,
    ):
        call_count = 0

        async def _complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _llm_tool(
                    [
                        ToolCall(id="tc-1", name="get_entity_info", arguments={"scope": "list"}),
                    ]
                )
            return _llm_text("Here are the entities.")

        mock_llm.complete = AsyncMock(side_effect=_complete)

        with patch.object(
            agent, "_load_knowledge", new_callable=AsyncMock, return_value=sample_knowledge
        ):
            result = await agent.run(context, question="List entities")

        assert result.status == "success"
        log_preview = result.tool_call_log[0]["result_preview"]
        assert "User" in log_preview
        assert "users" in log_preview

    # 7 ── get_entity_info scope=detail ───────────────────────────────

    @pytest.mark.asyncio
    async def test_get_entity_info_detail(
        self,
        agent,
        mock_llm,
        context,
        sample_knowledge,
    ):
        call_count = 0

        async def _complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _llm_tool(
                    [
                        ToolCall(
                            id="tc-1",
                            name="get_entity_info",
                            arguments={"scope": "detail", "entity_name": "User"},
                        ),
                    ]
                )
            return _llm_text("User entity details.")

        mock_llm.complete = AsyncMock(side_effect=_complete)

        with patch.object(
            agent, "_load_knowledge", new_callable=AsyncMock, return_value=sample_knowledge
        ):
            result = await agent.run(context, question="Details on User")

        log_preview = result.tool_call_log[0]["result_preview"]
        assert "User" in log_preview
        assert "org_id" in log_preview
        assert "Integer" in log_preview

    # 8 ── get_entity_info scope=table_map ────────────────────────────

    @pytest.mark.asyncio
    async def test_get_entity_info_table_map(
        self,
        agent,
        mock_llm,
        context,
        sample_knowledge,
    ):
        call_count = 0

        async def _complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _llm_tool(
                    [
                        ToolCall(
                            id="tc-1", name="get_entity_info", arguments={"scope": "table_map"}
                        ),
                    ]
                )
            return _llm_text("Table map listed.")

        mock_llm.complete = AsyncMock(side_effect=_complete)

        with patch.object(
            agent, "_load_knowledge", new_callable=AsyncMock, return_value=sample_knowledge
        ):
            result = await agent.run(context, question="Show table map")

        log_preview = result.tool_call_log[0]["result_preview"]
        assert "users" in log_preview
        assert "active" in log_preview

    # 9 ── get_entity_info scope=enums ────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_entity_info_enums(
        self,
        agent,
        mock_llm,
        context,
        sample_knowledge,
    ):
        call_count = 0

        async def _complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _llm_tool(
                    [
                        ToolCall(id="tc-1", name="get_entity_info", arguments={"scope": "enums"}),
                    ]
                )
            return _llm_text("Enum definitions.")

        mock_llm.complete = AsyncMock(side_effect=_complete)

        with patch.object(
            agent, "_load_knowledge", new_callable=AsyncMock, return_value=sample_knowledge
        ):
            result = await agent.run(context, question="Show enums")

        log_preview = result.tool_call_log[0]["result_preview"]
        assert "StatusEnum" in log_preview
        assert "active" in log_preview
        assert "get_user" in log_preview

    # 10 ── unknown tool returns error text ───────────────────────────

    @pytest.mark.asyncio
    async def test_unknown_tool(self, agent, mock_llm, context):
        call_count = 0

        async def _complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _llm_tool(
                    [
                        ToolCall(id="tc-1", name="nonexistent_tool", arguments={}),
                    ]
                )
            return _llm_text("Acknowledged.")

        mock_llm.complete = AsyncMock(side_effect=_complete)

        result = await agent.run(context, question="Do something weird")

        assert result.tool_call_log[0]["tool"] == "nonexistent_tool"
        assert "unknown tool" in result.tool_call_log[0]["result_preview"].lower()

    # 11 ── max iterations stops the loop ─────────────────────────────

    @pytest.mark.asyncio
    async def test_max_iterations(self, agent, mock_llm, mock_vector_store, context):
        mock_vector_store.query = MagicMock(return_value=[])

        mock_llm.complete = AsyncMock(
            return_value=_llm_tool(
                [ToolCall(id="tc-loop", name="search_knowledge", arguments={"query": "loop"})],
            ),
        )

        result = await agent.run(context, question="infinite loop?")

        assert mock_llm.complete.call_count == KnowledgeAgent.MAX_ITERATIONS
        assert result.status == "no_result" or result.answer != ""

    # 12 ── token usage accumulated across iterations ─────────────────

    @pytest.mark.asyncio
    async def test_token_usage(self, agent, mock_llm, mock_vector_store, context):
        mock_vector_store.query = MagicMock(return_value=[])

        call_count = 0

        async def _complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _llm_tool(
                    [ToolCall(id="tc-1", name="search_knowledge", arguments={"query": "tokens"})],
                    usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                )
            return _llm_text(
                "Done.",
                usage={"prompt_tokens": 150, "completion_tokens": 30, "total_tokens": 180},
            )

        mock_llm.complete = AsyncMock(side_effect=_complete)

        result = await agent.run(context, question="count tokens")

        assert result.token_usage["prompt_tokens"] == 250
        assert result.token_usage["completion_tokens"] == 50
        assert result.token_usage["total_tokens"] == 300
