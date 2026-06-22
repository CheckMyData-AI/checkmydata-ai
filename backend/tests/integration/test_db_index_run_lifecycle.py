"""P1: the DB-index pipeline must reuse a caller-provided wf_id (no self-begin)."""

from __future__ import annotations

import pytest


async def test_db_index_pipeline_reuses_external_wf_id(monkeypatch: pytest.MonkeyPatch):
    from app.connectors.base import ConnectionConfig
    from app.knowledge.db_index_pipeline import DbIndexPipeline

    pipe = DbIndexPipeline(db_index_batch_size=5)

    calls: list[str] = []

    async def fake_begin(pipeline, ctx=None):  # type: ignore[no-untyped-def]
        calls.append(pipeline)
        return "should-not-be-used"

    monkeypatch.setattr(pipe._tracker, "begin", fake_begin)

    cfg = ConnectionConfig(
        db_type="postgres",
        db_host="127.0.0.1",
        db_port=1,
        db_name="x",
        db_user="x",
        db_password="x",
    )
    # The pipeline handles the unreachable connection internally (returns a status
    # dict), but it must NOT have called begin() because we supplied wf_id.
    await pipe.run(connection_id="c", connection_config=cfg, project_id="p", wf_id="wf-ext")

    assert calls == []
