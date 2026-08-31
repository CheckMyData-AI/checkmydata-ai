"""A reaped repo index was destroyed and never re-enqueued.

`StaleRunReaper` flips a stalled `running` row to `failed` and catalogs it, and nothing
puts the work back. For most kinds that is survivable — the nightly cron re-runs them
within 24 hours. For `index_repo` it is not, and the reason is a seam between two
mechanisms that were built separately.

`reconcile_embeddings` advances the `embedding_fingerprint` marker **immediately after
enqueueing** (`embedding_reconcile.py`), not after the rebuild finishes. So when a
deploy restarts the worker twelve minutes into a 3.5-hour `force_full` rebuild, the
reap kills the job and the marker already says the rebuild happened. Nothing re-enqueues
it: not the reconcile, whose fingerprint now matches, and not the nightly cron, which
runs `force_full=False` and therefore cannot rebuild what only a clean run rebuilds.

That path became load-bearing when `GRAPH_EXTRACTION_SCHEMA` joined the fingerprint —
an extractor fix now depends on exactly the rebuild a deploy can silently swallow.

Scope is deliberately narrow. Only `index_repo` is re-enqueued: it is the long job whose
loss is both invisible and permanent. `db_index` and `code_db_sync` are short and the
nightly sync covers them, and re-enqueueing everything would multiply LLM cost on a
worker that is already the memory-constrained process.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.stale_run_reaper import StaleRunReaper


def _doomed(kind: str = "index_repo", *, run_id: str = "r1", project: str = "p1"):
    """The reaper's own tuple shape: (run_id, project_id, kind, connection_id, step)."""
    return [(run_id, project, kind, None, "graph_build")]


@pytest.fixture
def reaper():
    return StaleRunReaper()


class TestTheWorkComesBack:
    async def test_a_reaped_repo_index_is_re_enqueued(self, reaper) -> None:
        session = AsyncMock()
        with (
            patch("app.core.task_queue.enqueue", new=AsyncMock(return_value="job-1")) as enq,
            patch.object(reaper, "_requeue_attempts", new=AsyncMock(return_value=0)),
            patch.object(reaper, "_run_meta", new=AsyncMock(return_value={"force_full": False})),
        ):
            n = await reaper._requeue(session, _doomed())
        assert n == 1
        enq.assert_awaited_once()
        assert enq.await_args.args[0] == "run_repo_index"
        assert enq.await_args.kwargs["project_id"] == "p1"

    async def test_it_inherits_force_full_from_the_run_it_replaces(self, reaper) -> None:
        """A reaped `force_full` rebuild must come back as a rebuild. Coming back as an
        incremental run would look like recovery and fix nothing: `save_incremental`
        merges by FILE, so the untouched files keep the old extraction forever."""
        session = AsyncMock()
        with (
            patch("app.core.task_queue.enqueue", new=AsyncMock(return_value="job-1")) as enq,
            patch.object(reaper, "_requeue_attempts", new=AsyncMock(return_value=0)),
            patch.object(reaper, "_run_meta", new=AsyncMock(return_value={"force_full": True})),
        ):
            await reaper._requeue(session, _doomed())
        assert enq.await_args.kwargs["force_full"] is True


class TestItCannotLoop:
    async def test_it_stops_after_the_attempt_bound(self, reaper) -> None:
        """A run that dies for its own reasons rather than a deploy would otherwise be
        re-enqueued forever, each attempt burning the LLM budget of `generate_docs`."""
        session = AsyncMock()
        with (
            patch("app.core.task_queue.enqueue", new=AsyncMock()) as enq,
            patch.object(reaper, "_requeue_attempts", new=AsyncMock(return_value=99)),
            patch.object(reaper, "_run_meta", new=AsyncMock(return_value={})),
        ):
            n = await reaper._requeue(session, _doomed())
        assert n == 0
        enq.assert_not_awaited()

    async def test_the_bound_counts_recent_reaps_for_the_same_project(self, reaper) -> None:
        """Counting reaps rather than holding a counter on the row: the row being
        counted is the one just destroyed, and a fresh run starts a fresh row."""
        import inspect

        source = inspect.getsource(reaper._requeue_attempts)
        assert "REAP_ERROR" in source, "the bound must count reaped runs, not all failures"
        assert "project_id" in source and "kind" in source


class TestTheOtherKindsAreLeftAlone:
    @pytest.mark.parametrize("kind", ["db_index", "code_db_sync", "daily_sync"])
    async def test_short_kinds_are_not_re_enqueued(self, reaper, kind) -> None:
        session = AsyncMock()
        with (
            patch("app.core.task_queue.enqueue", new=AsyncMock()) as enq,
            patch.object(reaper, "_requeue_attempts", new=AsyncMock(return_value=0)),
            patch.object(reaper, "_run_meta", new=AsyncMock(return_value={})),
        ):
            n = await reaper._requeue(session, _doomed(kind=kind))
        assert n == 0
        enq.assert_not_awaited()


class TestItNeverBreaksTheReap:
    async def test_an_enqueue_failure_does_not_abort_the_reap(self, reaper) -> None:
        """The reap is the recovery. A re-enqueue that raises would leave `running` rows
        unreaped and the UI spinning — the exact state the reaper exists to end."""
        session = AsyncMock()
        with (
            patch("app.core.task_queue.enqueue", new=AsyncMock(side_effect=RuntimeError("redis"))),
            patch.object(reaper, "_requeue_attempts", new=AsyncMock(return_value=0)),
            patch.object(reaper, "_run_meta", new=AsyncMock(return_value={})),
        ):
            n = await reaper._requeue(session, _doomed())
        assert n == 0

    async def test_the_flag_switches_it_off(self, reaper) -> None:
        session = AsyncMock()
        with (
            patch("app.services.stale_run_reaper.settings") as s,
            patch("app.core.task_queue.enqueue", new=AsyncMock()) as enq,
        ):
            s.reaper_requeue_enabled = False
            n = await reaper._requeue(session, _doomed())
        assert n == 0
        enq.assert_not_awaited()


def test_reap_once_calls_requeue_after_cataloguing() -> None:
    """Order matters: catalog first so the failure is recorded even if the re-enqueue
    fails, and re-enqueue after the UPDATE so the bound counts the row just reaped."""
    import inspect

    source = inspect.getsource(StaleRunReaper.reap_once)
    assert "_requeue" in source, "reap_once never re-enqueues; a reaped index stays lost"
    assert source.index("_catalog") < source.index("_requeue")
