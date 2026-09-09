"""The worker could not enqueue anything, so every recovery it owns was a no-op.

Found on 2026-09-09 by the ERROR line the orphan sweep was given for exactly this reason:

    04:30:09  ERROR app.core.task_queue: No coro_factory for in-process fallback
                    of task run_repo_index
    04:30:09  ERROR app.ops.orphan_runs: orphan sweep: index_repo for project 38856e63 was
              orphaned by a restart and could NOT be put back — nothing is rebuilding it.
    04:30:09  INFO  app.ops.orphan_runs: orphan sweep: 1 running index_repo run(s) seen, 0 put back

The sweep worked: it identified the orphan, marked it terminal, and reported that it could
not replace it. What failed is one layer down. `app.core.task_queue.enqueue` routes through
a module-level `_arq_pool`, and `init_task_queue` — the only thing that sets it — is called
in `app/main.py`'s FastAPI lifespan. **The worker never called it.** So `_arq_pool` was
always `None` there, `enqueue` fell through to an in-process fallback that has no
`coro_factory`, and returned `None`.

The worker consumes jobs through arq's own connection, which is why this was invisible:
nothing about taking work was broken. What was broken is everything in that process that
PUTS work back — the orphan sweep, and `StaleRunReaper._requeue`, which runs from the
worker's own `reaper_loop`. The reaper's re-enqueue after a reap has therefore never
worked from the worker; only the copy running on `web`, where the lifespan had built a
pool, could do it.

Both of tonight's ledger entries about recovery — the reaper's requeue budget and the
orphan sweep — assumed an enqueue that could succeed. This is why the budget looked
exhausted rather than spent.
"""

from __future__ import annotations

import inspect
import re


def _startup_code() -> str:
    from app import worker

    src = inspect.getsource(worker.startup)
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))


class TestTheWorkerBuildsAQueueItCanPushTo:
    def test_startup_initialises_the_task_queue(self) -> None:
        assert "init_task_queue" in _startup_code(), (
            "the worker never builds an ARQ pool, so every `enqueue` from this process "
            "returns None — the orphan sweep and StaleRunReaper._requeue both silently "
            "do nothing"
        )

    def test_it_is_initialised_before_anything_enqueues(self) -> None:
        """Order is the whole defect. The orphan sweep ran first and found no pool; so
        would the reaper sweep two lines further down."""
        code = _startup_code()
        init = code.index("init_task_queue(")
        for consumer, why in (
            ("requeue_orphaned_runs", "the orphan sweep puts back what a restart killed"),
            ("run_reaper_sweep", "the reaper's requeue puts back what a reap destroyed"),
        ):
            assert consumer in code, f"{consumer} is not in startup at all"
            assert init < code.index(consumer), (
                f"{consumer} runs before the task queue exists — {why}, and with no pool "
                "it reports success while doing nothing"
            )

    def test_the_pool_is_built_from_the_same_env_the_worker_uses(self) -> None:
        code = _startup_code()
        window = code[code.index("init_task_queue(") - 200 : code.index("init_task_queue(") + 80]
        assert "REDIS_URL" in window or "redis_url" in window, (
            "the pool must be built from REDIS_URL, the same source arq itself uses"
        )


class TestTheFallbackCannotSubstituteHere:
    async def test_enqueue_without_a_pool_returns_none_rather_than_running_inline(self) -> None:
        """Why the failure was silent rather than loud: `enqueue` has an in-process
        fallback, but it needs a `coro_factory` the callers do not pass — deliberately,
        since running a repo index inside the web dyno is what `allow_in_process=False`
        exists to prevent. So it logs and returns `None`, and a caller that does not check
        the return value cannot tell.

        `async def` with a bare `await`, NOT `asyncio.run`. The first version used
        `asyncio.run` and took the suite's event loop out from under everything collected
        after it — three `test_connectors.py` cases went red, in a file this one does not
        touch. `asyncio_mode = "auto"` means an async test already gets a loop; starting a
        second one inside a running suite is the contamination.
        """
        from app.core import task_queue

        assert task_queue._arq_pool is None, "test process should have no pool"
        assert await task_queue.enqueue("run_repo_index", project_id="p1") is None
