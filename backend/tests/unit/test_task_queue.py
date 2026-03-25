"""Unit tests for the task queue abstraction (asyncio fallback path)."""

import asyncio

import pytest

from app.core.task_queue import (
    _fallback_tasks,
    close_task_queue,
    enqueue,
    init_task_queue,
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
