"""Tests for background task cancellation on shutdown."""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_connections_cancel_background_tasks():
    from app.api.routes import connections

    done_task = asyncio.create_task(asyncio.sleep(0))
    await done_task

    pending_task = asyncio.ensure_future(asyncio.sleep(100))
    connections._db_index_tasks["t1"] = done_task
    connections._sync_tasks["t2"] = pending_task

    await connections.cancel_background_tasks()

    assert pending_task.cancelled()
    assert len(connections._db_index_tasks) == 0
    assert len(connections._sync_tasks) == 0


@pytest.mark.asyncio
async def test_repos_cancel_background_tasks():
    from app.api.routes import repos

    pending_task = asyncio.ensure_future(asyncio.sleep(100))
    repos._indexing_tasks["r1"] = pending_task

    await repos.cancel_background_tasks()

    assert pending_task.cancelled()
    assert len(repos._indexing_tasks) == 0
