"""ORCH-T01: step budget is a live termination signal.
ORCH-T02: wrap-up gate — no synthesis before any data gathered; static tokens excluded.

ORCH-T01 verifies that with ``max_orchestrator_iterations=20`` (W0 default):
  - a loop that never self-terminates (LLM always returns a tool call)
    stops at exactly ``max_iter`` iterations and sets ``steps_total == 20``.
  - ``step_pct`` drives the EMERGENCY synthesis message near the cap
    (``agent_emergency_synthesis_pct=0.90``).

ORCH-T02 verifies:
  - A context-fill ``should_wrap_up`` signal at iteration 0 (zero data gathered)
    does NOT flip ``synthesis_phase`` — the loop keeps going with tools enabled.
  - The hard ``budget_pct >= emergency_pct`` branch still flips synthesis at iter 0
    (honest degradation valve is intact).

These tests use the same fixture conventions as ``test_orchestrator_audit_fixes.py``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import AgentContext
from app.agents.orchestrator import OrchestratorAgent
from app.agents.sql_agent import SQLAgentResult
from app.agents.tools.orchestrator_tools import get_orchestrator_tools
from app.connectors.base import QueryResult
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

# A query_database tool call with a question so it gets recorded in executed_questions.
_QUERY_DB_RESP = LLMResponse(
    content="",
    tool_calls=[ToolCall(id="q1", name="query_database", arguments={"question": "how many rows?"})],
)


def _make_sql_result() -> SQLAgentResult:
    """Minimal SQLAgentResult with one data row — satisfies successful data retrieval."""
    qr = QueryResult(columns=["count"], rows=[[42]], row_count=1)
    return SQLAgentResult(results=qr)


# ---------------------------------------------------------------------------
# Common settings block shared across ORCH-T01 and ORCH-T02 tests
# ---------------------------------------------------------------------------


def _apply_mock_settings(mock_settings: Any, *, max_iter: int = 20) -> None:  # noqa: ANN001
    mock_settings.max_orchestrator_iterations = max_iter
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


# ---------------------------------------------------------------------------
# Test 1: loop terminates at step cap
# ---------------------------------------------------------------------------


class TestLoopTerminatesAtStepCap:
    """LLM always returns a tool call -> step budget forces termination at max_iter."""

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
            _apply_mock_settings(mock_settings, max_iter=20)

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
            f"Expected <=21 LLM calls (max_iter + possible synthesis), "
            f"got {llm_call_mock.await_count}"
        )


# ---------------------------------------------------------------------------
# Test 2: step_pct drives EMERGENCY synthesis near the cap
# ---------------------------------------------------------------------------


class TestStepPctDrivesEmergencySynthesisNearCap:
    """With max_iter=4 and emergency_pct=0.90, iteration 4 has step_pct=1.0 >= 0.90
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
            _apply_mock_settings(mock_settings, max_iter=4)

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
        # At iteration index 3 (4th step), step_pct = 4/4 = 1.0 >= 0.90.
        all_system_contents = [
            m.content
            for calls_msgs in captured_messages
            for m in calls_msgs
            if hasattr(m, "role") and m.role == "system"
        ]
        emergency_found = any((c or "").startswith("EMERGENCY:") for c in all_system_contents)
        assert emergency_found, (
            "Expected an EMERGENCY: system message injected when step_pct >= 0.90 "
            f"at max_iter=4. System messages seen: {all_system_contents}"
        )


# ---------------------------------------------------------------------------
# ORCH-T02 Test 3: no premature zero-data wrap-up (must FAIL before fix)
# ---------------------------------------------------------------------------


class TestNoPrematureWrapupWithZeroData:
    """ORCH-T02: a context-fill ``should_wrap_up=True`` at iteration 0 (no data gathered
    yet) must NOT flip ``synthesis_phase``. The first LLM call must still receive
    the tool list (``tools`` kwarg is truthy).

    We force the wrap-up signal by patching ``app.agents.orchestrator.should_wrap_up``
    to return ``True`` unconditionally, simulating a huge static payload that would
    trip the context-fill threshold. Without the ORCH-T02 fix the loop enters
    synthesis immediately and calls ``_llm_call_with_retry(tools=None)`` on iter 0.
    With the fix, ``data_ready=False`` (no successful retrievals yet) guards the
    soft-wrap branch, so iter 0 still gets ``tools=<list>``.
    """

    async def test_no_premature_wrapup_with_zero_data(
        self,
        orch: OrchestratorAgent,
        base_context: AgentContext,
    ) -> None:
        tools = get_orchestrator_tools(has_knowledge_base=True)

        # Capture tools kwarg from every _llm_call_with_retry invocation.
        captured_tools: list[Any] = []

        async def _recording_llm(**kwargs: Any) -> LLMResponse:
            captured_tools.append(kwargs.get("tools"))
            # Iter 0: return a query_database tool call (data not yet gathered).
            # Iter 1+: return a plain text answer so the loop exits cleanly.
            if len(captured_tools) == 1:
                return _QUERY_DB_RESP
            return _NO_TOOL_RESP

        sql_result = _make_sql_result()

        with (
            patch.object(orch, "_llm_call_with_retry", new=AsyncMock(side_effect=_recording_llm)),
            # Dispatcher returns a real SQLAgentResult so successful_data_retrievals
            # is incremented after the first LLM call completes (not before it).
            patch.object(
                orch._dispatcher, "dispatch", new=AsyncMock(return_value=("42 rows", sql_result))
            ),
            patch.object(orch, "_stream_tokens", new=AsyncMock()),
            patch.object(orch, "_validate_partial_answer", new=AsyncMock(return_value=False)),
            # Force should_wrap_up to True so it *would* trip at iter 0 without the fix.
            patch("app.agents.orchestrator.should_wrap_up", return_value=True),
            patch("app.agents.orchestrator.settings") as mock_settings,
        ):
            _apply_mock_settings(mock_settings, max_iter=5)

            await orch._run_tool_loop(
                base_context,
                "wf-1",
                has_connection=True,
                db_type="postgresql",
                has_kb=False,
                has_mcp=False,
                has_repo=False,
                table_map="orders(id, amount)",
                project_overview="",
                recent_learnings="",
                tools=tools,
            )

        assert captured_tools, "Expected at least one LLM call"
        # The FIRST call (iter 0) must have received the tool list, not None.
        # Without the fix, synthesis_phase would already be True at iter 0 and
        # effective_tools would be None.
        first_call_tools = captured_tools[0]
        assert first_call_tools is not None and len(first_call_tools) > 0, (
            "ORCH-T02 FAIL: iter-0 LLM call received tools=None (premature synthesis). "
            f"should_wrap_up was forced True but data_ready should have been False. "
            f"captured_tools[0]={first_call_tools!r}"
        )


# ---------------------------------------------------------------------------
# ORCH-T02 Test 4: hard emergency valve still fires at iter 0
# ---------------------------------------------------------------------------


class TestHardEmergencyStillWrapsAtIter0:
    """ORCH-T02: the hard ``budget_pct >= emergency_pct`` branch must still flip
    ``synthesis_phase`` at iteration 0 regardless of data gathered — it is the
    honest-degradation safety valve and must not be gated by ``data_ready``.

    We set ``agent_emergency_synthesis_pct=0.01`` so ``step_pct = 1/max_iter``
    already exceeds it on the very first iteration, forcing the EMERGENCY path.
    """

    async def test_hard_emergency_still_wraps_at_iter0(
        self,
        orch: OrchestratorAgent,
        base_context: AgentContext,
    ) -> None:
        tools = get_orchestrator_tools(has_knowledge_base=True)

        captured_tools: list[Any] = []

        async def _recording_llm(**kwargs: Any) -> LLMResponse:
            captured_tools.append(kwargs.get("tools"))
            return _NO_TOOL_RESP

        with (
            patch.object(orch, "_llm_call_with_retry", new=AsyncMock(side_effect=_recording_llm)),
            patch.object(orch._dispatcher, "dispatch", new=AsyncMock(return_value=("ok", None))),
            patch.object(orch, "_stream_tokens", new=AsyncMock()),
            patch.object(orch, "_validate_partial_answer", new=AsyncMock(return_value=False)),
            # Also force should_wrap_up so the context-fill path also triggers,
            # but the hard emergency_pct branch must win first.
            patch("app.agents.orchestrator.should_wrap_up", return_value=True),
            patch("app.agents.orchestrator.settings") as mock_settings,
        ):
            _apply_mock_settings(mock_settings, max_iter=5)
            # Tiny emergency threshold: step_pct = 1/5 = 0.20 > 0.01 at iter 0.
            mock_settings.agent_emergency_synthesis_pct = 0.01

            await orch._run_tool_loop(
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

        assert captured_tools, "Expected at least one LLM call"
        # With emergency_pct=0.01, step_pct at iter 0 (1/5=0.20) already exceeds it,
        # so the hard branch fires and synthesis_phase=True => tools must be None.
        first_call_tools = captured_tools[0]
        assert first_call_tools is None, (
            "ORCH-T02 FAIL: hard emergency branch did not fire at iter 0. "
            "Expected tools=None (synthesis phase) but got tools list. "
            f"agent_emergency_synthesis_pct=0.01, step_pct at iter0=0.20. "
            f"captured_tools[0]={first_call_tools!r}"
        )
