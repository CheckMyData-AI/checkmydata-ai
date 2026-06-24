"""Tests for the orchestrator's post-call budget hard-stop (R2 / C4 / F-BILL-05).

When the LLM router's ``UsageSink`` reports a sticky ``budget_exceeded()``
reason between iterations of the unified tool loop, the orchestrator must:

* short-circuit the very next LLM call,
* return a terminal :class:`AgentResponse` carrying the reason in ``error``,
* mark ``response_type == "error"``.

These tests also cover propagation of the router's sink to the
``AdaptivePlanner`` and ``AnswerValidator`` sub-agents the orchestrator
constructs at runtime.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import AgentContext
from app.agents.orchestrator import OrchestratorAgent
from app.agents.tools.orchestrator_tools import get_orchestrator_tools
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import LLMResponse, ToolCall

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _StubSink:
    """Minimal UsageSink-shaped double whose ``budget_exceeded`` is scripted."""

    def __init__(self, reason: str | None = None) -> None:
        self._reason = reason
        self.observe_calls = 0

    async def observe(self, **_: object) -> None:  # pragma: no cover — protocol shape
        self.observe_calls += 1

    def budget_exceeded(self) -> str | None:
        return self._reason


@pytest.fixture
def mock_tracker():
    t = MagicMock(spec=WorkflowTracker)
    t.begin = AsyncMock(return_value="wf-1")
    t.end = AsyncMock()
    t.emit = AsyncMock()
    t.has_ended = MagicMock(return_value=True)

    @asynccontextmanager
    async def fake_step(wf_id, step, detail="", **kwargs):
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
        user_question="What is X?",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-1",
        project_name="TestProject",
    )


# ---------------------------------------------------------------------------
# Sink propagation
# ---------------------------------------------------------------------------


class TestLlmSinkAccessor:
    """The ``_llm_sink`` helper returns whatever the router carries on ``_sink``."""

    def test_returns_router_sink(self, mock_llm, mock_vs, mock_tracker):
        sink = _StubSink()
        mock_llm._sink = sink
        orch = OrchestratorAgent(
            llm_router=mock_llm,
            vector_store=mock_vs,
            workflow_tracker=mock_tracker,
        )
        assert orch._llm_sink() is sink

    def test_returns_none_when_router_has_no_sink(self, mock_vs, mock_tracker):
        """A bare object without ``_sink`` yields ``None`` (no AttributeError)."""

        class _NoSinkRouter:
            def get_context_window(self, _model):
                return 128_000

            async def complete(self, **_kwargs):
                return LLMResponse(content="x")

        orch = OrchestratorAgent(
            llm_router=_NoSinkRouter(),  # type: ignore[arg-type]
            vector_store=mock_vs,
            workflow_tracker=mock_tracker,
        )
        assert orch._llm_sink() is None


# ---------------------------------------------------------------------------
# Post-call hard-stop in the unified tool loop
# ---------------------------------------------------------------------------


class TestBudgetHardStop:
    @pytest.mark.asyncio
    async def test_orchestrator_short_circuits_on_sticky_budget_exceeded(
        self, orch, mock_llm, base_context
    ):
        """A sticky ``budget_exceeded`` reason must short-circuit the loop
        before the next LLM call and bubble the reason into the response.
        """
        reason = "Daily limit exceeded — upgrade"
        sink = _StubSink(reason=reason)
        mock_llm._sink = sink

        # If the orchestrator fails to short-circuit, this would be called.
        mock_llm.complete = AsyncMock(return_value=LLMResponse(content="should not be called"))

        tools = get_orchestrator_tools(has_knowledge_base=True)
        resp = await orch._run_tool_loop(
            base_context,
            "wf-1",
            has_connection=False,
            db_type=None,
            has_kb=True,
            has_mcp=False,
            has_repo=False,
            table_map="",
            project_overview=None,
            recent_learnings=None,
            custom_rules="",
            tools=tools,
            staleness_warning=None,
            route_result=None,
        )

        # No LLM call was issued.
        assert mock_llm.complete.await_count == 0
        # Terminal error response with the sticky reason.
        assert resp.error == reason
        assert resp.response_type == "error"

    @pytest.mark.asyncio
    async def test_orchestrator_proceeds_when_no_budget_breach(self, orch, mock_llm, base_context):
        """With ``budget_exceeded() -> None`` the loop runs normally."""
        sink = _StubSink(reason=None)
        mock_llm._sink = sink

        mock_llm.complete = AsyncMock(return_value=LLMResponse(content="Final answer."))

        tools = get_orchestrator_tools(has_knowledge_base=True)
        resp = await orch._run_tool_loop(
            base_context,
            "wf-1",
            has_connection=False,
            db_type=None,
            has_kb=True,
            has_mcp=False,
            has_repo=False,
            table_map="",
            project_overview=None,
            recent_learnings=None,
            custom_rules="",
            tools=tools,
            staleness_warning=None,
            route_result=None,
        )

        assert mock_llm.complete.await_count >= 1
        assert resp.response_type != "error"
        assert resp.answer == "Final answer."

    @pytest.mark.asyncio
    async def test_orchestrator_hard_stops_mid_loop(self, orch, mock_llm, base_context):
        """Budget breach AFTER the first LLM call must stop the loop before the next call."""
        sink = _StubSink(reason=None)
        mock_llm._sink = sink

        # First iteration: the model asks for a tool call; tool runs; then budget trips.
        call_count = {"n": 0}

        async def _complete(**_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(id="t1", name="search_codebase", arguments={"question": "x"}),
                    ],
                )
            # We must NOT reach here — budget should have tripped.
            return LLMResponse(content="LATE — should not run")

        mock_llm.complete = AsyncMock(side_effect=_complete)
        orch._dispatcher.dispatch = AsyncMock(return_value=("ok result", None))

        # After the first LLM call + tool dispatch, flip the sticky reason on.
        async def _flip_after_dispatch(*args, **kwargs):
            sink._reason = "Monthly limit exceeded — upgrade plan"
            return ("ok result", None)

        orch._dispatcher.dispatch = AsyncMock(side_effect=_flip_after_dispatch)

        tools = get_orchestrator_tools(has_knowledge_base=True)
        resp = await orch._run_tool_loop(
            base_context,
            "wf-1",
            has_connection=False,
            db_type=None,
            has_kb=True,
            has_mcp=False,
            has_repo=False,
            table_map="",
            project_overview=None,
            recent_learnings=None,
            custom_rules="",
            tools=tools,
            staleness_warning=None,
            route_result=None,
        )

        # Exactly one LLM call happened; the second iteration short-circuited.
        assert call_count["n"] == 1
        assert resp.response_type == "error"
        assert resp.error == "Monthly limit exceeded — upgrade plan"


# ---------------------------------------------------------------------------
# Sub-agent construction propagation
# ---------------------------------------------------------------------------


class TestSinkPropagationToSubAgents:
    @pytest.mark.asyncio
    async def test_orchestrator_passes_sink_to_answer_validator(self, orch, mock_llm, base_context):
        """``AnswerValidator`` constructed inside ``_validate_partial_answer``
        must receive the router's sink so its own LLM call updates the same
        sticky reason flag.
        """
        sink = _StubSink(reason=None)
        mock_llm._sink = sink

        captured: dict[str, object] = {}

        class _StubValidator:
            def __init__(self, llm, usage_sink=None):
                captured["llm"] = llm
                captured["usage_sink"] = usage_sink

            async def validate(self, **_kwargs):
                # Verdict shape — only addresses_question matters for the gate.
                v = MagicMock()
                v.addresses_question = True
                v.confidence = 0.9
                v.reason = "ok"
                return v

        with patch("app.agents.answer_validator.AnswerValidator", _StubValidator):
            ok = await orch._validate_partial_answer(
                "Some partial answer that is long enough.",
                question="q",
                sql_results=[],
                preferred_provider=None,
                model=None,
                wf_id="wf-1",
            )

        assert ok is True
        assert captured["usage_sink"] is sink
