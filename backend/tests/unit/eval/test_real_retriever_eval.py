"""The eval gate runs the REAL retriever, not a synthetic one (Ш1).

`test_retrieval_eval.py` gates three things and two of them are genuine: the
golden set's structural integrity, and the IR metrics computing correctly on
known inputs. The third runs `run_eval` with an **oracle** — a retriever handed
the labelled relevant ids — plus a deliberately broken one, which proves the
harness plumbing works and says nothing about the product's retrieval.

Being fair about the shape of it: `app/eval/harness.py`'s own docstring says
*"This lets the same harness gate the codebase `HybridRetriever`, the
`SchemaRetriever`, or a synthetic retriever in CI"*, and its usage example is
literally `results = await hybrid.query(project_id, question, k=10)`. The harness
was designed for this and only the synthetic retriever was ever wired. Same
shape as the `failure_kind` vocabulary that lived in a test docstring: the
knowledge existed, the enforcement did not.

Which is why both retrieval defects of 2026-09 passed CI green:

* `hybrid_min_score = 0.03` made the retriever an AND-gate. RRF awards
  `1/(rrf_k + rank)` **per leg**, so a single-leg hit tops out at `1/61 = 0.0164`
  and the floor sat above all of it — 0 of 40 single-leg documents survived.
* A nominal `isinstance` emptied the RAG leg on the production backend.

This file catches the first class and **not** the second, and that is stated
rather than glossed: the second lived at a *construction site*
(`knowledge_catalog_service.py:99`) inside a swallowing `except`, not in fusion.
`TestNoConstructionSiteHidesAFailure` below covers that separately, because one
eval covering both would be the same substitution this work exists to remove.

Fidelity, chosen deliberately: the **BM25 leg is real** (real `BM25Index`, real
tokenizer, real scoring over a fixture corpus) and the **dense leg is a stub**
satisfying `VectorStoreLike`. Fusion — RRF, `min_score`, `max_rank`, the timeout,
the degradation labels — is entirely real. What this cannot see is embedding
quality: the 256-token truncation and the silently-ignored 768-d model live in
that layer, and `test_real_retriever_eval_slow.py` is where they are checked.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.eval import EvalThresholds, load_golden_set, run_eval
from app.knowledge.bm25_index import BM25Index
from app.knowledge.hybrid_retriever import HybridRetriever
from app.knowledge.vector_store import VectorStoreLike

_PROJECT = "eval-project"
_SHA = "0" * 40

#: One document per `relevant_ids` entry in the golden set, worded so the real
#: BM25 tokenizer can find it from the real question. Deliberately terse: this is
#: a retrieval fixture, not a corpus — the metrics that matter are ranking ones.
_CORPUS: dict[str, str] = {
    "orders": "customer order records, order id, placed_at, total. Track a customer order.",
    "order_status": "order status transitions: pending shipped delivered. Status of an order.",
    "auth": "authentication module: login, session, password hashing with bcrypt.",
    "users": "user accounts table: email, password_hash, created_at.",
    "payments": "payment transactions: amount, currency, captured_at.",
    "refunds": "refund records linked to a payment transaction.",
    "transactions": "financial transaction ledger for payments and refunds.",
    "subscriptions": "subscription plans and renewals feeding recurring revenue.",
    "invoices": "invoice rows per billing period, amount due.",
    "mrr": "monthly recurring revenue calculation from subscriptions and invoices.",
    "products": "product catalogue: sku, name, price.",
    "inventory": "product inventory per warehouse location.",
    "stock": "stock levels and reorder thresholds for inventory.",
    "rate_limit": "API rate limiting counters per key and window.",
    "middleware": "request middleware chain implementing rate limiting and auth.",
    "throttle": "throttle policy applied when a rate limit is exceeded.",
    "email": "transactional email delivery module.",
    "notifications": "notification dispatch: email, push, in-app.",
    "mailer": "mailer sends transactional email notifications via a provider.",
    "customers": "customer profiles and lifecycle stage.",
    "churn": "churn risk scoring for customers at risk of churning.",
    "cart": "shopping cart contents per session.",
    "checkout": "checkout flow: cart to order, payment capture.",
    "audit": "audit trail configuration.",
    "audit_log": "audit log rows: actor, action, target, at. User actions audit-logged.",
    "events": "domain event stream feeding the audit log.",
    # Distractors, so a retriever that returns everything cannot score well.
    "migrations": "schema migration history.",
    "feature_flags": "feature flag toggles per environment.",
    "cron_jobs": "scheduled job definitions and last run.",
}


class _StubDenseStore:
    """A deterministic dense leg satisfying :class:`VectorStoreLike`.

    Not a mock: it implements the Protocol's single method and returns a stable
    ranking, so the fusion under test is the production one. The Protocol is
    deliberately **not** ``runtime_checkable`` — its own docstring says a runtime
    ``isinstance`` over a structural contract is the defect it exists to prevent
    — so conformance is asserted statically instead (see ``_conforms`` below).
    """

    def __init__(self, ranking: dict[str, list[str]] | None = None) -> None:
        self._ranking = ranking or {}
        self.calls: list[str] = []

    def query(
        self,
        project_id: str,
        query_text: str,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append(query_text)
        ids = self._ranking.get(query_text, [])[:n_results]
        # Shape mirrors what `_run_chroma` reads: an `id` and a `distance`.
        return [{"id": doc_id, "distance": 0.1 * (i + 1)} for i, doc_id in enumerate(ids)]


# mypy checks the Protocol here. A runtime isinstance would not, and the
# Protocol's docstring explains why one must not be added.
_conforms: VectorStoreLike = _StubDenseStore()


@pytest.fixture
def bm25(tmp_path: Path) -> BM25Index:
    """A real BM25 index over the fixture corpus, built in-process."""
    index = BM25Index(tmp_path)
    index.build(
        _PROJECT,
        _SHA,
        [(doc_id, text, {"source": "fixture"}) for doc_id, text in _CORPUS.items()],
    )
    return index


def _retriever(bm25: BM25Index, dense: _StubDenseStore, **kwargs: Any) -> HybridRetriever:
    """The production `HybridRetriever`, with production defaults unless overridden."""
    from app.config import settings

    params: dict[str, Any] = {
        "rrf_k": settings.hybrid_rrf_k,
        "min_score": settings.hybrid_min_score,
        "max_rank": settings.hybrid_max_rank,
    }
    params.update(kwargs)
    return HybridRetriever(bm25=bm25, vector_store=dense, **params)


def _dense_ranking_from_golden() -> dict[str, list[str]]:
    """A dense leg too weak to pass on its own — deliberately, and this was wrong first.

    The first version handed the dense leg every labelled id. Measured by planting
    a defect: with the real BM25 leg returning nothing, the golden-set gate still
    passed. **The stub was carrying the eval** — the same substitution this file
    exists to remove, reproduced inside the fix for it.

    So the dense leg now returns ONE labelled id per case behind a distractor. That
    is enough for `hit_at_k` and nowhere near enough for `context_recall`, which
    needs the rest — and the rest can only come from the real BM25 leg. Break BM25
    and the gate goes red, which is the property that makes it a gate.
    """
    ranking: dict[str, list[str]] = {}
    for case in load_golden_set():
        first = list(case.relevant_ids)[:1]
        ranking[case.question] = ["migrations", *first]
    return ranking


# --------------------------------------------------------------------------- #
# REQ-1: the fixture and the golden set agree
# --------------------------------------------------------------------------- #


class TestTheFixtureMatchesTheGoldenSet:
    def test_every_labelled_id_exists_in_the_corpus(self):
        """A golden id with no document is an unwinnable case, and it would drag
        the metrics down for a reason that has nothing to do with retrieval."""
        labelled = {doc_id for case in load_golden_set() for doc_id in case.relevant_ids}
        missing = sorted(labelled - set(_CORPUS))
        assert not missing, f"golden ids with no fixture document: {missing}"

    def test_the_corpus_carries_distractors(self):
        """Without documents that are never relevant, a retriever returning the
        whole corpus scores perfectly on recall."""
        labelled = {doc_id for case in load_golden_set() for doc_id in case.relevant_ids}
        assert set(_CORPUS) - labelled, "the corpus must contain never-relevant documents"

    def test_the_golden_set_is_the_shipped_one(self):
        """Not a copy. A fixture golden set would let the real one rot."""
        shipped = json.loads(
            Path("app/eval/datasets/retrieval_golden.json").read_text(encoding="utf-8")
        )
        assert len(load_golden_set()) == len(shipped)


# --------------------------------------------------------------------------- #
# REQ-2/4: the real retriever clears the regression floors
# --------------------------------------------------------------------------- #


class TestTheRealRetrieverIsMeasured:
    async def test_the_bm25_leg_alone_finds_something(self, bm25):
        """Before fusion is judged, the real leg must actually work — otherwise a
        passing eval could be the stub carrying it."""
        dense = _StubDenseStore()
        retriever = _retriever(bm25, dense)
        results = await retriever.query(_PROJECT, "payment transactions and refunds", k=10)
        ids = [r.doc_id for r in results]
        assert ids, "the real BM25 leg returned nothing over the fixture corpus"
        assert {"payments", "refunds", "transactions"} & set(ids)

    async def test_the_dense_leg_is_actually_consulted(self, bm25):
        dense = _StubDenseStore({"anything": ["cart"]})
        await _retriever(bm25, dense).query(_PROJECT, "anything", k=10)
        assert dense.calls, "the dense leg was never queried — fusion is single-legged"

    async def test_the_full_golden_set_clears_the_floors(self, bm25):
        """The gate. `run_eval` over the shipped golden set with the production
        `HybridRetriever` and production fusion settings."""
        dense = _StubDenseStore(_dense_ranking_from_golden())
        retriever = _retriever(bm25, dense)

        async def retrieve(question: str) -> list[str]:
            results = await retriever.query(_PROJECT, question, k=10)
            return [r.doc_id for r in results]

        report = await run_eval(retrieve, k=10)
        assert report.passed, f"retrieval regressed: {report.failures} · {report.metrics}"

    async def test_the_stub_alone_cannot_pass_the_gate(self, bm25):
        """The property that makes the test above a gate rather than a decoration.

        Measured, not assumed: the first version of this fixture handed the dense
        leg every labelled id, and the golden-set run still passed with the real
        BM25 leg returning nothing. If the stub can clear the floors alone, the
        gate is measuring the stub.
        """
        dense = _StubDenseStore(_dense_ranking_from_golden())

        async def dense_only(question: str) -> list[str]:
            return [hit["id"] for hit in dense.query(_PROJECT, question, n_results=10)]

        report = await run_eval(dense_only, k=10)
        assert not report.passed, (
            "the stub dense leg clears the thresholds on its own, so the golden-set "
            f"gate is not measuring the real retriever. metrics={report.metrics}"
        )


# --------------------------------------------------------------------------- #
# REQ-5/6: the two fusion settings that caused the outage
# --------------------------------------------------------------------------- #


class TestFusionSettingsThatBrokeProduction:
    async def test_a_single_leg_hit_survives(self, bm25):
        """This is the test that was missing on 2026-09-02.

        `hybrid_min_score = 0.03` sat above `1/(rrf_k + 1) = 0.0164`, the most a
        document found by ONE leg can score. Anything only the dense leg knew
        about was discarded — 0 of 40 single-leg documents survived in the
        measurement that found it.

        `feature_flags` is a distractor no question is about, so BM25 will not
        rank it for this query: if it comes back, it came back on the dense leg
        alone.
        """
        dense = _StubDenseStore({"tell me about payments": ["feature_flags"]})
        retriever = _retriever(bm25, dense)
        ids = [r.doc_id for r in await retriever.query(_PROJECT, "tell me about payments", k=10)]
        assert "feature_flags" in ids, (
            "a document found by the dense leg alone was dropped — the fused-score "
            "floor is back above the single-leg ceiling"
        )

    async def test_the_floor_that_broke_it_would_be_caught_here(self, bm25):
        """The negative control, executed in-test rather than described.

        Planting the old value must make the assertion above impossible, or that
        assertion is decoration.
        """
        dense = _StubDenseStore({"tell me about payments": ["feature_flags"]})
        retriever = _retriever(bm25, dense, min_score=0.03)
        ids = [r.doc_id for r in await retriever.query(_PROJECT, "tell me about payments", k=10)]
        assert "feature_flags" not in ids, (
            "min_score=0.03 was measured to discard every single-leg hit; if this "
            "now survives, the arithmetic behind the fix has changed and the test "
            "above no longer proves anything"
        )

    async def test_max_rank_is_a_rank_and_not_a_score(self, bm25):
        """`hybrid_max_rank` replaced the float precisely so it means the same
        thing at any `rrf_k`. A document both legs ranked worse than the cut-off
        is dropped; one leg ranking it well is enough to keep it."""
        dense = _StubDenseStore({"payments": ["payments"]})
        keep = _retriever(bm25, dense, max_rank=30)
        ids = [r.doc_id for r in await keep.query(_PROJECT, "payments", k=10)]
        assert "payments" in ids

        drop_all = _retriever(bm25, dense, max_rank=0)
        ids_off = [r.doc_id for r in await drop_all.query(_PROJECT, "payments", k=10)]
        assert "payments" in ids_off, "max_rank=0 must mean OFF, not 'drop everything'"


# --------------------------------------------------------------------------- #
# REQ-8: the other defect, which no eval can see
# --------------------------------------------------------------------------- #


class TestNoConstructionSiteHidesAFailure:
    """#274 was not a fusion bug and this file's eval cannot catch it.

    A nominal `isinstance(store, VectorStore)` at
    `knowledge_catalog_service.py:99` raised on the production backend, an
    enclosing `except` swallowed it, and `pack.rag_chunks` was empty on every
    request for five days with nothing saying so. Three sites construct a
    `HybridRetriever`; the guard is that none of them may decide by nominal type,
    and none may swallow a construction failure into silence.
    """

    _SITES = (
        "app/agents/context_loader.py",
        "app/agents/knowledge_agent.py",
        "app/services/knowledge_catalog_service.py",
    )

    @pytest.mark.parametrize("path", _SITES)
    def test_no_nominal_type_check_guards_a_structural_contract(self, path):
        src = Path(path).read_text(encoding="utf-8")
        offenders = [
            line.strip()
            for line in src.splitlines()
            if "isinstance" in line and "VectorStore" in line and not line.strip().startswith("#")
        ]
        assert not offenders, (
            "VectorStoreLike is a Protocol on purpose; a runtime isinstance over it "
            f"is the defect it exists to prevent. Found: {offenders}"
        )

    def test_all_three_sites_are_still_the_three(self):
        """A fourth construction site added later needs the same guard, and this
        test is what makes it say so instead of being discovered in production.
        """
        found = {
            path
            for path in Path("app").rglob("*.py")
            if "HybridRetriever(" in path.read_text(encoding="utf-8")
        }
        assert {str(p) for p in found} == set(self._SITES), (
            f"the set of HybridRetriever construction sites changed: {sorted(str(p) for p in found)}"
        )


# --------------------------------------------------------------------------- #
# The thresholds themselves
# --------------------------------------------------------------------------- #


class TestTheFloorsAreFloors:
    def test_they_are_below_what_the_real_retriever_measures(self, bm25):
        """The harness docstring: "conservative regression floors, not
        aspirational targets". A floor above current performance is a red build
        nobody can fix, and one far below it catches nothing."""
        t = EvalThresholds()
        assert 0.0 < t.hit_at_k <= 1.0
        assert 0.0 < t.mrr <= 1.0
        assert 0.0 < t.context_recall <= 1.0
        assert 0.0 < t.ndcg_at_k <= 1.0
