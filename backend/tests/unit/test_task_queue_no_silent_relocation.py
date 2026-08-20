"""F-SCHED-04 — an ARQ enqueue failure quietly moved the job into the web dyno.

`enqueue()` has two modes and they were collapsed into one. With no `REDIS_URL` the
in-process `asyncio.create_task` path is the *intended* mode — that is how dev runs, and
the module says so. With Redis configured, an `enqueue_job` that throws is a production
incident: the code logged a **warning** and ran the job in the web process anyway.

For `run_repo_index` that is the pipeline measured at ~1 GB peak, executing inside the
dyno that serves user requests. It either OOMs the API or badly degrades latency, and the
only trace is one line at warning level.

The fix does not remove the fallback — it is right for light work and for dev. It
separates the two situations:

* **No Redis configured** → in-process, `INFO`, unchanged.
* **Redis configured, enqueue failed** → `ERROR`, because something is wrong with Redis
  and a warning is where that goes to die.
* **Redis configured, enqueue failed, and the caller says in-process is not a substitute**
  → refuse. Returning `None` makes the caller surface a failure the user can retry,
  which is a better outcome than a gigabyte silently relocating into the web dyno.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.core import task_queue


@pytest.fixture(autouse=True)
def _clean_state():
    task_queue._fallback_tasks.clear()
    yield
    task_queue._fallback_tasks.clear()


async def _ran() -> str:
    return "ran in process"


class TestWithoutRedisNothingChanges:
    """In-process is the intended mode for dev; this is not the bug."""

    async def test_it_runs_in_process(self, caplog):
        with patch.object(task_queue, "_arq_pool", None):
            with caplog.at_level(logging.DEBUG):
                key = await task_queue.enqueue("run_repo_index", _ran, task_id="t1")

        assert key == "t1"
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    async def test_a_heavy_task_still_runs_in_process_without_redis(self):
        """The refusal is about Redis failing, not about the task being heavy. A
        deployment with no Redis has nowhere else to run it, and refusing would leave the
        feature simply broken."""
        with patch.object(task_queue, "_arq_pool", None):
            key = await task_queue.enqueue(
                "run_repo_index", _ran, task_id="t2", allow_in_process=False
            )

        assert key == "t2"


class TestWithRedisAFailureIsAnIncident:
    @pytest.fixture
    def failing_pool(self):
        pool = AsyncMock()
        pool.enqueue_job = AsyncMock(side_effect=ConnectionResetError("redis went away"))
        return pool

    async def test_the_failure_is_logged_at_error_not_warning(self, failing_pool, caplog):
        """A warning is where a broken Redis goes to die: production log level hides
        nothing at WARNING, but nobody alerts on it either."""
        with patch.object(task_queue, "_arq_pool", failing_pool):
            with caplog.at_level(logging.DEBUG):
                await task_queue.enqueue("run_db_index", _ran, task_id="t3")

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, "an enqueue failure with Redis configured is not a warning"
        assert "run_db_index" in errors[0].getMessage()

    async def test_a_light_task_still_falls_back(self, failing_pool):
        """The fallback is not the bug. Removing it would turn a Redis blip into lost
        work for tasks that cost nothing to run here."""
        with patch.object(task_queue, "_arq_pool", failing_pool):
            key = await task_queue.enqueue("send_notification", _ran, task_id="t4")

        assert key == "t4"

    async def test_a_task_that_refuses_in_process_returns_none(self, failing_pool):
        """The finding: `run_repo_index` peaks near 1 GB. Running it in the web dyno is
        not a degraded version of running it in the worker — it is an outage with extra
        steps."""
        with patch.object(task_queue, "_arq_pool", failing_pool):
            key = await task_queue.enqueue(
                "run_repo_index", _ran, task_id="t5", allow_in_process=False
            )

        assert key is None
        assert "t5" not in task_queue._fallback_tasks

    async def test_the_refusal_says_which_task_and_why(self, failing_pool, caplog):
        with patch.object(task_queue, "_arq_pool", failing_pool):
            with caplog.at_level(logging.DEBUG):
                await task_queue.enqueue(
                    "run_repo_index", _ran, task_id="t6", allow_in_process=False
                )

        said = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
        assert "run_repo_index" in said
        assert "web" in said.lower() or "in-process" in said.lower()


class TestTheHeavyCallSitesDeclareIt:
    """A parameter nobody passes is a parameter that does nothing."""

    def test_repo_index_refuses_in_process(self):
        import inspect

        from app.api.routes import repos

        src = inspect.getsource(repos)
        idx = src.index('"run_repo_index"')
        assert "allow_in_process=False" in src[idx : idx + 400], (
            "the repo index is the job that was measured at ~1 GB; it must not relocate "
            "into the web dyno"
        )

    def test_db_index_refuses_in_process(self):
        import inspect

        from app.api.routes import connections

        src = inspect.getsource(connections)
        for marker in ('"run_db_index"', '"run_code_db_sync"'):
            idx = src.index(marker)
            assert "allow_in_process=False" in src[idx : idx + 400], marker
