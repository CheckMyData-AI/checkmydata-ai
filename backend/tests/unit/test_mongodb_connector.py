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
