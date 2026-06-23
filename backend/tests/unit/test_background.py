import asyncio
import logging

from app.core.background import _BACKGROUND_TASKS, spawn_tracked


async def test_keeps_strong_reference_until_done():
    ran = asyncio.Event()

    async def work():
        ran.set()
        await asyncio.sleep(0.01)

    task = spawn_tracked(work(), name="t1")
    assert task in _BACKGROUND_TASKS  # referenced while in flight
    await ran.wait()
    await task
    await asyncio.sleep(0)  # let the done-callback run
    assert task not in _BACKGROUND_TASKS  # cleaned up afterwards


async def test_logs_and_swallows_task_exception(caplog):
    async def boom():
        raise ValueError("kaboom")

    with caplog.at_level(logging.ERROR):
        task = spawn_tracked(boom(), name="boomer")
        # the done-callback retrieves the exception; awaiting re-raises it
        await asyncio.sleep(0.01)

    assert task not in _BACKGROUND_TASKS
    assert any("boomer" in r.message and "failed" in r.message for r in caplog.records)
