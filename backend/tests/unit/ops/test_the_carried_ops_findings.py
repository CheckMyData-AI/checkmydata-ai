"""Board row 11b: the four findings #347 named and did not close.

OPS-03, OPS-10, OPS-15, OPS-16. They are one row because they share a subject —
what an operator can see about the process nobody watches — and one property: each
is a claim the system makes that nothing behind it supports.

- **OPS-03** — every counter the worker emits accumulates in its own heap and dies
  with it. `/api/metrics` renders the WEB process's collector, so a metric the
  documentation calls "the number that says whether the sampling budget is set too
  low" is not zero on that page, it is *absent*.
- **OPS-10** — `_requeue_attempts` counts the reap it is currently performing, so
  the documented "2 per 6 h" is really 1. The log line compounds it by printing
  `attempts + 1`, announcing the first requeue as "attempt 2".
- **OPS-15** — a Redis connect failure at boot leaves `_arq_pool = None` for the
  life of the process and nothing retries, so `is_arq_active()` is False forever:
  the full repo index runs inside the web dyno, which is exactly what
  `allow_in_process=False` exists to forbid.
- **OPS-16** — the orphan sweep marks a run `failed` with no `finished_at`, no
  `failure_kind` and no catalog row, including when its own re-enqueue returned
  `None` — the very failure the sweep exists to surface.
"""

from __future__ import annotations

from typing import Any

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


@pytest_asyncio.fixture(autouse=True)
def _this_process_is_a_worker(monkeypatch):
    """A test process has no `DYNO`, so `owner()` is empty and the sweep correctly
    skips everything — it must never act when it cannot tell whose run it sees."""
    monkeypatch.setenv("DYNO", "worker.1")


@pytest_asyncio.fixture
async def orphan_db():
    import app.models  # noqa: F401  — registers every table on the metadata
    from app.models.base import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


class _FakeRedis:
    """Enough of the async client for the metrics sink, with no Redis running."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, float]] = {}
        self.expiries: dict[str, int] = {}
        self.closed = False

    async def hincrbyfloat(self, key: str, field: str, amount: float) -> float:
        bucket = self.hashes.setdefault(key, {})
        bucket[field] = bucket.get(field, 0.0) + amount
        return bucket[field]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expiries[key] = seconds
        return True

    async def scan_iter(self, match: str = "*", **_: Any):
        prefix = match.rstrip("*")
        for key in list(self.hashes):
            if key.startswith(prefix):
                yield key

    async def hgetall(self, key: str) -> dict[str, str]:
        return {f: str(v) for f, v in self.hashes.get(key, {}).items()}

    async def aclose(self) -> None:
        self.closed = True


class TestTheWorkersCountersReachTheEndpoint:
    """OPS-03."""

    async def test_a_flush_publishes_this_process_contribution(self) -> None:
        from app.core.metrics import MetricsCollector
        from app.ops.metrics_store import MetricsStore

        collector = MetricsCollector()
        collector.inc("indexing_runs_total", kind="index_repo", status="completed")
        collector.inc("indexing_runs_total", kind="index_repo", status="completed")

        redis = _FakeRedis()
        store = MetricsStore(redis, process="worker")
        await store.flush(collector)

        published = await store.read_all()
        assert any(
            name == "indexing_runs_total" and value == 2.0 for name, _labels, value in published
        ), f"the worker's counters did not reach the shared store: {published}"

    async def test_a_second_flush_publishes_only_the_delta(self) -> None:
        """Two dynos of one process type share a namespace, so flushes must ADD.

        A flush that wrote the cumulative total with HSET would have the second web
        dyno clobber the first. `HINCRBY` of the delta sums correctly, and it is also
        what makes repeated flushes from one process idempotent rather than doubling.
        """
        from app.core.metrics import MetricsCollector
        from app.ops.metrics_store import MetricsStore

        collector = MetricsCollector()
        redis = _FakeRedis()
        store = MetricsStore(redis, process="worker")

        collector.inc("indexing_runs_total", kind="index_repo", status="completed")
        await store.flush(collector)
        await store.flush(collector)  # nothing new happened in between

        total = [v for n, _l, v in await store.read_all() if n == "indexing_runs_total"]
        assert total == [1.0], f"a second flush double-counted: {total}"

        collector.inc("indexing_runs_total", kind="index_repo", status="completed")
        await store.flush(collector)
        total = [v for n, _l, v in await store.read_all() if n == "indexing_runs_total"]
        assert total == [2.0]

    async def test_two_processes_are_summed_not_clobbered(self) -> None:
        from app.core.metrics import MetricsCollector
        from app.ops.metrics_store import MetricsStore

        redis = _FakeRedis()
        for process in ("web", "worker"):
            collector = MetricsCollector()
            collector.inc("indexing_runs_total", kind="index_repo", status="completed")
            await MetricsStore(redis, process=process).flush(collector)

        published = await MetricsStore(redis, process="web").read_all()
        total = [v for n, _l, v in published if n == "indexing_runs_total"]
        assert total == [2.0], f"processes did not sum: {published}"

    async def test_labels_survive_the_round_trip(self) -> None:
        """A counter without its labels answers a different question."""
        from app.core.metrics import MetricsCollector
        from app.ops.metrics_store import MetricsStore

        collector = MetricsCollector()
        collector.inc("indexing_runs_total", kind="index_repo", status="failed")
        redis = _FakeRedis()
        store = MetricsStore(redis, process="worker")
        await store.flush(collector)

        published = await store.read_all()
        labels = [dict(lbl) for n, lbl, _v in published if n == "indexing_runs_total"]
        assert labels and labels[0].get("status") == "failed", published

    async def test_the_endpoint_renders_the_shared_store_when_there_is_one(self) -> None:
        from app.core.metrics import MetricsCollector
        from app.ops.metrics_store import MetricsStore, render_with_store

        worker_view = MetricsCollector()
        worker_view.inc("indexing_runs_total", kind="index_repo", status="completed")
        redis = _FakeRedis()
        await MetricsStore(redis, process="worker").flush(worker_view)

        web_view = MetricsCollector()
        body = await render_with_store(web_view, MetricsStore(redis, process="web"))
        assert "indexing_runs_total" in body, (
            "the web process rendered only its own heap, so a counter the worker "
            "emitted is ABSENT from the page rather than zero (OPS-03)"
        )

    async def test_no_store_still_renders_the_local_view(self) -> None:
        """Dev has no Redis, and the endpoint must keep working there."""
        from app.core.metrics import MetricsCollector
        from app.ops.metrics_store import render_with_store

        local = MetricsCollector()
        local.inc("indexing_runs_total", kind="index_repo", status="completed")
        body = await render_with_store(local, None)
        assert "indexing_runs_total" in body


class TestTheWiringExists:
    """A store nothing calls is not a fix (OPS-03)."""

    def test_the_worker_starts_a_flush_loop(self) -> None:
        import ast
        import inspect

        from app import worker

        tree = ast.parse(inspect.getsource(worker.startup))
        started = {
            ast.unparse(node.value) for node in ast.walk(tree) if isinstance(node, ast.Assign)
        }
        assert any("_metrics_flush_loop" in call for call in started), (
            "the worker runs `arq`, not uvicorn, so nothing scrapes it: without a "
            "flush loop every counter it emits still dies with the process (OPS-03)"
        )

    def test_shutdown_cancels_it(self) -> None:
        import inspect

        from app import worker

        assert "metrics_task" in inspect.getsource(worker.shutdown), (
            "a task nobody cancels keeps the event loop alive past shutdown"
        )

    def test_the_prometheus_endpoint_reads_the_store(self) -> None:
        import inspect

        from app.api.routes.metrics import get_prometheus

        assert "render_with_store" in inspect.getsource(get_prometheus), (
            "the endpoint rendered the web process's own collector, which never saw "
            "an ARQ job's counters (OPS-03)"
        )

    async def test_the_flush_loop_survives_a_failing_store(self) -> None:
        """It measures the process; it must not be able to stop it."""
        import asyncio
        from unittest.mock import patch

        from app import worker

        class _Broken:
            async def flush(self, _collector):  # noqa: ANN001
                raise RuntimeError("redis went away")

        with (
            patch.object(worker, "METRICS_FLUSH_INTERVAL_SECONDS", 0.01),
            patch("app.ops.metrics_store.get_metrics_store", return_value=_Broken()),
        ):
            task = asyncio.create_task(worker._metrics_flush_loop())
            await asyncio.sleep(0.05)
            still_running = not task.done()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        assert still_running, "a failing flush killed the loop that performs it"


class TestTheRequeueBudgetIsTheOneDocumented:
    """OPS-10."""

    async def test_the_reap_in_flight_is_not_counted_against_itself(self) -> None:
        """The count must exclude the row `reap_once` has just written.

        `reap_once` runs the UPDATE, flushes, and only then calls `_requeue`, so the
        query behind the budget saw the reap it was deciding about.
        """
        from unittest.mock import AsyncMock, patch

        from app.services.stale_run_reaper import StaleRunReaper

        reaper = StaleRunReaper()
        seen: dict[str, Any] = {}

        async def _record(_session, project_id, kind, *, exclude_run_id=None):
            seen["excluded"] = exclude_run_id
            return 0

        with (
            patch("app.core.task_queue.enqueue", new=AsyncMock(return_value="job-1")),
            patch.object(reaper, "_requeue_attempts", new=_record),
            patch.object(reaper, "_run_meta", new=AsyncMock(return_value={})),
        ):
            await reaper._requeue(AsyncMock(), [("run-7", "p1", "index_repo", None, "step")])

        assert seen.get("excluded") == "run-7", (
            "with `reaper_requeue_max_attempts = 2` the first reap saw 1 and "
            "requeued, the second saw 2 and refused — a bound the operator is told "
            "allows two retries, spent after one (OPS-10)"
        )

    async def test_the_first_requeue_is_announced_as_the_first(self, caplog) -> None:
        from unittest.mock import AsyncMock, patch

        from app.services.stale_run_reaper import StaleRunReaper

        reaper = StaleRunReaper()
        with (
            patch("app.core.task_queue.enqueue", new=AsyncMock(return_value="job-1")),
            patch.object(reaper, "_requeue_attempts", new=AsyncMock(return_value=0)),
            patch.object(reaper, "_run_meta", new=AsyncMock(return_value={})),
            caplog.at_level("INFO", logger="app.services.stale_run_reaper"),
        ):
            await reaper._requeue(AsyncMock(), [("run-7", "p1", "index_repo", None, "step")])

        line = " ".join(r.getMessage() for r in caplog.records)
        assert "attempt 1 of" in line, (
            f"the reaper announced its first requeue as something else: {line!r}. It "
            "printed `attempts + 1` on a count that already contained this reap, so "
            "the first requeue was reported as 'attempt 2' (OPS-10)"
        )


class TestABootWithoutRedisIsNotPermanent:
    """OPS-15."""

    async def test_a_failed_connect_is_retried_once_the_backoff_has_passed(
        self, monkeypatch
    ) -> None:
        """Time is ADVANCED rather than the backoff being cleared.

        The first draft called `_reset_pool_backoff()` between the two attempts, and a
        planted defect that never retries — `if _next_pool_attempt: return None` —
        passed it, because clearing the flag satisfies that condition too. A guard has
        to move the thing the code reads, not the thing the test can reach.
        """
        from app.core import task_queue

        attempts = {"n": 0}
        clock = {"t": 1000.0}
        monkeypatch.setattr(task_queue.time, "monotonic", lambda: clock["t"])

        async def _flaky(_settings: Any) -> Any:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ConnectionError("redis is not up yet")
            return object()

        original = task_queue._arq_pool
        try:
            task_queue._arq_pool = None
            task_queue._reset_pool_backoff()
            await task_queue._ensure_pool("redis://x", create=_flaky)
            assert task_queue._arq_pool is None, "the first attempt must have failed"

            clock["t"] += task_queue.POOL_RETRY_BACKOFF_SECONDS + 1
            await task_queue._ensure_pool("redis://x", create=_flaky)
            assert task_queue._arq_pool is not None, (
                "`init_task_queue` caught the connect exception, left `_arq_pool` at "
                "None and nothing ever retried — so `is_arq_active()` was False for "
                "the process's life and the repo index ran inside the web dyno, which "
                "is exactly what `allow_in_process=False` forbids (OPS-15)"
            )
        finally:
            task_queue._arq_pool = original
            task_queue._reset_pool_backoff()

    async def test_the_retry_is_rate_limited(self) -> None:
        """A dead Redis must not mean a connect attempt per enqueue."""
        from app.core import task_queue

        attempts = {"n": 0}

        async def _always_fails(_settings: Any) -> Any:
            attempts["n"] += 1
            raise ConnectionError("down")

        original = task_queue._arq_pool
        try:
            task_queue._arq_pool = None
            task_queue._reset_pool_backoff()
            for _ in range(3):
                await task_queue._ensure_pool("redis://x", create=_always_fails)
            assert attempts["n"] == 1, (
                f"{attempts['n']} connect attempts in a row — a retry with no backoff "
                "turns one Redis outage into a connect storm on every enqueue"
            )
        finally:
            task_queue._arq_pool = original
            task_queue._reset_pool_backoff()

    async def test_with_no_redis_url_nothing_is_attempted(self) -> None:
        """Fallback mode is a configuration, not a fault — it must stay silent."""
        from app.core import task_queue

        attempts = {"n": 0}

        async def _counts(_settings: Any) -> Any:
            attempts["n"] += 1
            return object()

        original_pool, original_url = task_queue._arq_pool, task_queue._arq_url
        try:
            task_queue._arq_pool = None
            task_queue._arq_url = None
            task_queue._reset_pool_backoff()
            assert await task_queue._ensure_pool(None, create=_counts) is None
            assert attempts["n"] == 0, (
                "a deployment with no REDIS_URL would attempt a connection on every enqueue forever"
            )
        finally:
            task_queue._arq_pool, task_queue._arq_url = original_pool, original_url
            task_queue._reset_pool_backoff()


class TestAnOrphanedRunIsFinishedProperly:
    """OPS-16 — measured against a real row, not read off the source."""

    @staticmethod
    async def _orphan(db, *, job_id: str | None) -> Any:
        import json
        from unittest.mock import AsyncMock, patch

        from app.models.indexing_run import IndexingRun
        from app.ops.orphan_runs import requeue_orphaned_runs

        run = IndexingRun(
            id="run-orphan",
            workflow_id="wf-orphan",
            project_id="p1",
            kind="index_repo",
            status="running",
            current_step="graph_build",
            meta_json=json.dumps({"boot_id": "a-previous-boot", "owner": "worker"}),
        )
        db.add(run)
        await db.commit()

        with patch("app.core.task_queue.enqueue", new=AsyncMock(return_value=job_id)):
            await requeue_orphaned_runs(db)
        await db.refresh(run)
        return run

    async def test_the_sweep_stamps_what_makes_a_run_terminal(self, orphan_db) -> None:
        run = await self._orphan(orphan_db, job_id="job-1")
        assert run.status == "failed"
        assert run.finished_at is not None, (
            "the sweep set only `status` and `error`, leaving a terminal run whose "
            "duration `/sync-history` cannot compute (OPS-16)"
        )
        assert run.failure_kind, "and whose failure has no kind"

    async def test_the_error_marker_is_untouched(self) -> None:
        """`ORPHAN_ERROR` is compared verbatim — by `run_coordinator`, and by the
        reaper's budget, which must not spend a reap attempt on a restart."""
        from app.ops.orphan_runs import ORPHAN_ERROR
        from app.services.stale_run_reaper import REAP_ERROR

        assert ORPHAN_ERROR != REAP_ERROR

    async def test_an_orphan_reaches_the_error_catalog(self, orphan_db) -> None:
        from sqlalchemy import select

        from app.models.error_log import ErrorLog

        await self._orphan(orphan_db, job_id="job-1")
        rows = (await orphan_db.scalars(select(ErrorLog))).all()
        assert rows, (
            "unlike a reaped run (N3), an orphaned run never reached `error_log`, so "
            "`/api/logs` showed nothing (OPS-16)"
        )
        assert "graph_build" in (rows[0].message or ""), (
            "the marker alone collapses every orphaned run onto one line; it was the "
            f"step that made the 2026-09-08 cause findable: {rows[0].message!r}"
        )

    async def test_a_failed_re_enqueue_is_catalogued_as_fatal(self, orphan_db) -> None:
        """The very failure the sweep exists to surface produced no row at all."""
        from sqlalchemy import select

        from app.models.error_log import ErrorLog

        await self._orphan(orphan_db, job_id=None)
        rows = (await orphan_db.scalars(select(ErrorLog))).all()
        fatal = [r for r in rows if r.failure_kind == "fatal"]
        assert fatal, (
            "`enqueue` returns None on failure rather than raising, so the collections "
            "were closed, nothing was queued, and `/api/logs` carried no trace of it: "
            f"{[(r.failure_kind, r.message) for r in rows]}"
        )
