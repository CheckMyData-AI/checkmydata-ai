"""AUD-6 — one MCPSourceAgent serves every request in the process.

`orchestrator.py:367` builds `MCPSourceAgent(...)` in `__init__`, and the orchestrator
hangs off the module-level `ConversationalAgent()` in `chat.py:60`, so the instance is
shared. `run()` stashed the caller's adapter on `self._adapter` before awaiting, while
`_run_with_adapter` read it back off `self` — including at the `call_tool` site that
actually reaches a tenant's MCP server.

Two concurrent requests interleaved: A set its adapter and awaited, B overwrote it, and
A resumed to call **B's** server with A's question. The `finally` restore made the
residue worse rather than better — B wrote back A's adapter, then A wrote back its own
`prev`, leaving the shared field pointing at whichever request lost the race.

The invariant pinned here is behavioural, deliberately: *an adapter handed to one
`run()` call receives that call's tool invocations and no other's.* An earlier draft of
this file asserted on the source text of `run()`; that style of check has already been
caught in this project passing against a planted defect, so it is not used.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.agents.mcp_source_agent import MCPSourceAgent


class _ToolResult:
    def __init__(self, text: str) -> None:
        self.text = text
        self.is_error = False


class _Adapter:
    """Records which tenant's server was actually reached."""

    def __init__(self, tenant: str) -> None:
        self.tenant = tenant
        self.calls: list[str] = []

    def get_tool_schemas(self) -> list[Any]:
        schema = MagicMock()
        schema.name = f"tool_{self.tenant}"
        schema.description = f"tool of {self.tenant}"
        schema.input_schema = {"type": "object", "properties": {}}
        return [schema]

    async def call_tool(self, name: str, arguments: dict) -> _ToolResult:
        self.calls.append(name)
        return _ToolResult(f"data from {self.tenant}")


def _context(question: str) -> MagicMock:
    ctx = MagicMock()
    ctx.user_question = question
    ctx.preferred_provider = None
    ctx.model = None
    ctx.chat_history = []
    ctx.project_id = "p1"
    ctx.workflow_id = "wf1"
    tracker = MagicMock()
    tracker.step.return_value.__aenter__ = MagicMock(
        return_value=asyncio.get_event_loop().create_future()
    )
    ctx.tracker = tracker
    return ctx


@pytest.fixture
def agent() -> MCPSourceAgent:
    return MCPSourceAgent(llm_router=MagicMock())


async def test_two_concurrent_runs_do_not_swap_adapters(
    agent: MCPSourceAgent, monkeypatch: pytest.MonkeyPatch
):
    """Each tenant's tool call must land on that tenant's own server.

    Request A is suspended inside its LLM call — exactly where the real agent awaits —
    until request B has finished and restored the shared field. If the adapter travels
    on `self`, A resumes and calls B's server.
    """
    a, b = _Adapter("tenant-a"), _Adapter("tenant-b")
    b_holds_the_field = asyncio.Event()  # B has overwritten self._adapter
    a_done = asyncio.Event()  # A has made its tool call

    turns: dict[str, int] = {"A-question": 0, "B-question": 0}

    async def _llm(_router, **kwargs):
        question = next(m.content for m in kwargs["messages"] if getattr(m, "role", "") == "user")
        turns[question] += 1

        # The interleaving that leaks: BOTH requests are in flight, and A reaches its
        # tool call while B still owns the shared field. (Letting B *finish* first
        # hides the bug -- its `finally` hands A's adapter back by luck.)
        if turns[question] == 1:
            if question == "B-question":
                b_holds_the_field.set()
                await a_done.wait()
            else:
                await b_holds_the_field.wait()

        resp = MagicMock()
        resp.usage = {}
        resp.model = "m"
        if turns[question] > 1:
            resp.content = "done"
            resp.tool_calls = []
            return resp

        resp.content = ""
        call = MagicMock()
        call.name = "tool_tenant-a" if question == "A-question" else "tool_tenant-b"
        call.arguments = {}
        call.id = "c1"
        resp.tool_calls = [call]
        return resp

    monkeypatch.setattr("app.agents.mcp_source_agent.llm_call_with_retry", _llm, raising=False)

    task_a = asyncio.create_task(
        agent.run(_context("A-question"), question="A-question", adapter=a)
    )
    task_b = asyncio.create_task(
        agent.run(_context("B-question"), question="B-question", adapter=b)
    )
    await task_a
    a_done.set()
    await task_b

    assert a.calls == ["tool_tenant-a"], f"tenant A's request reached the wrong server: {a.calls}"
    assert b.calls == ["tool_tenant-b"], f"tenant B's request reached the wrong server: {b.calls}"
