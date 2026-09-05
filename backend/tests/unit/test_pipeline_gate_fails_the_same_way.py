"""When the validator itself crashes, the two paths disagreed (board row 2.9).

`answer_validator_fail_closed` (default **True**) exists so that "an unverifiable
answer is framed as a continuable partial result rather than asserted as a
verified final answer" — its own words, at `orchestrator.py:_validate_partial_answer`.
The flat loop honours it: on a validator exception it returns `False`, and the
response is downgraded.

The pipeline's gate answered the same exception with a bare `return None`, and
`build_pipeline_response` reads `None` as accept. So for one question, whether a
crashed validator downgraded the answer or published it depended on which path a
router the user cannot see had chosen.

**The fail-open was documented**, which is why this is worth writing down rather
than just fixing: the docstring says "non-critical; fail-open to avoid blocking a
successful pipeline". But nothing here blocks. Any non-`accept` directive maps to
`step_limit_reached` (`response_builder.py:104-109`), which **preserves the answer
text** and adds the "Continue analysis" CTA. The fail-open was defending against a
cost that does not exist, and paying for it with an unverified answer presented as
verified.

So the fix is parity, not severity: `warn` when the setting says fail closed,
`None` when it says fail open.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.orchestrator import OrchestratorAgent


@pytest.fixture
def tracker():
    from app.core.workflow_tracker import WorkflowTracker

    t = MagicMock(spec=WorkflowTracker)
    t.emit = AsyncMock()
    t.end = AsyncMock()
    t.get_owner = MagicMock(return_value={"project_id": "p1"})

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
def exec_result():
    from app.agents.stage_context import ExecutionPlan, StageContext

    result = MagicMock()
    result.status = "completed"
    result.final_answer = "Revenue grew 12% quarter over quarter."
    result.stage_ctx = StageContext(plan=ExecutionPlan(plan_id="p", question="q", stages=[]))
    return result


@pytest.fixture
def context(llm, tracker):
    from app.agents.base import AgentContext

    return AgentContext(
        project_id="p1",
        connection_config=None,
        user_question="How did revenue move?",
        chat_history=[],
        llm_router=llm,
        tracker=tracker,
        workflow_id="wf-1",
    )


def _make_the_gate_crash(monkeypatch):
    """The validator throws — a provider outage, a malformed response, anything."""
    import app.agents.answer_validator as av

    def _boom(*_a, **_kw):
        raise RuntimeError("validator unavailable")

    monkeypatch.setattr(av, "AnswerValidator", _boom)


class TestACrashedGateIsNotAnAcceptance:
    async def test_fail_closed_downgrades_instead_of_publishing(
        self, orch, exec_result, context, monkeypatch
    ):
        """The defect. `None` means accept to `build_pipeline_response`."""
        from app.config import settings

        monkeypatch.setattr(settings, "answer_validator_enabled", True)
        monkeypatch.setattr(settings, "answer_validator_fail_closed", True)
        _make_the_gate_crash(monkeypatch)

        directive = await orch._evaluate_pipeline_answer(
            exec_result=exec_result, context=context, wf_id="wf-1"
        )

        assert directive is not None, (
            "a crashed gate returned None, which build_pipeline_response reads as accept — "
            "so an unverifiable answer was published as verified on the pipeline path while "
            "the flat loop downgraded the same answer"
        )
        assert directive.action != "accept"

    async def test_fail_open_still_publishes_when_the_operator_asked_for_that(
        self, orch, exec_result, context, monkeypatch
    ):
        """The setting is honoured in both directions, or it is not a setting."""
        from app.config import settings

        monkeypatch.setattr(settings, "answer_validator_enabled", True)
        monkeypatch.setattr(settings, "answer_validator_fail_closed", False)
        _make_the_gate_crash(monkeypatch)

        directive = await orch._evaluate_pipeline_answer(
            exec_result=exec_result, context=context, wf_id="wf-1"
        )

        assert directive is None


class TestTheDowngradeDoesNotWithholdTheAnswer:
    """The documented fear was "blocking a successful pipeline". Nothing blocks:
    a non-accept directive maps to `step_limit_reached`, which keeps the text."""

    def test_a_warn_directive_preserves_the_answer_text(self):
        from app.agents.response_builder import ResponseBuilder
        from app.agents.result_validation import ResultDirective

        exec_result = MagicMock()
        exec_result.status = "completed"
        exec_result.final_answer = "Revenue grew 12% quarter over quarter."
        exec_result.stage_ctx = MagicMock()
        exec_result.stage_ctx.plan.stages = []
        exec_result.degraded_reason = None

        resp = ResponseBuilder.build_pipeline_response(
            exec_result,
            "wf-1",
            None,
            "run-1",
            answer_directive=ResultDirective(action="warn", reason="could not verify"),
        )
        assert resp.response_type == "step_limit_reached"
        assert "Revenue grew 12%" in resp.answer


class TestTheSkipPathsAreUnchanged:
    """A gate that never ran is not a gate that failed, and must stay `None`."""

    async def test_a_disabled_validator_still_returns_none(
        self, orch, exec_result, context, monkeypatch
    ):
        from app.config import settings

        monkeypatch.setattr(settings, "answer_validator_enabled", False)
        monkeypatch.setattr(settings, "answer_validator_fail_closed", True)

        assert (
            await orch._evaluate_pipeline_answer(
                exec_result=exec_result, context=context, wf_id="wf-1"
            )
            is None
        )

    async def test_an_unfinished_pipeline_still_returns_none(
        self, orch, exec_result, context, monkeypatch
    ):
        from app.config import settings

        monkeypatch.setattr(settings, "answer_validator_enabled", True)
        monkeypatch.setattr(settings, "answer_validator_fail_closed", True)
        exec_result.status = "failed"

        assert (
            await orch._evaluate_pipeline_answer(
                exec_result=exec_result, context=context, wf_id="wf-1"
            )
            is None
        )
