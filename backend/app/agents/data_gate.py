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
from app.config import settings
from app.connectors.base import QueryResult

logger = logging.getLogger(__name__)

# Legacy constants kept for tests / backwards-compat imports. New code should
# read thresholds from :data:`app.config.settings` (``data_gate_*``).
_MAX_SAMPLE = settings.data_gate_max_sample
_HIGH_NULL_RATIO = settings.data_gate_high_null_ratio
_HIGH_DUPLICATE_RATIO = settings.data_gate_high_duplicate_ratio


# Keyword-based semantic hints used when LLM classification is disabled.
# Kept intentionally narrow — they're only a fallback, not the source of truth.
_PERCENT_KEYWORDS: tuple[str, ...] = ("percent", "pct", "ratio", "rate")
_DATE_KEYWORDS: tuple[str, ...] = ("date", "created", "updated", "timestamp")


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
    """Runs data-quality checks on a ``StageResult``.

    Thresholds come from :mod:`app.config` (``data_gate_*`` knobs) so ops
    can tune them without redeploying. Explicit constructor args still win
    (used by tests).
    """

    def __init__(
        self,
        *,
        null_threshold: float | None = None,
        duplicate_threshold: float | None = None,
        max_sample: int | None = None,
        llm_semantics: bool | None = None,
        column_semantic_classifier: Any = None,
    ) -> None:
        self._null_threshold = (
            null_threshold
            if null_threshold is not None
            else settings.data_gate_high_null_ratio
        )
        self._dup_threshold = (
            duplicate_threshold
            if duplicate_threshold is not None
            else settings.data_gate_high_duplicate_ratio
        )
        self._max_sample = (
            max_sample if max_sample is not None else settings.data_gate_max_sample
        )
        self._llm_semantics = (
            llm_semantics
            if llm_semantics is not None
            else settings.data_gate_llm_semantics
        )
        # Optional callable: ``(columns, sample_rows) -> dict[col_name, kind]``
        # where ``kind`` ∈ {"percent", "date", "amount", "id", "other"}. When
        # present, it takes precedence over the keyword heuristic.
        self._semantic_classifier = column_semantic_classifier

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

    def _check_type_consistency(self, qr: QueryResult, outcome: DataGateOutcome) -> None:
        """Warn if a column has a mix of unrelated Python types."""
        sample = qr.rows[: self._max_sample]
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

    def _classify_columns(self, qr: QueryResult) -> dict[str, str]:
        """Classify each column by semantic kind (percent / date / …).

        Prefers the injected ``_semantic_classifier`` (LLM-backed in prod);
        falls back to a narrow keyword heuristic so the gate still works
        offline. Returns a dict ``{column_name: kind}``.
        """
        if self._semantic_classifier is not None:
            try:
                sample = qr.rows[: self._max_sample]
                result = self._semantic_classifier(list(qr.columns), sample)
                if isinstance(result, dict):
                    return {str(k): str(v) for k, v in result.items()}
            except Exception:
                logger.debug("LLM column semantic classifier failed", exc_info=True)

        classified: dict[str, str] = {}
        for col in qr.columns:
            low = col.lower()
            if any(kw in low for kw in _PERCENT_KEYWORDS):
                classified[col] = "percent"
            elif any(kw in low for kw in _DATE_KEYWORDS):
                classified[col] = "date"
            else:
                classified[col] = "other"
        return classified

    def _check_value_ranges(self, qr: QueryResult, outcome: DataGateOutcome) -> None:
        """Sanity-check obviously out-of-range values."""
        sample = qr.rows[: self._max_sample]
        if not sample:
            return
        kinds = self._classify_columns(qr)
        sample_limit = settings.data_gate_value_range_sample
        pct_min = settings.data_gate_percent_min
        pct_max = settings.data_gate_percent_max
        year_min = settings.data_gate_year_min
        year_max = settings.data_gate_year_max

        for col_idx, col_name in enumerate(qr.columns):
            kind = kinds.get(col_name, "other")
            if kind not in ("percent", "date"):
                continue
            for row in sample[:sample_limit]:
                try:
                    val = row[col_idx]
                except (IndexError, TypeError):
                    continue
                if val is None:
                    continue
                if kind == "percent" and isinstance(val, (int, float)):
                    if val < pct_min or val > pct_max:
                        outcome.warn(
                            f"Column '{col_name}' has value {val} "
                            "which looks out of range for a percentage.",
                        )
                        break
                elif kind == "date" and isinstance(val, str):
                    try:
                        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                        if dt.year < year_min or dt.year > year_max:
                            outcome.warn(
                                f"Column '{col_name}' has suspicious date: {val}",
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
        common_limits = set(settings.data_gate_common_limits)
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
            cartesian_mul = settings.data_gate_cartesian_multiplier
            if dep_qr.row_count > 0 and qr.row_count > dep_qr.row_count * cartesian_mul:
                outcome.warn(
                    f"Stage '{stage.stage_id}' produced {qr.row_count} rows "
                    f"from dependency '{dep_id}' which had {dep_qr.row_count} — "
                    "possible cartesian join.",
                    suggestion="Check for missing JOIN conditions in the query.",
                )
