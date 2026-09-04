"""A cost figure that no process could ever produce (Ш0b · REQ-7/8).

Measured on production 2026-09-04: `estimated_cost_usd` is NULL on **all 7 664**
`token_usage` rows and **all 222** `request_traces` — every month back to
2026-04, both processes. The operator has no cost figure for any request ever
made, while 60.2 million tokens were metered exactly.

The cause was one import. `estimate_cost` read
`app.api.routes.models._cache` — an in-process dict populated **only** as a side
effect of somebody requesting `GET /api/models`. The worker serves no HTTP, so
its copy was forever empty; the web dyno's was empty until a user happened to open the
model picker.

The fix is smaller than it looked, and the first design here was wrong. I
proposed a Redis store on the reasoning that "the worker cannot reach the data".
It can: `_fetch_openrouter_models()` is an async call to *OpenRouter*, not to our
own API, and any process can make it. The bug was never reachability — it was
that nothing ever **awaited the fetch**, only peeked at its cache. So: await it,
and let each process warm its own copy under the TTL that was always there.

`price_source` is recorded beside the number because the same figure means
different things from a live price and from an empty table, and a cost nobody can
attribute cannot be audited later.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services.model_pricing_service import (
    clear_price_cache,
    get_price,
    price_table,
)

_FAKE = [
    {"id": "openai/gpt-4o", "pricing": {"prompt": "0.0000025", "completion": "0.00001"}},
    {
        "id": "anthropic/claude-4.6-opus",
        "pricing": {"prompt": "0.000015", "completion": "0.000075"},
    },
]


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_price_cache()
    yield
    clear_price_cache()


class TestThePriceIsFetchedNotPeekedAt:
    async def test_a_cold_process_gets_a_price(self):
        """The whole defect in one test: no HTTP request has been served, and a
        price is still available."""
        with patch(
            "app.services.model_pricing_service._fetch_openrouter_models",
            new=AsyncMock(return_value=_FAKE),
        ):
            price = await get_price("openai/gpt-4o")

        assert price is not None
        assert price.prompt_per_token == pytest.approx(0.0000025)
        assert price.completion_per_token == pytest.approx(0.00001)
        assert price.source == "process_cache"

    async def test_the_fetch_happens_once_and_the_second_read_is_cached(self):
        fetch = AsyncMock(return_value=_FAKE)
        with patch("app.services.model_pricing_service._fetch_openrouter_models", new=fetch):
            await get_price("openai/gpt-4o")
            await get_price("anthropic/claude-4.6-opus")

        assert fetch.await_count == 1, (
            f"the table is fetched per process, not per model; awaited {fetch.await_count} times"
        )

    async def test_an_unknown_model_is_none_and_not_zero(self):
        """A model absent from the table has no price. Zero would be a claim."""
        with patch(
            "app.services.model_pricing_service._fetch_openrouter_models",
            new=AsyncMock(return_value=_FAKE),
        ):
            assert await get_price("some/model-nobody-has") is None

    async def test_a_failed_fetch_degrades_to_none_rather_than_raising(self):
        """Pricing is telemetry. It must never be the thing that fails a request
        the user is waiting for."""
        with patch(
            "app.services.model_pricing_service._fetch_openrouter_models",
            new=AsyncMock(side_effect=RuntimeError("registry down")),
        ):
            assert await get_price("openai/gpt-4o") is None

    async def test_a_failed_fetch_is_not_cached_as_an_empty_table(self):
        """Caching a failure would turn one outage into a TTL of missing costs."""
        failing = AsyncMock(side_effect=RuntimeError("registry down"))
        with patch("app.services.model_pricing_service._fetch_openrouter_models", new=failing):
            await get_price("openai/gpt-4o")
        with patch(
            "app.services.model_pricing_service._fetch_openrouter_models",
            new=AsyncMock(return_value=_FAKE),
        ):
            assert await get_price("openai/gpt-4o") is not None


class TestTheCostItself:
    async def test_it_multiplies_tokens_by_the_two_prices(self):
        from app.services.cost_estimation_service import estimate_cost_async

        with patch(
            "app.services.model_pricing_service._fetch_openrouter_models",
            new=AsyncMock(return_value=_FAKE),
        ):
            cost, source = await estimate_cost_async("openai/gpt-4o", 1000, 500)

        # 1000 * 0.0000025 + 500 * 0.00001 = 0.0025 + 0.005
        assert cost == pytest.approx(0.0075)
        assert source == "process_cache"

    async def test_no_price_returns_none_with_source_none(self):
        from app.services.cost_estimation_service import estimate_cost_async

        with patch(
            "app.services.model_pricing_service._fetch_openrouter_models",
            new=AsyncMock(return_value=_FAKE),
        ):
            cost, source = await estimate_cost_async("nope/nope", 10, 10)

        assert cost is None
        assert source == "none", "the source must say why there is no number"

    async def test_an_absent_model_name_is_not_an_error(self):
        from app.services.cost_estimation_service import estimate_cost_async

        assert await estimate_cost_async(None, 10, 10) == (None, "none")

    async def test_the_source_is_one_the_trace_record_accepts(self):
        """`TraceMeta` validates `price_source` at construction, so a source this
        function invents would raise at the call site instead of here."""
        from app.core.trace_meta import PRICE_SOURCES
        from app.services.cost_estimation_service import estimate_cost_async

        with patch(
            "app.services.model_pricing_service._fetch_openrouter_models",
            new=AsyncMock(return_value=_FAKE),
        ):
            _, source = await estimate_cost_async("openai/gpt-4o", 1, 1)
        assert source in PRICE_SOURCES


class TestTheDependencyPointsTheRightWay:
    def test_the_service_does_not_import_a_route_module(self):
        """It did: `cost_estimation_service` reached into
        `app.api.routes.models._cache`. A service importing a route is how the
        price table ended up living in an HTTP handler's side effect."""
        src = Path(inspect.getfile(price_table)).read_text(encoding="utf-8")
        offenders = {
            node.module
            for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("app.api")
        }
        assert not offenders, f"the pricing service must not import routes; found {offenders}"

    def test_cost_estimation_no_longer_reaches_into_the_route_cache(self):
        from app.services import cost_estimation_service

        # An IMPORT or an attribute read — not a mention. The module's own
        # docstring names the old path to explain the defect, and forbidding
        # that would forbid the explanation.
        src = Path(inspect.getfile(cost_estimation_service)).read_text(encoding="utf-8")
        imports = {
            node.module
            for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert "app.api.routes.models" not in imports, (
            "reading a route module's private cache is what made the cost NULL "
            f"on 7664 rows; imports: {sorted(imports)}"
        )
        assert "_cache" not in src.replace("``app.api.routes.models._cache``", ""), (
            "no reference to the route's private cache may remain in code"
        )

    def test_the_route_now_consumes_the_service(self):
        """One fetch, one cache. Two would drift and double the outbound calls."""
        src = Path("app/api/routes/models.py").read_text(encoding="utf-8")
        assert "model_pricing_service" in src


class TestTheUsageSinkComputesIt:
    def test_the_sink_awaits_the_async_estimator(self):
        """`DbUsageSink.observe` writes the 7664 rows. If it kept the sync
        helper, every one of them would still carry NULL."""
        from app.llm import usage_sink

        src = Path(inspect.getfile(usage_sink)).read_text(encoding="utf-8")
        assert "estimate_cost_async" in src, "the sink must use the async estimator"
