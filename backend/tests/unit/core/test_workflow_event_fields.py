from __future__ import annotations

import dataclasses
import json

from app.core.workflow_tracker import WorkflowEvent, tracker


def test_event_has_first_class_progress_fields():
    ev = WorkflowEvent(
        workflow_id="wf",
        step="analyze_files",
        status="completed",
        run_id="run-1",
        kind="index_repo",
        step_index=3,
        total_steps=9,
        progress_pct=33,
    )
    payload = json.loads(ev.to_json())
    assert payload["run_id"] == "run-1"
    assert payload["kind"] == "index_repo"
    assert payload["step_index"] == 3
    assert payload["total_steps"] == 9
    assert payload["progress_pct"] == 33


async def test_broadcast_external_tolerates_unknown_keys():
    payload = {
        "workflow_id": "wf-x",
        "step": "pipeline_start",
        "status": "started",
        "pipeline": "db_index",
        "run_id": "r",
        "future_field": "ignore-me",
    }
    fields = {f.name for f in dataclasses.fields(WorkflowEvent)}
    ev = WorkflowEvent(**{k: v for k, v in payload.items() if k in fields})
    # Must not raise even if the instance later carries an unexpected attribute.
    ev.future_field = "ignore-me"  # type: ignore[attr-defined]
    await tracker.broadcast_external(ev)
    assert ev.run_id == "r"
