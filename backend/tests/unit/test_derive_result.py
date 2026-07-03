from __future__ import annotations

import pytest

from app.connectors.base import QueryResult, derive_result


def test_truncated_carries_forward_when_base_truncated():
    base = QueryResult(columns=["a"], rows=[[1]], row_count=1, truncated=True)
    out = derive_result(base, [[2], [3]])
    assert out.truncated is True
    assert out.rows == [[2], [3]]
    assert out.row_count == 2
    assert out.columns == ["a"]


def test_extra_truncation_ors_in():
    base = QueryResult(columns=["a"], rows=[[1]], row_count=1, truncated=False)
    out = derive_result(base, [[2]], extra_truncation=True)
    assert out.truncated is True


def test_neither_truncated_stays_false():
    base = QueryResult(columns=["a"], rows=[[1]], row_count=1, truncated=False)
    out = derive_result(base, [[2]])
    assert out.truncated is False


def test_columns_override_and_overrides_win():
    base = QueryResult(columns=["a"], rows=[[1]], row_count=1, execution_time_ms=5.0)
    out = derive_result(base, [[2, 3]], columns=["x", "y"], execution_time_ms=9.0)
    assert out.columns == ["x", "y"]
    assert out.execution_time_ms == 9.0
    assert out.row_count == 1  # base row_count not auto-recomputed? -> see semantics
    # explicit row_count override honoured:
    out2 = derive_result(base, [[2, 3]], columns=["x", "y"], row_count=7)
    assert out2.row_count == 7


def test_passing_truncated_kwarg_is_rejected():
    base = QueryResult(columns=["a"], rows=[[1]], row_count=1)
    with pytest.raises(TypeError):
        derive_result(base, [[2]], truncated=False)
