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

from app.connectors.mongodb import MongoDBConnector, _to_jsonable


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
