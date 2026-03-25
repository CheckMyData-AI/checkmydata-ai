"""Per-stage validation for the multi-stage pipeline.

Checks data shape, row-count bounds, cross-stage consistency, and
business rules after each stage completes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.agents.stage_context import PlanStage, StageContext, StageResult

logger = logging.getLogger(__name__)


@dataclass
class StageValidationOutcome:
    passed: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def error_summary(self) -> str:
        return "; ".join(self.errors) if self.errors else ""

    def fail(self, msg: str) -> None:
        self.passed = False
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "warnings": self.warnings,
            "errors": self.errors,
        }


class StageValidator:
    """Validates a single stage result against its plan-defined criteria."""

    def __init__(self, *, strict_row_bounds: bool = False) -> None:
        self._strict_row_bounds = strict_row_bounds

    def validate(
        self,
        stage: PlanStage,
        result: StageResult,
        stage_ctx: StageContext,
    ) -> StageValidationOutcome:
        outcome = StageValidationOutcome()

        if result.status == "error":
            outcome.fail(f"Stage returned error: {result.error or 'unknown'}")
            return outcome

        qr = result.query_result
        v = stage.validation

        if v.expected_columns and qr:
            missing = set(v.expected_columns) - {c.lower() for c in qr.columns}
            if missing:
                outcome.fail(f"Missing expected columns: {sorted(missing)}")

        strict = self._strict_row_bounds or getattr(v, "strict_row_bounds", False)
        if qr:
            if v.min_rows is not None and qr.row_count < v.min_rows:
                msg = f"Expected at least {v.min_rows} rows, got {qr.row_count}"
                if strict:
                    outcome.fail(msg)
                else:
                    outcome.warn(msg)
            if v.max_rows is not None and qr.row_count > v.max_rows:
                msg = f"Got {qr.row_count} rows, expected at most {v.max_rows}"
                if strict:
                    outcome.fail(msg)
                else:
                    outcome.warn(msg)

        if v.cross_stage_checks:
            for check in v.cross_stage_checks:
                self._evaluate_cross_check(check, result, stage_ctx, outcome)

        if v.business_rules and qr:
            for rule in v.business_rules:
                self._evaluate_business_rule(rule, result, outcome)

        return outcome

    @staticmethod
    def _evaluate_cross_check(
        check: str,
        result: StageResult,
        stage_ctx: StageContext,
        outcome: StageValidationOutcome,
    ) -> None:
        """Evaluate a cross-stage consistency check.

        Supported format: ``row_count <= stage_id.row_count * N``
        """
        pattern = re.compile(
            r"row_count\s*(<=|>=|<|>|==)\s*(\w+)\.row_count\s*\*?\s*(\d+\.?\d*)?",
        )
        m = pattern.match(check.strip())
        if not m:
            logger.debug("Unrecognised cross-stage check format: %s", check)
            return

        op, ref_stage, multiplier_str = m.group(1), m.group(2), m.group(3)
        multiplier = float(multiplier_str) if multiplier_str else 1.0

        ref = stage_ctx.get_result(ref_stage)
        if not ref or not ref.query_result:
            logger.debug("Referenced stage '%s' has no result yet", ref_stage)
            return

        current_count = result.query_result.row_count if result.query_result else 0
        ref_count = ref.query_result.row_count * multiplier

        ops = {
            "<=": current_count <= ref_count,
            ">=": current_count >= ref_count,
            "<": current_count < ref_count,
            ">": current_count > ref_count,
            "==": current_count == ref_count,
        }

        if not ops.get(op, True):
            outcome.warn(
                f"Cross-stage check failed: row_count ({current_count}) "
                f"{op} {ref_stage}.row_count*{multiplier} ({ref_count})"
            )

    @staticmethod
    def _evaluate_business_rule(
        rule: str,
        result: StageResult,
        outcome: StageValidationOutcome,
    ) -> None:
        """Best-effort heuristic for simple business rules."""
        qr = result.query_result
        if not qr or not qr.rows:
            return

        rule_lower = rule.lower()
        if "no negative" in rule_lower:
            for col_idx, col in enumerate(qr.columns):
                try:
                    for row in qr.rows[:100]:
                        val = row[col_idx]
                        if isinstance(val, (int, float)) and val < 0:
                            outcome.warn(
                                f"Business rule '{rule}' violated: "
                                f"negative value {val} in column '{col}'"
                            )
                            return
                except (IndexError, TypeError):
                    continue
