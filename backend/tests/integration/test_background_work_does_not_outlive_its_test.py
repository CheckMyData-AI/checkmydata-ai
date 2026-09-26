"""B-21: background work a test starts has finished before the next test begins.

The two tests run in file order. The first starts a task that takes a moment and does
not await it; the second asserts the `db_session` teardown waited for it — and did not
cancel it, because cancelling mid-statement destroys the shared SQLite database
(see `_drain_background_work`). Without the drain the task is still sleeping when the
second test starts.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.background import _BACKGROUND_TASKS, spawn_tracked

_STARTED: list[asyncio.Task] = []
_FINISHED: list[bool] = []


@pytest.mark.asyncio
async def test_a_test_that_leaves_work_running(db_session):
    async def a_moment_of_work():
        await asyncio.sleep(0.5)
        _FINISHED.append(True)

    _STARTED.append(spawn_tracked(a_moment_of_work(), name="b21-a-moment"))
    assert not _FINISHED


@pytest.mark.asyncio
async def test_the_next_test_does_not_inherit_it(db_session):
    assert _STARTED, "the first test did not run first"
    assert _FINISHED == [True], "the previous test's work was still running"
    assert not _STARTED[0].cancelled(), "the drain waits; it must not cancel"
    assert not [t for t in _BACKGROUND_TASKS if not t.done()]
