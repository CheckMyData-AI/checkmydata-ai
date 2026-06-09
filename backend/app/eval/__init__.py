"""Retrieval evaluation harness (Phase 3 — golden-set + RAGAS-style metrics).

This package provides a deterministic, dependency-light way to measure
retrieval quality so changes to the retrieval stack (RRF fusion, the
cross-encoder reranker, schema retrieval) can be gated in CI instead of judged
by eye.

Modules:

* :mod:`app.eval.golden_set` — the labelled query→relevant-doc dataset and its
  loader.
* :mod:`app.eval.retrieval_metrics` — deterministic IR metrics (hit@k, MRR,
  nDCG, context precision/recall) that mirror the retrieval-side of RAGAS
  without requiring an LLM judge or network access.
* :mod:`app.eval.harness` — runs a retriever over the golden set, aggregates
  metrics, and compares against thresholds (pass/fail for CI).
"""

from app.eval.golden_set import GoldenCase, load_golden_set
from app.eval.harness import EvalReport, EvalThresholds, run_eval
from app.eval.retrieval_metrics import (
    aggregate_metrics,
    context_precision,
    context_recall,
    hit_at_k,
    mrr,
    ndcg_at_k,
)

__all__ = [
    "EvalReport",
    "EvalThresholds",
    "GoldenCase",
    "aggregate_metrics",
    "context_precision",
    "context_recall",
    "hit_at_k",
    "load_golden_set",
    "mrr",
    "ndcg_at_k",
    "run_eval",
]
