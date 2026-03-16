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
        plan = json.dumps([{
            "Plan": {
                "Node Type": "Index Scan",
                "Plan Rows": 10,
            },
        }])
        connector = AsyncMock()
        connector.execute_query.return_value = QueryResult(
            columns=["QUERY PLAN"],
            rows=[[plan]],
            row_count=1,
        )
        result = await validator.validate(
            connector, "SELECT * FROM users", "postgresql",
        )
        assert result.is_valid
        assert len(result.warnings) == 0

    @pytest.mark.asyncio
    async def test_postgres_seq_scan_warning(self, validator):
        plan = json.dumps([{
            "Plan": {
                "Node Type": "Seq Scan",
                "Plan Rows": 50000,
                "Relation Name": "big_table",
            },
        }])
        connector = AsyncMock()
        connector.execute_query.return_value = QueryResult(
            columns=["QUERY PLAN"],
            rows=[[plan]],
            row_count=1,
        )
        result = await validator.validate(
            connector, "SELECT * FROM big_table", "postgresql",
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
            connector, "SELECT * FROM bad_table", "postgresql",
        )
        assert not result.is_valid
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_explain_exception(self, validator):
        connector = AsyncMock()
        connector.execute_query.side_effect = Exception("connection lost")
        result = await validator.validate(
            connector, "SELECT * FROM users", "postgresql",
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
            connector, "SELECT * FROM big_table", "mysql",
        )
        assert result.is_valid
        assert any("big_table" in w for w in result.warnings)
