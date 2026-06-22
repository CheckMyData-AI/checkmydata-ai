from __future__ import annotations

import inspect

from app.agents import stage_executor


def test_emit_data_gate_uses_validation_span_type_and_catalogs():
    src = inspect.getsource(stage_executor.StageExecutor._emit_data_gate)
    assert 'span_type="validation"' in src
    assert "upsert_validation_failure" in src
