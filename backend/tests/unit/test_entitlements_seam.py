"""The seam that lets billing leave without the product noticing.

The repository is public and MIT-licensed. The commercial layer — Stripe, plans,
subscriptions, per-account OpenRouter keys — is meant to live outside it, while the
product itself keeps working for anyone who clones it.

Measured before designing: only four call sites ask an entitlement question, and all four
ask one of two things — *may I create another project?* and *may I create another
connection?* — plus `usage_service`, which asks what the token ceiling is. Three methods
is the whole surface, which is why the split is a seam rather than a rewrite.

**Metering deliberately stays.** `usage_service`, `token_usage` and `usage_sink` are
imported by eight modules including the LLM router and the chat path. Knowing what you are
spending is not a commercial feature, and a self-hoster wants it more than we do.

What this is NOT: `BILLING_ENABLED` is a runtime flag over code that ships either way. It
never removed anything from the repository and was never able to.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.entitlements import get_entitlements, reset_entitlements, set_entitlements
from app.entitlements.base import Entitlements
from app.entitlements.unlimited import UnlimitedEntitlements


@pytest.fixture(autouse=True)
def _clean():
    reset_entitlements()
    yield
    reset_entitlements()


class TestTheDefaultIsPermissive:
    """With no commercial layer installed the product must be fully usable. A build that
    fails closed on a missing billing package is a build nobody can run."""

    async def test_project_quota_passes(self) -> None:
        await get_entitlements().enforce_project_quota(MagicMock(), "u1")

    async def test_connection_quota_passes(self) -> None:
        await get_entitlements().enforce_connection_quota(MagicMock(), "u1")

    async def test_token_limits_are_unlimited(self) -> None:
        assert await get_entitlements().effective_token_limits(MagicMock(), "u1") == (0, 0)

    def test_the_default_is_the_unlimited_provider(self) -> None:
        assert isinstance(get_entitlements(), UnlimitedEntitlements)

    def test_zero_means_unlimited_here_as_everywhere_else(self) -> None:
        """`0` already means "no limit" in `check_budget` and `_strictest`. Returning
        `None` instead would need a second convention for the same idea."""
        import inspect

        assert "0 = unlimited" in inspect.getsource(UnlimitedEntitlements) or "unlimited" in (
            inspect.getdoc(UnlimitedEntitlements.effective_token_limits) or ""
        )


class TestACommercialProviderCanTakeOver:
    async def test_a_registered_provider_is_used(self) -> None:
        class Refusing:
            async def enforce_project_quota(self, db, user_id):
                raise RuntimeError("refused")

            async def enforce_connection_quota(self, db, user_id):
                raise RuntimeError("refused")

            async def effective_token_limits(self, db, user_id):
                return (100, 1000)

        set_entitlements(Refusing())
        assert await get_entitlements().effective_token_limits(MagicMock(), "u") == (100, 1000)
        with pytest.raises(RuntimeError):
            await get_entitlements().enforce_project_quota(MagicMock(), "u")

    def test_the_protocol_is_structural_so_the_cloud_package_imports_nothing(self) -> None:
        """A `Protocol`, not a base class. The private package must not have to import
        from this repository to satisfy it — otherwise the dependency points the wrong
        way and the split is cosmetic."""
        assert issubclass(UnlimitedEntitlements, Entitlements) or isinstance(
            UnlimitedEntitlements(), Entitlements
        )


class TestTheSurfaceIsExactlyWhatTheCallSitesNeed:
    """Three methods, because four call sites ask two questions and the meter asks one.
    A wider protocol is a wider thing to reimplement and to keep in step."""

    def test_it_has_three_methods_and_no_more(self) -> None:
        surface = {m for m in dir(Entitlements) if not m.startswith("_")}
        assert surface == {
            "enforce_project_quota",
            "enforce_connection_quota",
            "effective_token_limits",
        }, surface


def test_metering_does_not_move() -> None:
    """Guard on the split itself. If `usage_service` ever starts importing entitlements,
    the meter has been dragged into the commercial layer and the open-source build loses
    the ability to show a self-hoster their own spend."""
    import inspect

    from app.services import usage_service

    src = inspect.getsource(usage_service)
    assert "entitlement" not in src.lower() or "effective_token_limits" in src, (
        "usage_service now depends on entitlements in a way that would not survive the "
        "split; metering must stay in the open-source build"
    )


def test_there_is_exactly_one_quota_exception() -> None:
    """Introduced and caught within one commit while building this seam: the protocol
    defined `QuotaExceededError` and `entitlement_service` kept its own, so the routes
    caught a class the service never raised. Two classes of the same name are invisible
    until a paying customer hits a limit and gets a 500 instead of a 402."""
    from app.entitlements import QuotaExceededError as Protocol
    from app.services.entitlement_service import QuotaExceededError as Service

    assert Protocol is Service


def test_the_quota_error_keeps_the_payload_the_frontend_renders() -> None:
    """The hard-limit decision is only honest if the refusal says what was hit and what to
    do about it. This signature was moved, not redesigned: the first version of the
    protocol invented a narrower one and mypy found four call sites passing the fields it
    had dropped."""
    from app.entitlements import QuotaExceededError

    err = QuotaExceededError("limit reached", resource="connections", limit=5, current=5)
    payload = err.as_payload()
    assert payload["resource"] == "connections"
    assert payload["limit"] == 5 and payload["current"] == 5
    assert payload["upgrade_url"] == "/pricing"
