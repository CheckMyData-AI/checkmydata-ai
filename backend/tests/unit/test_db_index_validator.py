"""Unit tests for DbIndexValidator."""

from unittest.mock import AsyncMock

import pytest

from app.connectors.base import (
    ColumnInfo,
    ForeignKeyInfo,
    IndexInfo,
    QueryResult,
    SchemaInfo,
    TableInfo,
)
from app.knowledge.db_index_validator import (
    DbIndexValidator,
    TableAnalysis,
)
from app.llm.base import LLMResponse, ToolCall


def _make_table(
    name="users",
    row_count=1000,
    columns=None,
    foreign_keys=None,
    indexes=None,
    schema="public",
    comment=None,
) -> TableInfo:
    if columns is None:
        columns = [
            ColumnInfo(name="id", data_type="integer", is_primary_key=True, is_nullable=False),
            ColumnInfo(name="email", data_type="varchar(255)", is_nullable=False),
            ColumnInfo(name="created_at", data_type="timestamp", is_nullable=False),
        ]
    return TableInfo(
        name=name,
        schema=schema,
        columns=columns,
        row_count=row_count,
        foreign_keys=foreign_keys or [],
        indexes=indexes or [],
        comment=comment,
    )


def _make_sample_data(rows=None, columns=None) -> QueryResult:
    if columns is None:
        columns = ["id", "email", "created_at"]
    if rows is None:
        rows = [
            [1, "alice@example.com", "2026-03-17 10:00:00"],
            [2, "bob@example.com", "2026-03-16 09:00:00"],
        ]
    return QueryResult(columns=columns, rows=rows, row_count=len(rows))


def _make_llm_response(args: dict) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id="call-1",
                name="table_analysis",
                arguments=args,
            )
        ],
        usage={"prompt_tokens": 100, "completion_tokens": 50},
    )


class TestFallbackAnalysis:
    def test_empty_table(self):
        validator = DbIndexValidator()
        table = _make_table(row_count=0)
        sample = QueryResult(columns=[], rows=[], row_count=0)
        result = validator._fallback_analysis(table, sample)
        assert result.table_name == "users"
        assert result.is_active is False
        assert result.relevance_score == 1

    def test_populated_table(self):
        validator = DbIndexValidator()
        table = _make_table(row_count=50000)
        sample = _make_sample_data()
        result = validator._fallback_analysis(table, sample)
        assert result.is_active is True
        assert result.relevance_score == 4

    def test_moderate_table(self):
        validator = DbIndexValidator()
        table = _make_table(row_count=500)
        sample = _make_sample_data()
        result = validator._fallback_analysis(table, sample)
        assert result.is_active is True
        assert result.relevance_score == 3

    def test_with_comment(self):
        validator = DbIndexValidator()
        table = _make_table(comment="User accounts table")
        sample = _make_sample_data()
        result = validator._fallback_analysis(table, sample)
        assert result.business_description == "User accounts table"

    def test_with_foreign_keys(self):
        validator = DbIndexValidator()
        table = _make_table(
            foreign_keys=[
                ForeignKeyInfo(column="user_id", references_table="users", references_column="id")
            ]
        )
        sample = _make_sample_data()
        result = validator._fallback_analysis(table, sample)
        assert "FK: user_id" in result.query_hints

    def test_none_sample(self):
        validator = DbIndexValidator()
        table = _make_table(row_count=100)
        result = validator._fallback_analysis(table, None)
        assert result.is_active is True


class TestBuildTablePrompt:
    def test_basic_prompt(self):
        table = _make_table()
        sample = _make_sample_data()
        prompt = DbIndexValidator._build_table_prompt(table, sample, "", "")
        assert "## Table: users" in prompt
        assert "id: integer" in prompt
        assert "alice@example.com" in prompt

    def test_with_code_context(self):
        table = _make_table()
        prompt = DbIndexValidator._build_table_prompt(
            table, None, "Entity 'User' maps to table 'users'", ""
        )
        assert "Entity 'User'" in prompt

    def test_with_rules(self):
        table = _make_table()
        prompt = DbIndexValidator._build_table_prompt(table, None, "", "Always use UTC timestamps")
        assert "UTC timestamps" in prompt

    def test_empty_sample(self):
        table = _make_table()
        sample = QueryResult(columns=["id"], rows=[], row_count=0)
        prompt = DbIndexValidator._build_table_prompt(table, sample, "", "")
        assert "empty table" in prompt

    def test_with_fks_and_indexes(self):
        table = _make_table(
            foreign_keys=[
                ForeignKeyInfo(column="user_id", references_table="users", references_column="id")
            ],
            indexes=[IndexInfo(name="idx_email", columns=["email"], is_unique=True)],
        )
        prompt = DbIndexValidator._build_table_prompt(table, None, "", "")
        assert "user_id" in prompt
        assert "idx_email" in prompt


class TestAnalyzeTable:
    @pytest.mark.asyncio
    async def test_successful_analysis(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "is_active": True,
                    "relevance_score": 5,
                    "business_description": "User accounts with authentication data",
                    "data_patterns": "email is unique, status enum: active/inactive",
                    "column_notes": '{"id": "auto-increment PK", "email": "unique"}',
                    "query_hints": "Filter by status, join via id FK",
                    "code_match_status": "matched",
                    "code_match_details": "",
                }
            )
        )

        validator = DbIndexValidator(mock_llm)
        result = await validator.analyze_table(
            table=_make_table(),
            sample_data=_make_sample_data(),
            code_context="",
            rules_context="",
        )
        assert result.is_active is True
        assert result.relevance_score == 5
        assert "authentication" in result.business_description

    @pytest.mark.asyncio
    async def test_clamps_relevance(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "is_active": True,
                    "relevance_score": 10,
                    "business_description": "test",
                    "data_patterns": "",
                    "column_notes": "{}",
                    "query_hints": "",
                    "code_match_status": "matched",
                }
            )
        )

        validator = DbIndexValidator(mock_llm)
        result = await validator.analyze_table(
            table=_make_table(), sample_data=None, code_context="", rules_context=""
        )
        assert result.relevance_score == 5

    @pytest.mark.asyncio
    async def test_llm_failure_fallback(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(side_effect=Exception("API error"))

        validator = DbIndexValidator(mock_llm)
        result = await validator.analyze_table(
            table=_make_table(), sample_data=_make_sample_data(), code_context="", rules_context=""
        )
        assert result.table_name == "users"
        assert result.is_active is True

    @pytest.mark.asyncio
    async def test_no_tool_calls_fallback(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(content="analysis text", tool_calls=[])
        )

        validator = DbIndexValidator(mock_llm)
        result = await validator.analyze_table(
            table=_make_table(), sample_data=_make_sample_data(), code_context="", rules_context=""
        )
        assert result.table_name == "users"

    @pytest.mark.asyncio
    async def test_dict_column_notes(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "is_active": True,
                    "relevance_score": 3,
                    "business_description": "test",
                    "data_patterns": "",
                    "column_notes": {"id": "PK", "email": "unique"},
                    "query_hints": "",
                    "code_match_status": "no_code_info",
                }
            )
        )

        validator = DbIndexValidator(mock_llm)
        result = await validator.analyze_table(
            table=_make_table(), sample_data=None, code_context="", rules_context=""
        )
        import json

        notes = json.loads(result.column_notes_json)
        assert notes["id"] == "PK"


class TestGenerateSummary:
    @pytest.mark.asyncio
    async def test_summary_generation(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="connection_summary",
                        arguments={
                            "summary_text": "E-commerce database with 10 tables",
                            "recommendations": "- Use created_at for time queries",
                        },
                    )
                ],
            )
        )

        validator = DbIndexValidator(mock_llm)
        analyses = [
            TableAnalysis(table_name="users", is_active=True, relevance_score=5),
            TableAnalysis(table_name="orders", is_active=True, relevance_score=4),
            TableAnalysis(table_name="temp", is_active=False, relevance_score=1),
        ]
        schema = SchemaInfo(
            tables=[_make_table("users"), _make_table("orders"), _make_table("temp")],
            db_type="postgres",
            db_name="shop",
        )

        result = await validator.generate_summary(
            analyses=analyses, schema=schema, code_tables={"users", "orders"}
        )
        assert "E-commerce" in result.summary_text
        assert "created_at" in result.recommendations

    @pytest.mark.asyncio
    async def test_summary_fallback_on_error(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(side_effect=Exception("API down"))

        validator = DbIndexValidator(mock_llm)
        analyses = [
            TableAnalysis(table_name="users", is_active=True),
        ]
        schema = SchemaInfo(
            tables=[_make_table("users")],
            db_type="postgres",
            db_name="shop",
        )

        result = await validator.generate_summary(
            analyses=analyses, schema=schema, code_tables=set()
        )
        assert "shop" in result.summary_text
        assert "1 active" in result.summary_text


class TestAnalyzeTableBatch:
    @pytest.mark.asyncio
    async def test_batch_analysis(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="table_analysis",
                        arguments={
                            "is_active": False,
                            "relevance_score": 1,
                            "business_description": "Empty migration table",
                            "data_patterns": "",
                            "column_notes": "{}",
                            "query_hints": "",
                            "code_match_status": "orphan",
                        },
                    ),
                    ToolCall(
                        id="c2",
                        name="table_analysis",
                        arguments={
                            "is_active": False,
                            "relevance_score": 1,
                            "business_description": "Empty temp table",
                            "data_patterns": "",
                            "column_notes": "{}",
                            "query_hints": "",
                            "code_match_status": "orphan",
                        },
                    ),
                ],
            )
        )

        validator = DbIndexValidator(mock_llm)
        tables = [
            (_make_table("migrations", row_count=0), QueryResult()),
            (_make_table("temp", row_count=0), QueryResult()),
        ]
        results = await validator.analyze_table_batch(
            tables=tables, code_context="", rules_context=""
        )
        assert len(results) == 2
        assert results[0].table_name == "migrations"
        assert results[1].table_name == "temp"

    @pytest.mark.asyncio
    async def test_batch_partial_failure(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="table_analysis",
                        arguments={
                            "is_active": True,
                            "relevance_score": 3,
                            "business_description": "First table",
                            "data_patterns": "",
                            "column_notes": "{}",
                            "query_hints": "",
                            "code_match_status": "no_code_info",
                        },
                    ),
                ],
            )
        )

        validator = DbIndexValidator(mock_llm)
        tables = [
            (_make_table("t1", row_count=0), QueryResult()),
            (_make_table("t2", row_count=0), QueryResult()),
        ]
        results = await validator.analyze_table_batch(
            tables=tables, code_context="", rules_context=""
        )
        assert len(results) == 2
        assert results[0].business_description == "First table"
        assert results[1].table_name == "t2"

    @pytest.mark.asyncio
    async def test_empty_batch(self):
        validator = DbIndexValidator()
        results = await validator.analyze_table_batch(tables=[], code_context="", rules_context="")
        assert results == []


class TestNumericFormatNotes:
    @pytest.mark.asyncio
    async def test_numeric_format_notes_from_llm(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "is_active": True,
                    "relevance_score": 4,
                    "business_description": "Payments table",
                    "data_patterns": "amount in cents",
                    "column_notes": "{}",
                    "query_hints": "",
                    "code_match_status": "matched",
                    "numeric_format_notes": '{"amount": "cents (integer), divide by 100 for USD"}',
                }
            )
        )

        validator = DbIndexValidator(mock_llm)
        result = await validator.analyze_table(
            table=_make_table(),
            sample_data=_make_sample_data(),
            code_context="",
            rules_context="",
        )
        import json

        notes = json.loads(result.numeric_format_notes)
        assert "amount" in notes
        assert "cents" in notes["amount"]

    @pytest.mark.asyncio
    async def test_numeric_format_notes_dict_converted(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "is_active": True,
                    "relevance_score": 3,
                    "business_description": "test",
                    "data_patterns": "",
                    "column_notes": "{}",
                    "query_hints": "",
                    "code_match_status": "no_code_info",
                    "numeric_format_notes": {"price": "USD dollars, decimal(10,2)"},
                }
            )
        )

        validator = DbIndexValidator(mock_llm)
        result = await validator.analyze_table(
            table=_make_table(), sample_data=None, code_context="", rules_context=""
        )
        import json

        notes = json.loads(result.numeric_format_notes)
        assert notes["price"] == "USD dollars, decimal(10,2)"

    def test_fallback_has_empty_numeric_notes(self):
        validator = DbIndexValidator()
        table = _make_table(row_count=100)
        result = validator._fallback_analysis(table, None)
        assert result.numeric_format_notes == "{}"

    def test_system_prompt_mentions_numeric(self):
        prompt = DbIndexValidator._system_prompt()
        assert "numeric" in prompt.lower() or "NUMERIC" in prompt
        assert "cents" in prompt.lower()
        assert "currency" in prompt.lower()


class TestCodeMatchStatusClamping:
    def test_valid_statuses_pass_through(self):
        from app.knowledge.db_index_validator import _clamp_code_match

        for status in ("matched", "orphan", "mismatch", "no_code_info"):
            assert _clamp_code_match(status) == status

    def test_invalid_status_falls_back(self):
        from app.knowledge.db_index_validator import _clamp_code_match

        assert _clamp_code_match("hallucinated_value") == "no_code_info"
        assert _clamp_code_match("") == "no_code_info"
        assert _clamp_code_match("MATCHED") == "no_code_info"

    @pytest.mark.asyncio
    async def test_llm_invalid_code_match_clamped(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "is_active": True,
                    "relevance_score": 3,
                    "business_description": "test",
                    "data_patterns": "",
                    "column_notes": "{}",
                    "query_hints": "",
                    "code_match_status": "hallucinated",
                }
            )
        )
        validator = DbIndexValidator(mock_llm)
        result = await validator.analyze_table(
            table=_make_table(), sample_data=None, code_context="", rules_context=""
        )
        assert result.code_match_status == "no_code_info"
