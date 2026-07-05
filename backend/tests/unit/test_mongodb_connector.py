"""Unit tests for MongoDB connector BSON value coercion.

Regression: only the top-level ``_id`` was stringified, so any other-field
ObjectId (reference fields are ubiquitous in Mongo), Decimal128, or a BSON
value nested inside a subdocument/array reached the response serializer as a
raw BSON object and broke it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from bson import ObjectId
from bson.decimal128 import Decimal128

from app.connectors.base import ConnectionConfig
from app.connectors.mongodb import (
    MongoDBConnector,
    _assert_mongo_read_safe,
    _infer_fields,
    _to_jsonable,
)


class TestToJsonable:
    def test_objectid_becomes_hex_str(self):
        oid = ObjectId()
        assert _to_jsonable(oid) == str(oid)
        assert isinstance(_to_jsonable(oid), str)

    def test_decimal128_becomes_decimal(self):
        assert _to_jsonable(Decimal128("3.50")) == Decimal("3.50")

    def test_nested_dict_is_coerced(self):
        oid = ObjectId()
        assert _to_jsonable({"ref": oid, "n": 1}) == {"ref": str(oid), "n": 1}

    def test_nested_list_is_coerced(self):
        oid = ObjectId()
        assert _to_jsonable([oid, 2, {"x": oid}]) == [str(oid), 2, {"x": str(oid)}]

    def test_datetime_and_plain_values_pass_through(self):
        dt = datetime(2026, 1, 1, tzinfo=UTC)
        assert _to_jsonable(dt) is dt
        assert _to_jsonable("a") == "a"
        assert _to_jsonable(None) is None
        assert _to_jsonable(7) == 7


class _FakeCursor:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def limit(self, n: int) -> _FakeCursor:
        return self

    async def to_list(self, length: int | None = None) -> list[dict]:
        return self._docs


class _FakeCollection:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def find(self, filter=None, projection=None) -> _FakeCursor:
        return _FakeCursor(self._docs)


class _FakeDB:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def __getitem__(self, name: str) -> _FakeCollection:
        return _FakeCollection(self._docs)


class TestExecuteQueryCoercion:
    @pytest.mark.asyncio
    async def test_reference_and_nested_objectids_are_serializable(self):
        oid = ObjectId()
        ref = ObjectId()
        nested_ref = ObjectId()
        docs = [
            {
                "_id": oid,
                "owner_id": ref,  # non-_id reference — previously left raw
                "created_at": datetime(2026, 1, 1, tzinfo=UTC),
                "amount": Decimal128("9.99"),
                "meta": {"parent": nested_ref},  # nested subdocument
                "tags": [nested_ref],  # array of refs
            }
        ]
        conn = MongoDBConnector()
        conn._db = _FakeDB(docs)

        result = await conn.execute_query(json.dumps({"collection": "orders", "operation": "find"}))

        assert result.error is None
        col = {c: i for i, c in enumerate(result.columns)}
        row = result.rows[0]
        assert row[col["_id"]] == str(oid)
        # The previously-unhandled reference ObjectId is now a hex str.
        assert isinstance(row[col["owner_id"]], str)
        assert row[col["owner_id"]] == str(ref)
        # Nested structures are coerced recursively.
        assert row[col["meta"]]["parent"] == str(nested_ref)
        assert row[col["tags"]][0] == str(nested_ref)
        # Decimal128 → Decimal (matches asyncpg numeric results).
        assert row[col["amount"]] == Decimal("9.99")


class TestAssertMongoReadSafe:
    """C4 (F-CONN-03 / F-CONN-10): the read-safety guard for read-only conns."""

    @pytest.mark.parametrize(
        "op",
        [
            "insert",
            "update",
            "delete",
            "drop",
            "rename",
            "create_index",
            "drop_index",
            "replace",
        ],
    )
    def test_write_operations_rejected(self, op: str):
        with pytest.raises(ValueError, match="not allowed"):
            _assert_mongo_read_safe({"collection": "c", "operation": op})

    def test_aggregation_out_stage_rejected(self):
        with pytest.raises(ValueError, match=r"\$out"):
            _assert_mongo_read_safe({"operation": "aggregate", "pipeline": [{"$out": "x"}]})

    def test_aggregation_merge_stage_rejected(self):
        with pytest.raises(ValueError, match=r"\$merge"):
            _assert_mongo_read_safe({"operation": "aggregate", "pipeline": [{"$merge": {}}]})

    def test_where_js_operator_rejected(self):
        with pytest.raises(ValueError, match=r"\$where"):
            _assert_mongo_read_safe({"operation": "find", "filter": {"$where": "this.x > 1"}})

    def test_function_js_operator_rejected(self):
        with pytest.raises(ValueError, match=r"\$function"):
            _assert_mongo_read_safe({"operation": "find", "filter": {"$function": {}}})

    def test_accumulator_js_operator_rejected(self):
        with pytest.raises(ValueError, match=r"\$accumulator"):
            _assert_mongo_read_safe(
                {
                    "operation": "aggregate",
                    "pipeline": [{"$group": {"x": {"$accumulator": {}}}}],
                }
            )

    def test_nested_js_operator_rejected(self):
        """JS operators buried in a sub-document are still caught."""
        with pytest.raises(ValueError, match=r"\$where"):
            _assert_mongo_read_safe({"operation": "find", "filter": {"$and": [{"$where": "true"}]}})

    def test_plain_find_allowed(self):
        # Must not raise.
        _assert_mongo_read_safe({"operation": "find", "filter": {}})

    def test_read_aggregate_allowed(self):
        # Must not raise: a read-only aggregate pipeline.
        _assert_mongo_read_safe(
            {
                "operation": "aggregate",
                "pipeline": [
                    {"$match": {"status": "active"}},
                    {"$group": {"_id": "$kind", "n": {"$sum": 1}}},
                ],
            }
        )

    def test_default_operation_is_find_and_allowed(self):
        # No "operation" key → defaults to find, must not raise.
        _assert_mongo_read_safe({"collection": "c", "filter": {}})


class TestExecuteQueryReadOnlyGuard:
    """The guard is wired into execute_query and degrades to QueryResult.error."""

    @pytest.mark.asyncio
    async def test_write_op_returns_query_result_error(self):
        conn = MongoDBConnector()
        conn._db = _FakeDB([])
        conn._config = ConnectionConfig(db_type="mongodb", is_read_only=True)

        result = await conn.execute_query(json.dumps({"collection": "c", "operation": "insert"}))

        assert result.rows == []
        assert result.error is not None
        assert "not allowed" in result.error

    @pytest.mark.asyncio
    async def test_out_stage_returns_query_result_error(self):
        conn = MongoDBConnector()
        conn._db = _FakeDB([])
        conn._config = ConnectionConfig(db_type="mongodb", is_read_only=True)

        result = await conn.execute_query(
            json.dumps({"collection": "c", "operation": "aggregate", "pipeline": [{"$out": "x"}]})
        )

        assert result.error is not None
        assert "$out" in result.error

    @pytest.mark.asyncio
    async def test_writable_connection_bypasses_guard(self):
        """When the connection is not read-only, the guard does not run."""
        conn = MongoDBConnector()
        conn._db = _FakeDB([{"_id": ObjectId(), "ok": 1}])
        conn._config = ConnectionConfig(db_type="mongodb", is_read_only=False)

        # A $where filter would be rejected under read-only; here it must pass
        # the guard (the fake collection ignores the filter and returns docs).
        result = await conn.execute_query(
            json.dumps({"collection": "c", "operation": "find", "filter": {"$where": "true"}})
        )

        assert result.error is None

    @pytest.mark.asyncio
    async def test_read_only_find_still_works(self):
        conn = MongoDBConnector()
        conn._db = _FakeDB([{"_id": ObjectId(), "ok": 1}])
        conn._config = ConnectionConfig(db_type="mongodb", is_read_only=True)

        result = await conn.execute_query(
            json.dumps({"collection": "c", "operation": "find", "filter": {}})
        )

        assert result.error is None
        assert result.row_count == 1


# ---------------------------------------------------------------------------
# TestMongoNativeCapture — DBIDX-D1/D2/D3 native distinct/stats overrides
# ---------------------------------------------------------------------------


class _FakeDistinctCollection(_FakeCollection):
    def __init__(self, docs, distinct_map=None, agg_rows=None):
        super().__init__(docs)
        self._distinct_map = distinct_map or {}
        self._agg_rows = agg_rows or []

    async def distinct(self, key, filter=None):
        return self._distinct_map.get(key, [])

    def aggregate(self, pipeline):
        return _FakeCursor(self._agg_rows)


class _FakeDistinctDB(_FakeDB):
    def __init__(self, docs, **kw):
        super().__init__(docs)
        self._kw = kw

    def __getitem__(self, name):
        return _FakeDistinctCollection(self._docs, **self._kw)


class TestMongoNativeCapture:
    @pytest.mark.asyncio
    async def test_distinct_values_uses_native_distinct(self):
        conn = MongoDBConnector()
        conn._db = _FakeDistinctDB([], distinct_map={"status": ["a", "b", "c"]})
        conn._config = ConnectionConfig(db_type="mongodb", is_read_only=True)
        vals = await conn.distinct_values("orders", "status", limit=50)
        assert vals == ["a", "b", "c"]  # NOT empty — the D2 regression was empty

    @pytest.mark.asyncio
    async def test_distinct_values_caps_to_limit(self):
        conn = MongoDBConnector()
        conn._db = _FakeDistinctDB([], distinct_map={"c": [str(i) for i in range(200)]})
        conn._config = ConnectionConfig(db_type="mongodb", is_read_only=True)
        vals = await conn.distinct_values("t", "c", limit=50)
        assert len(vals) == 50

    @pytest.mark.asyncio
    async def test_approx_stats_uses_group_pipeline(self):
        conn = MongoDBConnector()
        # $group row shape: {_id:None, distinct:.., nulls:.., total:.., min:.., max:..}
        conn._db = _FakeDistinctDB(
            [],
            agg_rows=[{"_id": None, "distinct": 4, "nulls": 1, "total": 10, "min": 1, "max": 99}],
        )
        conn._config = ConnectionConfig(db_type="mongodb", is_read_only=True)
        stats = await conn.approx_stats("t", "amount")
        assert stats.distinct_count == 4
        assert stats.null_rate == 0.1
        assert stats.min_value == 1 and stats.max_value == 99

    @pytest.mark.asyncio
    async def test_capture_methods_no_db_return_empty(self):
        conn = MongoDBConnector()  # _db is None
        assert await conn.distinct_values("t", "c") == []
        s = await conn.approx_stats("t", "c")
        assert s.distinct_count is None


# ---------------------------------------------------------------------------
# TestMongoInfer — DBIDX-D11 schema inference: type union, nested paths
# ---------------------------------------------------------------------------


class TestMongoInfer:
    """Pure unit tests for the _infer_fields() helper — no network required."""

    def test_type_union_across_docs(self):
        """A field that is str in doc1 and int in doc2 → 'int|str' union."""
        docs = [{"x": "a"}, {"x": 1}]
        fields = _infer_fields(docs)
        assert set(fields["x"].split("|")) == {"str", "int"}

    def test_nested_paths_flattened(self):
        """Nested subdoc fields surface as dotted paths."""
        docs = [{"addr": {"city": "NYC", "zip": 10001}}]
        fields = _infer_fields(docs)
        assert "addr.city" in fields
        assert "addr.zip" in fields
        # The parent key itself should NOT appear as a top-level column.
        assert "addr" not in fields

    def test_depth_bounded(self):
        """Recursion stops at max_depth — paths deeper than max_depth are not emitted."""
        docs = [{"a": {"b": {"c": {"d": 1}}}}]
        fields = _infer_fields(docs, max_depth=2)
        # With max_depth=2 we allow at most 2 dots, i.e. depth-3 paths like a.b.c.
        # The spec says: assert not any(k.count(".") > 2 for k in fields)
        assert not any(k.count(".") > 2 for k in fields)

    def test_arrays_reported_as_array(self):
        """List values are typed 'array', not 'list'."""
        docs = [{"tags": [1, 2, 3]}]
        fields = _infer_fields(docs)
        assert "array" in fields["tags"]

    def test_optional_field_absent_in_first_doc_captured(self):
        """A field absent from doc1 but present in doc3 must still appear."""
        docs = [{"x": 1}, {"x": 2}, {"x": 3, "rare": "hello"}]
        fields = _infer_fields(docs)
        assert "rare" in fields
        assert fields["rare"] == "str"

    def test_top_level_types_deduplicated(self):
        """Same type across all docs produces a single type (no duplication)."""
        docs = [{"n": 1}, {"n": 2}, {"n": 3}]
        fields = _infer_fields(docs)
        assert fields["n"] == "int"

    def test_union_sorted_deterministic(self):
        """Type union string is sorted so result is deterministic regardless of order."""
        docs_ab = [{"v": "hello"}, {"v": 42}]
        docs_ba = [{"v": 42}, {"v": "hello"}]
        assert _infer_fields(docs_ab)["v"] == _infer_fields(docs_ba)["v"]

    def test_none_values_ignored_in_type_set(self):
        """None values don't contribute 'NoneType' to the type union."""
        docs = [{"f": None}, {"f": "hello"}]
        fields = _infer_fields(docs)
        assert "NoneType" not in fields["f"]
        assert fields["f"] == "str"

    def test_empty_docs_list_returns_empty(self):
        """No docs → no fields."""
        assert _infer_fields([]) == {}

    def test_id_field_preserved(self):
        """_id survives inference (used by introspect_schema PK detection)."""
        from bson import ObjectId

        docs = [{"_id": ObjectId(), "name": "Alice"}]
        fields = _infer_fields(docs)
        assert "_id" in fields
        assert "name" in fields
