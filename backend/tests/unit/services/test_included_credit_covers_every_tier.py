"""Every tier the product sells must have an answer about its included LLM credit.

`_INCLUDED_CREDIT_USD` held two entries — `base` and `scale` — and `_included_credit_for`
resolved anything else through `.get(..., 0.0)`. The catalogue has held four tiers since
2026-08-31, so `team` (sold as "$150/month of LLM credit at cost") and `enterprise`
provisioned their OpenRouter key with `limit: 0.0`: a lifetime ceiling of zero dollars,
written by a default rather than by a decision (BIZ-02, audit 2026-09-09).

Two decisions close it, and they are different decisions:

**D-SPEND-2a — `team` is a number, and the number lives once.** The dollar figure is already
in `plan_catalogue.PROMISED_CREDIT_USD`, which is what the token ceiling is derived from. A
second copy here is how the migration and the catalogue came to disagree (DATA-01).

**D-SPEND-2b — `enterprise` is provisioned no key at all.** Its own description sells "LLM
credit at cost with no monthly cap". A key exists to carry a ceiling; where the offer is
"no cap", there is nothing for it to carry, and `0` — today's value — is the single reading
that contradicts the promise outright. `key_hash is None` is a state every method in
`OpenRouterCreditService` already handles, so "no ceiling" needs no new column and no new
concept: `balance()` reports `provisioned: False`, `renew()` records the grant without a
remote call, and `_adjust` skips the PATCH.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.billing_service import _INCLUDED_CREDIT_USD, _included_credit_for
from app.services.plan_catalogue import PAID_TIERS, PROMISED_CREDIT_USD


@pytest.mark.parametrize("plan_id", [t["id"] for t in PAID_TIERS])
def test_every_sold_tier_has_an_explicit_answer(plan_id: str) -> None:
    """Not a `.get` default. A tier that falls through resolves to a $0 spending key."""
    assert plan_id in _INCLUDED_CREDIT_USD, (
        f"{plan_id} is sold but absent from the included-credit table, so it provisions "
        "a key with a $0 lifetime ceiling"
    )


@pytest.mark.parametrize("plan_id", sorted(PROMISED_CREDIT_USD))
def test_the_credit_matches_the_promise_the_ceiling_is_derived_from(plan_id: str) -> None:
    """One home for the dollar figure: the same table the token ceiling is computed from."""
    assert _INCLUDED_CREDIT_USD[plan_id] == PROMISED_CREDIT_USD[plan_id]


def test_team_is_the_hundred_and_fifty_its_description_sells() -> None:
    assert _included_credit_for(SimpleNamespace(id="team")) == 150.0


def test_enterprise_asks_for_no_key_ceiling() -> None:
    """`None`, not `0.0` — the two mean opposite things at the provider."""
    assert _included_credit_for(SimpleNamespace(id="enterprise")) is None


def test_an_unknown_plan_is_not_silently_a_zero_ceiling(caplog) -> None:
    """A tier id nobody planned for still resolves, and says so.

    Returning `0.0` is the safe direction — an unknown tier gets no spending headroom on
    the key — but doing it silently is how `team` spent three weeks at zero.
    """
    with caplog.at_level("WARNING"):
        assert _included_credit_for(SimpleNamespace(id="mystery")) == 0.0
    assert any("mystery" in r.getMessage() for r in caplog.records), (
        "an unknown tier resolved to $0 with no log line"
    )


class TestAnUncappedTierHoldsNoKey:
    """D-SPEND-2b end to end: the two lifecycle paths must both honour ``None``."""

    @pytest.mark.asyncio
    async def test_provisioning_an_uncapped_tier_revokes_instead_of_minting(self) -> None:
        from unittest.mock import AsyncMock

        from app.services.billing_service import BillingService

        svc = BillingService()
        svc._revoke_key = AsyncMock()
        with pytest.MonkeyPatch.context() as mp:
            minted = AsyncMock()
            mp.setattr(
                "app.services.openrouter_credit_service.OpenRouterCreditService.provision",
                minted,
            )
            await svc._provision_key(AsyncMock(), "u1", included_usd=None)
        # `assert_not_awaited` raises on its own; a trailing string here would be a tuple.
        minted.assert_not_awaited()
        svc._revoke_key.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_capped_tier_still_mints(self) -> None:
        """The guard above must not turn provisioning off for the tiers that need it."""
        from unittest.mock import AsyncMock

        from app.services.billing_service import BillingService

        svc = BillingService()
        with pytest.MonkeyPatch.context() as mp:
            minted = AsyncMock(return_value="sk-or-test")
            mp.setattr(
                "app.services.openrouter_credit_service.OpenRouterCreditService.provision",
                minted,
            )
            await svc._provision_key(AsyncMock(), "u1", included_usd=30.0)
        minted.assert_awaited_once()
