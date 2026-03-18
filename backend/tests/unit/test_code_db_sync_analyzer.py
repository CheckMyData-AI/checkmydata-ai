"""Unit tests for CodeDbSyncAnalyzer."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.knowledge.code_db_sync_analyzer import (
    CodeDbSyncAnalyzer,
    SyncSummaryResult,
    TableSyncAnalysis,
)
from app.llm.base import LLMResponse, ToolCall


@pytest.fixture
def mock_llm():
    router = MagicMock()
    router.complete = AsyncMock()
    return router


@pytest.fixture
def analyzer(mock_llm):
    return CodeDbSyncAnalyzer(llm_router=mock_llm)


class TestAnalyzeTable:
    @pytest.mark.asyncio
    async def test_successful_analysis(self, analyzer, mock_llm):
        mock_llm.complete.return_value = LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="table_sync_analysis",
                    arguments={
                        "data_format_notes": "Amount in cents",
                        "column_sync_notes": '{"amount": "cents"}',
                        "business_logic_notes": "Order processing",
                        "conversion_warnings": "Divide by 100",
                        "query_recommendations": "Filter by status",
                        "sync_status": "matched",
                        "confidence_score": 4,
                    },
                )
            ],
        )

        result = await analyzer.analyze_table("orders", "DB schema...", "Code context...")

        assert isinstance(result, TableSyncAnalysis)
        assert result.table_name == "orders"
        assert result.sync_status == "matched"
        assert result.confidence_score == 4
        assert "cents" in result.data_format_notes
        assert "Divide by 100" in result.conversion_warnings

    @pytest.mark.asyncio
    async def test_no_tool_call_returns_fallback(self, analyzer, mock_llm):
        mock_llm.complete.return_value = LLMResponse(content="Some text response")

        result = await analyzer.analyze_table("users", "schema", "code")

        assert result.sync_status == "unknown"
        assert result.confidence_score == 1

    @pytest.mark.asyncio
    async def test_llm_exception_returns_fallback(self, analyzer, mock_llm):
        mock_llm.complete.side_effect = Exception("LLM error")

        result = await analyzer.analyze_table("users", "schema", "code")

        assert result.sync_status == "unknown"
        assert result.confidence_score == 1
        assert "fallback" in result.data_format_notes.lower()

    @pytest.mark.asyncio
    async def test_column_sync_notes_dict_converted(self, analyzer, mock_llm):
        mock_llm.complete.return_value = LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="table_sync_analysis",
                    arguments={
                        "data_format_notes": "",
                        "column_sync_notes": {"amount": "in cents"},
                        "business_logic_notes": "",
                        "conversion_warnings": "",
                        "query_recommendations": "",
                        "sync_status": "matched",
                        "confidence_score": 3,
                    },
                )
            ],
        )

        result = await analyzer.analyze_table("orders", "", "")
        assert '"amount"' in result.column_sync_notes_json

    @pytest.mark.asyncio
    async def test_confidence_score_clamped(self, analyzer, mock_llm):
        mock_llm.complete.return_value = LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="table_sync_analysis",
                    arguments={
                        "data_format_notes": "",
                        "column_sync_notes": "{}",
                        "business_logic_notes": "",
                        "conversion_warnings": "",
                        "query_recommendations": "",
                        "sync_status": "matched",
                        "confidence_score": 10,
                    },
                )
            ],
        )

        result = await analyzer.analyze_table("t", "", "")
        assert result.confidence_score == 5


class TestAnalyzeTableBatch:
    @pytest.mark.asyncio
    async def test_batch_analysis(self, analyzer, mock_llm):
        mock_llm.complete.return_value = LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="table_sync_analysis",
                    arguments={
                        "data_format_notes": "Table 1",
                        "column_sync_notes": "{}",
                        "business_logic_notes": "",
                        "conversion_warnings": "",
                        "query_recommendations": "",
                        "sync_status": "matched",
                        "confidence_score": 3,
                    },
                ),
                ToolCall(
                    id="call_2",
                    name="table_sync_analysis",
                    arguments={
                        "data_format_notes": "Table 2",
                        "column_sync_notes": "{}",
                        "business_logic_notes": "",
                        "conversion_warnings": "",
                        "query_recommendations": "",
                        "sync_status": "db_only",
                        "confidence_score": 2,
                    },
                ),
            ],
        )

        results = await analyzer.analyze_table_batch(
            [
                ("t1", "db1", "code1"),
                ("t2", "db2", "code2"),
            ]
        )

        assert len(results) == 2
        assert results[0].table_name == "t1"
        assert results[1].table_name == "t2"
        assert results[1].sync_status == "db_only"

    @pytest.mark.asyncio
    async def test_batch_fills_missing_with_fallback(self, analyzer, mock_llm):
        mock_llm.complete.return_value = LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="table_sync_analysis",
                    arguments={
                        "data_format_notes": "",
                        "column_sync_notes": "{}",
                        "business_logic_notes": "",
                        "conversion_warnings": "",
                        "query_recommendations": "",
                        "sync_status": "matched",
                        "confidence_score": 3,
                    },
                ),
            ],
        )

        results = await analyzer.analyze_table_batch(
            [
                ("t1", "db1", "code1"),
                ("t2", "db2", "code2"),
            ]
        )

        assert len(results) == 2
        assert results[0].sync_status == "matched"
        assert results[1].sync_status == "unknown"
        assert results[1].confidence_score == 1

    @pytest.mark.asyncio
    async def test_empty_batch(self, analyzer, mock_llm):
        results = await analyzer.analyze_table_batch([])
        assert results == []


class TestGenerateSummary:
    @pytest.mark.asyncio
    async def test_summary_generation(self, analyzer, mock_llm):
        mock_llm.complete.return_value = LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="sync_summary",
                    arguments={
                        "global_notes": "E-commerce app",
                        "data_conventions": "Money in cents, UTC timestamps",
                        "query_guidelines": "- Divide amount by 100",
                    },
                )
            ],
        )

        analyses = [
            TableSyncAnalysis(table_name="orders", sync_status="matched", confidence_score=4),
            TableSyncAnalysis(table_name="users", sync_status="matched", confidence_score=5),
        ]

        result = await analyzer.generate_summary(analyses, "2 entities, 2 tables")

        assert isinstance(result, SyncSummaryResult)
        assert "E-commerce" in result.global_notes
        assert "cents" in result.data_conventions

    @pytest.mark.asyncio
    async def test_summary_fallback_on_no_tool_call(self, analyzer, mock_llm):
        mock_llm.complete.return_value = LLMResponse(content="Some analysis text")

        analyses = [
            TableSyncAnalysis(table_name="t1", sync_status="matched"),
        ]

        result = await analyzer.generate_summary(analyses, "context")
        assert "Some analysis" in result.global_notes

    @pytest.mark.asyncio
    async def test_summary_fallback_on_error(self, analyzer, mock_llm):
        mock_llm.complete.side_effect = Exception("Error")

        result = await analyzer.generate_summary([], "ctx")
        assert "0 tables" in result.global_notes


class TestSyncStatusClamping:
    def test_valid_statuses_pass_through(self):
        from app.knowledge.code_db_sync_analyzer import _clamp_sync_status

        for status in ("matched", "code_only", "db_only", "mismatch", "unknown"):
            assert _clamp_sync_status(status) == status

    def test_invalid_status_falls_back(self):
        from app.knowledge.code_db_sync_analyzer import _clamp_sync_status

        assert _clamp_sync_status("synced") == "unknown"
        assert _clamp_sync_status("") == "unknown"
        assert _clamp_sync_status("MATCHED") == "unknown"

    @pytest.mark.asyncio
    async def test_llm_invalid_sync_status_clamped(self, analyzer, mock_llm):
        mock_llm.complete.return_value = LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="table_sync_analysis",
                    arguments={
                        "data_format_notes": "",
                        "column_sync_notes": "{}",
                        "business_logic_notes": "",
                        "conversion_warnings": "",
                        "query_recommendations": "",
                        "sync_status": "synced",
                        "confidence_score": 3,
                    },
                )
            ],
        )
        result = await analyzer.analyze_table("orders", "schema", "code")
        assert result.sync_status == "unknown"
