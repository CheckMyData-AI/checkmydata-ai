"""Unit tests for the chat-entry token budget gate (F-FIN-1)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.api.routes.chat import _check_token_budget
from app.services.usage_service import BudgetExceededError


class TestCheckTokenBudget:
    @pytest.mark.asyncio
    async def test_no_limits_configured_skips_check(self):
        with (
            patch("app.config.settings.user_daily_token_limit", 0),
            patch("app.config.settings.user_monthly_token_limit", 0),
            patch("app.api.routes.chat._usage_svc") as mock_svc,
        ):
            mock_svc.check_budget = AsyncMock()
            result = await _check_token_budget(AsyncMock(), "u1")

        assert result is None
        mock_svc.check_budget.assert_not_called()

    @pytest.mark.asyncio
    async def test_within_budget_allows(self):
        with (
            patch("app.config.settings.user_daily_token_limit", 1000),
            patch("app.config.settings.user_monthly_token_limit", 0),
            patch("app.api.routes.chat._usage_svc") as mock_svc,
        ):
            mock_svc.check_budget = AsyncMock(return_value={"allowed": True})
            result = await _check_token_budget(AsyncMock(), "u1")

        assert result is None
        mock_svc.check_budget.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exceeded_budget_blocks_with_message(self):
        with (
            patch("app.config.settings.user_daily_token_limit", 1000),
            patch("app.config.settings.user_monthly_token_limit", 0),
            patch("app.api.routes.chat._usage_svc") as mock_svc,
        ):
            mock_svc.check_budget = AsyncMock(
                side_effect=BudgetExceededError(
                    "Daily token budget exceeded (1,200/1,000)", used=1200, limit=1000
                )
            )
            result = await _check_token_budget(AsyncMock(), "u1")

        assert result is not None
        assert "Daily token budget exceeded" in result

    @pytest.mark.asyncio
    async def test_infrastructure_error_fails_open(self):
        """A broken usage query must not take chat down."""
        with (
            patch("app.config.settings.user_daily_token_limit", 1000),
            patch("app.config.settings.user_monthly_token_limit", 0),
            patch("app.api.routes.chat._usage_svc") as mock_svc,
        ):
            mock_svc.check_budget = AsyncMock(side_effect=RuntimeError("db down"))
            result = await _check_token_budget(AsyncMock(), "u1")

        assert result is None
