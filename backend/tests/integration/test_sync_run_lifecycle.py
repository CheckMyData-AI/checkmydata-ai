"""P1: the code-DB sync pipeline must reuse a caller-provided wf_id (no self-begin)."""

from __future__ import annotations

import pytest


async def test_sync_pipeline_reuses_external_wf_id(monkeypatch: pytest.MonkeyPatch):
    from app.knowledge.code_db_sync_pipeline import CodeDbSyncPipeline

    pipe = CodeDbSyncPipeline()

    calls: list[str] = []

    async def fake_begin(pipeline, ctx=None):  # type: ignore[no-untyped-def]
        calls.append(pipeline)
        return "unused"

    monkeypatch.setattr(pipe._tracker, "begin", fake_begin)

    # run() handles "no code knowledge / no DB index" internally (returns a status
    # dict), but must NOT call begin() because we supplied wf_id.
    await pipe.run(connection_id="c", project_id="p", wf_id="wf-ext")

    assert calls == []
