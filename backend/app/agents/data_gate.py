"""DataGate — intermediate data-quality checks between pipeline stages.

Sits *after* StageValidator (plan-criteria) and complements
AgentResultValidator (structural) by inspecting the actual data content:

- Null / empty rate anomalies
- Type consistency within columns
- Duplicate-row detection
- Value-range sanity (dates, percentages, numeric sign)
- Cross-stage row-count consistency
- Truncation detection

Returns a ``DataGateOutcome`` that the executor can act on (warn, retry,
or replan).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.agents.stage_context import PlanStage, StageContext, StageResult
from app.connectors.base import QueryResult

logger = logging.getLogger(__name__)

_MAX_SAMPLE = 200
_HIGH_NULL_RATIO = 0.5
_HIGH_DUPLICATE_RATIO = 0.9


@dataclass
class DataGateOutcome:
    passed: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    @property
    def error_summary(self) -> str:
        return "; ".join(self.errors) if self.errors else ""

    def fail(self, msg: str, *, suggestion: str = "") -> None:
        self.passed = False
        self.errors.append(msg)
        if suggestion:
            self.suggestions.append(suggestion)

    def warn(self, msg: str, *, suggestion: str = "") -> None:
        self.warnings.append(msg)
        if suggestion:
            self.suggestions.append(suggestion)

    def merge(self, other: DataGateOutcome) -> None:
        if not other.passed:
            self.passed = False
        self.warnings.extend(other.warnings)
        self.errors.extend(other.errors)
        self.suggestions.extend(other.suggestions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "warnings": self.warnings,
            "errors": self.errors,
            "suggestions": self.suggestions,
        }


class DataGate:
    """Runs data-quality checks on a ``StageResult``."""

    def __init__(
        self,
        *,
        null_threshold: float = _HIGH_NULL_RATIO,
        duplicate_threshold: float = _HIGH_DUPLICATE_RATIO,
        max_sample: int = _MAX_SAMPLE,
    ) -> None:
        self._null_threshold = null_threshold
        self._dup_threshold = duplicate_threshold
        self._max_sample = max_sample

    def check(
        self,
        stage: PlanStage,
        result: StageResult,
        stage_ctx: StageContext,
    ) -> DataGateOutcome:
        outcome = DataGateOutcome()

        if result.status == "error":
            return outcome

        qr = result.query_result
        if qr is None or not qr.rows:
            return outcome

        self._check_nulls(qr, outcome)
        self._check_type_consistency(qr, outcome)
        self._check_duplicates(qr, outcome)
        self._check_value_ranges(qr, outcome)
        self._check_truncation(qr, stage, outcome)
        self._check_cross_stage_consistency(stage, result, stage_ctx, outcome)

        return outcome

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_nulls(self, qr: QueryResult, outcome: DataGateOutcome) -> None:
        """Flag columns where null/empty rate exceeds the threshold."""
        sample = qr.rows[: self._max_sample]
        if not sample:
            return
        n = len(sample)
        for col_idx, col_name in enumerate(qr.columns):
            nulls = 0
            for row in sample:
                try:
                    val = row[col_idx]
                except (IndexError, TypeError):
                    nulls += 1
                    continue
                if val is None or val == "" or (isinstance(val, float) and math.isnan(val)):
                    nulls += 1
            ratio = nulls / n
            if ratio >= self._null_threshold:
                outcome.warn(
                    f"Column '{col_name}' has {ratio:.0%} null/empty values "
                    f"({nulls}/{n} sampled rows)",
                    suggestion=(
                        f"Verify the query returns meaningful data for '{col_name}'; "
                        "consider adding a WHERE clause or choosing a different column."
                    ),
                )

    @staticmethod
    def _check_type_consistency(qr: QueryResult, outcome: DataGateOutcome) -> None:
        """Warn if a column has a mix of unrelated Python types."""
        sample = qr.rows[:_MAX_SAMPLE]
        if not sample:
            return
        for col_idx, col_name in enumerate(qr.columns):
            type_set: set[str] = set()
            for row in sample:
                try:
                    val = row[col_idx]
                except (IndexError, TypeError):
                    continue
                if val is None:
                    continue
                type_set.add(type(val).__name__)
            if len(type_set) > 2:
                outcome.warn(
                    f"Column '{col_name}' has mixed types: {sorted(type_set)}",
                    suggestion=(f"CAST '{col_name}' to a consistent type in the SQL query."),
                )

    def _check_duplicates(self, qr: QueryResult, outcome: DataGateOutcome) -> None:
        """Detect suspiciously high duplicate-row ratio."""
        sample = qr.rows[: self._max_sample]
        if len(sample) < 3:
            return
        seen: set[tuple] = set()
        dupes = 0
        for row in sample:
            key = tuple(row)
            if key in seen:
                dupes += 1
            else:
                seen.add(key)
        ratio = dupes / len(sample) if sample else 0
        if ratio >= self._dup_threshold:
            outcome.warn(
                f"{ratio:.0%} of sampled rows are exact duplicates ({dupes}/{len(sample)})",
                suggestion="Add DISTINCT or GROUP BY to the query if duplicates are unintended.",
            )

    @staticmethod
    def _check_value_ranges(qr: QueryResult, outcome: DataGateOutcome) -> None:
        """Sanity-check obviously out-of-range values."""
        sample = qr.rows[:_MAX_SAMPLE]
        if not sample:
            return
        col_lower = [c.lower() for c in qr.columns]
        for col_idx, col_name_lower in enumerate(col_lower):
            _is_pct = any(kw in col_name_lower for kw in ("percent", "pct", "ratio", "rate"))
            _is_date = any(
                kw in col_name_lower for kw in ("date", "created", "updated", "timestamp")
            )
            for row in sample[:50]:
                try:
                    val = row[col_idx]
                except (IndexError, TypeError):
                    continue
                if val is None:
                    continue
                if _is_pct and isinstance(val, (int, float)):
                    if val < -1 or val > 200:
                        outcome.warn(
                            f"Column '{qr.columns[col_idx]}' has value {val} "
                            "which looks out of range for a percentage.",
                        )
                        break
                if _is_date and isinstance(val, str):
                    try:
                        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                        if dt.year < 1900 or dt.year > 2100:
                            outcome.warn(
                                f"Column '{qr.columns[col_idx]}' has suspicious date: {val}",
                            )
                            break
                    except (ValueError, TypeError):
                        pass

    @staticmethod
    def _check_truncation(
        qr: QueryResult,
        stage: PlanStage,
        outcome: DataGateOutcome,
    ) -> None:
        """Warn if the result looks truncated."""
        common_limits = {100, 500, 1000, 5000, 10000, 50000}
        if qr.row_count in common_limits:
            outcome.warn(
                f"Row count ({qr.row_count}) is a common LIMIT value — result may be truncated.",
                suggestion="Verify the query's LIMIT clause returns all needed data.",
            )

    def _check_cross_stage_consistency(
        self,
        stage: PlanStage,
        result: StageResult,
        stage_ctx: StageContext,
        outcome: DataGateOutcome,
    ) -> None:
        """Lightweight cross-stage data consistency checks."""
        qr = result.query_result
        if not qr or not stage.depends_on:
            return
        for dep_id in stage.depends_on:
            dep = stage_ctx.get_result(dep_id)
            if not dep or not dep.query_result:
                continue
            dep_qr = dep.query_result
            if dep_qr.row_count > 0 and qr.row_count > dep_qr.row_count * 100:
                outcome.warn(
                    f"Stage '{stage.stage_id}' produced {qr.row_count} rows "
                    f"from dependency '{dep_id}' which had {dep_qr.row_count} — "
                    "possible cartesian join.",
                    suggestion="Check for missing JOIN conditions in the query.",
                )
