from __future__ import annotations

import pytest

from app.services.trace_persistence_service import classify_span_type


@pytest.mark.parametrize(
    "step,expected",
    [
        ("data_gate", "validation"),
        ("answer_validate", "validation"),
        ("validate_tables", "validation"),
        ("execute_query", "db_query"),
    ],
)
def test_classify_span_type_known_steps(step, expected):
    assert classify_span_type(step) == expected
