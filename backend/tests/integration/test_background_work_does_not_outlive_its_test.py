"""B-21: background work a test starts is gone before the next test begins.

The two tests run in file order. The first deliberately leaves a task running; the
second asserts the `db_session` teardown cancelled it. Without the drain in
`tests/integration/conftest.py` the second fails.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.background import _BACKGROUND_TASKS, spawn_tracked

_LEFT_BEHIND: list[asyncio.Task] = []


@pytest.mark.asyncio
async def test_a_test_that_leaves_work_running(db_session):
    started = asyncio.Event()

    async def lingering():
        started.set()
        await asyncio.sleep(3600)

    _LEFT_BEHIND.append(spawn_tracked(lingering(), name="b21-lingering"))
    await started.wait()


@pytest.mark.asyncio
async def test_the_next_test_does_not_inherit_it(db_session):
    assert _LEFT_BEHIND, "the first test did not run first"
    assert _LEFT_BEHIND[0].done(), "a task from the previous test is still running"
    assert not [t for t in _BACKGROUND_TASKS if not t.done()]
