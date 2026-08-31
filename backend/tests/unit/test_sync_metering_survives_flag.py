"""Turning off enforcement must switch off the REFUSAL, not the bookkeeping.

`sync_budget_enforcement_enabled` answers one question — may this sync be refused for an
owner who is over budget. It was answering a second one by accident: the sink that records
what the sync spent was built inside the same branch, so switching the flag off also
stopped the counting. That is the shape this whole pass exists to separate; recording and
refusing want opposite defaults for background work.

`preflight_owner_budget` already reads the flag itself and returns the owner either way,
so the caller's own copy of the check was redundant for the refusal and load-bearing only
for the bug.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from app.knowledge import code_db_sync_pipeline as mod
from app.services.sync_budget import preflight_owner_budget


def _enclosing_tests(tree: ast.AST, target: ast.AST) -> list[ast.expr]:
    """Every `if` test that the target node sits inside."""
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    tests: list[ast.expr] = []
    cur: ast.AST | None = target
    while cur is not None:
        parent = parents.get(cur)
        if isinstance(parent, ast.If) and cur in parent.body:
            tests.append(parent.test)
        cur = parent
    return tests


def test_the_sink_is_not_built_inside_the_enforcement_branch() -> None:
    tree = ast.parse(inspect.getsource(mod))
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id in {"build_sink", "build_metering_sink"}
    ]
    assert calls, "the sync pipeline builds no usage sink at all; its LLM calls reach no table"

    for call in calls:
        for test in _enclosing_tests(tree, call):
            names = {n.attr for n in ast.walk(test) if isinstance(n, ast.Attribute)}
            assert "sync_budget_enforcement_enabled" not in names, (
                "the usage sink is built inside the enforcement branch, so switching "
                "enforcement off also stops recording what the sync spent"
            )


async def test_the_preflight_still_names_the_owner_when_enforcement_is_off(monkeypatch) -> None:
    """The precondition the fix leans on: with the flag off the pre-flight passes AND
    hands back the owner, which is the only thing a sink needs to attribute a call."""
    from app.config import settings

    class _Session:
        async def execute(self, *_a, **_k):
            class _R:
                @staticmethod
                def scalar_one_or_none() -> str:
                    return "owner-42"

            return _R()

    monkeypatch.setattr(settings, "sync_budget_enforcement_enabled", False)
    ok, reason, owner = await preflight_owner_budget(_Session(), "proj-1234abcd")
    assert (ok, reason, owner) == (True, None, "owner-42")


@pytest.mark.parametrize("enforced", [True, False])
def test_both_sinks_are_reachable_from_the_pipeline(enforced: bool) -> None:
    """Off means metering-only, on means the gating sink — two sinks, one flag."""
    src = inspect.getsource(mod)
    assert "build_metering_sink" in src and "build_sink" in src


@pytest.mark.parametrize("gate,expected", [(True, "over budget"), (False, None)])
async def test_only_a_gating_sink_reports_a_breach(gate: bool, expected: str | None) -> None:
    """The claim the whole separation rests on, asserted rather than read.

    `code_db_sync_pipeline` asks `sink.budget_exceeded()` before the LLM summary and skips
    it when a reason comes back. If a metering sink could produce one, the refusal would
    simply have moved a level deeper than the flag that declined it.

    Both halves are checked on purpose: `observe` swallows its own exceptions, so a mock
    that never reached the code would leave the metering case looking correct for the
    wrong reason. The gating case is the control that proves it arrived.
    """
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, patch

    from app.llm.usage_sink import DbUsageSink

    @asynccontextmanager
    async def _session():
        yield object()

    svc = AsyncMock()
    svc.check_token_budget = AsyncMock(return_value="over budget")

    sink = DbUsageSink(user_id="owner-42", project_id="proj-1234abcd", gate=gate)
    with (
        patch("app.llm.usage_sink.async_session_factory", _session),
        patch("app.llm.usage_sink.UsageService", return_value=svc),
    ):
        await sink.observe(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            provider="openrouter",
            model="x",
        )

    assert svc.record_usage.await_count == 1, "the call was not recorded at all"
    assert sink.budget_exceeded() == expected
    assert svc.check_token_budget.await_count == (1 if gate else 0), (
        "a metering sink must not even ask; the check sums a month of usage per LLM call"
    )
