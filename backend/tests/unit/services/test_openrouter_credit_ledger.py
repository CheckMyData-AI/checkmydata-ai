"""Two pockets over one counter, and the one ordering that is not a preference.

OpenRouter gives a key a spend CEILING and a running total: `limit`, `usage`,
`limit_remaining = limit - usage`. That is one counter. The billing model has two pockets
with different lifetimes — an included allowance granted monthly with the tier and expiring
at renewal, and purchased credit that never expires because the customer paid for it
separately.

**Spend depletes the included pocket first, always.** With the order reversed, a customer
who under-used their monthly allowance would lose purchased credit at every renewal, which
is the one arithmetic error here that is indistinguishable from taking their money.

`usage_at_period_start` is the hinge: OpenRouter's `usage` is monotonic by design
(`limit_reset: null`), so "spent this period" is a subtraction against a stored watermark
rather than anything readable.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.openrouter_credit_service import CreditError, OpenRouterCreditService


@pytest.fixture
def svc():
    return OpenRouterCreditService(management_key="sk-mgmt-test")


class TestTheSplitIsIncludedFirst:
    def test_spend_inside_the_allowance_touches_nothing_purchased(self, svc) -> None:
        included, purchased = svc._split(Decimal("10"), Decimal("30"))
        assert (included, purchased) == (Decimal("10"), Decimal("0"))

    def test_spend_past_the_allowance_bills_the_remainder_to_purchased(self, svc) -> None:
        included, purchased = svc._split(Decimal("45"), Decimal("30"))
        assert (included, purchased) == (Decimal("30"), Decimal("15"))

    def test_exactly_the_allowance_leaves_purchased_untouched(self, svc) -> None:
        assert svc._split(Decimal("30"), Decimal("30")) == (Decimal("30"), Decimal("0"))

    def test_no_allowance_bills_everything_to_purchased(self, svc) -> None:
        assert svc._split(Decimal("12"), Decimal("0")) == (Decimal("0"), Decimal("12"))

    def test_no_spend_takes_from_neither(self, svc) -> None:
        assert svc._split(Decimal("0"), Decimal("30")) == (Decimal("0"), Decimal("0"))

    def test_the_order_is_not_reversible(self, svc) -> None:
        """The failure this protects against, stated as a number: with purchased consumed
        first, a customer spending $10 of a $30 allowance while holding $50 of bought
        credit would end the month with $40 instead of $50 — $10 taken for nothing."""
        spent, allowance = Decimal("10"), Decimal("30")
        from_included, from_purchased = svc._split(spent, allowance)
        assert from_purchased == 0, (
            "purchased credit was consumed while the included allowance still had room"
        )


class TestTheCeilingIsExpressedAgainstUsage:
    """OpenRouter's counter is monotonic, so a ceiling sent as a running total rather than
    as `usage + remaining` would sit below `usage` and refuse every further call."""

    async def test_the_limit_is_usage_plus_both_pockets(self, svc) -> None:
        row = _row(included=30, purchased=20)
        assert await svc._limit_for(row, Decimal("100")) == Decimal("150.000000")

    async def test_a_spent_out_account_still_gets_a_ceiling_above_its_usage(self, svc) -> None:
        row = _row(included=0, purchased=0)
        limit = await svc._limit_for(row, Decimal("77.5"))
        assert limit == Decimal("77.500000"), (
            "the ceiling must not fall below usage; a lower one refuses every call rather "
            "than refusing the next dollar"
        )


class TestMoneyIsNotAFloat:
    def test_amounts_quantise_to_six_places(self) -> None:
        from app.services.openrouter_credit_service import _q

        assert _q(0.1) + _q(0.2) == _q(0.3), (
            "credit arithmetic is running in binary float, where 0.1 + 0.2 != 0.3 and a "
            "balance drifts by cents over a year"
        )

    def test_openrouter_fractions_of_a_cent_survive(self) -> None:
        from app.services.openrouter_credit_service import _q

        assert _q("0.000123") == Decimal("0.000123")


class TestItRefusesRatherThanGuesses:
    async def test_no_management_key_is_an_error_not_a_silent_skip(self) -> None:
        bare = OpenRouterCreditService(management_key="")
        with pytest.raises(CreditError, match="MANAGEMENT_KEY"):
            await bare._call("GET", "/abc")

    async def test_a_non_positive_top_up_is_refused(self, svc) -> None:
        with pytest.raises(CreditError, match="positive"):
            await svc.top_up(_db(), "u1", amount_usd=0)

    async def test_a_top_up_before_provisioning_is_refused(self, svc, monkeypatch) -> None:
        """Raising the ceiling of a key that does not exist would take the money and grant
        nothing. The webhook must provision first."""
        from unittest.mock import AsyncMock

        monkeypatch.setattr(svc, "_row", AsyncMock(return_value=_row(included=0, purchased=0)))
        with pytest.raises(CreditError, match="provision"):
            await svc.top_up(_db(), "u1", amount_usd=25)


def test_the_error_body_is_never_echoed() -> None:
    """OpenRouter's error payloads can carry the key. Only the status code is logged or
    raised — an exception message that quotes the body puts a spending credential into
    every log aggregator downstream."""
    import inspect

    src = inspect.getsource(OpenRouterCreditService._call)
    # The RAISE line specifically — the success path below it reads the body legitimately,
    # and the first version of this assertion banned `resp.json()` from everything after
    # the status check, which failed on the return statement rather than on a leak.
    # The raise that reports an HTTP failure, not the one about a missing config key —
    # `next()` over every `raise CreditError` picked the wrong line first time.
    raise_line = next(
        line for line in src.splitlines() if "raise CreditError" in line and "failed" in line
    )
    assert "resp.status_code" in raise_line, "the failure must name the status"
    for leak in ("resp.text", "resp.json", "resp.content"):
        assert leak not in raise_line, (
            f"the error message quotes {leak}; OpenRouter's error payloads can carry the "
            "key, which would put a spending credential into every log downstream"
        )


# ── helpers ───────────────────────────────────────────────────────────────


def _row(*, included: float, purchased: float):
    from app.models.llm_credit import LlmCredit

    return LlmCredit(
        user_id="u1",
        key_hash=None,
        usage_at_period_start=0,
        included_grant_usd=included,
        purchased_balance_usd=purchased,
        provision_count=0,
    )


def _db():
    from unittest.mock import AsyncMock, MagicMock

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    return db
