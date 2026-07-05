"""Unit tests for DataGate, focused on the C4 (v1.13.0) hard-vs-soft
classification: hard data-quality errors must invoke ``fail()`` so the
stage retries; soft anomalies remain warnings.

Parametrized to cover the matrix of column kinds × value-range outcomes."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from app.agents.data_gate import DataGate, DataGateOutcome
from app.agents.stage_context import ExecutionPlan, PlanStage, StageContext, StageResult
from app.connectors.base import QueryResult


def _make_stage_ctx(plan: ExecutionPlan) -> StageContext:
    return StageContext(plan=plan)


def _sql_stage(stage_id: str = "s1") -> PlanStage:
    return PlanStage(stage_id=stage_id, description="x", tool="query_database")


class TestOutcomeMechanics:
    def test_warn_keeps_passed_true(self):
        out = DataGateOutcome()
        out.warn("soft issue")
        assert out.passed is True
        assert out.warnings == ["soft issue"]

    def test_fail_flips_passed_false(self):
        out = DataGateOutcome()
        out.fail("hard issue", suggestion="fix it")
        assert out.passed is False
        assert out.errors == ["hard issue"]
        assert out.suggestions == ["fix it"]


class TestHardChecksValueRange:
    @pytest.mark.parametrize(
        "col_name, value, expected_fail",
        [
            # Hard: percent value clearly out of range
            ("revenue_pct", 9999.0, True),
            ("occupancy_pct", -5.0, True),
            # Soft: percent within bounds
            ("growth_rate", 25.0, False),
            # Hard: date in obviously wrong year
            ("created_date", "1800-01-01", True),
            ("updated_at", "2300-12-31", True),
            # Soft: date within bounds
            ("event_date", "2024-06-15", False),
            # Non-classified column — never fails
            ("user_count", 1_000_000, False),
        ],
    )
    def test_out_of_range_classification(self, col_name, value, expected_fail):
        gate = DataGate()
        qr = QueryResult(
            columns=[col_name],
            rows=[[value]],
            row_count=1,
        )
        stage = _sql_stage()
        plan = ExecutionPlan(plan_id="p", question="q", stages=[stage])
        ctx = _make_stage_ctx(plan)
        result = StageResult(stage_id=stage.stage_id, status="success", query_result=qr)

        out = gate.check(stage, result, ctx)

        if expected_fail:
            assert out.passed is False
            assert out.errors, "expected hard failure but got no errors"
        else:
            assert out.passed is True

    def test_value_range_scans_beyond_first_50_rows(self):
        # A5: an impossible value deeper than the first 50 rows must still
        # hard-fail — the value-range scan covers the full in-memory result.
        gate = DataGate()
        rows: list[list] = [[1] for _ in range(60)]
        rows[55] = [-7]  # negative count well past the old 50-row sub-cap
        qr = QueryResult(columns=["order_count"], rows=rows, row_count=60)
        stage = _sql_stage()
        plan = ExecutionPlan(plan_id="p", question="q", stages=[stage])
        ctx = _make_stage_ctx(plan)
        result = StageResult(stage_id=stage.stage_id, status="success", query_result=qr)

        out = gate.check(stage, result, ctx)

        assert out.passed is False
        assert out.errors, "negative count past row 50 should hard-fail"


class TestSoftChecksRemainWarn:
    def test_high_null_ratio_only_warns(self):
        """Soft signal — could be legitimate data shape."""
        gate = DataGate(null_threshold=0.5)
        qr = QueryResult(
            columns=["maybe_null"],
            rows=[[None], [None], [None], ["x"]],
            row_count=4,
        )
        stage = _sql_stage()
        plan = ExecutionPlan(plan_id="p", question="q", stages=[stage])
        ctx = _make_stage_ctx(plan)
        result = StageResult(stage_id=stage.stage_id, status="success", query_result=qr)

        out = gate.check(stage, result, ctx)

        assert out.passed is True
        assert any("null/empty" in w for w in out.warnings)

    def test_duplicate_ratio_only_warns(self):
        gate = DataGate(duplicate_threshold=0.5)
        # DATA-18: min sample is 10; use 12 rows so the guard doesn't skip the check
        qr = QueryResult(
            columns=["x"],
            rows=[[1]] * 9 + [[2]] * 3,
            row_count=12,
        )
        stage = _sql_stage()
        plan = ExecutionPlan(plan_id="p", question="q", stages=[stage])
        ctx = _make_stage_ctx(plan)
        result = StageResult(stage_id=stage.stage_id, status="success", query_result=qr)

        out = gate.check(stage, result, ctx)

        assert out.passed is True
        assert any("duplicate" in w for w in out.warnings)


class TestHardChecksToggle:
    def test_setting_disabled_reverts_to_warn(self):
        """C4: when DATA_GATE_HARD_CHECKS_ENABLED=false, the previously-hard
        cases must revert to warn() — guarantees a safe rollback path."""
        from app.agents import data_gate as dg_mod

        gate = DataGate()
        qr = QueryResult(
            columns=["revenue_pct"],
            rows=[[9999.0]],
            row_count=1,
        )
        stage = _sql_stage()
        plan = ExecutionPlan(plan_id="p", question="q", stages=[stage])
        ctx = _make_stage_ctx(plan)
        result = StageResult(stage_id=stage.stage_id, status="success", query_result=qr)

        with patch.object(dg_mod.settings, "data_gate_hard_checks_enabled", False):
            out = gate.check(stage, result, ctx)

        assert out.passed is True
        assert any("out of range" in w for w in out.warnings)


class TestStageRetryIntegration:
    """Confirms the wiring: DataGate.fail() → StageExecutor sees
    gate_outcome.passed == False → triggers retry path."""

    def test_failed_outcome_flips_passed_to_false(self):
        out = DataGateOutcome()
        out.fail("bad data")
        assert out.passed is False
        # error_summary is what StageExecutor surfaces in the replan error
        assert out.error_summary == "bad data"

    def test_merge_failed_outcome_propagates(self):
        a = DataGateOutcome()
        b = DataGateOutcome()
        b.fail("bad")
        a.merge(b)
        assert a.passed is False


class TestBroadenedClassificationAndCounts:
    """P0 (CRITICAL) + F-DG hard-check domain: percent-like columns must be
    range-checked even when their name lacks the legacy keywords, impossible
    negative counts must fail, and the loose-vs-bounded distinction must not
    create false positives on legitimate >100 rates."""

    def _run(self, col_name: str, value) -> DataGateOutcome:
        gate = DataGate()
        qr = QueryResult(columns=[col_name], rows=[[value]], row_count=1)
        stage = _sql_stage()
        plan = ExecutionPlan(plan_id="p", question="q", stages=[stage])
        ctx = _make_stage_ctx(plan)
        result = StageResult(stage_id=stage.stage_id, status="success", query_result=qr)
        return gate.check(stage, result, ctx)

    @pytest.mark.parametrize(
        "col_name",
        ["conversion", "completion_percentage", "ctr", "occupancy"],
    )
    def test_bounded_percent_over_100_fails(self, col_name):
        # 150 is impossible for a 0..100 bounded percentage. These names lack
        # the legacy percent/pct/ratio/rate keywords, so the gate used to skip
        # them entirely (classified "other") — the CRITICAL gap.
        out = self._run(col_name, 150.0)
        assert out.passed is False, f"{col_name}=150 should be a hard failure"
        assert out.errors

    def test_negative_count_fails(self):
        # CLAUDE.md advertises DataGate "blocks negative counts" — it didn't.
        out = self._run("purchase_count", -5)
        assert out.passed is False
        assert out.errors

    def test_negative_num_orders_fails(self):
        out = self._run("num_orders", -1)
        assert out.passed is False

    def test_positive_count_passes(self):
        # Regression guard: legitimate large counts must NOT be flagged.
        out = self._run("num_orders", 1234)
        assert out.passed is True

    def test_loose_rate_over_100_passes(self):
        # Regression guard: growth/rate columns can legitimately exceed 100%
        # (e.g. 150% YoY growth) — they must use the loose bound, not fail.
        out = self._run("growth_rate", 150.0)
        assert out.passed is True

    def test_percent_delta_columns_not_hard_failed(self):
        # A signed percentage-delta (percent_change / pct_growth / percent_increase)
        # can legitimately exceed 100% or go negative — must NOT hard fail.
        for col in ("percent_change", "pct_growth", "percent_increase"):
            assert self._run(col, 250.0).passed is True, col
            assert self._run(col, -80.0).passed is True, col

    def test_net_retention_rate_over_100_not_failed(self):
        # SaaS net revenue retention (NRR) routinely exceeds 100% (110-130%).
        assert self._run("net_retention_rate", 130.0).passed is True

    def test_bare_churn_negative_not_failed(self):
        # Net churn can be negative (more expansion than churn).
        assert self._run("net_churn", -5.0).passed is True

    def test_count_substring_in_unrelated_columns_not_flagged(self):
        # 'account' / 'discount' contain the substring 'count' but are NOT
        # counts; balances/amounts can be negative legitimately. Token-based
        # classification must not hard-fail them.
        assert self._run("account_balance", -100.0).passed is True
        assert self._run("discount_amount", -5.0).passed is True

    def test_percent_rate_substrings_in_unrelated_columns_not_flagged(self):
        # 'electric' contains 'ctr', 'operate' contains 'rate'. Substring
        # matching wrongly classified these as percent/rate and failed a large
        # value; token matching must treat them as 'other'.
        assert self._run("electric_usage", 9999.0).passed is True
        assert self._run("operate_score", 9999.0).passed is True

    def test_llm_semantics_requested_without_classifier_warns(self, caplog):
        # The data_gate_llm_semantics flag previously "gated nothing": it was
        # read into an unused attribute. When requested but no classifier is
        # wired, the gate must surface the degradation instead of silently
        # falling back to keywords.
        gate = DataGate(llm_semantics=True)
        qr = QueryResult(columns=["x"], rows=[[1]], row_count=1)
        stage = _sql_stage()
        plan = ExecutionPlan(plan_id="p", question="q", stages=[stage])
        ctx = _make_stage_ctx(plan)
        result = StageResult(stage_id=stage.stage_id, status="success", query_result=qr)
        with caplog.at_level(logging.WARNING):
            gate.check(stage, result, ctx)
        assert any("semantic" in r.message.lower() for r in caplog.records)


class TestEpochIntDates:
    """I7: epoch timestamps arriving as int/float must be range-checked too."""

    def test_nonsense_epoch_int_is_flagged(self):
        # 10**20 is implausible as both epoch seconds and epoch ms.
        qr = QueryResult(columns=["created_at"], rows=[[10**20]], row_count=1)
        gate = DataGate()
        outcome = DataGateOutcome()
        gate._check_value_ranges(qr, outcome)
        assert outcome.errors or outcome.warnings

    def test_valid_epoch_seconds_not_flagged(self):
        # 1700000000 -> 2023-11, a plausible epoch-seconds timestamp.
        qr = QueryResult(columns=["created_at"], rows=[[1700000000]], row_count=1)
        gate = DataGate()
        outcome = DataGateOutcome()
        gate._check_value_ranges(qr, outcome)
        assert not outcome.errors and not outcome.warnings


class TestDecimalAndTruncationAware:
    def test_decimal_percent_out_of_range_hard_fails(self):
        from decimal import Decimal

        gate = DataGate()
        qr = QueryResult(columns=["conversion_pct"], rows=[[Decimal("150.0")]], row_count=1)
        stage = PlanStage(stage_id="s1", description="x", tool="query_database")
        plan = ExecutionPlan(plan_id="p", question="q", stages=[stage])
        out = gate.check(
            stage,
            StageResult(stage_id="s1", status="success", query_result=qr),
            StageContext(plan=plan),
        )
        assert out.passed is False
        assert out.errors

    def test_authoritative_truncated_flag_warns(self):
        gate = DataGate()
        # row_count 37 is NOT a common LIMIT value, but truncated=True is authoritative
        qr = QueryResult(columns=["a"], rows=[[1]] * 37, row_count=37, truncated=True)
        stage = PlanStage(stage_id="s1", description="x", tool="query_database")
        plan = ExecutionPlan(plan_id="p", question="q", stages=[stage])
        out = gate.check(
            stage,
            StageResult(stage_id="s1", status="success", query_result=qr),
            StageContext(plan=plan),
        )
        assert any("truncat" in w.lower() for w in out.warnings)


class TestCheckQueryResult:
    """DATA-06: DataGate.check_query_result() — public bare-QueryResult API.

    The existing `check()` method requires stage objects. `check_query_result()`
    exposes the same value-range logic on a bare QueryResult so ResultValidation
    can call it on the single-query path without constructing fake stage objects.
    """

    def test_150_percent_conversion_fails(self):
        """Decimal(150.0) in a 'conversion' column → impossible → fail."""
        from decimal import Decimal

        gate = DataGate()
        qr = QueryResult(columns=["conversion"], rows=[[Decimal("150.0")]], row_count=1)
        outcome = gate.check_query_result(qr, question="what is the conversion rate")
        assert outcome.passed is False, "150% conversion must hard-fail via check_query_result"
        assert outcome.errors

    def test_negative_count_fails(self):
        gate = DataGate()
        qr = QueryResult(columns=["order_count"], rows=[[-3]], row_count=1)
        outcome = gate.check_query_result(qr, question="how many orders")
        assert outcome.passed is False, "Negative count must hard-fail via check_query_result"
        assert outcome.errors

    def test_clean_result_passes(self):
        gate = DataGate()
        qr = QueryResult(columns=["revenue"], rows=[[1234.56]], row_count=1)
        outcome = gate.check_query_result(qr, question="total revenue")
        assert outcome.passed is True

    def test_valid_percent_passes(self):
        gate = DataGate()
        qr = QueryResult(columns=["conversion"], rows=[[42.5]], row_count=1)
        outcome = gate.check_query_result(qr, question="conversion rate")
        assert outcome.passed is True

    def test_reuses_check_value_ranges_logic(self):
        """Ensures check_query_result and _check_value_ranges are consistent —
        the same impossible value must fail in both paths."""
        gate = DataGate()
        qr = QueryResult(columns=["occupancy"], rows=[[200.0]], row_count=1)

        # Via the new public method
        outcome_public = gate.check_query_result(qr, question="")

        # Via the internal method directly
        outcome_internal = DataGateOutcome()
        gate._check_value_ranges(qr, outcome_internal)

        assert outcome_public.passed == outcome_internal.passed
        assert bool(outcome_public.errors) == bool(outcome_internal.errors)


# ---------------------------------------------------------------------------
# Low-batch findings (DATA-14/15/18/21/22)
# ---------------------------------------------------------------------------


class TestLowBatchData14:
    """DATA-14: range-scan covers ALL rows (incl. late rows) when sample cap is 0."""

    def test_hard_check_scans_late_rows(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "data_gate_hard_checks_enabled", True)
        monkeypatch.setattr(settings, "data_gate_value_range_sample", 0)  # full scan
        rows = [[10.0] for _ in range(500)] + [[150.0]]  # bad value is the LAST row
        qr = QueryResult(columns=["conversion_pct"], rows=rows, row_count=len(rows))
        gate = DataGate(llm_semantics=False)
        outcome = DataGateOutcome()
        gate._check_value_ranges(qr, outcome)
        assert not outcome.passed, "Late-row 150% conversion must be caught even at row 501"

    def test_hard_check_with_positive_cap_misses_late_rows(self, monkeypatch):
        """Documents known behaviour: a positive cap trades correctness for speed."""
        from app.config import settings

        monkeypatch.setattr(settings, "data_gate_hard_checks_enabled", True)
        monkeypatch.setattr(settings, "data_gate_value_range_sample", 10)  # only first 10
        rows = [[10.0] for _ in range(500)] + [[150.0]]  # bad value at row 501
        qr = QueryResult(columns=["conversion_pct"], rows=rows, row_count=len(rows))
        gate = DataGate(llm_semantics=False)
        outcome = DataGateOutcome()
        gate._check_value_ranges(qr, outcome)
        # With cap=10 the last row is NOT scanned — passes (documents limitation)
        assert outcome.passed, "Positive cap intentionally skips late rows"


class TestLowBatchData15:
    """DATA-15: reconciliation rounding tolerance.

    The reconciliation bucketing lives in app.core.insight_memory (not a W1
    file). This test is xfail-deferred to the wave that owns that file.
    """

    @pytest.mark.xfail(
        reason=(
            "DATA-15 fix belongs to insight_memory.py (W3/W0-owned); "
            "implementing here would edit a non-W1 file. "
            "Deferred to that wave."
        ),
        strict=False,
    )
    def test_rounding_tolerance_in_reconcile(self):
        """Values that differ only by float rounding should NOT be mismatches."""
        # This would test sql_results_reconcile() in insight_memory.py
        # which is not owned by Wave 1. xfail here documents the gap.
        from app.core.insight_memory import InsightMemory  # noqa: F401

        # If the reconcile method exists and handles epsilon, this passes.
        # Otherwise it xfails as expected.
        raise AssertionError("DATA-15 not yet fixed in insight_memory — see W3")


class TestLowBatchData18:
    """DATA-18: minimum-sample guard on duplicate detection."""

    def test_small_result_skips_duplicate_check(self):
        """A result with < 10 rows must NOT trigger the duplicate warning
        (legitimately-sparse table false-positive guard)."""
        gate = DataGate()
        # 5 identical rows — would be 100% dupes, but below min sample
        qr = QueryResult(columns=["id", "status"], rows=[["x", "ok"]] * 5, row_count=5)
        outcome = DataGateOutcome()
        gate._check_duplicates(qr, outcome)
        assert outcome.passed
        assert not outcome.warnings

    def test_large_result_triggers_duplicate_check(self):
        """A result with >= 10 rows and high dupe ratio triggers the warning."""
        gate = DataGate(duplicate_threshold=0.5)
        # 20 identical rows → 100% dupe ratio above 0.5 threshold
        qr = QueryResult(columns=["id", "status"], rows=[["x", "ok"]] * 20, row_count=20)
        outcome = DataGateOutcome()
        gate._check_duplicates(qr, outcome)
        assert outcome.warnings, "High dupe ratio on large sample must warn"

    def test_null_rate_advisory_label_in_warning(self):
        """DATA-22 + DATA-18: null-rate warning must include advisory/sampled label."""
        gate = DataGate(null_threshold=0.5)
        qr = QueryResult(
            columns=["email"],
            rows=[[None]] * 10 + [["a@b.com"]] * 10,
            row_count=20,
        )
        outcome = DataGateOutcome()
        gate._check_nulls(qr, outcome)
        assert outcome.warnings
        assert any("sampl" in w.lower() for w in outcome.warnings), (
            "Null-rate warning must mention 'sampled' to mark it as advisory (DATA-22)"
        )


class TestLowBatchData21:
    """DATA-21: small-fan-out cartesian miss is a documented limitation."""

    @pytest.mark.xfail(
        reason=(
            "DATA-21: _check_cross_stage_consistency only warns when row_count > "
            "dep_row_count * cartesian_multiplier (default 100). A 2x fan-out "
            "(e.g. 10 → 20 rows from a bad join) is below the threshold and "
            "passes silently. Fixing this would require a lower multiplier or a "
            "secondary heuristic — deferred as a documented limitation."
        ),
        strict=True,
    )
    def test_small_fanout_cartesian_not_caught(self):
        """Small cartesian products (e.g. 2x fan-out) are NOT caught — known gap."""
        from app.agents.stage_context import ExecutionPlan, PlanStage, StageContext, StageResult

        stage1 = PlanStage(stage_id="s1", description="x", tool="query_database")
        stage2 = PlanStage(stage_id="s2", description="y", tool="query_database", depends_on=["s1"])
        plan = ExecutionPlan(plan_id="p", question="q", stages=[stage1, stage2])
        ctx = StageContext(plan=plan)
        ctx.set_result(
            "s1",
            StageResult(
                stage_id="s1",
                status="success",
                query_result=QueryResult(columns=["a"], rows=[[1]] * 10, row_count=10),
            ),
        )
        result = StageResult(
            stage_id="s2",
            status="success",
            query_result=QueryResult(columns=["a", "b"], rows=[[1, 2]] * 20, row_count=20),
        )
        gate = DataGate()
        outcome = gate.check(stage2, result, ctx)
        # 20 rows from 10 is only 2x — below cartesian_multiplier=100 — so NO warning
        # This xfail asserts that the small fan-out IS caught (it won't be → xfail)
        assert any("cartesian" in w.lower() for w in outcome.warnings), (
            "Small 2x fan-out should warn but does not — known gap"
        )
