"""Tests for ValidationLoop controller."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.connectors.base import (
    ColumnInfo,
    ConnectionConfig,
    QueryResult,
    SchemaInfo,
    TableInfo,
)
from app.core.query_validation import (
    QueryErrorType,
    ValidationConfig,
)
from app.core.validation_loop import ValidationLoop


def _schema() -> SchemaInfo:
    return SchemaInfo(
        tables=[
            TableInfo(
                name="users",
                columns=[
                    ColumnInfo(name="id", data_type="int"),
                    ColumnInfo(name="username", data_type="varchar"),
                ],
            ),
        ],
        db_type="postgresql",
    )


def _config(**kwargs) -> ValidationConfig:
    defaults = dict(
        max_retries=3,
        enable_explain=False,
        enable_schema_validation=False,
        empty_result_retry=False,
    )
    defaults.update(kwargs)
    return ValidationConfig(**defaults)


def _conn_config() -> ConnectionConfig:
    return ConnectionConfig(db_type="postgresql", db_name="test")


def _tracker() -> MagicMock:
    t = MagicMock()
    t.step = MagicMock()
    t.step.return_value.__aenter__ = AsyncMock()
    t.step.return_value.__aexit__ = AsyncMock()
    t.emit = AsyncMock()
    return t


def _make_loop(
    config=None,
    repairer_result=None,
    **kwargs,
) -> ValidationLoop:
    from app.core.context_enricher import ContextEnricher
    from app.core.error_classifier import ErrorClassifier
    from app.core.query_repair import QueryRepairer
    from app.core.retry_strategy import RetryStrategy

    cfg = config or _config()

    mock_repairer = MagicMock(spec=QueryRepairer)
    if repairer_result:
        mock_repairer.repair = AsyncMock(return_value=repairer_result)
    else:
        mock_repairer.repair = AsyncMock(
            return_value={
                "query": "SELECT username FROM users",
                "explanation": "Fixed",
            }
        )

    return ValidationLoop(
        config=cfg,
        error_classifier=ErrorClassifier(),
        context_enricher=ContextEnricher(_schema()),
        query_repairer=mock_repairer,
        retry_strategy=RetryStrategy(),
        tracker=_tracker(),
    )


class TestValidationLoop:
    @pytest.mark.asyncio
    async def test_success_first_try(self):
        loop = _make_loop()
        connector = AsyncMock()
        connector.execute_query.return_value = QueryResult(
            columns=["id"],
            rows=[[1]],
            row_count=1,
            execution_time_ms=10,
        )

        result = await loop.execute(
            initial_query="SELECT id FROM users",
            initial_explanation="Get IDs",
            connector=connector,
            schema=_schema(),
            question="Get user IDs",
            project_id="p1",
            workflow_id="wf1",
            connection_config=_conn_config(),
        )

        assert result.success
        assert result.total_attempts == 1
        assert result.results is not None

    @pytest.mark.asyncio
    async def test_retry_on_db_error(self):
        loop = _make_loop()
        connector = AsyncMock()

        error_result = QueryResult(
            error='column "user_name" does not exist',
        )
        success_result = QueryResult(
            columns=["username"],
            rows=[["alice"]],
            row_count=1,
            execution_time_ms=5,
        )
        connector.execute_query.side_effect = [error_result, success_result]

        result = await loop.execute(
            initial_query="SELECT user_name FROM users",
            initial_explanation="Get names",
            connector=connector,
            schema=_schema(),
            question="Get usernames",
            project_id="p1",
            workflow_id="wf1",
            connection_config=_conn_config(),
        )

        assert result.success
        assert result.total_attempts == 2

    @pytest.mark.asyncio
    async def test_max_attempts_exhausted(self):
        loop = _make_loop(
            config=_config(max_retries=2),
            repairer_result={
                "query": "SELECT still_wrong FROM users",
                "explanation": "oops",
            },
        )
        connector = AsyncMock()
        connector.execute_query.return_value = QueryResult(
            error='column "still_wrong" does not exist',
        )

        result = await loop.execute(
            initial_query="SELECT bad FROM users",
            initial_explanation="test",
            connector=connector,
            schema=_schema(),
            question="Get data",
            project_id="p1",
            workflow_id="wf1",
            connection_config=_conn_config(),
        )

        assert not result.success
        assert result.total_attempts == 2
        assert result.final_error is not None

    @pytest.mark.asyncio
    async def test_non_retryable_error(self):
        loop = _make_loop()
        connector = AsyncMock()
        connector.execute_query.return_value = QueryResult(
            error="permission denied for table users",
        )

        result = await loop.execute(
            initial_query="SELECT * FROM users",
            initial_explanation="test",
            connector=connector,
            schema=_schema(),
            question="Get data",
            project_id="p1",
            workflow_id="wf1",
            connection_config=_conn_config(),
        )

        assert not result.success
        assert result.total_attempts == 1
        assert result.final_error is not None
        assert result.final_error.error_type == QueryErrorType.PERMISSION_DENIED

    @pytest.mark.asyncio
    async def test_safety_block(self):
        loop = _make_loop()
        connector = AsyncMock()

        conn_cfg = ConnectionConfig(
            db_type="postgresql",
            db_name="test",
            is_read_only=True,
        )

        result = await loop.execute(
            initial_query="DROP TABLE users",
            initial_explanation="test",
            connector=connector,
            schema=_schema(),
            question="Drop table",
            project_id="p1",
            workflow_id="wf1",
            connection_config=conn_cfg,
        )

        assert not result.success
        assert result.final_error is not None
        assert result.final_error.error_type == QueryErrorType.PERMISSION_DENIED

    @pytest.mark.asyncio
    async def test_schema_validation_catches_bad_table(self):
        loop = _make_loop(
            config=_config(enable_schema_validation=True),
        )
        connector = AsyncMock()
        connector.execute_query.return_value = QueryResult(
            columns=["username"],
            rows=[["alice"]],
            row_count=1,
            execution_time_ms=5,
        )

        result = await loop.execute(
            initial_query="SELECT * FROM nonexistent",
            initial_explanation="test",
            connector=connector,
            schema=_schema(),
            question="Get data",
            project_id="p1",
            workflow_id="wf1",
            connection_config=_conn_config(),
        )

        assert result.total_attempts >= 1

    @pytest.mark.asyncio
    async def test_empty_result_retry_off(self):
        loop = _make_loop(
            config=_config(empty_result_retry=False),
        )
        connector = AsyncMock()
        connector.execute_query.return_value = QueryResult(
            columns=["id"],
            rows=[],
            row_count=0,
            execution_time_ms=5,
        )

        result = await loop.execute(
            initial_query="SELECT * FROM users WHERE 1=0",
            initial_explanation="test",
            connector=connector,
            schema=_schema(),
            question="Get nothing",
            project_id="p1",
            workflow_id="wf1",
            connection_config=_conn_config(),
        )

        assert result.success
        assert result.total_attempts == 1

    @pytest.mark.asyncio
    async def test_repair_failure_stops_loop(self):
        loop = _make_loop(
            repairer_result={"query": "", "explanation": "", "error": "LLM failed"},
        )
        connector = AsyncMock()
        connector.execute_query.return_value = QueryResult(
            error='column "bad" does not exist',
        )

        result = await loop.execute(
            initial_query="SELECT bad FROM users",
            initial_explanation="test",
            connector=connector,
            schema=_schema(),
            question="Get data",
            project_id="p1",
            workflow_id="wf1",
            connection_config=_conn_config(),
        )

        assert not result.success
        assert result.total_attempts == 1
