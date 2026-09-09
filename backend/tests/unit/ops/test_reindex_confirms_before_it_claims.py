"""Dropping the vectors and failing to queue the rebuild must not read as success.

Found on 2026-09-09 while measuring T05, by doing it: a one-off dyno called
`queue_embedding_reindex` for the one production project and the log said

    INFO  queue_embedding_reindex: dropped collection for project 38856e63
    ERROR No coro_factory for in-process fallback of task run_repo_index
    INFO  queue_embedding_reindex: enqueued run_repo_index for project 38856e63 (job=None)
    INFO  queue_embedding_reindex: done — 1 project(s) queued for re-embedding.

The embeddings were gone and nothing was going to rebuild them. Two of those four lines
are INFO-level statements of success about a failure, and the last one counts the INPUT
list rather than the outcome.

The consequence is worse one level up. `reconcile_embeddings` (`embedding_reconcile.py:90`)
**discards the return value**, then advances the `embedding_fingerprint` marker and logs
"reindexed %d project(s)" from `len(ids)`. So a failed enqueue leaves: collections
dropped, no rebuild queued, and a marker asserting the rebuild already happened. The
nightly cron runs `force_full=False` and cannot redo what only a clean run does — which is
the same reasoning CLAUDE.md already records for why `StaleRunReaper._requeue` exists for
`index_repo` alone.

Three claims computed from the input instead of the outcome, in a row. The rule here is
the one this repository keeps re-learning: **a summary must be counted from what
happened.**
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch


class TestTheEnqueueIsChecked:
    async def test_a_failed_enqueue_is_an_error_not_an_info(self, caplog) -> None:
        from app.services.embedding_reindex import queue_embedding_reindex

        with (
            patch("app.services.embedding_reindex.make_vector_store", return_value=MagicMock()),
            patch("app.services.embedding_reindex.enqueue", new=AsyncMock(return_value=None)),
            caplog.at_level(logging.DEBUG),
        ):
            out = await queue_embedding_reindex(["p1"])

        assert out == [None]
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, "a dropped collection with no rebuild queued was logged as success"
        joined = " ".join(r.getMessage() for r in errors)
        assert "p1"[:8] in joined

    async def test_the_summary_counts_what_happened(self, caplog) -> None:
        """`done — 1 project(s) queued` was computed from the argument list. One that
        counts the outcome cannot say "queued" about a project that was not."""
        from app.services.embedding_reindex import queue_embedding_reindex

        async def _half(*_a, project_id: str = "", **_k):
            return "job-1" if project_id == "p1" else None

        with (
            patch("app.services.embedding_reindex.make_vector_store", return_value=MagicMock()),
            patch("app.services.embedding_reindex.enqueue", new=AsyncMock(side_effect=_half)),
            caplog.at_level(logging.INFO),
        ):
            out = await queue_embedding_reindex(["p1", "p2"])

        assert out == ["job-1", None]
        summary = [r.getMessage() for r in caplog.records if "done" in r.getMessage()]
        assert summary, "no summary line"
        assert "1" in summary[0] and "2" in summary[0], (
            f"the summary must name both numbers, got {summary[0]!r} — a run that queued "
            "one of two projects and reported '2 queued' is the defect this replaces"
        )

    async def test_a_clean_run_still_reports_cleanly(self, caplog) -> None:
        from app.services.embedding_reindex import queue_embedding_reindex

        with (
            patch("app.services.embedding_reindex.make_vector_store", return_value=MagicMock()),
            patch("app.services.embedding_reindex.enqueue", new=AsyncMock(return_value="j")),
            caplog.at_level(logging.DEBUG),
        ):
            out = await queue_embedding_reindex(["p1", "p2"])

        assert out == ["j", "j"]
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


class TestTheMarkerDescribesWhatHappened:
    """The half that actually loses data.

    `reconcile_embeddings` advances `embedding_fingerprint` on ENQUEUE, which is right —
    the rebuild is asynchronous and waiting for it would block boot. But it must advance
    on an enqueue that HAPPENED. A marker saying "this config has been rebuilt" when
    nothing was queued is unrecoverable by the nightly cron, which is incremental.
    """

    def test_the_reconcile_reads_the_result_it_used_to_discard(self) -> None:
        import inspect
        import re

        from app.ops import embedding_reconcile

        src = inspect.getsource(embedding_reconcile.reconcile_embeddings)
        body = re.sub(r'"""[\s\S]*?"""', "", src)
        body = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
        call = next(ln for ln in body.splitlines() if "queue_embedding_reindex(" in ln)
        assert "=" in call.split("await")[0], (
            f"the return value is discarded ({call.strip()!r}); a failed enqueue would "
            "advance the marker and claim the rebuild happened"
        )
        assert "queued" in " ".join(body.split()), "the result must be inspected, not just bound"

    def test_the_marker_is_not_advanced_when_nothing_was_queued(self) -> None:
        """Source-level, because the alternative needs an advisory lock, a real session
        and a Redis pool. The property: the assignment to `stored.value` must be reachable
        only through a check on the enqueue outcome."""
        import inspect
        import re

        from app.ops import embedding_reconcile

        src = inspect.getsource(embedding_reconcile.reconcile_embeddings)
        body = re.sub(r'"""[\s\S]*?"""', "", src)
        lines = [ln for ln in body.splitlines() if not ln.lstrip().startswith("#")]
        advance = next(i for i, ln in enumerate(lines) if "stored.value = current" in ln)
        guard = next(
            (i for i, ln in enumerate(lines) if "queued" in ln and ln.lstrip().startswith("if")),
            None,
        )
        assert guard is not None and guard < advance, (
            "the fingerprint marker is advanced without checking that anything was "
            "actually enqueued — the state that leaves is: collections dropped, no "
            "rebuild queued, and a marker asserting it already ran"
        )
