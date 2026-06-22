from __future__ import annotations

import inspect

from app.agents import orchestrator


def test_partial_answer_failclose_is_cataloged():
    src = inspect.getsource(orchestrator.OrchestratorAgent._validate_partial_answer)
    assert "upsert_validation_failure" in src
    assert 'span_type="validation"' in src
