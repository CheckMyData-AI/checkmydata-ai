from __future__ import annotations

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


async def test_distinct_values_base_sql_default():
    """The base DatabaseAdapter now provides a SQL default implementation
    (Wave 4 T2).  Concrete SQL connectors inherit it; non-SQL adapters
    (e.g. MongoDB) override it.  Here we verify the default generates
    correct SQL and degrades gracefully on error."""
    from app.connectors.base import ColumnStats, DatabaseAdapter, QueryResult

    class _Stub(DatabaseAdapter):
        @property
        def db_type(self) -> str:  # type: ignore[override]
            return "postgres"

        def __init__(self):
            self.last_query: str = ""
            self._qr: QueryResult = QueryResult(columns=["v"], rows=[["x"], [None]])

        async def connect(self, config):  # pragma: no cover
            ...

        async def disconnect(self):  # pragma: no cover
            ...

        async def test_connection(self):  # pragma: no cover
            return True

        async def execute_query(self, query, params=None, *, timeout_seconds=None):
            self.last_query = query
            return self._qr

        async def introspect_schema(self):  # pragma: no cover
            return SchemaInfo()

    stub = _Stub()

    # distinct_values: SQL generated, NULL filtered, result returned
    vals = await stub.distinct_values("t", "c", 10)
    assert vals == ["x"]
    assert "DISTINCT" in stub.last_query
    assert "LIMIT 10" in stub.last_query

    # approx_stats: degrades to empty ColumnStats on error
    stub._qr = QueryResult(error="db error")
    s = await stub.approx_stats("t", "c")
    assert isinstance(s, ColumnStats)
    assert s.distinct_count is None
