"""In-memory state for multi-stage pipeline execution.

``StageContext`` is the single source of truth while a pipeline runs.
It carries structured ``StageResult`` objects that later stages can
reference.  Persistence to ``PipelineRun`` stores only compact summaries.
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field
from typing import Any

from app.connectors.base import QueryResult

# ------------------------------------------------------------------
# Execution plan data structures (produced by QueryPlanner)
# ------------------------------------------------------------------


@dataclass
class StageValidation:
    expected_columns: list[str] | None = None
    min_rows: int | None = None
    max_rows: int | None = None
    business_rules: list[str] | None = None
    cross_stage_checks: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_columns": self.expected_columns,
            "min_rows": self.min_rows,
            "max_rows": self.max_rows,
            "business_rules": self.business_rules,
            "cross_stage_checks": self.cross_stage_checks,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StageValidation:
        return cls(
            expected_columns=d.get("expected_columns"),
            min_rows=d.get("min_rows"),
            max_rows=d.get("max_rows"),
            business_rules=d.get("business_rules"),
            cross_stage_checks=d.get("cross_stage_checks"),
        )


@dataclass
class PlanStage:
    stage_id: str
    description: str
    tool: str  # query_database | search_codebase | process_data | analyze_results | synthesize
    depends_on: list[str] = field(default_factory=list)
    input_context: str = ""
    validation: StageValidation = field(default_factory=StageValidation)
    checkpoint: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "description": self.description,
            "tool": self.tool,
            "depends_on": self.depends_on,
            "input_context": self.input_context,
            "validation": self.validation.to_dict(),
            "checkpoint": self.checkpoint,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PlanStage:
        return cls(
            stage_id=d["stage_id"],
            description=d["description"],
            tool=d["tool"],
            depends_on=d.get("depends_on", []),
            input_context=d.get("input_context", ""),
            validation=StageValidation.from_dict(d.get("validation", {})),
            checkpoint=d.get("checkpoint", False),
        )


@dataclass
class ExecutionPlan:
    plan_id: str
    question: str
    stages: list[PlanStage]
    complexity_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "question": self.question,
            "stages": [s.to_dict() for s in self.stages],
            "complexity_reason": self.complexity_reason,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ExecutionPlan:
        return cls(
            plan_id=d["plan_id"],
            question=d["question"],
            stages=[PlanStage.from_dict(s) for s in d.get("stages", [])],
            complexity_reason=d.get("complexity_reason", ""),
        )

    @classmethod
    def from_json(cls, raw: str) -> ExecutionPlan:
        return cls.from_dict(json.loads(raw))


# ------------------------------------------------------------------
# Stage result (one per completed/failed stage)
# ------------------------------------------------------------------

_MAX_SAMPLE_ROWS = 10


@dataclass
class StageResult:
    stage_id: str
    status: str = "success"  # success | error | skipped
    query: str | None = None
    query_result: QueryResult | None = None
    summary: str = ""
    error: str | None = None
    token_usage: dict[str, int] = field(
        default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )

    def to_summary_dict(self) -> dict[str, Any]:
        """Compact representation for DB persistence (no full rows)."""
        d: dict[str, Any] = {
            "stage_id": self.stage_id,
            "status": self.status,
            "summary": self.summary,
            "error": self.error,
            "token_usage": self.token_usage,
        }
        if self.query:
            d["query"] = self.query
        if self.query_result:
            d["columns"] = self.query_result.columns
            d["row_count"] = self.query_result.row_count
            d["sample_rows"] = self.query_result.rows[:_MAX_SAMPLE_ROWS]
        return d

    @classmethod
    def from_summary_dict(cls, d: dict[str, Any]) -> StageResult:
        """Restore from persisted summary.  Full QueryResult is NOT restored.

        Note: only sample rows (up to ``_MAX_SAMPLE_ROWS``) are persisted.
        The ``row_count`` field preserves the original total so downstream
        stages can detect truncation (``len(rows) < row_count``).
        """
        qr: QueryResult | None = None
        if "columns" in d:
            qr = QueryResult(
                columns=d["columns"],
                rows=d.get("sample_rows", []),
                row_count=d.get("row_count", 0),
            )
            actual_rows = len(qr.rows)
            if actual_rows < qr.row_count:
                import logging as _logging

                _logging.getLogger(__name__).warning(
                    "Stage %s restored with %d/%d rows (sample only)",
                    d.get("stage_id", "?"),
                    actual_rows,
                    qr.row_count,
                )
        return cls(
            stage_id=d["stage_id"],
            status=d.get("status", "success"),
            query=d.get("query"),
            query_result=qr,
            summary=d.get("summary", ""),
            error=d.get("error"),
            token_usage=d.get("token_usage", {}),
        )


# ------------------------------------------------------------------
# StageContext — the pipeline's in-memory state
# ------------------------------------------------------------------


@dataclass
class StageContext:
    plan: ExecutionPlan
    results: dict[str, StageResult] = field(default_factory=dict)
    user_feedback: list[dict[str, Any]] = field(default_factory=list)
    current_stage_idx: int = 0
    pipeline_run_id: str = ""

    def get_result(self, stage_id: str) -> StageResult | None:
        return self.results.get(stage_id)

    def set_result(self, stage_id: str, result: StageResult) -> None:
        self.results[stage_id] = result

    def build_context_for_stage(self, stage_id: str) -> str:
        """Build a text summary of completed stages for the LLM prompt.

        Includes stage descriptions, result summaries, column names,
        row counts, and any user feedback.
        """
        parts: list[str] = []

        stage = next((s for s in self.plan.stages if s.stage_id == stage_id), None)
        deps = stage.depends_on if stage else []

        for prev_stage in self.plan.stages:
            if prev_stage.stage_id == stage_id:
                break
            sr = self.results.get(prev_stage.stage_id)
            if not sr:
                continue

            is_dep = prev_stage.stage_id in deps
            prefix = "[DEPENDENCY] " if is_dep else ""

            lines: list[str] = [f"{prefix}Stage '{prev_stage.stage_id}': {prev_stage.description}"]
            lines.append(f"  Status: {sr.status}")
            if sr.query:
                lines.append(f"  SQL: {sr.query}")
            if sr.query_result:
                lines.append(f"  Columns: {sr.query_result.columns}")
                lines.append(f"  Rows: {sr.query_result.row_count}")
                if sr.query_result.rows:
                    sample = sr.query_result.rows[:5]
                    lines.append(f"  Sample data (first {len(sample)} rows): {sample}")
            if sr.summary:
                lines.append(f"  Summary: {sr.summary}")
            if sr.error:
                lines.append(f"  Error: {sr.error}")

            parts.append("\n".join(lines))

        for fb in self.user_feedback:
            if fb.get("stage_id") == stage_id or not deps or fb.get("stage_id") in deps:
                fb_stage = fb.get("stage_id")
                fb_text = fb.get("feedback_text", "")
                parts.append(f"User feedback (after stage '{fb_stage}'): {fb_text}")

        if not parts:
            return ""
        return textwrap.dedent(
            """\
            === Previous stage results ===
            {body}
            === End previous stage results ==="""
        ).format(body="\n\n".join(parts))

    def to_persistence_dict(self) -> dict[str, Any]:
        """Serialize for PipelineRun DB columns."""
        return {stage_id: sr.to_summary_dict() for stage_id, sr in self.results.items()}

    @classmethod
    def from_persistence(
        cls,
        plan: ExecutionPlan,
        stage_results_raw: dict[str, Any],
        user_feedback: list[dict[str, Any]],
        current_stage_idx: int,
        pipeline_run_id: str,
    ) -> StageContext:
        """Restore from DB for resume.  Full QueryResults are sample-only."""
        results = {
            sid: StageResult.from_summary_dict(data) for sid, data in stage_results_raw.items()
        }
        return cls(
            plan=plan,
            results=results,
            user_feedback=user_feedback,
            current_stage_idx=current_stage_idx,
            pipeline_run_id=pipeline_run_id,
        )
