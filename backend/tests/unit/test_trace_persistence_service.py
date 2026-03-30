"""Unit tests for TracePersistenceService — span classification and buffer logic."""

import pytest

from app.services.trace_persistence_service import (
    TracePersistenceService,
    _WorkflowBuffer,
    classify_span_type,
    _truncate,
)
from app.core.workflow_tracker import WorkflowEvent, WorkflowTracker


class TestClassifySpanType:
    def test_orchestrator_llm_call(self):
        assert classify_span_type("orchestrator:llm_call") == "llm_call"

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

    def test_completely_unknown(self):
        assert classify_span_type("something_random") == "tool_call"


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

    def test_single_tool_call(self):
        svc = TracePersistenceService.__new__(TracePersistenceService)
        spans = svc._build_spans_from_tool_log([
            {
                "tool": "execute_query",
                "args": {"sql": "SELECT 1"},
                "result": "OK",
                "elapsed_ms": 42.5,
            }
        ])
        assert len(spans) == 1
        assert spans[0]["span_type"] == "db_query"
        assert spans[0]["name"] == "execute_query"
        assert spans[0]["status"] == "completed"
        assert spans[0]["duration_ms"] == 42.5

    def test_failed_tool_call(self):
        svc = TracePersistenceService.__new__(TracePersistenceService)
        spans = svc._build_spans_from_tool_log([
            {"tool": "execute_query", "error": "syntax error"}
        ])
        assert spans[0]["status"] == "failed"
        assert "syntax error" in spans[0]["detail"]


class TestPersistenceHookRegistration:
    @pytest.mark.asyncio
    async def test_hook_is_called(self):
        tracker = WorkflowTracker()
        svc = TracePersistenceService(tracker)

        received = []
        original_on_event = svc._on_event

        async def capture_event(event):
            received.append(event)

        svc._on_event = capture_event
        tracker.add_persistence_hook(svc._on_event)

        wf_id = await tracker.begin("agent", {"question": "test"})
        await tracker.end(wf_id, "agent")

        assert len(received) >= 2
        assert received[0].step == "pipeline_start"
        assert received[-1].step == "pipeline_end"
