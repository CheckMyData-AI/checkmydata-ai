"""A parallel layer needs a gate before the node that consumes it (Ш3).

`StageExecutor` runs up to `PIPELINE_MAX_PARALLEL_STAGES = 3` stages at once and
then synthesises. Every check it has is **per stage** — `StageValidator` on the
stage's own shape, `DataGate` on the stage's own rows. Nothing compares the
arriving siblings, and synthesis takes its edges straight from them.

That is the diamond's silent failure, and the doctrine states it as the defect of
the *convergence* rather than of any branch: three branches run, one returns a
hallucination or an empty result, and the synthesis node cannot tell — so it
produces a confident answer built partly on garbage. In a chain a bad step
produces a visibly bad output; at a convergence the bad output is **mixed** with
good ones, the damage spreads thin, and the trace back to its source is gone.

The contract is six items, and this checker implements **four**:

    missing        a branch the split promised never came back    code   ✅
    empty          it arrived and carries nothing usable          code   ✅
    unevidenced    a claim with no receipt a reader could check   code   ✅
    malformed      a shape that will break the convergence        code   ✅
    contradictory  two results that cannot both be true           model  ✗
    off-topic      an answer to a different question              model  ✗

The four cost nothing; the last two need an LLM call per layer on a path whose
worst measured request already ran 296 s. They are **declared unimplemented**
rather than quietly omitted, because the doctrine's own words are that a checker
which cannot say which of the six it is asserting is not a checker.

`missing` takes the arrival count as a **given**, never infers it: the fan-out is
fixed when the layer is built, so the checker is handed the number to expect. Without
that number a vanished branch is caught only when its slot happens to hold nothing —
item 2 by luck rather than by design.
"""

from __future__ import annotations

import pytest

from app.agents.layer_checker import (
    CHECKER_ITEMS,
    CODE_ITEMS,
    MODEL_ITEMS,
    LayerChecker,
    LayerVerdict,
)
from app.agents.stage_context import PlanStage, StageResult
from app.connectors.base import QueryResult


def _stage(stage_id: str, tool: str = "query_database") -> PlanStage:
    return PlanStage(stage_id=stage_id, description=stage_id, tool=tool)


def _ok(stage_id: str, *, rows: int = 2) -> StageResult:
    return StageResult(
        stage_id=stage_id,
        status="success",
        query=f"SELECT * FROM t_{stage_id}",
        query_result=QueryResult(
            columns=["a", "b"],
            rows=[["x", i] for i in range(rows)],
            row_count=rows,
        ),
        summary=f"{rows} rows from {stage_id}",
    )


@pytest.fixture
def checker() -> LayerChecker:
    return LayerChecker()


class TestTheContractIsStated:
    def test_the_six_items_are_named(self):
        assert CHECKER_ITEMS == (
            "missing",
            "empty",
            "unevidenced",
            "malformed",
            "contradictory",
            "off_topic",
        )

    def test_four_are_code_and_two_need_a_model(self):
        assert CODE_ITEMS == ("missing", "empty", "unevidenced", "malformed")
        assert MODEL_ITEMS == ("contradictory", "off_topic")
        assert set(CODE_ITEMS) | set(MODEL_ITEMS) == set(CHECKER_ITEMS)
        assert not set(CODE_ITEMS) & set(MODEL_ITEMS)

    def test_a_verdict_says_which_items_it_asserted_and_which_it_did_not(self, checker):
        """The doctrine's own words: a checker that cannot say which of the six it
        is asserting is not a checker. Silence about the two unimplemented ones
        would read as a clean bill of health on all six."""
        verdict = checker.check(expected=1, batch=[_stage("a")], results=[_ok("a")])
        assert verdict.asserted == CODE_ITEMS
        assert verdict.not_asserted == MODEL_ITEMS

    def test_a_clean_layer_passes(self, checker):
        verdict = checker.check(
            expected=2, batch=[_stage("a"), _stage("b")], results=[_ok("a"), _ok("b")]
        )
        assert verdict.passed, verdict.failures
        assert not verdict.failures


class TestItemOneMissing:
    def test_a_branch_that_never_returned_is_caught_by_count(self, checker):
        """Not by its slot being empty — by the number it was told to expect."""
        verdict = checker.check(expected=3, batch=[_stage("a"), _stage("b")], results=[_ok("a")])
        assert not verdict.passed
        assert any("missing" in f for f in verdict.failures), verdict.failures

    def test_a_none_result_counts_as_missing(self, checker):
        """`asyncio.gather(..., return_exceptions=True)` converts a thrower into a
        slot the host filled; a host that drops it makes a short list look
        complete."""
        verdict = checker.check(
            expected=2, batch=[_stage("a"), _stage("b")], results=[_ok("a"), None]
        )
        assert not verdict.passed
        assert any("missing" in f for f in verdict.failures)

    def test_an_expected_count_of_zero_is_a_programming_error(self, checker):
        with pytest.raises(ValueError, match="expected"):
            checker.check(expected=0, batch=[], results=[])


class TestItemTwoEmpty:
    def test_a_success_with_no_summary_and_no_rows_is_empty(self, checker):
        hollow = StageResult(stage_id="b", status="success", summary="", query_result=None)
        verdict = checker.check(
            expected=2, batch=[_stage("a"), _stage("b")], results=[_ok("a"), hollow]
        )
        assert not verdict.passed
        assert any("empty" in f and "b" in f for f in verdict.failures), verdict.failures

    def test_zero_rows_with_a_query_is_not_empty(self, checker):
        """An answered question with no matching rows is a result, not a hole.

        This is the same distinction `StageValidator` had to learn: all seven
        production `stage_validation` failures said "missing expected columns"
        and at least two named columns the query provably selected — it matched
        zero rows, and emptiness is what `min_rows` is for.
        """
        empty_but_answered = StageResult(
            stage_id="b",
            status="success",
            query="SELECT * FROM t WHERE 1=0",
            query_result=QueryResult(columns=[], rows=[], row_count=0),
            summary="no rows matched",
        )
        verdict = checker.check(
            expected=2, batch=[_stage("a"), _stage("b")], results=[_ok("a"), empty_but_answered]
        )
        assert verdict.passed, verdict.failures


class TestItemThreeUnevidenced:
    def test_a_data_stage_claiming_success_with_no_receipt_is_rejected(self, checker):
        """The item most checkers are missing. Whether the claim is WRONG is items
        5-6's business; this one is about a claim nobody downstream can check."""
        no_receipt = StageResult(
            stage_id="b",
            status="success",
            summary="revenue grew 12%",
            query=None,
            query_result=None,
        )
        verdict = checker.check(
            expected=2, batch=[_stage("a"), _stage("b")], results=[_ok("a"), no_receipt]
        )
        assert not verdict.passed
        assert any("unevidenced" in f for f in verdict.failures), verdict.failures

    def test_a_text_stage_is_evidenced_by_its_summary(self, checker):
        """`search_codebase` and friends produce prose by design. Demanding rows
        of them is the false-positive `StageValidator` already learned to avoid,
        and the exempt set is imported from it rather than copied."""
        from app.agents.stage_validator import _TEXT_STAGE_TOOLS

        for tool in sorted(_TEXT_STAGE_TOOLS):
            prose = StageResult(stage_id="t", status="success", summary="found the handler")
            verdict = checker.check(expected=1, batch=[_stage("t", tool)], results=[prose])
            assert verdict.passed, f"{tool}: {verdict.failures}"

    def test_the_exempt_set_is_not_a_second_copy(self):
        """One definition. A second list of text tools is how two sides of a
        split come to disagree — the `failure_kind` lesson, applied here."""
        import inspect

        from app.agents import layer_checker

        src = inspect.getsource(layer_checker)
        assert "_TEXT_STAGE_TOOLS" in src
        assert "analyze_results" not in src.replace("_TEXT_STAGE_TOOLS", ""), (
            "the text-tool names must come from stage_validator, not be re-listed"
        )


class TestItemFourMalformed:
    def test_rows_without_columns_break_the_convergence(self, checker):
        broken = StageResult(
            stage_id="b",
            status="success",
            query="SELECT 1",
            query_result=QueryResult(columns=[], rows=[[1], [2]], row_count=2),
            summary="two rows",
        )
        verdict = checker.check(
            expected=2, batch=[_stage("a"), _stage("b")], results=[_ok("a"), broken]
        )
        assert not verdict.passed
        assert any("malformed" in f for f in verdict.failures), verdict.failures

    def test_a_row_wider_than_its_columns_is_malformed(self, checker):
        ragged = StageResult(
            stage_id="b",
            status="success",
            query="SELECT 1",
            query_result=QueryResult(columns=["a"], rows=[[1, 2, 3]], row_count=1),
            summary="one row",
        )
        verdict = checker.check(
            expected=2, batch=[_stage("a"), _stage("b")], results=[_ok("a"), ragged]
        )
        assert not verdict.passed
        assert any("malformed" in f for f in verdict.failures)


class TestConfidenceIsAHintAndNotAGate:
    def test_the_checker_takes_no_confidence_argument(self):
        """*Under-confident* was demoted to a hint deliberately: an uncalibrated
        judge is an opinion with a number attached, and for anything consequential
        the control is a deterministic limit or a human — never a classifier's
        confidence. Low confidence flags; absent evidence blocks.
        """
        import inspect

        sig = inspect.signature(LayerChecker.check)
        assert "confidence" not in sig.parameters


class TestTheVerdictIsRecordable:
    def test_it_is_frozen_and_carries_its_reasons(self, checker):
        verdict = checker.check(
            expected=2, batch=[_stage("a"), _stage("b")], results=[_ok("a"), None]
        )
        assert isinstance(verdict, LayerVerdict)
        with pytest.raises(Exception):
            verdict.passed = True  # type: ignore[misc]

    def test_rejections_are_counted_per_item(self, checker):
        """ "A checker that has never rejected anything is a finding" is only
        askable if the verdicts are recorded as scores with a source."""
        verdict = checker.check(
            expected=2, batch=[_stage("a"), _stage("b")], results=[_ok("a"), None]
        )
        assert verdict.rejected_items, "the verdict must say WHICH items rejected"
        assert set(verdict.rejected_items) <= set(CHECKER_ITEMS)


# --------------------------------------------------------------------------- #
# The wiring: the convergence must depend on the CHECKER, not on the layer
# --------------------------------------------------------------------------- #


class TestTheExecutorConsultsIt:
    """ "Wire the convergence to the checker, not to the layer."

    If synthesis also takes a direct edge from a branch, the gate has a bypass
    and the shape is decoration. So the executor must consult the checker after a
    parallel batch and refuse to continue on a rejection.
    """

    def test_the_executor_holds_a_checker(self):
        import inspect

        from app.agents.stage_executor import StageExecutor

        assert "layer_checker" in inspect.signature(StageExecutor.__init__).parameters, (
            "the checker must be injectable, or a test cannot watch it refuse"
        )

    def test_it_is_consulted_only_for_a_layer_of_more_than_one(self):
        """A single stage has no siblings to compare, and paying a cross-item gate
        on a one-item layer is the barrier the doctrine says most convergences do
        not need."""
        import inspect

        from app.agents import stage_executor

        src = inspect.getsource(stage_executor)
        assert "len(batch) > 1" in src, (
            "the cross-item gate belongs behind a >1 guard; a one-stage layer has "
            "nothing to compare"
        )

    @pytest.mark.asyncio
    async def test_a_rejected_layer_stops_the_run_instead_of_converging(self):
        """The property the whole file exists for: a bad sibling must not reach
        the synthesis node."""
        from unittest.mock import AsyncMock, MagicMock, create_autospec

        from app.agents.base import AgentContext
        from app.agents.stage_context import ExecutionPlan, StageContext
        from app.agents.stage_executor import StageExecutor
        from app.agents.stage_validator import StageValidationOutcome, StageValidator
        from app.connectors.base import ConnectionConfig
        from app.core.workflow_tracker import WorkflowTracker

        # Two independent stages in one layer, then a synthesis that depends on both.
        a, b = _stage("a"), _stage("b")
        syn = PlanStage(stage_id="syn", description="s", tool="synthesize", depends_on=["a", "b"])
        plan = ExecutionPlan(plan_id="p", question="q", stages=[a, b, syn])

        validator = MagicMock(spec=StageValidator)
        validator.validate = MagicMock(return_value=StageValidationOutcome(passed=True))

        llm = MagicMock()
        llm.complete = AsyncMock()

        rejecting = MagicMock()
        rejecting.check = MagicMock(
            return_value=LayerVerdict(
                passed=False,
                asserted=CODE_ITEMS,
                not_asserted=MODEL_ITEMS,
                failures=["empty: stage 'b' succeeded with no summary and no result"],
                rejected_items=("empty",),
            )
        )

        synth = AsyncMock()
        executor = StageExecutor(
            sql_agent=AsyncMock(),
            knowledge_agent=AsyncMock(),
            llm_router=llm,
            tracker=create_autospec(WorkflowTracker, instance=True),
            validator=validator,
            layer_checker=rejecting,
        )
        # Both stages "succeed" so nothing else can stop the run.
        executor._execute_stage = AsyncMock(side_effect=lambda st, *_a, **_k: _ok(st.stage_id))  # type: ignore[method-assign]
        executor._synthesize = synth  # type: ignore[method-assign]

        ctx = AgentContext(
            project_id="p",
            connection_config=ConnectionConfig(db_type="postgres"),
            user_question="q",
            chat_history=[],
            llm_router=llm,
            tracker=create_autospec(WorkflowTracker, instance=True),
            workflow_id="wf-1",
        )
        outcome = await executor.execute(plan, ctx, stage_ctx=StageContext(plan=plan))

        rejecting.check.assert_called_once()
        assert outcome.status == "stage_failed", (
            f"a rejected layer must stop the run; got {outcome.status}"
        )
        synth.assert_not_awaited(), "synthesis must not run on a flagged layer"

    @pytest.mark.asyncio
    async def test_the_reject_counter_actually_records(self):
        """The metric call itself, executed — not asserted from the source.

        The first version of this block reached for a module-level `metrics` and
        an `increment(name, dict)` signature that do not exist. It sat inside a
        broad `except`, so the counter would have recorded NOTHING, forever, with
        no test noticing. The real API is `get_metrics_collector().inc(name,
        **labels)`, and the handler is gone: `inc` swallows its own failures, so
        one here could only hide a wrong call.
        """
        from unittest.mock import AsyncMock, MagicMock, create_autospec

        from app.agents.stage_executor import StageExecutor
        from app.core.metrics import get_metrics_collector
        from app.core.workflow_tracker import WorkflowTracker

        collector = get_metrics_collector()
        before = collector.snapshot() if hasattr(collector, "snapshot") else None

        executor = StageExecutor(
            sql_agent=AsyncMock(),
            knowledge_agent=AsyncMock(),
            llm_router=MagicMock(),
            tracker=create_autospec(WorkflowTracker, instance=True),
        )
        await executor._emit_layer_verdict(
            "wf-1",
            [_stage("a"), _stage("b")],
            LayerVerdict(
                passed=False,
                asserted=CODE_ITEMS,
                not_asserted=MODEL_ITEMS,
                failures=["empty: stage 'b' ..."],
                rejected_items=("empty",),
            ),
        )

        rendered = collector.render_prometheus() if hasattr(collector, "render_prometheus") else ""
        assert "layer_checker_reject_total" in rendered, (
            "the reject counter did not record — the metric call is wrong and the "
            f"old handler would have hidden it. before={before!r}"
        )
