"""Unit tests for :mod:`app.services.cost_estimation_service` (T23)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.services.cost_estimation_service import (
    compute_sql_complexity,
    estimate_cost_async,
    estimate_tokens,
)


class TestComputeSqlComplexity:
    def test_empty_returns_simple(self):
        assert compute_sql_complexity("") == "simple"

    def test_single_table_select_is_simple(self):
        assert compute_sql_complexity("SELECT * FROM users") == "simple"

    def test_single_join_is_moderate(self):
        assert compute_sql_complexity("SELECT * FROM a JOIN b ON a.id = b.a_id") == "moderate"

    def test_cte_is_complex(self):
        sql = "WITH x AS (SELECT 1) SELECT * FROM x"
        assert compute_sql_complexity(sql) == "complex"

    def test_recursive_cte_is_expert(self):
        sql = "WITH RECURSIVE x AS (SELECT 1 UNION SELECT 2) SELECT * FROM x"
        assert compute_sql_complexity(sql) == "expert"

    def test_window_function_is_complex(self):
        sql = "SELECT SUM(x) OVER (PARTITION BY y) FROM t"
        assert compute_sql_complexity(sql) == "complex"


class TestEstimateTokens:
    def test_empty_returns_zero(self):
        assert estimate_tokens("") == 0

    def test_approximate_four_chars_per_token(self):
        assert estimate_tokens("1234") == 1
        assert estimate_tokens("12345678") == 2


class TestEstimateCost:
    """Rewritten by Ш0b, and the rewrite is the finding.

    These tests patched ``app.api.routes.models._cache`` and asserted that a
    missing cache returns ``None``. That is not a requirement — it is the defect:
    the cache was populated only as a side effect of an HTTP request to
    ``GET /api/models``, so the worker's copy was always empty and production
    carried NULL costs on **all 7 664** ``token_usage`` rows and **all 222**
    traces (measured 2026-09-04). A test that pins "no cache ⇒ no cost" makes
    the empty cache acceptable, and it was the **eighth** time in this programme
    that a test held the defect in place.

    The price table is now fetched by whichever process needs it, so the
    interesting cases are: a cold process still gets a price, and a model absent
    from the catalogue has no price rather than a zero one.
    """

    async def test_no_model_returns_none_with_a_reason(self):
        assert await estimate_cost_async(None, 100, 100) == (None, "none")

    async def test_a_cold_process_still_gets_a_price(self):
        """The inversion of `test_missing_cache_returns_none`: nothing has served
        an HTTP request, and a cost comes back anyway."""
        fake = [{"id": "openai/gpt-x", "pricing": {"prompt": "0.0001", "completion": "0.0002"}}]
        with patch(
            "app.services.model_pricing_service._fetch_openrouter_models",
            new=AsyncMock(return_value=fake),
        ):
            cost, source = await estimate_cost_async("openai/gpt-x", 100, 50)

        # 100 * 0.0001 + 50 * 0.0002 = 0.01 + 0.01
        assert cost == 0.02
        assert source == "process_cache"

    async def test_a_model_outside_the_catalogue_has_no_price_not_a_zero_one(self):
        fake = [{"id": "openai/gpt-x", "pricing": {"prompt": "0.0001", "completion": "0.0002"}}]
        with patch(
            "app.services.model_pricing_service._fetch_openrouter_models",
            new=AsyncMock(return_value=fake),
        ):
            assert await estimate_cost_async("someone/else", 100, 50) == (None, "none")
