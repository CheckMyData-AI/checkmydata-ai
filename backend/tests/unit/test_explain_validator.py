"""Tests for EXPLAIN dry-run validator."""

import json
from unittest.mock import AsyncMock

import pytest

from app.connectors.base import QueryResult
from app.core.explain_validator import ExplainValidator


@pytest.fixture()
def validator():
    return ExplainValidator(row_warning_threshold=1000)


class TestExplainValidator:
    @pytest.mark.asyncio
    async def test_skip_mongodb(self, validator):
        connector = AsyncMock()
        result = await validator.validate(connector, "{}", "mongodb")
        assert result.is_valid
        connector.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_postgres_success(self, validator):
        plan = json.dumps(
            [
                {
                    "Plan": {
                        "Node Type": "Index Scan",
                        "Plan Rows": 10,
                    },
                }
            ]
        )
        connector = AsyncMock()
        connector.execute_query.return_value = QueryResult(
            columns=["QUERY PLAN"],
            rows=[[plan]],
            row_count=1,
        )
        result = await validator.validate(
            connector,
            "SELECT * FROM users",
            "postgresql",
        )
        assert result.is_valid
        assert len(result.warnings) == 0

    @pytest.mark.asyncio
    async def test_postgres_seq_scan_warning(self, validator):
        plan = json.dumps(
            [
                {
                    "Plan": {
                        "Node Type": "Seq Scan",
                        "Plan Rows": 50000,
                        "Relation Name": "big_table",
                    },
                }
            ]
        )
        connector = AsyncMock()
        connector.execute_query.return_value = QueryResult(
            columns=["QUERY PLAN"],
            rows=[[plan]],
            row_count=1,
        )
        result = await validator.validate(
            connector,
            "SELECT * FROM big_table",
            "postgresql",
        )
        assert result.is_valid
        assert any("big_table" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_explain_error_returns_invalid(self, validator):
        connector = AsyncMock()
        connector.execute_query.return_value = QueryResult(
            error='relation "bad_table" does not exist',
        )
        result = await validator.validate(
            connector,
            "SELECT * FROM bad_table",
            "postgresql",
        )
        assert not result.is_valid
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_explain_exception(self, validator):
        connector = AsyncMock()
        connector.execute_query.side_effect = Exception("connection lost")
        result = await validator.validate(
            connector,
            "SELECT * FROM users",
            "postgresql",
        )
        assert not result.is_valid

    @pytest.mark.asyncio
    async def test_mysql_full_scan_warning(self, validator):
        connector = AsyncMock()
        connector.execute_query.return_value = QueryResult(
            columns=["id", "select_type", "table", "type", "rows"],
            rows=[[1, "SIMPLE", "big_table", "ALL", 50000]],
            row_count=1,
        )
        result = await validator.validate(
            connector,
            "SELECT * FROM big_table",
            "mysql",
        )
        assert result.is_valid
        assert any("big_table" in w for w in result.warnings)


class TestClickHouseExplainIndexes:
    """B3 (audit 05-cross-db): plain ``EXPLAIN`` on CH 24.8 never contains the
    words where/prewhere — the filter node is an unnamed ``Expression`` and a
    key predicate hides inside ``ReadFromMergeTree`` — so the old heuristic
    raised a false "full MergeTree scan" warning even for key lookups.
    ``EXPLAIN indexes = 1`` exposes real index usage (Condition / Granules)."""

    KEY_LOOKUP_PLAN = [
        ["Expression ((Project names + Projection))"],
        ["  Expression"],
        ["    ReadFromMergeTree (e2e.users)"],
        ["    Indexes:"],
        ["      PrimaryKey"],
        ["        Keys: id"],
        ["        Condition: (id in [5, 5])"],
        ["        Parts: 1/1"],
        ["        Granules: 1/1"],
    ]

    FULL_SCAN_PLAN = [
        ["Expression ((Project names + Projection))"],
        ["  Expression"],
        ["    ReadFromMergeTree (e2e.users)"],
        ["    Indexes:"],
        ["      PrimaryKey"],
        ["        Keys: id"],
        ["        Condition: true"],
        ["        Parts: 10/10"],
        ["        Granules: 1280/1280"],
    ]

    def _connector_returning(self, rows) -> AsyncMock:
        connector = AsyncMock()
        connector.execute_query.return_value = QueryResult(
            columns=["explain"],
            rows=rows,
            row_count=len(rows),
        )
        return connector

    @pytest.mark.asyncio
    async def test_explain_query_uses_indexes_1(self, validator):
        connector = self._connector_returning(self.KEY_LOOKUP_PLAN)
        await validator.validate(connector, "SELECT * FROM users WHERE id = 5", "clickhouse")
        sent = connector.execute_query.call_args[0][0]
        assert sent == "EXPLAIN indexes = 1 SELECT * FROM users WHERE id = 5"

    @pytest.mark.asyncio
    async def test_key_lookup_produces_no_warnings(self, validator):
        connector = self._connector_returning(self.KEY_LOOKUP_PLAN)
        result = await validator.validate(
            connector, "SELECT * FROM users WHERE id = 5", "clickhouse"
        )
        assert result.is_valid
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_full_scan_warns(self, validator):
        connector = self._connector_returning(self.FULL_SCAN_PLAN)
        result = await validator.validate(connector, "SELECT * FROM users", "clickhouse")
        assert result.is_valid
        assert any("full MergeTree scan" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_granule_pruning_counts_as_bounded_read(self, validator):
        """A plan reading fewer granules than the table holds is not a full scan
        even when the condition line itself is not selective-looking."""
        plan = [
            ["    ReadFromMergeTree (e2e.events)"],
            ["    Indexes:"],
            ["      MinMax"],
            ["        Keys: ts"],
            ["        Condition: true"],
            ["        Parts: 2/8"],
            ["        Granules: 120/1280"],
        ]
        connector = self._connector_returning(plan)
        result = await validator.validate(
            connector, "SELECT * FROM events WHERE ts > now() - 3600", "clickhouse"
        )
        assert result.is_valid
        assert not any("full MergeTree scan" in w for w in result.warnings)
