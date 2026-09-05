"""The degraded-retrieval line was built in the UI for an event nothing sent (1.9).

`emit_retrieval_degraded` does two things: it records a metric, which needs
nothing, and it emits a `retrieval_degraded` workflow event — **only if a tracker
was given**. That event is what renders the reader-facing line the
degraded-retrieval scenario promises ("keyword search is unavailable for this
project … re-indexing the repository restores it").

`HybridRetriever` takes `tracker` in its constructor, and all three production
sites omit it. So on the chat path a degraded BM25 leg increments a counter and
shows the reader nothing: an answer built on one leg of two renders exactly like
one built on both. Third occurrence today of one shape — a rule implemented in
one layer and unreachable because another layer never sends the value.

**Half the obvious fix would have been a cross-request leak, and the halves are
not the ones the row's title suggests.** `chat.py:62` is
`_agent = ConversationalAgent()` at module scope — a process-wide singleton — and
each of the three sites caches its retriever lazily on `self`.

`WorkflowTracker` is a central BUS: `emit(workflow_id, …)` takes the id as its
first argument, and that id is what addresses one request's stream. So a tracker
held on a singleton is correct and already normal — `context_loader.py:163` does
exactly that. What must never be held there is the **`workflow_id`**, which
`HybridRetriever.__init__` also accepts and stores: a request's id captured at
construction would deliver every later request's events into the first one's
stream.

This docstring first said the tracker was the leak. Reading `WorkflowTracker`
corrected it, and the guard below moved with it — a test that forbids the wrong
thing teaches the wrong lesson to whoever reads it next.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.knowledge.hybrid_retriever import HybridRetriever


class _Tracker:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def emit(self, workflow_id, event, status, message, **extra):  # noqa: ANN001
        self.events.append((workflow_id, event))


def _retriever(*, bm25_reason: str, dense_hits: list[dict], **kwargs) -> HybridRetriever:
    bm25 = MagicMock()
    bm25.query_with_reason = MagicMock(return_value=([], bm25_reason))
    vector = MagicMock()
    vector.query = MagicMock(return_value=dense_hits)
    return HybridRetriever(bm25=bm25, vector_store=vector, **kwargs)


_DENSE = [{"id": "d1:0", "document": "text", "metadata": {}, "distance": 0.2}]


class TestTheEventReachesAPerRequestTracker:
    async def test_a_degraded_bm25_leg_emits_when_the_call_carries_a_tracker(self):
        tracker = _Tracker()
        retriever = _retriever(bm25_reason="no_snapshot", dense_hits=_DENSE)

        await retriever.query("proj", "how does sync work", tracker=tracker, workflow_id="wf-1")

        assert [e for _wf, e in tracker.events] == ["retrieval_degraded"], (
            "the reader-facing line is rendered from this event; without it the "
            "answer looks identical to one retrieved from both legs"
        )

    async def test_the_workflow_id_travels_with_it(self):
        """It addresses the stream. A wrong one delivers the event to another
        request, which is the failure the constructor route would have made
        systematic."""
        tracker = _Tracker()
        retriever = _retriever(bm25_reason="corrupt", dense_hits=_DENSE)

        await retriever.query("proj", "q", tracker=tracker, workflow_id="wf-42")

        assert tracker.events[0][0] == "wf-42"

    async def test_a_healthy_leg_emits_nothing(self):
        """`no_match` is not degradation — a working index that found nothing is
        the normal case, and a caveat on the normal path is what teaches people
        to ignore caveats."""
        tracker = _Tracker()
        retriever = _retriever(bm25_reason="no_match", dense_hits=_DENSE)

        await retriever.query("proj", "q", tracker=tracker, workflow_id="wf-1")

        assert tracker.events == []

    async def test_it_still_works_with_no_tracker_at_all(self):
        """The eval harness and any standalone caller pass none, and retrieval
        must not care."""
        retriever = _retriever(bm25_reason="no_snapshot", dense_hits=_DENSE)
        assert await retriever.query("proj", "q") is not None


class TestTheCallOverridesTheConstructor:
    async def test_a_per_call_tracker_wins(self):
        """The retriever may be process-wide; the tracker is per request."""
        constructed, per_call = _Tracker(), _Tracker()
        retriever = _retriever(
            bm25_reason="no_snapshot", dense_hits=_DENSE, tracker=constructed, workflow_id="old"
        )

        await retriever.query("proj", "q", tracker=per_call, workflow_id="new")

        assert per_call.events and not constructed.events


class TestNoSiteBindsARequestIdToTheSingleton:
    """`chat.py:62` builds `ConversationalAgent()` at module scope, and each site
    caches its retriever on `self`. A `workflow_id=` in any of these constructor
    calls is a cross-request event leak, not a style preference — it names one
    request's stream and the object outlives that request. A `tracker=` there
    would be harmless, because the tracker is a bus."""

    @pytest.mark.parametrize(
        "path",
        [
            "app/agents/knowledge_agent.py",
            "app/agents/context_loader.py",
            "app/services/knowledge_catalog_service.py",
        ],
    )
    def test_the_constructor_is_not_given_a_workflow_id(self, path):
        import ast
        from pathlib import Path

        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        offenders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "HybridRetriever"
            and any(kw.arg == "workflow_id" for kw in node.keywords)
        ]
        assert not offenders, (
            f"{path}:{offenders} binds a request-scoped workflow_id to a retriever "
            "cached on a process-wide singleton — every later request would emit into "
            "the first one's stream"
        )

    @pytest.mark.parametrize(
        "path",
        [
            "app/agents/knowledge_agent.py",
            "app/agents/context_loader.py",
            "app/services/knowledge_catalog_service.py",
        ],
    )
    def test_the_query_call_does_carry_one(self, path):
        from pathlib import Path

        src = Path(path).read_text(encoding="utf-8")
        assert "tracker=" in src, f"{path} never passes a tracker to .query()"
