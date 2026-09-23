"""T07 / PRJ-07 S-04 — one repository index at a time, whichever path starts it.

`MAX_CONCURRENT_REPO_INDEXES = 1` was enforced only inside the ARQ wrapper
`worker.run_repo_index`. The nightly sync calls `run_repo_index_task` directly under the
worker's `max_jobs = 8`, and the wave enqueues every project due at an hour in the same
second — so N projects at one hour meant N concurrent indexes on a dyno one index already
fills (OPS-08). The slot now lives in `run_repo_index_task` itself.
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_two_indexes_started_at_once_run_one_after_the_other(monkeypatch) -> None:
    from app.api.routes import repos

    running = 0
    peak = 0

    async def _body(project_id, force_full=False, *, chain_sync=True, wf_id=None):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1

    monkeypatch.setattr(repos, "_run_repo_index_task_unlocked", _body)
    await asyncio.gather(repos.run_repo_index_task("p1"), repos.run_repo_index_task("p2"))
    assert peak == 1, "two repository indexes ran at once"


def test_the_arq_wrapper_does_not_take_a_second_slot() -> None:
    """One slot, acquired once: a wrapper that also held it would deadlock on itself."""
    import inspect

    from app import worker

    assert "_repo_index_slots" not in inspect.getsource(worker.run_repo_index)
