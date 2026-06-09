"""Tests + CI gate for the retrieval eval harness (Phase 3).

Covers three things:

1. The golden set loads and is structurally valid (the dataset itself is a
   gate — a malformed dataset must fail loudly).
2. The deterministic IR metrics compute correct values on known inputs.
3. The harness runs end-to-end: an oracle retriever passes the thresholds and a
   broken retriever fails them. This is the regression gate that runs in CI.
"""

from __future__ import annotations

import pytest

from app.eval import (
    EvalThresholds,
    GoldenCase,
    aggregate_metrics,
    context_precision,
    context_recall,
    hit_at_k,
    load_golden_set,
    mrr,
    ndcg_at_k,
    run_eval,
)


# --------------------------------------------------------------------------- #
# Golden set integrity
# --------------------------------------------------------------------------- #
def test_golden_set_loads_and_is_valid() -> None:
    cases = load_golden_set()
    assert len(cases) >= 8
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids)), "golden case ids must be unique"
    for c in cases:
        assert c.question.strip()
        assert c.relevant_ids, f"{c.id} has no relevant_ids"


def test_golden_set_rejects_malformed(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty"):
        load_golden_set(bad)

    dup = tmp_path / "dup.json"
    dup.write_text(
        '[{"id":"a","question":"q","relevant_ids":["x"]},'
        '{"id":"a","question":"q2","relevant_ids":["y"]}]',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_golden_set(dup)


# --------------------------------------------------------------------------- #
# Metric math
# --------------------------------------------------------------------------- #
def _rel(*relevant: str):
    case = GoldenCase(id="t", question="q", relevant_ids=relevant)
    return case.is_relevant


def test_hit_at_k() -> None:
    is_rel = _rel("orders")
    assert hit_at_k(["users", "orders", "items"], is_rel, k=3) == 1.0
    assert hit_at_k(["users", "items"], is_rel, k=3) == 0.0
    # k bounds the window: relevant hit sits outside top-1.
    assert hit_at_k(["users", "orders"], is_rel, k=1) == 0.0


def test_mrr() -> None:
    is_rel = _rel("orders")
    assert mrr(["orders", "x", "y"], is_rel) == 1.0
    assert mrr(["x", "orders", "y"], is_rel) == 0.5
    assert mrr(["x", "y"], is_rel) == 0.0


def test_context_precision() -> None:
    is_rel = _rel("orders", "payments")
    # 2 of top-4 are relevant.
    assert context_precision(["orders", "x", "payments", "y"], is_rel, k=4) == 0.5
    assert context_precision([], is_rel, k=4) == 0.0


def test_context_recall_distinct_labels() -> None:
    is_rel = _rel("orders", "payments")
    # Both labels covered.
    assert context_recall(["orders", "payments"], ["orders", "payments"], is_rel, k=10) == 1.0
    # Duplicate of one label doesn't inflate recall past 0.5.
    assert context_recall(["orders", "orders_x"], ["orders", "payments"], is_rel, k=10) == 0.5


def test_ndcg_rewards_earlier_hits() -> None:
    is_rel = _rel("orders")
    early = ndcg_at_k(["orders", "x", "y"], is_rel, k=3)
    late = ndcg_at_k(["x", "y", "orders"], is_rel, k=3)
    assert early == 1.0
    assert late < early


def test_aggregate_metrics_mean() -> None:
    agg = aggregate_metrics([{"a": 1.0, "b": 0.0}, {"a": 0.0, "b": 1.0}])
    assert agg == {"a": 0.5, "b": 0.5}
    assert aggregate_metrics([]) == {}


# --------------------------------------------------------------------------- #
# Harness end-to-end (the CI gate)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_harness_oracle_passes_thresholds() -> None:
    """An oracle retriever (returns the labelled relevant ids first) must clear
    the regression floors — this is the gate other PRs run against."""
    cases = load_golden_set()
    by_q = {c.question: c for c in cases}

    async def oracle(question: str) -> list[str]:
        case = by_q[question]
        # Relevant ids first, then plausible noise.
        return [*list(case.relevant_ids), "noise_a", "noise_b"]

    report = await run_eval(oracle, k=10)
    assert report.passed, report.summary()
    assert report.n_cases == len(cases)
    assert report.metrics["hit_at_k"] == 1.0
    # Per-category breakdown is populated.
    assert "schema" in report.by_category


@pytest.mark.asyncio
async def test_harness_broken_retriever_fails() -> None:
    async def broken(_question: str) -> list[str]:
        return ["totally_unrelated_doc"]

    report = await run_eval(broken, k=10)
    assert not report.passed
    assert any("hit_at_k" in f for f in report.failures)


@pytest.mark.asyncio
async def test_harness_contains_retriever_exceptions() -> None:
    async def explode(_question: str) -> list[str]:
        raise RuntimeError("retriever down")

    # Should not raise; failed cases score zero.
    report = await run_eval(explode, k=10, thresholds=EvalThresholds())
    assert report.metrics["hit_at_k"] == 0.0
    assert not report.passed
