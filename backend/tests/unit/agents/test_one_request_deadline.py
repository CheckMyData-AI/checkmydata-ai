"""One request deadline, and it interrupts rather than advises (PRJ-03).

Measured on production over 30 days before this change: 6 of 23 traces ran past 1.2x the
180 s `agent_wall_clock_timeout_seconds`, and failed requests ran a median of **283 s**.
Two causes, both structural:

- the tool loop checked its wall clock only BETWEEN iterations, so one iteration — a
  single orchestrator LLM call, or one dispatch that runs the whole SQL agent — could
  outlast the limit by its entire duration with nothing able to stop it;
- the clock started at the loop's first line, and the pipeline path computed a fresh
  deadline when its stages began, so routing, context loading and capability probes
  were outside the limit on both paths.

Tests are in real time but seconds-scale: the limit is patched to a fraction of a second
and a stub hangs, so the assertion is "returned in about the limit" rather than "returned".
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import AgentContext
from app.agents.orchestrator import (
    LOCALIZE_GRACE_SECONDS,
    OrchestratorAgent,
    WallClockExceeded,
    _new_pipeline_deadline,
    bounded,
    hard_remaining_seconds,
    request_started_at,
)

ORCH = pathlib.Path(__file__).resolve().parents[3] / "app" / "agents" / "orchestrator.py"


def _context(tracker=None, llm=None) -> AgentContext:
    return AgentContext(
        project_id="p",
        connection_config=None,
        user_question="How many orders last quarter?",
        chat_history=[],
        llm_router=llm or MagicMock(),
        tracker=tracker or MagicMock(),
        workflow_id="wf-1",
        project_name="P",
        max_orchestrator_steps=5,
    )


class TestTheRequestHasOneClock:
    def test_the_start_is_set_once_and_read_back(self) -> None:
        ctx = _context()
        first = request_started_at(ctx)
        time.sleep(0.01)
        assert request_started_at(ctx) == first

    def test_a_copied_context_shares_the_start(self) -> None:
        """`dataclasses.replace` copies the `extra` dict's reference, so every sub-agent
        copy reads the same start — which is why it lives there."""
        from dataclasses import replace

        ctx = _context()
        start = request_started_at(ctx)
        assert request_started_at(replace(ctx, user_question="other")) == start

    def test_the_pipeline_deadline_counts_from_the_request_not_the_stages(self) -> None:
        """Time spent routing and loading context before the stages must be spent."""
        ctx = _context()
        request_started_at(ctx)
        ctx.extra["_request_started_at"] -= 100.0  # the request began 100 s ago
        with patch("app.agents.orchestrator.settings") as s:
            s.pipeline_max_wall_seconds = 0
            s.agent_wall_clock_timeout_seconds = 180
            deadline = _new_pipeline_deadline(ctx)
        assert deadline is not None
        assert 75 < deadline - time.monotonic() < 85, (
            "the pipeline was handed a fresh 180 s after 100 s had already gone"
        )


class TestBounded:
    async def test_a_hanging_await_is_cut_at_the_hard_deadline(self) -> None:
        ctx = _context()
        request_started_at(ctx)
        started = time.monotonic()
        with pytest.raises(WallClockExceeded):
            await bounded(asyncio.sleep(30), ctx, limit=0.25)  # hard cut at 0.3 s
        assert time.monotonic() - started < 1.5

    async def test_a_fast_await_returns_its_value(self) -> None:
        ctx = _context()

        async def quick() -> int:
            return 7

        assert await bounded(quick(), ctx, limit=60) == 7

    async def test_nothing_starts_once_the_deadline_is_spent(self) -> None:
        ctx = _context()
        request_started_at(ctx)
        ctx.extra["_request_started_at"] -= 1000.0
        assert hard_remaining_seconds(ctx, 180) == 0
        with pytest.raises(WallClockExceeded):
            await bounded(asyncio.sleep(0), ctx, limit=180)

    def test_it_is_not_swallowed_by_except_exception(self) -> None:
        """The loop turns dispatch failures into directives inside `except Exception`.
        A deadline caught there would read as "the tool failed, try again"."""
        assert not issubclass(WallClockExceeded, Exception)


@pytest.fixture
def tracker():
    from app.core.workflow_tracker import WorkflowTracker

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


def _orch(llm, tracker) -> OrchestratorAgent:
    vs = MagicMock()
    collection = MagicMock()
    collection.count = MagicMock(return_value=0)
    vs.get_or_create_collection = MagicMock(return_value=collection)
    return OrchestratorAgent(llm_router=llm, vector_store=vs, workflow_tracker=tracker)


async def _run_loop(orch, context):
    from app.agents.tools.orchestrator_tools import get_orchestrator_tools

    return await orch._run_tool_loop(
        context,
        "wf-1",
        has_connection=True,
        db_type="postgres",
        has_kb=False,
        has_mcp=False,
        has_repo=False,
        table_map="",
        project_overview=None,
        recent_learnings=None,
        custom_rules="",
        tools=get_orchestrator_tools(has_connection=True),
        staleness_warning=None,
        route_result=None,
    )


class TestTheToolLoopIsInterrupted:
    async def test_a_hanging_llm_call_is_cut_at_the_deadline(self, tracker) -> None:
        llm = MagicMock()
        llm.get_context_window = MagicMock(return_value=128_000)

        async def hang(*_a, **_k):
            await asyncio.sleep(60)

        llm.complete = AsyncMock(side_effect=hang)
        orch = _orch(llm, tracker)
        ctx = _context(tracker, llm)
        started = time.monotonic()
        with patch("app.agents.orchestrator.settings.agent_wall_clock_timeout_seconds", 1):
            resp = await _run_loop(orch, ctx)
        elapsed = time.monotonic() - started
        # 1 s x 1.2 hard cutoff, plus the localizer's explicit grace — which is itself
        # bounded now: it was an uncapped 12 s and this test measured 13 s until it was.
        ceiling = 1.2 + LOCALIZE_GRACE_SECONDS + 1.5
        assert elapsed < ceiling, f"a hanging LLM call held the request for {elapsed:.1f}s"
        assert resp.answer, "the cut must still produce an answer the user can read"

    async def test_a_hanging_dispatch_is_cut_at_the_deadline(self, tracker) -> None:
        """The dispatcher is told the remaining time; a tool that ignores it — an MCP
        source, a socket read — used to hold the whole request."""
        from app.llm.base import LLMResponse, ToolCall

        llm = MagicMock()
        llm.get_context_window = MagicMock(return_value=128_000)
        llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[ToolCall(id="t", name="query_database", arguments={"question": "q"})],
            )
        )
        orch = _orch(llm, tracker)

        async def hang(*_a, **_k):
            await asyncio.sleep(60)

        orch._dispatcher.dispatch = AsyncMock(side_effect=hang)
        ctx = _context(tracker, llm)
        started = time.monotonic()
        with patch("app.agents.orchestrator.settings.agent_wall_clock_timeout_seconds", 1):
            resp = await _run_loop(orch, ctx)
        elapsed = time.monotonic() - started
        ceiling = 1.2 + LOCALIZE_GRACE_SECONDS + 1.5
        assert elapsed < ceiling, f"a hanging dispatch held the request for {elapsed:.1f}s"
        assert resp.answer


def test_every_llm_call_and_dispatch_in_the_loop_is_bounded() -> None:
    """A new call added to the loop unbounded reopens the defect for exactly that call."""
    tree = ast.parse(ORCH.read_text(encoding="utf-8"))
    loop = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_tool_loop"
    )
    unbounded: list[int] = []
    for node in ast.walk(loop):
        if not isinstance(node, ast.Call):
            continue
        name = ast.unparse(node.func)
        if name in ("self._llm_call_with_retry", "self._dispatcher.dispatch", "self._llm.complete"):
            unbounded.append(node.lineno)
        # The partial-answer validator is an LLM call too, and it runs AFTER the loop,
        # which is where the first version of this guard found an unbounded synthesis.
        if name == "self._validate_partial_answer":
            parent_is_bounded = any(
                isinstance(p, ast.Call) and ast.unparse(p.func) == "bounded" and node in p.args
                for p in ast.walk(loop)
            )
            if not parent_is_bounded:
                unbounded.append(node.lineno)
    assert not unbounded, (
        f"orchestrator.py lines {unbounded} await an LLM call or a dispatch in the tool "
        "loop without the request deadline — use _bounded_llm_call / _bounded_dispatch"
    )
