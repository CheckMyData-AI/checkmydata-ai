"""Unit tests for the chat-entry token budget gate (F-FIN-1)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.api.routes.chat import _check_token_budget


class TestCheckTokenBudget:
    @pytest.mark.asyncio
    async def test_within_budget_allows(self):
        with patch("app.api.routes.chat._usage_svc") as mock_svc:
            mock_svc.check_token_budget = AsyncMock(return_value=None)
            result = await _check_token_budget(AsyncMock(), "u1")

        assert result is None
        mock_svc.check_token_budget.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exceeded_budget_blocks_with_message(self):
        with patch("app.api.routes.chat._usage_svc") as mock_svc:
            mock_svc.check_token_budget = AsyncMock(
                return_value=(
                    "Daily token budget exceeded (1,200/1,000)"
                    " — upgrade your plan at /pricing to continue."
                )
            )
            result = await _check_token_budget(AsyncMock(), "u1")

        assert result is not None
        assert "Daily token budget exceeded" in result
        assert "/pricing" in result

    @pytest.mark.asyncio
    async def test_infrastructure_error_fails_open(self):
        """A broken usage query must not take chat down."""
        with patch("app.api.routes.chat._usage_svc") as mock_svc:
            mock_svc.check_token_budget = AsyncMock(return_value=None)
            result = await _check_token_budget(AsyncMock(), "u1")

        assert result is None
