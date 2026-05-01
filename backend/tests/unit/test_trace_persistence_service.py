"""Unit tests for TracePersistenceService — span classification, filtering, and enrichment."""

import json

import pytest

from app.core.workflow_tracker import WorkflowEvent, WorkflowTracker
from app.services.trace_persistence_service import (
    TracePersistenceService,
    _truncate,
    _WorkflowBuffer,
    classify_span_type,
)


class TestClassifySpanType:
    def test_orchestrator_llm_call(self):
        assert classify_span_type("orchestrator:llm_call") == "llm_call"

    def test_orchestrator_planning(self):
        assert classify_span_type("orchestrator:planning") == "tool_call"

    def test_orchestrator_sql_agent(self):
        assert classify_span_type("orchestrator:sql_agent") == "sub_agent"

    def test_orchestrator_knowledge_agent(self):
        assert classify_span_type("orchestrator:knowledge_agent") == "sub_agent"

    def test_orchestrator_mcp_source_agent(self):
        assert classify_span_type("orchestrator:mcp_source_agent") == "sub_agent"

    def test_orchestrator_manage_rules(self):
        assert classify_span_type("orchestrator:manage_rules") == "tool_call"

    def test_orchestrator_viz(self):
        assert classify_span_type("orchestrator:viz") == "viz"

    def test_sql_llm_call(self):
        assert classify_span_type("sql:llm_call") == "llm_call"

    def test_sql_tool_execute_query(self):
        assert classify_span_type("sql:tool:execute_query") == "db_query"

    def test_sql_tool_get_schema_info(self):
        assert classify_span_type("sql:tool:get_schema_info") == "db_query"

    def test_sql_tool_get_db_index(self):
        assert classify_span_type("sql:tool:get_db_index") == "rag"

    def test_knowledge_llm_call(self):
        assert classify_span_type("knowledge:llm_call") == "llm_call"

    def test_knowledge_tool_search(self):
        assert classify_span_type("knowledge:tool:search_knowledge") == "rag"

    def test_execute_query(self):
        assert classify_span_type("execute_query") == "db_query"

    def test_safety_check(self):
        assert classify_span_type("safety_check") == "validation"

    def test_pre_validate(self):
        assert classify_span_type("pre_validate") == "validation"

    def test_post_validate(self):
        assert classify_span_type("post_validate") == "validation"

    def test_render_viz(self):
        assert classify_span_type("render_viz") == "viz"

    def test_rag_context(self):
        assert classify_span_type("rag_context") == "rag"

    def test_build_query(self):
        assert classify_span_type("build_query") == "tool_call"

    def test_sql_agent_prefix(self):
        assert classify_span_type("sql_agent:generate") == "sub_agent"

    def test_knowledge_agent_prefix(self):
        assert classify_span_type("knowledge_agent:search") == "sub_agent"

    def test_viz_agent_prefix(self):
        assert classify_span_type("viz_agent:pick") == "sub_agent"

    def test_mcp_source_agent_prefix(self):
        assert classify_span_type("mcp_source_agent:fetch") == "sub_agent"

    def test_unknown_step_with_llm_keyword(self):
        assert classify_span_type("some_llm_step") == "llm_call"

    def test_unknown_step_with_query_keyword(self):
        assert classify_span_type("run_query_thing") == "db_query"

    def test_generate_title_llm_call(self):
        assert classify_span_type("generate_title:llm_call") == "llm_call"

    def test_explain_sql_llm_call(self):
        assert classify_span_type("explain_sql:llm_call") == "llm_call"

    def test_summarize_llm_call(self):
        assert classify_span_type("summarize:llm_call") == "llm_call"

    def test_completely_unknown(self):
        assert classify_span_type("something_random") == "tool_call"

    def test_explicit_span_type_takes_precedence(self):
        """T14: explicit span_type from producer overrides the heuristic."""
        assert classify_span_type("something_random", "llm_call") == "llm_call"
        assert classify_span_type("execute_query", "validation") == "validation"

    def test_explicit_invalid_span_type_falls_back(self):
        """An unrecognised explicit value must fall back to the heuristic."""
        assert classify_span_type("orchestrator:viz", "bogus") == "viz"


class TestTruncate:
    def test_none(self):
        assert _truncate(None) is None

    def test_short_string(self):
        assert _truncate("hello") == "hello"

    def test_exact_max(self):
        s = "a" * 1000
        assert _truncate(s) == s

    def test_over_max(self):
        s = "a" * 1500
        assert len(_truncate(s)) == 1000

    def test_custom_max(self):
        assert _truncate("abcdef", 3) == "abc"


class TestWorkflowBuffer:
    def test_init(self):
        buf = _WorkflowBuffer("wf-1", "agent", {"question": "test"})
        assert buf.workflow_id == "wf-1"
        assert buf.pipeline == "agent"
        assert buf.events == []
        assert buf.context == {"question": "test"}


class TestBuildSpansFromToolLog:
    def test_empty_log(self):
        svc = TracePersistenceService.__new__(TracePersistenceService)
        assert svc._build_spans_from_tool_log([]) == []

    def test_single_tool_call_with_args(self):
        svc = TracePersistenceService.__new__(TracePersistenceService)
        spans = svc._build_spans_from_tool_log(
            [
                {
                    "tool": "execute_query",
                    "args": {"sql": "SELECT 1"},
                    "result": "OK",
                    "elapsed_ms": 42.5,
                }
            ]
        )
        assert len(spans) == 1
        assert spans[0]["span_type"] == "db_query"
        assert spans[0]["name"] == "execute_query"
        assert spans[0]["status"] == "completed"
        assert spans[0]["duration_ms"] == 42.5
        assert spans[0]["input_preview"] is not None
        assert spans[0]["output_preview"] == "OK"

    def test_single_tool_call_with_arguments_key(self):
        """Verify the key mismatch fix: 'arguments' and 'result_preview' keys work."""
        svc = TracePersistenceService.__new__(TracePersistenceService)
        spans = svc._build_spans_from_tool_log(
            [
                {
                    "tool": "search_codebase",
                    "arguments": {"query": "auth"},
                    "result_preview": "Found 3 results",
                    "elapsed_ms": 100,
                }
            ]
        )
        assert len(spans) == 1
        assert '"query"' in spans[0]["input_preview"]
        assert "auth" in spans[0]["input_preview"]
        assert spans[0]["output_preview"] == "Found 3 results"

    def test_failed_tool_call(self):
        svc = TracePersistenceService.__new__(TracePersistenceService)
        spans = svc._build_spans_from_tool_log([{"tool": "execute_query", "error": "syntax error"}])
        assert spans[0]["status"] == "failed"
        assert "syntax error" in spans[0]["detail"]


class TestNoiseFiltering:
    """Verify that _SKIP_STEPS and duplicate execute_query filtering work."""

    def test_skip_steps_constant(self):
        skip = TracePersistenceService._SKIP_STEPS
        assert "token" in skip
        assert "thinking" in skip
        assert "orchestrator:warning" in skip
        assert "orchestrator:llm_retry" in skip
        assert "pipeline_start" in skip
        assert "pipeline_end" in skip

    def test_regular_step_not_skipped(self):
        skip = TracePersistenceService._SKIP_STEPS
        assert "orchestrator:llm_call" not in skip
        assert "execute_query" not in skip
        assert "sql:llm_call" not in skip


class TestTokenUsageExtraction:
    def test_extracts_usage(self):
        extra = {
            "model": "gpt-4o",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
        result = TracePersistenceService._extract_token_usage(extra)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["model"] == "gpt-4o"
        assert parsed["prompt_tokens"] == 100
        assert parsed["total_tokens"] == 150

    def test_returns_none_when_no_keys(self):
        assert TracePersistenceService._extract_token_usage({}) is None
        assert TracePersistenceService._extract_token_usage({"foo": "bar"}) is None

    def test_partial_keys(self):
        result = TracePersistenceService._extract_token_usage({"model": "claude-3"})
        assert result is not None
        parsed = json.loads(result)
        assert parsed["model"] == "claude-3"
        assert "prompt_tokens" not in parsed


class TestExtraToMetadata:
    def test_excludes_dedicated_columns(self):
        extra = {
            "input_preview": "hello",
            "output_preview": "world",
            "model": "gpt-4",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "some_other_key": "value",
        }
        result = TracePersistenceService._extra_to_metadata(extra)
        assert result is not None
        parsed = json.loads(result)
        assert "input_preview" not in parsed
        assert "output_preview" not in parsed
        assert "model" not in parsed
        assert "prompt_tokens" not in parsed
        assert parsed["some_other_key"] == "value"

    def test_returns_none_when_empty_after_exclusion(self):
        extra = {"input_preview": "hello", "output_preview": "world"}
        assert TracePersistenceService._extra_to_metadata(extra) is None


class TestPersistenceHookRegistration:
    @pytest.mark.asyncio
    async def test_hook_is_called(self):
        tracker = WorkflowTracker()
        svc = TracePersistenceService(tracker)

        received = []

        async def capture_event(event):
            received.append(event)

        svc._on_event = capture_event
        tracker.add_persistence_hook(svc._on_event)

        wf_id = await tracker.begin("agent", {"question": "test"})
        await tracker.end(wf_id, "agent")

        assert len(received) >= 2
        assert received[0].step == "pipeline_start"
        assert received[-1].step == "pipeline_end"


class TestStepDataPropagation:
    """Verify WorkflowTracker.step() propagates step_data as extra on completion."""

    @pytest.mark.asyncio
    async def test_step_data_in_completed_event(self):
        tracker = WorkflowTracker()
        received: list[WorkflowEvent] = []

        async def capture(event):
            received.append(event)

        tracker.add_persistence_hook(capture)

        wf_id = await tracker.begin("agent", {})
        sd = {"input_preview": "SELECT 1", "output_preview": "1 row"}
        async with tracker.step(wf_id, "execute_query", "test", step_data=sd):
            sd["extra_key"] = "added_inside"
        await tracker.end(wf_id, "agent")

        completed = [e for e in received if e.step == "execute_query" and e.status == "completed"]
        assert len(completed) == 1
        assert completed[0].extra["input_preview"] == "SELECT 1"
        assert completed[0].extra["output_preview"] == "1 row"
        assert completed[0].extra["extra_key"] == "added_inside"

    @pytest.mark.asyncio
    async def test_step_data_in_failed_event(self):
        tracker = WorkflowTracker()
        received: list[WorkflowEvent] = []

        async def capture(event):
            received.append(event)

        tracker.add_persistence_hook(capture)

        wf_id = await tracker.begin("agent", {})
        sd = {"input_preview": "bad query"}
        with pytest.raises(ValueError):
            async with tracker.step(wf_id, "execute_query", "test", step_data=sd):
                raise ValueError("oops")
        await tracker.end(wf_id, "agent")

        failed = [e for e in received if e.step == "execute_query" and e.status == "failed"]
        assert len(failed) == 1
        assert failed[0].extra["input_preview"] == "bad query"

    @pytest.mark.asyncio
    async def test_step_without_step_data(self):
        tracker = WorkflowTracker()
        received: list[WorkflowEvent] = []

        async def capture(event):
            received.append(event)

        tracker.add_persistence_hook(capture)

        wf_id = await tracker.begin("agent", {})
        async with tracker.step(wf_id, "some_step", "no data"):
            pass
        await tracker.end(wf_id, "agent")

        completed = [e for e in received if e.step == "some_step" and e.status == "completed"]
        assert len(completed) == 1
        assert completed[0].extra == {}


class TestMCPToolsUseSingletonTracker:
    """Verify that MCP tools import the singleton tracker, not a new instance."""

    def test_import_singleton(self):
        from app.mcp_server import tools as mcp_tools

        assert hasattr(mcp_tools, "_singleton_tracker")
        assert mcp_tools._singleton_tracker is not None
        from app.core.workflow_tracker import tracker as global_tracker

        assert mcp_tools._singleton_tracker is global_tracker

    def test_no_local_workflow_tracker_class_usage(self):
        import inspect

        from app.mcp_server import tools as mcp_tools

        source = inspect.getsource(mcp_tools)
        assert "WorkflowTracker()" not in source


class TestPersistWorkflowWithEmptyIds:
    """Verify _persist_workflow skips INSERT when project_id is empty to avoid FK violation.

    finalize_trace will later CREATE the row with real IDs via its else branch.
    """

    @pytest.mark.asyncio
    async def test_returns_early_when_project_id_empty(self):
        """Empty project_id causes FK violation — skip persist, let finalize_trace handle it."""
        import inspect

        from app.services import trace_persistence_service as tps_mod

        source = inspect.getsource(tps_mod.TracePersistenceService._persist_workflow)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "not project_id or not user_id" in line:
                remaining = "\n".join(lines[i : i + 12])
                assert "return" in remaining, "_persist_workflow should return early on empty IDs"
                break
        else:
            pytest.fail("Expected empty-id guard not found in _persist_workflow")


class TestBatchServiceProjectIdInContext:
    """Verify batch_service passes project_id in tracker.begin() context."""

    def test_tracker_begin_includes_project_id(self):
        import inspect

        from app.services import batch_service

        source = inspect.getsource(batch_service.BatchService.execute_batch)
        assert '"project_id"' in source or "'project_id'" in source


class TestDataValidationSingletonTracker:
    """Verify data_validation uses singleton tracker."""

    def test_no_local_workflow_tracker_instantiation(self):
        import inspect

        from app.api.routes import data_investigations

        source = inspect.getsource(data_investigations._run_investigation_background)
        assert "WorkflowTracker()" not in source
        assert "singleton_tracker" in source


class TestTrackerHasEnded:
    """Verify WorkflowTracker.has_ended() tracks completed workflows."""

    @pytest.mark.asyncio
    async def test_has_ended_false_before_end(self):
        tracker = WorkflowTracker()
        wf_id = await tracker.begin("agent", {})
        assert not tracker.has_ended(wf_id)

    @pytest.mark.asyncio
    async def test_has_ended_true_after_end(self):
        tracker = WorkflowTracker()
        wf_id = await tracker.begin("agent", {})
        await tracker.end(wf_id, "agent")
        assert tracker.has_ended(wf_id)

    @pytest.mark.asyncio
    async def test_has_ended_unknown_id(self):
        tracker = WorkflowTracker()
        assert not tracker.has_ended("nonexistent-id")


class TestAgentSafetyNet:
    """Verify ConversationalAgent.run() always emits pipeline_end."""

    @pytest.mark.asyncio
    async def test_pipeline_end_on_orchestrator_success(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.agents.orchestrator import AgentResponse
        from app.core.agent import ConversationalAgent

        tracker = WorkflowTracker()
        received: list[WorkflowEvent] = []

        async def capture(event):
            received.append(event)

        tracker.add_persistence_hook(capture)

        agent = ConversationalAgent(workflow_tracker=tracker)

        mock_resp = AgentResponse(
            answer="test",
            workflow_id="will-be-overwritten",
        )

        with patch.object(agent._orchestrator, "run", new=AsyncMock(return_value=mock_resp)):
            with patch.object(agent._orchestrator, "_llm", MagicMock()):
                await agent.run(
                    question="test",
                    project_id="p1",
                    user_id="u1",
                )

        ends = [e for e in received if e.step == "pipeline_end"]
        assert len(ends) >= 1

    @pytest.mark.asyncio
    async def test_pipeline_end_on_orchestrator_exception(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.core.agent import ConversationalAgent

        tracker = WorkflowTracker()
        received: list[WorkflowEvent] = []

        async def capture(event):
            received.append(event)

        tracker.add_persistence_hook(capture)

        agent = ConversationalAgent(workflow_tracker=tracker)

        with patch.object(
            agent._orchestrator,
            "run",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            with patch.object(agent._orchestrator, "_llm", MagicMock()):
                with pytest.raises(RuntimeError, match="boom"):
                    await agent.run(
                        question="test",
                        project_id="p1",
                        user_id="u1",
                    )

        ends = [e for e in received if e.step == "pipeline_end"]
        assert len(ends) >= 1
        assert ends[0].status == "failed"
        assert "boom" in ends[0].detail


class TestStaleBufferPersistence:
    """Verify _cleanup_stale_buffers persists stale buffers instead of discarding."""

    def test_cleanup_does_not_discard(self):
        import inspect

        from app.services import trace_persistence_service as tps_mod

        source = inspect.getsource(tps_mod.TracePersistenceService._cleanup_stale_buffers)
        assert "_persist_workflow" in source
        assert "Stale: pipeline_end never received" in source
