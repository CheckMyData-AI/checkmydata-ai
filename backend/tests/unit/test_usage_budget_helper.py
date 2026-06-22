from unittest.mock import AsyncMock, patch

from app.services.usage_service import BudgetExceededError, UsageService


async def test_returns_none_when_within_budget():
    svc = UsageService()
    db = AsyncMock()
    with (
        patch(
            "app.services.entitlement_service.EntitlementService.effective_token_limits",
            new=AsyncMock(return_value=(1000, 0)),
        ),
        patch.object(svc, "check_budget", new=AsyncMock(return_value={"allowed": True})),
    ):
        assert await svc.check_token_budget(db, "u1") is None


async def test_returns_message_when_budget_exceeded():
    svc = UsageService()
    db = AsyncMock()
    with (
        patch(
            "app.services.entitlement_service.EntitlementService.effective_token_limits",
            new=AsyncMock(return_value=(1000, 0)),
        ),
        patch.object(
            svc,
            "check_budget",
            new=AsyncMock(
                side_effect=BudgetExceededError(
                    "Daily token budget exceeded", used=1000, limit=1000
                )
            ),
        ),
    ):
        msg = await svc.check_token_budget(db, "u1")
        assert msg is not None and "/pricing" in msg


async def test_unlimited_limits_short_circuit():
    svc = UsageService()
    db = AsyncMock()
    with patch(
        "app.services.entitlement_service.EntitlementService.effective_token_limits",
        new=AsyncMock(return_value=(0, 0)),
    ):
        assert await svc.check_token_budget(db, "u1") is None
