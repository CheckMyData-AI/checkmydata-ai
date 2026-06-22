from __future__ import annotations

import dataclasses
import inspect

from app.core import workflow_events
from app.core.workflow_tracker import WorkflowEvent


def test_known_field_filter_drops_extras():
    payload = {
        "workflow_id": "w",
        "step": "s",
        "status": "started",
        "run_id": "r",
        "progress_pct": 40,
        "totally_new_key": 1,
    }
    fields = {f.name for f in dataclasses.fields(WorkflowEvent)}
    ev = WorkflowEvent(**{k: v for k, v in payload.items() if k in fields})
    assert ev.run_id == "r"
    assert ev.progress_pct == 40


def test_subscribe_loop_uses_field_filter():
    src = inspect.getsource(workflow_events._subscribe_loop)
    assert "dataclasses.fields" in src
