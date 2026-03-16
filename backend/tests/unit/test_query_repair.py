"""Tests for query repairer."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.query_repair import QueryRepairer


class TestQueryRepairer:
    @pytest.mark.asyncio
    async def test_successful_repair(self):
        mock_router = MagicMock()
        mock_response = MagicMock()
        mock_tc = MagicMock()
        mock_tc.name = "execute_query"
        mock_tc.arguments = {
            "query": "SELECT username FROM users",
            "explanation": "Fixed column name",
        }
        mock_response.tool_calls = [mock_tc]
        mock_router.complete = AsyncMock(return_value=mock_response)

        repairer = QueryRepairer(mock_router)
        result = await repairer.repair(
            repair_context="some context",
            db_type="postgresql",
        )
        assert result["query"] == "SELECT username FROM users"
        assert result["explanation"] == "Fixed column name"
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_repair_no_tool_call(self):
        mock_router = MagicMock()
        mock_response = MagicMock()
        mock_response.tool_calls = []
        mock_response.content = "I couldn't fix the query"
        mock_router.complete = AsyncMock(return_value=mock_response)

        repairer = QueryRepairer(mock_router)
        result = await repairer.repair(
            repair_context="some context",
            db_type="postgresql",
        )
        assert result.get("error")
        assert result["query"] == ""

    @pytest.mark.asyncio
    async def test_repair_llm_exception(self):
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(
            side_effect=Exception("LLM unavailable"),
        )

        repairer = QueryRepairer(mock_router)
        result = await repairer.repair(
            repair_context="some context",
            db_type="postgresql",
        )
        assert "error" in result
        assert "LLM" in result["error"]
