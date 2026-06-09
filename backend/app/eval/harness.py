"""Retrieval evaluation harness — runs a retriever over the golden set.

The harness is retriever-agnostic: callers pass an async ``retrieve`` callable
that maps a question to an ordered list of document ids. This lets the same
harness gate the codebase ``HybridRetriever``, the ``SchemaRetriever``, or a
synthetic retriever in CI.

Usage::

    async def retrieve(question: str) -> list[str]:
        results = await hybrid.query(project_id, question, k=10)
        return [r.doc_id for r in results]

    report = await run_eval(retrieve, k=10)
    assert report.passed, report.failures

The default thresholds are conservative regression floors, not aspirational
targets — they exist to catch a retrieval *regression*, so set them just below
current measured performance.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.eval.golden_set import GoldenCase, load_golden_set
from app.eval.retrieval_metrics import (
    aggregate_metrics,
    context_precision,
    context_recall,
    hit_at_k,
    mrr,
    ndcg_at_k,
)

logger = logging.getLogger(__name__)

Retriever = Callable[[str], Awaitable[list[str]]]


@dataclass(frozen=True)
class EvalThresholds:
    """Minimum aggregate metrics for a passing run (regression floors)."""

    hit_at_k: float = 0.70
    mrr: float = 0.50
    context_recall: float = 0.60
    ndcg_at_k: float = 0.50

    def check(self, metrics: dict[str, float]) -> list[str]:
        """Return a list of human-readable threshold violations (empty = pass)."""
        failures: list[str] = []
        checks = {
            "hit_at_k": self.hit_at_k,
            "mrr": self.mrr,
            "context_recall": self.context_recall,
            "ndcg_at_k": self.ndcg_at_k,
        }
        for name, floor in checks.items():
            got = metrics.get(name, 0.0)
            if got + 1e-9 < floor:
                failures.append(f"{name}={got:.3f} below floor {floor:.3f}")
        return failures


@dataclass
class EvalReport:
    """Aggregate + per-case results of an eval run."""

    k: int
    n_cases: int
    metrics: dict[str, float]
    per_case: list[dict[str, object]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    by_category: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.failures

    def summary(self) -> str:
        lines = [
            f"Retrieval eval — {self.n_cases} cases @ k={self.k} "
            f"[{'PASS' if self.passed else 'FAIL'}]",
        ]
        for name, val in sorted(self.metrics.items()):
            lines.append(f"  {name:18s} {val:.3f}")
        if self.by_category:
            lines.append("  by category:")
            for cat, m in sorted(self.by_category.items()):
                inner = ", ".join(f"{n}={v:.2f}" for n, v in sorted(m.items()))
                lines.append(f"    {cat:14s} {inner}")
        for f in self.failures:
            lines.append(f"  ✗ {f}")
        return "\n".join(lines)


async def run_eval(
    retrieve: Retriever,
    *,
    k: int = 10,
    cases: list[GoldenCase] | None = None,
    thresholds: EvalThresholds | None = None,
) -> EvalReport:
    """Run ``retrieve`` over the golden set and score it.

    A retriever failure on one case is contained (logged, scored as zero) so a
    single broken query can't abort the whole run.
    """
    golden = cases if cases is not None else load_golden_set()
    thresholds = thresholds or EvalThresholds()

    per_case_metrics: list[dict[str, float]] = []
    per_case_detail: list[dict[str, object]] = []
    cat_buckets: dict[str, list[dict[str, float]]] = {}

    for case in golden:
        try:
            retrieved = await retrieve(case.question)
        except Exception:
            logger.warning("eval: retriever failed for case %s", case.id, exc_info=True)
            retrieved = []

        m = {
            "hit_at_k": hit_at_k(retrieved, case.is_relevant, k),
            "mrr": mrr(retrieved, case.is_relevant),
            "context_precision": context_precision(retrieved, case.is_relevant, k),
            "context_recall": context_recall(retrieved, case.relevant_ids, case.is_relevant, k),
            "ndcg_at_k": ndcg_at_k(retrieved, case.is_relevant, k),
        }
        per_case_metrics.append(m)
        per_case_detail.append(
            {"id": case.id, "category": case.category, "retrieved": retrieved[:k], **m}
        )
        cat_buckets.setdefault(case.category, []).append(m)

    metrics = aggregate_metrics(per_case_metrics)
    by_category = {cat: aggregate_metrics(ms) for cat, ms in cat_buckets.items()}
    failures = thresholds.check(metrics)

    return EvalReport(
        k=k,
        n_cases=len(golden),
        metrics=metrics,
        per_case=per_case_detail,
        failures=failures,
        by_category=by_category,
    )


__all__ = ["EvalReport", "EvalThresholds", "Retriever", "run_eval"]
