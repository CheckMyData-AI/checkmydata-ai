"""ORCH-T01: step budget is a live termination signal.

Verifies that with ``max_orchestrator_iterations=20`` (W0 default):
  - a loop that never self-terminates (LLM always returns a tool call)
    stops at exactly ``max_iter`` iterations and sets ``steps_total == 20``.
  - ``step_pct`` drives the EMERGENCY synthesis message near the cap
    (``agent_emergency_synthesis_pct=0.90``).

These tests use the same fixture conventions as ``test_orchestrator_audit_fixes.py``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import AgentContext
from app.agents.orchestrator import OrchestratorAgent
from app.agents.tools.orchestrator_tools import get_orchestrator_tools
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import LLMResponse, ToolCall

# ---------------------------------------------------------------------------
# Shared doubles (same shape as test_orchestrator_audit_fixes.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_tracker():
    t = MagicMock(spec=WorkflowTracker)
    t.begin = AsyncMock(return_value="wf-1")
    t.end = AsyncMock()
    t.emit = AsyncMock()
    t.has_ended = MagicMock(return_value=False)

    @asynccontextmanager
    async def fake_step(wf_id: str, step: str, detail: str = "", **kwargs: Any):
        yield

    t.step = MagicMock(side_effect=fake_step)
    return t


@pytest.fixture
def mock_llm():
    router = MagicMock()
    router.complete = AsyncMock()
    router.get_context_window = MagicMock(return_value=128_000)
    return router


@pytest.fixture
def mock_vs():
    vs = MagicMock()
    collection = MagicMock()
    collection.count = MagicMock(return_value=0)
    vs.get_or_create_collection = MagicMock(return_value=collection)
    return vs


@pytest.fixture
def orch(mock_llm, mock_vs, mock_tracker):
    return OrchestratorAgent(
        llm_router=mock_llm,
        vector_store=mock_vs,
        workflow_tracker=mock_tracker,
    )


@pytest.fixture
def base_context(mock_llm, mock_tracker):
    return AgentContext(
        project_id="test-proj",
        connection_config=None,
        user_question="How many rows in orders?",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-1",
        project_name="TestProject",
    )


# ---------------------------------------------------------------------------
# Helper: a ToolCall-returning LLMResponse so the loop never self-terminates
# ---------------------------------------------------------------------------

_TOOL_CALL_RESP = LLMResponse(
    content="",
    tool_calls=[ToolCall(id="c1", name="search_codebase", arguments={"question": "q"})],
)

_NO_TOOL_RESP = LLMResponse(content="Final answer.", tool_calls=[])


# ---------------------------------------------------------------------------
# Test 1: loop terminates at step cap
# ---------------------------------------------------------------------------


class TestLoopTerminatesAtStepCap:
    """LLM always returns a tool call → step budget forces termination at max_iter."""

    async def test_loop_terminates_at_step_cap(
        self,
        orch: OrchestratorAgent,
        base_context: AgentContext,
    ) -> None:
        tools = get_orchestrator_tools(has_knowledge_base=True)

        # Every LLM call returns a tool call so the loop never self-terminates.
        llm_call_mock = AsyncMock(return_value=_TOOL_CALL_RESP)
        with (
            patch.object(orch, "_llm_call_with_retry", new=llm_call_mock),
            patch.object(orch._dispatcher, "dispatch", new=AsyncMock(return_value=("ok", None))),
            patch.object(orch, "_stream_tokens", new=AsyncMock()),
            patch.object(orch, "_validate_partial_answer", new=AsyncMock(return_value=False)),
            patch("app.agents.orchestrator.settings") as mock_settings,
        ):
            # Wire settings: low cap, wall-clock never trips.
            mock_settings.max_orchestrator_iterations = 20
            mock_settings.agent_wall_clock_timeout_seconds = 10_000
            mock_settings.agent_emergency_synthesis_pct = 0.90
            mock_settings.orchestrator_final_synthesis = False
            mock_settings.max_context_tokens = 100_000
            mock_settings.tool_result_insert_max_chars = 10_000
            mock_settings.history_tail_messages = 10
            mock_settings.orchestrator_result_gate_enabled = False
            mock_settings.answer_validator_enabled = False
            mock_settings.answer_validator_fail_closed = False
            mock_settings.answer_validator_min_chars = 10
            mock_settings.orchestrator_pipeline_table_threshold = 5
            mock_settings.orchestrator_max_result_corrections = 3
            mock_settings.query_empty_result_retry = False
            mock_settings.max_pipeline_replans = 2
            mock_settings.custom_rules_dir = ""
            mock_settings.history_summary_model = None
            mock_settings.max_history_tokens = 4_000
            mock_settings.viz_timeout_seconds = 30
            mock_settings.max_parallel_tool_calls = 3

            resp = await orch._run_tool_loop(
                base_context,
                "wf-1",
                has_connection=False,
                db_type=None,
                has_kb=True,
                has_mcp=False,
                has_repo=False,
                table_map="",
                project_overview="",
                recent_learnings="",
                tools=tools,
            )

        assert resp.steps_total == 20, (
            f"steps_total should equal max_iter=20, got {resp.steps_total}"
        )
        assert resp.steps_used <= 20, f"steps_used should not exceed cap, got {resp.steps_used}"
        assert resp.response_type in {
            "step_limit_reached",
            "knowledge",
            "text",
            "error",
        }, f"unexpected response_type: {resp.response_type!r}"

        # LLM was called at most max_iter times (no synthesis call because
        # orchestrator_final_synthesis=False).
        assert llm_call_mock.await_count <= 21, (
            f"Expected ≤21 LLM calls (max_iter + possible synthesis), "
            f"got {llm_call_mock.await_count}"
        )


# ---------------------------------------------------------------------------
# Test 2: step_pct drives EMERGENCY synthesis near the cap
# ---------------------------------------------------------------------------


class TestStepPctDrivesEmergencySynthesisNearCap:
    """With max_iter=4 and emergency_pct=0.90, iteration 4 has step_pct=1.0 ≥ 0.90
    so the EMERGENCY system message must be injected before the final LLM call.
    """

    async def test_step_pct_drives_emergency_synthesis_near_cap(
        self,
        orch: OrchestratorAgent,
        base_context: AgentContext,
    ) -> None:
        tools = get_orchestrator_tools(has_knowledge_base=True)

        # Capture messages from every LLM call so we can inspect the last one.
        captured_messages: list[list] = []

        async def _recording_llm(**kwargs: Any) -> LLMResponse:
            msgs = kwargs.get("messages", [])
            captured_messages.append(list(msgs))
            # After 4 iterations the loop should have already injected EMERGENCY
            # and stop; return a plain text response to let it exit cleanly.
            if len(captured_messages) >= 4:
                return _NO_TOOL_RESP
            return _TOOL_CALL_RESP

        with (
            patch.object(orch, "_llm_call_with_retry", new=AsyncMock(side_effect=_recording_llm)),
            patch.object(orch._dispatcher, "dispatch", new=AsyncMock(return_value=("ok", None))),
            patch.object(orch, "_stream_tokens", new=AsyncMock()),
            patch.object(orch, "_validate_partial_answer", new=AsyncMock(return_value=True)),
            patch("app.agents.orchestrator.settings") as mock_settings,
        ):
            mock_settings.max_orchestrator_iterations = 4
            mock_settings.agent_wall_clock_timeout_seconds = 10_000
            mock_settings.agent_emergency_synthesis_pct = 0.90
            mock_settings.orchestrator_final_synthesis = False
            mock_settings.max_context_tokens = 100_000
            mock_settings.tool_result_insert_max_chars = 10_000
            mock_settings.history_tail_messages = 10
            mock_settings.orchestrator_result_gate_enabled = False
            mock_settings.answer_validator_enabled = False
            mock_settings.answer_validator_fail_closed = False
            mock_settings.answer_validator_min_chars = 10
            mock_settings.orchestrator_pipeline_table_threshold = 5
            mock_settings.orchestrator_max_result_corrections = 3
            mock_settings.query_empty_result_retry = False
            mock_settings.max_pipeline_replans = 2
            mock_settings.custom_rules_dir = ""
            mock_settings.history_summary_model = None
            mock_settings.max_history_tokens = 4_000
            mock_settings.viz_timeout_seconds = 30
            mock_settings.max_parallel_tool_calls = 3

            resp = await orch._run_tool_loop(
                base_context,
                "wf-1",
                has_connection=False,
                db_type=None,
                has_kb=True,
                has_mcp=False,
                has_repo=False,
                table_map="",
                project_overview="",
                recent_learnings="",
                tools=tools,
            )

        assert resp.steps_total == 4, f"steps_total should be 4, got {resp.steps_total}"

        # The EMERGENCY message must appear in the messages of at least one LLM call.
        # At iteration index 3 (4th step), step_pct = 4/4 = 1.0 ≥ 0.90.
        all_system_contents = [
            m.content
            for calls_msgs in captured_messages
            for m in calls_msgs
            if hasattr(m, "role") and m.role == "system"
        ]
        emergency_found = any((c or "").startswith("EMERGENCY:") for c in all_system_contents)
        assert emergency_found, (
            "Expected an EMERGENCY: system message injected when step_pct ≥ 0.90 "
            f"at max_iter=4. System messages seen: {all_system_contents}"
        )
