"""RET-R1: wire build_context_pack into orchestrator runtime.

Tests for ``ContextLoader.assemble_knowledge_block`` — the seam that
chooses pack-vs-legacy based on ``context_planner_enabled``:

* Flag ON  → calls ``build_context_pack`` + ``render_context_block``;
            returns provenance block.
* Flag OFF → falls through to legacy ``load_relevant_knowledge`` unchanged.
* Orchestrator's ``_run_unified_agent`` calls the seam (not the raw
  ``load_relevant_knowledge`` directly) when has_kb is True.
* Graceful degradation: if ``build_context_pack`` returns ``None`` (e.g. on
  failure) the seam falls back to ``load_relevant_knowledge`` automatically
  (vision invariant #5).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.context_loader import ContextLoader
from app.knowledge.context_pack import Artifact, ContextPack

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loader() -> ContextLoader:
    return ContextLoader(
        vector_store=MagicMock(),
        tracker=MagicMock(),
        mcp_cache={},
    )


def _make_pack_with_artifact() -> ContextPack:
    """A non-empty ContextPack with one rag_chunks artifact."""
    artifact = Artifact(
        id="a1",
        type="rag_chunk",
        title="README snippet",
        summary="some insight",
        confidence=0.9,
        provenance={"source": "docs/README.md", "commit_sha": "abc1234"},
        freshness={"indexed_at": "2026-06-01T00:00:00Z"},
    )
    pack = ContextPack(
        project_id="proj-1",
        connection_id="conn-1",
        question="test question",
        rag_chunks=[artifact],
    )
    return pack


# ---------------------------------------------------------------------------
# assemble_knowledge_block — flag OFF (legacy path)
# ---------------------------------------------------------------------------


class TestAssembleKnowledgeBlockLegacyPath:
    """When context_planner_enabled=False, uses load_relevant_knowledge."""

    async def test_flag_off_calls_legacy_not_pack(self):
        loader = _make_loader()
        legacy_result = "RELEVANT KNOWLEDGE (top documentation snippets):\n- [doc] some chunk"

        loader.load_relevant_knowledge = AsyncMock(return_value=legacy_result)
        loader.build_context_pack = AsyncMock()

        import app.config as _cfg

        with patch.object(_cfg.settings, "context_planner_enabled", False):
            result = await loader.assemble_knowledge_block(
                project_id="proj-1",
                connection_id="conn-1",
                question="how many rows?",
                has_connection=True,
                has_repo=False,
                estimated_queries=1,
                needs_multiple_data_sources=False,
            )

        loader.load_relevant_knowledge.assert_awaited_once_with("proj-1", "how many rows?")
        loader.build_context_pack.assert_not_called()
        assert result == legacy_result

    async def test_flag_off_returns_none_when_legacy_empty(self):
        loader = _make_loader()
        loader.load_relevant_knowledge = AsyncMock(return_value=None)
        loader.build_context_pack = AsyncMock()

        import app.config as _cfg

        with patch.object(_cfg.settings, "context_planner_enabled", False):
            result = await loader.assemble_knowledge_block(
                project_id="proj-1",
                connection_id=None,
                question="show users",
                has_connection=False,
                has_repo=False,
                estimated_queries=1,
                needs_multiple_data_sources=False,
            )

        assert result is None
        loader.build_context_pack.assert_not_called()


# ---------------------------------------------------------------------------
# assemble_knowledge_block — flag ON (pack path)
# ---------------------------------------------------------------------------


class TestAssembleKnowledgeBlockPackPath:
    """When context_planner_enabled=True, uses build_context_pack + render."""

    async def test_flag_on_calls_build_and_render(self):
        loader = _make_loader()
        pack = _make_pack_with_artifact()

        loader.build_context_pack = AsyncMock(return_value=pack)
        loader.load_relevant_knowledge = AsyncMock()

        import app.config as _cfg

        with patch.object(_cfg.settings, "context_planner_enabled", True):
            result = await loader.assemble_knowledge_block(
                project_id="proj-1",
                connection_id="conn-1",
                question="count orders by status",
                has_connection=True,
                has_repo=False,
                estimated_queries=2,
                needs_multiple_data_sources=False,
            )

        loader.build_context_pack.assert_awaited_once()
        loader.load_relevant_knowledge.assert_not_called()
        # result should be the rendered provenance block
        assert result is not None
        assert "RELEVANT KNOWLEDGE (traceable):" in result
        assert "docs/README.md" in result
        assert "abc1234" in result

    async def test_flag_on_pack_empty_falls_back_to_legacy(self):
        """Empty pack → graceful degradation to legacy (vision #5)."""
        loader = _make_loader()
        empty_pack = ContextPack(project_id="proj-1", question="q")
        assert empty_pack.is_empty()

        loader.build_context_pack = AsyncMock(return_value=empty_pack)
        legacy_result = "RELEVANT KNOWLEDGE:\n- [doc] chunk"
        loader.load_relevant_knowledge = AsyncMock(return_value=legacy_result)

        import app.config as _cfg

        with patch.object(_cfg.settings, "context_planner_enabled", True):
            result = await loader.assemble_knowledge_block(
                project_id="proj-1",
                connection_id=None,
                question="q",
                has_connection=False,
                has_repo=False,
                estimated_queries=1,
                needs_multiple_data_sources=False,
            )

        loader.load_relevant_knowledge.assert_awaited_once_with("proj-1", "q")
        assert result == legacy_result

    async def test_flag_on_pack_none_falls_back_to_legacy(self):
        """build_context_pack returns None (failure) → legacy (vision #5)."""
        loader = _make_loader()
        loader.build_context_pack = AsyncMock(return_value=None)
        legacy_result = "RELEVANT KNOWLEDGE:\n- [doc] chunk"
        loader.load_relevant_knowledge = AsyncMock(return_value=legacy_result)

        import app.config as _cfg

        with patch.object(_cfg.settings, "context_planner_enabled", True):
            result = await loader.assemble_knowledge_block(
                project_id="proj-1",
                connection_id=None,
                question="q",
                has_connection=False,
                has_repo=False,
                estimated_queries=1,
                needs_multiple_data_sources=False,
            )

        loader.load_relevant_knowledge.assert_awaited_once_with("proj-1", "q")
        assert result == legacy_result

    async def test_flag_on_passes_correct_args_to_build(self):
        """Keyword args are forwarded correctly to build_context_pack."""
        loader = _make_loader()
        pack = _make_pack_with_artifact()
        loader.build_context_pack = AsyncMock(return_value=pack)
        loader.load_relevant_knowledge = AsyncMock()

        import app.config as _cfg

        with patch.object(_cfg.settings, "context_planner_enabled", True):
            await loader.assemble_knowledge_block(
                project_id="proj-42",
                connection_id="conn-99",
                question="find anomalies",
                has_connection=True,
                has_repo=True,
                estimated_queries=3,
                needs_multiple_data_sources=True,
            )

        call_kwargs = loader.build_context_pack.call_args.kwargs
        assert call_kwargs["project_id"] == "proj-42"
        assert call_kwargs["connection_id"] == "conn-99"
        assert call_kwargs["question"] == "find anomalies"
        assert call_kwargs["has_connection"] is True
        assert call_kwargs["has_repo"] is True
        assert call_kwargs["estimated_queries"] == 3
        assert call_kwargs["needs_multiple_data_sources"] is True


# ---------------------------------------------------------------------------
# Orchestrator uses assemble_knowledge_block as its knowledge seam
# ---------------------------------------------------------------------------


class TestOrchestratorUsesAssembleSeam:
    """_run_unified_agent must call assemble_knowledge_block (not the raw
    load_relevant_knowledge) when has_kb is True."""

    def _make_orchestrator(self):
        from app.agents.orchestrator import OrchestratorAgent
        from app.core.workflow_tracker import WorkflowTracker
        from app.knowledge.vector_store import VectorStore
        from app.llm.base import LLMResponse
        from app.llm.router import LLMRouter

        tracker = MagicMock(spec=WorkflowTracker)
        tracker.emit = AsyncMock()
        llm_router = MagicMock(spec=LLMRouter)
        llm_router.complete = AsyncMock(
            return_value=LLMResponse(
                content="final answer", tool_calls=[], finish_reason="end_turn"
            )
        )
        vector_store = MagicMock(spec=VectorStore)
        agent = OrchestratorAgent(
            llm_router=llm_router,
            workflow_tracker=tracker,
            vector_store=vector_store,
        )
        return agent

    def _make_context(self):
        from app.agents.base import AgentContext
        from app.connectors.base import ConnectionConfig
        from app.llm.router import LLMRouter

        return AgentContext(
            user_question="how many orders?",
            project_id="proj-1",
            connection_config=ConnectionConfig(
                connection_id="conn-1",
                db_type="postgres",
                db_host="localhost",
                db_name="db",
                db_user="u",
                db_password="p",
                db_port=5432,
            ),
            chat_history=[],
            llm_router=MagicMock(spec=LLMRouter),
            tracker=MagicMock(),
            workflow_id="wf-1",
        )

    def _make_route_result(self):
        from app.agents.router import RouteResult

        return RouteResult(
            route="unified",
            complexity="simple",
            approach="direct",
            estimated_queries=1,
            needs_multiple_data_sources=False,
        )

    async def test_orchestrator_calls_assemble_knowledge_block_when_has_kb(self):
        agent = self._make_orchestrator()
        context = self._make_context()
        route_result = self._make_route_result()
        knowledge_block = (
            "RELEVANT KNOWLEDGE (traceable):\n"
            "- [docs/README.md @ abc1234 · — · conf=0.90] some insight"
        )

        # Patch at the loader level so we confirm the seam is used
        agent._ctx_loader.load_project_overview = AsyncMock(return_value=None)
        agent._ctx_loader.load_recent_learnings = AsyncMock(return_value=None)
        agent._ctx_loader.load_relevant_insights = AsyncMock(return_value=None)
        agent._ctx_loader.assemble_knowledge_block = AsyncMock(return_value=knowledge_block)
        agent._ctx_loader.load_relevant_knowledge = AsyncMock(return_value="OLD LEGACY BLOCK")
        agent._ctx_loader.has_mcp_sources = AsyncMock(return_value=False)
        agent._ctx_loader.check_staleness = AsyncMock(return_value=None)
        agent._ctx_loader.build_table_map = AsyncMock(return_value="")

        # Patch the tool loop so we don't need an LLM
        from app.agents.orchestrator import AgentResponse

        agent._run_tool_loop = AsyncMock(return_value=AgentResponse(answer="done"))
        agent._load_table_map = AsyncMock(return_value="")
        agent._load_custom_rules_text = AsyncMock(return_value="")

        await agent._run_unified_agent(
            context,
            wf_id="wf-1",
            has_connection=True,
            db_type="postgres",
            has_kb=True,
            has_mcp=False,
            has_repo=False,
            route_result=route_result,
        )

        # assemble_knowledge_block MUST have been called
        agent._ctx_loader.assemble_knowledge_block.assert_awaited_once()
        # The raw load_relevant_knowledge must NOT be called directly by orchestrator
        agent._ctx_loader.load_relevant_knowledge.assert_not_called()
