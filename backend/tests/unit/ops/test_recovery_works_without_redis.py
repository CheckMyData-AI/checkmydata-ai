"""T07 / PRJ-07 S-07 — recovery that works in every deployment, not only on Heroku+Redis.

Two independent gaps made an `index_repo` interrupted by a restart unrecoverable in the
in-process mode (no `REDIS_URL`: Docker Compose, DigitalOcean App Platform):

* the reaper's requeue and the orphan sweep call `enqueue(task_name, **kwargs)` with no
  `coro_factory`, which the in-process fallback answered with `None` — "No coro_factory";
* `owner()` reads Heroku's `DYNO` only, so off Heroku every run was stamped with an empty
  owner, and the sweep skips an unstamped run by design — it could never act there;
* and the sweep ran only in `worker.startup`, which a deployment without Redis never runs.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_a_worker_job_runs_in_process_without_a_factory(monkeypatch) -> None:
    from app import worker
    from app.core import task_queue

    seen: list[dict] = []

    async def _fake(ctx, **kwargs):
        seen.append(kwargs)

    monkeypatch.setattr(task_queue, "_arq_pool", None)
    monkeypatch.setattr(worker, "run_repo_index", _fake)
    job = await task_queue.enqueue("run_repo_index", project_id="p1", force_full=True)
    assert job is not None, "the in-process fallback refused a job the worker knows"
    await task_queue._fallback_tasks[job]
    assert seen == [{"project_id": "p1", "force_full": True}]


@pytest.mark.asyncio
async def test_an_unknown_job_is_still_refused(monkeypatch) -> None:
    from app.core import task_queue

    monkeypatch.setattr(task_queue, "_arq_pool", None)
    assert await task_queue.enqueue("no_such_job", x=1) is None


def test_the_process_role_is_known_off_heroku(monkeypatch) -> None:
    from app.core import release

    monkeypatch.delenv("DYNO", raising=False)
    monkeypatch.setitem(release._ROLE, "role", "")
    assert release.owner() == ""
    release.set_process_role("web")
    assert release.owner() == "web"
    monkeypatch.setenv("DYNO", "worker.1")
    assert release.owner() == "worker", "Heroku's own word still wins"


def test_the_web_process_sweeps_orphans_when_it_is_the_only_process() -> None:
    import inspect

    from app import main

    src = inspect.getsource(main.lifespan)
    assert 'set_process_role("web")' in src
    assert "requeue_orphaned_runs" in src, "with no worker, nothing else would put runs back"


def test_the_in_process_list_is_the_registered_list() -> None:
    """One source of truth in two shapes: a job added to `WorkerSettings.functions`
    without `IN_PROCESS_JOBS` would be unrecoverable without Redis again."""
    import importlib

    worker = importlib.import_module("app.worker")
    registered = {
        getattr(getattr(f, "coroutine", f), "__name__", None)
        for f in worker.WorkerSettings.functions
    }
    assert registered == set(worker.IN_PROCESS_JOBS)
