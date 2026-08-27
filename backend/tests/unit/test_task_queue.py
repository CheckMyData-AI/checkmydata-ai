"""Unit tests for the task queue abstraction (asyncio fallback path)."""

import asyncio

import pytest

from app.core.task_queue import (
    _fallback_tasks,
    close_task_queue,
    enqueue,
    init_task_queue,
    is_arq_active,
    is_task_running,
)


@pytest.fixture(autouse=True)
async def _clean_queue():
    """Ensure the queue is in a clean state before and after each test."""
    _fallback_tasks.clear()
    yield
    await close_task_queue()


@pytest.mark.asyncio
async def test_init_without_redis():
    await init_task_queue(None)
    assert len(_fallback_tasks) == 0


@pytest.mark.asyncio
async def test_enqueue_runs_in_process():
    result: dict = {}

    async def my_task(value: int = 0):
        result["v"] = value

    task_id = await enqueue("my_task", my_task, task_id="t1", value=42)
    assert task_id == "t1"
    await asyncio.sleep(0.05)
    assert result["v"] == 42


@pytest.mark.asyncio
async def test_enqueue_deduplicates():
    call_count = 0

    async def slow_task():
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(1)

    await enqueue("slow", slow_task, task_id="dup1")
    dup = await enqueue("slow", slow_task, task_id="dup1")
    assert dup == "dup1"
    assert is_task_running("dup1")


@pytest.mark.asyncio
async def test_is_task_running():
    async def long_task():
        await asyncio.sleep(10)

    assert not is_task_running("nonexistent")
    await enqueue("long", long_task, task_id="running1")
    assert is_task_running("running1")


@pytest.mark.asyncio
async def test_enqueue_no_factory_returns_none():
    result = await enqueue("missing_task", None, task_id="x")
    assert result is None


@pytest.mark.asyncio
async def test_close_cancels_running_tasks():
    async def forever():
        await asyncio.sleep(999)

    await enqueue("forever", forever, task_id="c1")
    assert is_task_running("c1")
    await close_task_queue()
    assert not is_task_running("c1")
    assert len(_fallback_tasks) == 0


@pytest.mark.asyncio
async def test_cleanup_on_task_completion():
    async def quick():
        pass

    await enqueue("quick", quick, task_id="done1")
    await asyncio.sleep(0.05)
    assert not is_task_running("done1")
    assert "done1" not in _fallback_tasks


@pytest.mark.asyncio
async def test_is_arq_active_false_in_fallback():
    """Without Redis the queue runs in-process and ARQ is never active."""
    await init_task_queue(None)
    assert is_arq_active() is False


@pytest.mark.asyncio
async def test_enqueue_arq_does_not_forward_job_timeout(monkeypatch):
    """arq's ``enqueue_job`` has no ``_job_timeout`` parameter — unknown kwargs
    are forwarded to the task coroutine, so passing it caused
    ``TypeError: ... got an unexpected keyword argument '_job_timeout'`` on the
    worker (prod daily_sync failures). Per-function timeouts belong to the
    WorkerSettings registration (``arq.worker.func(timeout=...)``), not to the
    enqueue call."""
    from unittest.mock import AsyncMock

    import app.core.task_queue as tq

    pool = AsyncMock()
    pool.enqueue_job.return_value.job_id = "job-1"
    monkeypatch.setattr(tq, "_arq_pool", pool)

    async def dummy():  # pragma: no cover - never runs
        pass

    jid = await tq.enqueue(
        "run_daily_project_knowledge_sync",
        dummy,
        task_id="daily_sync:p1:2026-07-25",
        _job_timeout=7200,
        project_id="p1",
    )

    assert jid == "job-1"
    _, call_kwargs = pool.enqueue_job.call_args
    assert "_job_timeout" not in call_kwargs
    assert call_kwargs["_job_id"] == "daily_sync:p1:2026-07-25"
    assert call_kwargs["project_id"] == "p1"


def _import_worker_with_arq_stub(monkeypatch, worker_module):
    """Import ``app.worker`` fresh with arq stubbed (arq is not installed in the
    unit-test venv; ``WorkerSettings`` builds RedisSettings at class definition)."""
    import importlib
    import sys
    from unittest.mock import MagicMock

    arq_stub = MagicMock()
    arq_stub.connections.RedisSettings = MagicMock(return_value=MagicMock())
    monkeypatch.setitem(sys.modules, "arq", arq_stub)
    monkeypatch.setitem(sys.modules, "arq.connections", arq_stub.connections)
    monkeypatch.setitem(sys.modules, "arq.worker", worker_module)
    redis_tls_stub = MagicMock()
    redis_tls_stub.arq_redis_settings = MagicMock(return_value=MagicMock())
    monkeypatch.setitem(sys.modules, "app.core.redis_tls", redis_tls_stub)
    monkeypatch.delitem(sys.modules, "app.worker", raising=False)
    return importlib.import_module("app.worker")


def test_arq_func_with_timeout_falls_back_without_arq(monkeypatch):
    """Where arq has no ``worker.func`` (or arq is absent) the helper must return
    the raw coroutine so the registration degrades gracefully."""
    import types

    worker_mod = types.ModuleType("arq.worker")  # no `func` attribute on purpose
    w = _import_worker_with_arq_stub(monkeypatch, worker_mod)

    assert (
        w._arq_func_with_timeout(w.run_daily_project_knowledge_sync, 7200)
        is w.run_daily_project_knowledge_sync
    )


def test_daily_sync_registered_with_timeout_when_arq_available(monkeypatch):
    """With arq available the daily sync is registered via ``arq.worker.func``
    carrying the configured per-function timeout (7200s by default) — arq's
    ``enqueue_job`` forwards unknown kwargs to the coroutine, so the timeout
    must live on the function registration."""
    import types

    captured: list = []

    def fake_func(coroutine, **kwargs):
        captured.append((coroutine, kwargs))
        return ("Function", coroutine.__name__, kwargs)

    worker_mod = types.ModuleType("arq.worker")
    worker_mod.func = fake_func
    w = _import_worker_with_arq_stub(monkeypatch, worker_mod)

    # Select by NAME, not by position. This used to take the first tuple in the
    # list, which silently meant "the only wrapped function" — so registering a
    # second one (run_repo_index, AUD-0819-20) broke a test that was never about
    # ordering.
    registration = next(
        f
        for f in w.WorkerSettings.functions
        if isinstance(f, tuple) and f[1] == "run_daily_project_knowledge_sync"
    )
    assert registration == (
        "Function",
        "run_daily_project_knowledge_sync",
        {"timeout": 7200},
    )
    # `captured` holds the coroutine object, not its name.
    assert {c.__name__: kw for c, kw in captured}["run_daily_project_knowledge_sync"] == {
        "timeout": 7200
    }


@pytest.mark.asyncio
async def test_dispatch_db_index_uses_enqueue_when_arq_active(monkeypatch):
    """Phase 0 consolidation: in ARQ mode the DB index goes through the worker
    (task_queue.enqueue) and no in-process task handle is registered."""
    from app.api.routes import connections as conn_routes

    captured: dict = {}

    async def fake_enqueue(task_name, coro_factory=None, *, task_id=None, **kwargs):
        captured["task_name"] = task_name
        captured["task_id"] = task_id
        captured["kwargs"] = kwargs
        return "job-1"

    monkeypatch.setattr(conn_routes.task_queue, "is_arq_active", lambda: True)
    monkeypatch.setattr(conn_routes.task_queue, "enqueue", fake_enqueue)
    conn_routes._db_index_tasks.clear()

    await conn_routes._dispatch_db_index("conn123", object(), "proj456", wf_id="wf-x")

    assert captured["task_name"] == "run_db_index"
    # Task IDs include a random suffix (e.g. "db_index:conn123:abc12345") so
    # each retry gets a unique ARQ job id and is never silently de-duplicated.
    assert captured["task_id"].startswith("db_index:conn123")
    assert captured["kwargs"] == {
        "connection_id": "conn123",
        "project_id": "proj456",
        "wf_id": "wf-x",
        # F-SCHED-04: if the enqueue fails, the DB index must not relocate into the web
        # dyno. Asserted here rather than only at the queue, because a flag the call site
        # forgets to pass is a flag that does nothing.
        "allow_in_process": False,
    }
    # No local handle in ARQ mode — persisted status is authoritative.
    assert "conn123" not in conn_routes._db_index_tasks


@pytest.mark.asyncio
async def test_dispatch_db_index_falls_back_in_process(monkeypatch):
    """Without ARQ the DB index runs in-process and is tracked for the status
    endpoint / 409 guard (unchanged dev behaviour)."""
    from app.api.routes import connections as conn_routes

    ran: dict = {}

    async def fake_bg(connection_id, config, project_id, *, wf_id=None):
        ran["connection_id"] = connection_id
        ran["wf_id"] = wf_id

    monkeypatch.setattr(conn_routes.task_queue, "is_arq_active", lambda: False)
    monkeypatch.setattr(conn_routes, "_run_db_index_background", fake_bg)
    conn_routes._db_index_tasks.clear()

    await conn_routes._dispatch_db_index("connA", object(), "projB", wf_id="wf-y")

    assert "connA" in conn_routes._db_index_tasks
    await asyncio.sleep(0.05)
    assert ran["connection_id"] == "connA"


def test_repo_index_registered_with_its_own_configurable_timeout(monkeypatch):
    """AUD-0819-20: the longest job in the system had the only unconfigurable ceiling.

    `run_repo_index` inherited the class-level `job_timeout = 1800` while its two
    newer siblings read `daily_knowledge_sync_job_timeout_seconds` and
    `analytics_collect_job_timeout_seconds`. Production hit that hardcoded ceiling
    on 2026-08-19: `1800.09s ! run_repo_index failed, TimeoutError` with
    `code_symbol_embed` still running after 29 minutes on a repo of 8,552 files.
    This test used to pin the literal 1800, which is how a default measured as too
    small came to look deliberate: the knob landed, the value did not move, and a
    green test asserted the bad number. It hit production again on 2026-08-27 —
    `1800.02s ! run_repo_index failed, TimeoutError` — while the nightly cron
    rebuilt the same repository in 42.4 min under its own 7200 s ceiling. The
    default is now 3600 and the assertion below compares the registration against
    the setting, which is the wiring this test is named for; the value itself is
    argued in `tests/unit/services/test_repo_index_ceiling.py`, where the
    measurement lives.
    """
    import types

    captured: list = []

    def fake_func(coroutine, **kwargs):
        captured.append((coroutine.__name__, kwargs))
        return ("Function", coroutine.__name__, kwargs)

    worker_mod = types.ModuleType("arq.worker")
    worker_mod.func = fake_func
    w = _import_worker_with_arq_stub(monkeypatch, worker_mod)

    names = {n: kw for n, kw in captured}
    assert "run_repo_index" in names, (
        "run_repo_index must be registered with an explicit timeout, not left on the "
        "class-level job_timeout"
    )
    from app.config import settings

    assert names["run_repo_index"] == {"timeout": settings.repo_index_job_timeout_seconds}
    # The raw coroutine must no longer be registered bare beside the wrapped one.
    bare = [f for f in w.WorkerSettings.functions if getattr(f, "__name__", "") == "run_repo_index"]
    assert bare == []


def test_repo_index_timeout_reads_the_setting(monkeypatch):
    """The value comes from config, so an operator can raise it for a huge repo."""
    import types

    from app.config import settings

    monkeypatch.setattr(settings, "repo_index_job_timeout_seconds", 5400, raising=False)

    captured: list = []

    def fake_func(coroutine, **kwargs):
        captured.append((coroutine.__name__, kwargs))
        return ("Function", coroutine.__name__, kwargs)

    worker_mod = types.ModuleType("arq.worker")
    worker_mod.func = fake_func
    w = _import_worker_with_arq_stub(monkeypatch, worker_mod)
    assert w is not None
    assert dict(captured)["run_repo_index"] == {"timeout": 5400}


def test_a_non_positive_repo_index_timeout_is_refused_at_boot():
    """Project convention: a non-positive bound reads as configured and idles."""
    import pytest as _pytest

    from app.config import Settings

    with _pytest.raises(ValueError, match="REPO_INDEX_JOB_TIMEOUT_SECONDS"):
        Settings(repo_index_job_timeout_seconds=0)
