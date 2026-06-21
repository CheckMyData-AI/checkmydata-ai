"""Unit tests: ARQ job ids must be unique per run (not static strings).

Rationale: a static task_id causes ARQ to silently no-op a re-enqueue while
a prior result key lingers in Redis. DB-status + 409 guard remain the dedup
source of truth; uniqueness here ensures every trigger actually reaches the
worker.
"""

from __future__ import annotations

import app.api.routes.connections as conn_routes


async def test_db_index_enqueue_uses_unique_job_id(monkeypatch):
    captured: dict = {}

    async def fake_enqueue(name, **kwargs):
        captured["name"] = name
        captured["task_id"] = kwargs.get("task_id")
        return "job"

    monkeypatch.setattr(conn_routes.task_queue, "is_arq_active", lambda: True)
    monkeypatch.setattr(conn_routes.task_queue, "enqueue", fake_enqueue)

    await conn_routes._dispatch_db_index("conn-123", object(), "proj-1")
    assert captured["name"] == "run_db_index"
    assert captured["task_id"].startswith("db_index:conn-123:")
    assert captured["task_id"] != "db_index:conn-123"


async def test_code_db_sync_enqueue_uses_unique_job_id(monkeypatch):
    captured: dict = {}

    async def fake_enqueue(name, **kwargs):
        captured["name"] = name
        captured["task_id"] = kwargs.get("task_id")
        return "job"

    monkeypatch.setattr(conn_routes.task_queue, "is_arq_active", lambda: True)
    monkeypatch.setattr(conn_routes.task_queue, "enqueue", fake_enqueue)

    await conn_routes._dispatch_code_db_sync("conn-456", "proj-2")
    assert captured["name"] == "run_code_db_sync"
    assert captured["task_id"].startswith("code_db_sync:conn-456:")
    assert captured["task_id"] != "code_db_sync:conn-456"


async def test_job_ids_differ_across_calls(monkeypatch):
    """Two sequential calls must produce distinct task_ids."""
    ids: list[str] = []

    async def fake_enqueue(name, **kwargs):
        ids.append(kwargs.get("task_id", ""))
        return "job"

    monkeypatch.setattr(conn_routes.task_queue, "is_arq_active", lambda: True)
    monkeypatch.setattr(conn_routes.task_queue, "enqueue", fake_enqueue)

    await conn_routes._dispatch_db_index("conn-789", object(), "proj-3")
    await conn_routes._dispatch_db_index("conn-789", object(), "proj-3")
    assert ids[0] != ids[1], "Two enqueues for the same connection must get different task_ids"
