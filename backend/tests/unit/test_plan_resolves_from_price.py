"""F-BILL-01 — the plan was resolved from stale metadata instead of the live price.

`_resolve_plan_id` read `metadata.plan_id` off the Stripe subscription and returned it
immediately, falling back to the price only when metadata was absent.

Stripe's `metadata` is set once, when our Checkout session creates the subscription, and
**does not change when the subscription's price changes.** So a customer who upgrades or
downgrades through the Customer Portal keeps the plan they originally bought:

* downgrade Team → Pro: they pay Pro and keep Team's limits;
* upgrade Pro → Team: they pay Team and keep Pro's limits.

Both directions are wrong and both are money. The price is what Stripe actually charges, so
the price is the authority; metadata is a hint about intent that ages badly.

Metadata is still worth reading, in one situation only: the price is real but no catalog row
matches it — a price added in Stripe before the catalog caught up. Falling back there beats
returning `None`, because the caller leaves `sub.plan_id` untouched on `None` and a paying
customer would silently keep whatever they had. It logs at warning, because a catalog behind
Stripe is an operator problem that only shows up as a wrong entitlement.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.billing_service import BillingService


@dataclass
class _Plan:
    id: str
    stripe_price_id: str | None = None


class _Scalars:
    def __init__(self, plans: list[_Plan]):
        self._plans = plans

    def all(self) -> list[_Plan]:
        return self._plans


class _Result:
    def __init__(self, plans: list[_Plan]):
        self._plans = plans

    def scalars(self) -> _Scalars:
        return _Scalars(self._plans)


class _Db:
    """The two calls the resolver makes, and nothing else — nested closures for this read
    worse than three small classes and tripped the naming rule besides."""

    def __init__(self, plans: list[_Plan]):
        self._plans = plans

    async def execute(self, _stmt) -> _Result:
        return _Result(self._plans)


def _sub(*, price: str | None, meta: str | None) -> dict:
    obj: dict = {"metadata": {}}
    if meta is not None:
        obj["metadata"]["plan_id"] = meta
    if price is not None:
        obj["items"] = {"data": [{"price": {"id": price}}]}
    return obj


CATALOG = [
    _Plan(id="pro", stripe_price_id="price_pro"),
    _Plan(id="team", stripe_price_id="price_team"),
]


class TestThePriceWins:
    async def test_a_downgrade_is_honoured(self):
        """Bought Team, moved to the Pro price. Metadata still says team; the customer is
        being charged for pro."""
        got = await BillingService()._resolve_plan_id(
            _Db(CATALOG), _sub(price="price_pro", meta="team")
        )

        assert got == "pro"

    async def test_an_upgrade_is_honoured(self):
        got = await BillingService()._resolve_plan_id(
            _Db(CATALOG), _sub(price="price_team", meta="pro")
        )

        assert got == "team"

    async def test_they_agree_when_nothing_changed(self):
        got = await BillingService()._resolve_plan_id(
            _Db(CATALOG), _sub(price="price_pro", meta="pro")
        )

        assert got == "pro"


class TestMetadataIsTheFallbackAndSaysSo:
    async def test_an_unknown_price_falls_back_to_metadata(self, caplog):
        """A price that exists in Stripe and not in the catalog. Returning `None` here
        leaves `sub.plan_id` untouched — a paying customer silently keeps whatever they
        had — so the intent recorded at purchase is the better of two imperfect answers."""
        with caplog.at_level(logging.DEBUG):
            got = await BillingService()._resolve_plan_id(
                _Db(CATALOG), _sub(price="price_brand_new", meta="team")
            )

        assert got == "team"
        assert [r for r in caplog.records if r.levelno >= logging.WARNING], (
            "a catalog behind Stripe only ever shows up as a wrong entitlement; it has to "
            "be visible before that"
        )

    async def test_no_price_and_no_metadata_resolves_to_nothing(self):
        got = await BillingService()._resolve_plan_id(_Db(CATALOG), _sub(price=None, meta=None))

        assert got is None

    async def test_no_price_falls_back_to_metadata(self):
        """Some webhook payloads arrive without expanded items."""
        got = await BillingService()._resolve_plan_id(_Db(CATALOG), _sub(price=None, meta="pro"))

        assert got == "pro"

    async def test_an_unknown_price_with_no_metadata_warns_and_returns_none(self, caplog):
        with caplog.at_level(logging.DEBUG):
            got = await BillingService()._resolve_plan_id(
                _Db(CATALOG), _sub(price="price_mystery", meta=None)
            )

        assert got is None
        assert [r for r in caplog.records if r.levelno >= logging.WARNING]


class TestTheOrderIsTheFix:
    def test_the_price_is_read_before_metadata(self):
        """Asserted on the AST: the previous version returned metadata on line one, so any
        amount of correct price-matching below it was unreachable."""
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(BillingService._resolve_plan_id)))
        first_meta = min(
            (
                n.lineno
                for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and n.value == "plan_id"
            ),
            default=10**6,
        )
        first_price = min(
            (
                n.lineno
                for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and n.value == "price"
            ),
            default=10**6,
        )

        assert first_price < first_meta, (
            "metadata is consulted before the price, which is how a stale plan survives an upgrade"
        )
