"""Deterministic information-retrieval metrics for the eval harness.

These mirror the *retrieval-side* of RAGAS (context precision / recall) plus
the standard ranking metrics, computed against a labelled golden set. They are
intentionally LLM-free and network-free so they are cheap, reproducible, and
safe to run as a CI gate.

Each function takes:

* ``retrieved_ids`` — the ordered list of document ids a retriever returned.
* ``is_relevant`` — a predicate ``(doc_id) -> bool`` (provided by
  :class:`~app.eval.golden_set.GoldenCase`).

Conventions: an empty ``retrieved_ids`` yields 0.0 for every metric.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

Predicate = Callable[[str], bool]


def hit_at_k(retrieved_ids: Sequence[str], is_relevant: Predicate, k: int) -> float:
    """1.0 if any of the top-``k`` results is relevant, else 0.0."""
    return 1.0 if any(is_relevant(d) for d in retrieved_ids[:k]) else 0.0


def mrr(retrieved_ids: Sequence[str], is_relevant: Predicate) -> float:
    """Reciprocal rank of the first relevant hit (0.0 if none)."""
    for rank, doc in enumerate(retrieved_ids, start=1):
        if is_relevant(doc):
            return 1.0 / rank
    return 0.0


def context_precision(retrieved_ids: Sequence[str], is_relevant: Predicate, k: int) -> float:
    """Fraction of the top-``k`` retrieved docs that are relevant."""
    top = retrieved_ids[:k]
    if not top:
        return 0.0
    relevant = sum(1 for d in top if is_relevant(d))
    return relevant / len(top)


def context_recall(
    retrieved_ids: Sequence[str],
    relevant_ids: Sequence[str],
    is_relevant: Predicate,
    k: int,
) -> float:
    """Fraction of labelled relevant ids that appear in the top-``k``.

    Counts *distinct* relevant labels covered, so duplicate retrievals of the
    same relevant doc don't inflate recall.
    """
    if not relevant_ids:
        return 0.0
    top = retrieved_ids[:k]
    covered: set[str] = set()
    for rel in relevant_ids:
        rel_l = rel.lower()
        if any(rel_l in (d or "").lower() for d in top):
            covered.add(rel_l)
    return len(covered) / len(relevant_ids)


def ndcg_at_k(retrieved_ids: Sequence[str], is_relevant: Predicate, k: int) -> float:
    """Binary nDCG@k (ideal DCG assumes all top slots are relevant)."""
    top = retrieved_ids[:k]
    if not top:
        return 0.0
    dcg = 0.0
    for i, doc in enumerate(top, start=1):
        if is_relevant(doc):
            dcg += 1.0 / math.log2(i + 1)
    ideal_hits = min(k, sum(1 for d in top if is_relevant(d))) or 1
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def aggregate_metrics(per_case: list[dict[str, float]]) -> dict[str, float]:
    """Mean each metric across cases. Empty input → empty dict."""
    if not per_case:
        return {}
    keys = per_case[0].keys()
    return {key: sum(c[key] for c in per_case) / len(per_case) for key in keys}


__all__ = [
    "aggregate_metrics",
    "context_precision",
    "context_recall",
    "hit_at_k",
    "mrr",
    "ndcg_at_k",
]
