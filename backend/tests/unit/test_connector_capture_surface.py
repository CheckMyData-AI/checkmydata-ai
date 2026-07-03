from __future__ import annotations

import pytest

from app.connectors.base import ColumnInfo, ColumnStats, SchemaInfo, TableInfo


def test_columninfo_new_fields_default_backcompat():
    c = ColumnInfo(name="status", data_type="text")
    assert c.enum_labels is None
    assert c.check_constraints == []
    assert c.is_sort_key is False
    assert c.distinct_values is None
    assert c.distinct_count is None
    assert c.null_rate is None
    assert c.numeric_format is None


def test_object_kind_defaults_table():
    assert TableInfo(name="t").object_kind == "table"
    assert SchemaInfo().object_kind == "table"


def test_columnstats_dataclass():
    s = ColumnStats(distinct_count=3, null_rate=0.1, min_value=1, max_value=9)
    assert s.distinct_count == 3 and s.null_rate == 0.1


async def test_distinct_values_base_raises():
    from app.connectors.base import DatabaseAdapter

    class _Stub(DatabaseAdapter):
        @property
        def db_type(self) -> str:  # type: ignore[override]
            return "postgres"

        async def connect(self, config):  # pragma: no cover
            ...

        async def disconnect(self):  # pragma: no cover
            ...

        async def test_connection(self):  # pragma: no cover
            return True

        async def execute_query(  # pragma: no cover
            self, query, params=None, *, timeout_seconds=None
        ):
            from app.connectors.base import QueryResult

            return QueryResult()

        async def introspect_schema(self):  # pragma: no cover
            return SchemaInfo()

    stub = _Stub()
    with pytest.raises(NotImplementedError):
        await stub.distinct_values("t", "c", 10)
    with pytest.raises(NotImplementedError):
        await stub.approx_stats("t", "c")
