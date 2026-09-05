"""A budget-exhausted run must not be sealed as verified (board row 1.7).

`docs/ux/scenarios.md:2159` states the contract without hedging:

    a failed or budget-exhausted run seals **Unverified** even when a query is
    attached to it, because a partial run's evidence proves nothing about the
    answer.

The frontend honours it — `sealStateFor` (`components/ui/Seal.tsx:73-91`)
returns `"unverified"` for `step_limit_reached`, and `"verified"` for
`sql_result` with a query attached. The backend does not. `orchestrator.py`
enters the exhausted-budget branch on `step_limit_hit or wall_clock_timeout_hit`
and then returns the **ordinary** response type whenever the partial answer
`has_meaningful_data and answer_addresses_question`. So a cut-off run whose
partial answer merely looks complete is typed `sql_result`, and the reader is
shown a **Verified** seal over evidence that proves nothing.

`step_limit_reached` is reached only when the partial answer already looks
bad — that is, exactly when the badge adds least.

**The validator cannot settle this, and that is the crux.**
`_validate_partial_answer` is asked whether the answer addresses the question.
It sees the answer and the question; it cannot see the data the run did not
reach. Judging a partial answer against itself is not evidence that the cut-off
did not matter.

Nothing caught it because **no test in this suite exhausts the step budget** —
`grep -rnE "max_orchestrator_steps|step_limit_hit" tests/` returns nothing
outside this file. The neighbouring test that asserts `step_limit_reached`
(`test_orchestrator.py::test_answer_gate_downgrades_suspicious_normal_completion`)
reaches it down the I6 *normal-completion* path, with zero rows, so the branch
that this row is about had never been executed by a test at all.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.base import AgentContext
from app.agents.orchestrator import OrchestratorAgent


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


@pytest.fixture
def llm():
    router = MagicMock()
    router.complete = AsyncMock()
    router.get_context_window = MagicMock(return_value=128_000)
    return router


@pytest.fixture
def orch(llm, tracker):
    vs = MagicMock()
    collection = MagicMock()
    collection.count = MagicMock(return_value=0)
    vs.get_or_create_collection = MagicMock(return_value=collection)
    return OrchestratorAgent(llm_router=llm, vector_store=vs, workflow_tracker=tracker)


@pytest.fixture
def context(llm, tracker):
    return AgentContext(
        project_id="test-proj",
        connection_config=None,
        user_question="How many orders were placed last quarter, by region?",
        chat_history=[],
        llm_router=llm,
        tracker=tracker,
        workflow_id="wf-1",
        project_name="TestProject",
        max_orchestrator_steps=1,
    )


async def _run_until_budget_is_spent(orch, llm, context, *, answer_looks_good: bool):
    """Drive the flat loop until its step budget is spent, with rows on the table.

    Every LLM turn asks for another query, so the loop never exits cleanly and
    the budget is what stops it — which is the branch under test.
    """
    from app.agents.sql_agent import SQLAgentResult
    from app.agents.tools.orchestrator_tools import get_orchestrator_tools
    from app.connectors.base import QueryResult
    from app.llm.base import LLMResponse, ToolCall

    populated = SQLAgentResult(
        status="success",
        query="SELECT region, count(*) FROM orders GROUP BY region",
        results=QueryResult(
            columns=["region", "count"],
            rows=[["EU", 412], ["APAC", 118]],
            row_count=2,
        ),
    )

    def _always_another_query(*_a, **_kw):
        return LLMResponse(
            content="",
            tool_calls=[
                ToolCall(id="t", name="query_database", arguments={"question": "how many"})
            ],
        )

    llm.complete = AsyncMock(side_effect=_always_another_query)
    orch._dispatcher.dispatch = AsyncMock(return_value=("1 row", populated))
    orch._validate_partial_answer = AsyncMock(return_value=answer_looks_good)

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


class TestABudgetExhaustedRunSaysSo:
    async def test_a_plausible_partial_answer_is_still_typed_as_cut_short(self, orch, llm, context):
        """The defect. Rows on the table, a validator that approves — and the
        run was still cut off, so the reader must be told."""
        resp = await _run_until_budget_is_spent(orch, llm, context, answer_looks_good=True)

        assert resp.response_type == "step_limit_reached", (
            "a run stopped by its budget was typed as an ordinary answer, which seals "
            "Verified in the UI over evidence a partial run cannot support "
            "(docs/ux/scenarios.md:2159)"
        )

    async def test_an_implausible_partial_answer_is_unchanged(self, orch, llm, context):
        """The pre-existing behaviour, kept: this half was already right."""
        resp = await _run_until_budget_is_spent(orch, llm, context, answer_looks_good=False)

        assert resp.response_type == "step_limit_reached"


class TestTheAnswerTextStillCarriesTheData:
    async def test_the_partial_answer_is_returned_rather_than_discarded(self, orch, llm, context):
        """Typing the run as cut short must not throw away what it did find.

        The scenario's other half (`scenarios.md:1090`) is that the answer names
        what it did not reach — an honest partial answer, not an error page.
        """
        resp = await _run_until_budget_is_spent(orch, llm, context, answer_looks_good=True)

        assert resp.answer, "a cut-off run must still return the data it gathered"


class TestTheValidatorIsStillConsulted:
    async def test_it_is_asked_even_though_it_no_longer_decides_the_type(self, orch, llm, context):
        """Written first with the wrong reason, and corrected by reading it.

        The claim here was that the validator feeds the answer TEXT. It does
        not: its docstring says it exists "to decide whether to surface the
        answer as ``sql_result`` or as ``step_limit_reached``", and the text is
        already built above. Once the type is forced, that job is gone.

        What survives is a side effect: on a verdict of "does not address the
        question" it catalogs a validation failure through
        ``ErrorLogService.upsert_validation_failure``, which is how the errors
        screen learns that a cut-off run produced an answer missing its point.
        The call is asserted here so that signal is not removed later as
        obviously-dead code — because by the type's reckoning it now is."""
        await _run_until_budget_is_spent(orch, llm, context, answer_looks_good=True)

        orch._validate_partial_answer.assert_awaited()
