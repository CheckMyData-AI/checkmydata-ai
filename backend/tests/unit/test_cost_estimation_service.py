"""Unit tests for :mod:`app.services.cost_estimation_service` (T23)."""

from __future__ import annotations

from unittest.mock import patch

from app.services.cost_estimation_service import (
    compute_sql_complexity,
    estimate_cost,
    estimate_tokens,
)


class TestComputeSqlComplexity:
    def test_empty_returns_simple(self):
        assert compute_sql_complexity("") == "simple"

    def test_single_table_select_is_simple(self):
        assert compute_sql_complexity("SELECT * FROM users") == "simple"

    def test_single_join_is_moderate(self):
        assert compute_sql_complexity(
            "SELECT * FROM a JOIN b ON a.id = b.a_id"
        ) == "moderate"

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
    def test_no_model_returns_none(self):
        assert estimate_cost(None, 100, 100) is None

    def test_missing_cache_returns_none(self):
        with patch("app.api.routes.models._cache") as mock_cache:
            mock_cache.get.return_value = None
            assert estimate_cost("m", 100, 100) is None

    def test_known_model_returns_cost(self):
        fake_cache = [
            (
                0,
                [
                    {
                        "id": "openai/gpt-x",
                        "pricing": {"prompt": "0.0001", "completion": "0.0002"},
                    }
                ],
            )
        ]
        with patch("app.api.routes.models._cache") as mock_cache:
            mock_cache.get.return_value = fake_cache[0]
            cost = estimate_cost("openai/gpt-x", 100, 50)
        assert cost is not None
        assert cost > 0
