"""Integration tests for the full validation loop with mocked LLM + SQLite."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.connectors.base import (
    ColumnInfo,
    ConnectionConfig,
    QueryResult,
    SchemaInfo,
    TableInfo,
)
from app.core.context_enricher import ContextEnricher
from app.core.error_classifier import ErrorClassifier
from app.core.query_repair import QueryRepairer
from app.core.query_validation import QueryErrorType, ValidationConfig
from app.core.retry_strategy import RetryStrategy
from app.core.validation_loop import ValidationLoop
from app.core.workflow_tracker import WorkflowTracker


def _schema() -> SchemaInfo:
    return SchemaInfo(
        tables=[
            TableInfo(
                name="users",
                columns=[
                    ColumnInfo(
                        name="id", data_type="INTEGER",
                        is_primary_key=True,
                    ),
                    ColumnInfo(name="username", data_type="TEXT"),
                    ColumnInfo(name="email", data_type="TEXT"),
                ],
            ),
            TableInfo(
                name="orders",
                columns=[
                    ColumnInfo(
                        name="id", data_type="INTEGER",
                        is_primary_key=True,
                    ),
                    ColumnInfo(name="user_id", data_type="INTEGER"),
                    ColumnInfo(name="total", data_type="REAL"),
                    ColumnInfo(name="status", data_type="TEXT"),
                ],
            ),
        ],
        db_type="postgresql",
        db_name="testdb",
    )


def _conn_config() -> ConnectionConfig:
    return ConnectionConfig(
        db_type="postgresql", db_name="testdb", is_read_only=True,
    )


def _make_tracker() -> WorkflowTracker:
    return WorkflowTracker()


def _make_repairer(
    fixed_query: str = "SELECT username FROM users",
    explanation: str = "Fixed column name",
    fail: bool = False,
) -> MagicMock:
    mock = MagicMock(spec=QueryRepairer)
    if fail:
        mock.repair = AsyncMock(return_value={
            "query": "",
            "explanation": "",
            "error": "LLM failed",
        })
    else:
        mock.repair = AsyncMock(return_value={
            "query": fixed_query,
            "explanation": explanation,
        })
    return mock


def _make_loop(
    config: ValidationConfig | None = None,
    repairer: MagicMock | None = None,
) -> ValidationLoop:
    cfg = config or ValidationConfig(
        max_retries=3,
        enable_explain=False,
        enable_schema_validation=True,
        empty_result_retry=False,
    )
    tracker = _make_tracker()
    schema = _schema()

    return ValidationLoop(
        config=cfg,
        error_classifier=ErrorClassifier(),
        context_enricher=ContextEnricher(schema),
        query_repairer=repairer or _make_repairer(),
        retry_strategy=RetryStrategy(),
        tracker=tracker,
    )


class TestIntegrationValidationLoop:
    @pytest.mark.asyncio
    async def test_correct_query_first_try(self):
        """Test 1: Correct query on first attempt — no retry."""
        loop = _make_loop()
        connector = AsyncMock()
        connector.execute_query.return_value = QueryResult(
            columns=["id", "username"],
            rows=[[1, "alice"], [2, "bob"]],
            row_count=2,
            execution_time_ms=12.5,
        )

        wf_id = await _make_tracker().begin("query")
        result = await loop.execute(
            initial_query="SELECT id, username FROM users",
            initial_explanation="Get all users",
            connector=connector,
            schema=_schema(),
            question="Show me all users",
            project_id="proj1",
            workflow_id=wf_id,
            connection_config=_conn_config(),
        )

        assert result.success
        assert result.total_attempts == 1
        assert result.results is not None
        assert result.results.row_count == 2
        assert len(result.attempts) == 1
        assert result.attempts[0].error is None

    @pytest.mark.asyncio
    async def test_wrong_column_retry_success(self):
        """Test 2: Wrong column → DB error → repair → success on attempt 2."""
        repairer = _make_repairer(
            fixed_query="SELECT username FROM users",
            explanation="Fixed: user_name -> username",
        )
        loop = _make_loop(repairer=repairer)
        connector = AsyncMock()

        error_result = QueryResult(
            error='column "user_name" does not exist',
        )
        success_result = QueryResult(
            columns=["username"],
            rows=[["alice"], ["bob"]],
            row_count=2,
            execution_time_ms=8.0,
        )
        connector.execute_query.side_effect = [
            error_result, success_result,
        ]

        wf_id = await _make_tracker().begin("query")
        result = await loop.execute(
            initial_query="SELECT user_name FROM users",
            initial_explanation="Get usernames",
            connector=connector,
            schema=_schema(),
            question="Get all usernames",
            project_id="proj1",
            workflow_id=wf_id,
            connection_config=_conn_config(),
        )

        assert result.success
        assert result.total_attempts == 2
        assert result.attempts[0].error is not None
        assert result.attempts[1].error is None

    @pytest.mark.asyncio
    async def test_max_attempts_exhausted(self):
        """Test 3: 3 bad queries → max attempts → error with history."""
        repairer = _make_repairer(
            fixed_query="SELECT still_bad_col FROM users",
        )
        config = ValidationConfig(
            max_retries=3,
            enable_explain=False,
            enable_schema_validation=False,
            empty_result_retry=False,
        )
        loop = _make_loop(config=config, repairer=repairer)
        connector = AsyncMock()
        connector.execute_query.return_value = QueryResult(
            error='column "still_bad_col" does not exist',
        )

        wf_id = await _make_tracker().begin("query")
        result = await loop.execute(
            initial_query="SELECT bad_col FROM users",
            initial_explanation="test",
            connector=connector,
            schema=_schema(),
            question="Get data",
            project_id="proj1",
            workflow_id=wf_id,
            connection_config=_conn_config(),
        )

        assert not result.success
        assert result.total_attempts == 3
        assert result.final_error is not None
        assert len(result.attempts) == 3

    @pytest.mark.asyncio
    async def test_permission_denied_no_retry(self):
        """Test 4: Permission denied → no retry → immediate return."""
        loop = _make_loop()
        connector = AsyncMock()
        connector.execute_query.return_value = QueryResult(
            error="permission denied for table users",
        )

        wf_id = await _make_tracker().begin("query")
        result = await loop.execute(
            initial_query="SELECT * FROM users",
            initial_explanation="test",
            connector=connector,
            schema=_schema(),
            question="Get users",
            project_id="proj1",
            workflow_id=wf_id,
            connection_config=_conn_config(),
        )

        assert not result.success
        assert result.total_attempts == 1
        er = result.final_error
        assert er is not None
        assert er.error_type == QueryErrorType.PERMISSION_DENIED

    @pytest.mark.asyncio
    async def test_empty_result_retry_success(self):
        """Test 5: Empty result with retry ON → broader query → success."""
        repairer = _make_repairer(
            fixed_query="SELECT * FROM users",
            explanation="Removed WHERE clause",
        )
        config = ValidationConfig(
            max_retries=3,
            enable_explain=False,
            enable_schema_validation=False,
            empty_result_retry=True,
        )
        loop = _make_loop(config=config, repairer=repairer)
        connector = AsyncMock()

        empty_result = QueryResult(
            columns=["id"], rows=[], row_count=0,
            execution_time_ms=5,
        )
        full_result = QueryResult(
            columns=["id", "username", "email"],
            rows=[[1, "alice", "a@b.com"]],
            row_count=1,
            execution_time_ms=10,
        )
        connector.execute_query.side_effect = [
            empty_result, full_result,
        ]

        wf_id = await _make_tracker().begin("query")
        result = await loop.execute(
            initial_query=(
                "SELECT * FROM users WHERE username = 'nonexistent'"
            ),
            initial_explanation="test",
            connector=connector,
            schema=_schema(),
            question="Find user",
            project_id="proj1",
            workflow_id=wf_id,
            connection_config=_conn_config(),
        )

        assert result.success
        assert result.total_attempts == 2

    @pytest.mark.asyncio
    async def test_schema_pre_validation_catches_bad_table(self):
        """Test 6: Schema pre-validation catches non-existent table."""
        repairer = _make_repairer(
            fixed_query="SELECT * FROM users",
            explanation="Fixed table name",
        )
        config = ValidationConfig(
            max_retries=3,
            enable_explain=False,
            enable_schema_validation=True,
            empty_result_retry=False,
        )
        loop = _make_loop(config=config, repairer=repairer)
        connector = AsyncMock()
        connector.execute_query.return_value = QueryResult(
            columns=["id", "username", "email"],
            rows=[[1, "alice", "a@b.com"]],
            row_count=1,
            execution_time_ms=5,
        )

        wf_id = await _make_tracker().begin("query")
        result = await loop.execute(
            initial_query="SELECT * FROM userz",
            initial_explanation="test",
            connector=connector,
            schema=_schema(),
            question="Get users",
            project_id="proj1",
            workflow_id=wf_id,
            connection_config=_conn_config(),
        )

        assert result.success
        assert result.total_attempts == 2
        assert result.attempts[0].error is not None
        assert (
            result.attempts[0].error.error_type
            == QueryErrorType.TABLE_NOT_FOUND
        )
