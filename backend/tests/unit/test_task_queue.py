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
