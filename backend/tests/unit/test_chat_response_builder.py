"""Unit tests for :mod:`app.services.chat_response_builder` (T23)."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.chat_response_builder import (
    build_raw_result,
    build_search_snippet,
    build_sql_results_payload,
    build_structured_error,
    has_rules_changed,
)


class TestHasRulesChanged:
    def test_empty_log_false(self):
        assert has_rules_changed(None) is False
        assert has_rules_changed([]) is False

    def test_detects_manage_rules(self):
        assert has_rules_changed([{"tool": "manage_rules"}]) is True

    def test_detects_manage_custom_rules(self):
        assert has_rules_changed([{"tool": "manage_custom_rules"}]) is True

    def test_ignores_other_tools(self):
        assert has_rules_changed([{"tool": "sql_agent"}]) is False


class TestBuildStructuredError:
    def test_plain_exception(self):
        payload = build_structured_error(RuntimeError("boom"))
        assert payload["error_type"] == "internal"
        assert payload["is_retryable"] is True
        assert "unexpected" in payload["user_message"].lower()

    def test_llm_error_preserves_fields(self):
        from app.llm.errors import LLMRateLimitError

        exc = LLMRateLimitError("rate limited")
        payload = build_structured_error(exc)
        assert payload["error_type"] == "LLMRateLimitError"
        assert payload["is_retryable"] is True
        assert "overloaded" in payload["user_message"].lower()


class TestBuildRawResult:
    def test_no_results(self):
        assert build_raw_result(None, row_cap=100) is None

    def test_missing_columns(self):
        res = SimpleNamespace(columns=None, rows=[[1]])
        assert build_raw_result(res, row_cap=100) is None

    def test_caps_rows(self):
        res = SimpleNamespace(
            columns=["c"],
            rows=[[i] for i in range(10)],
            row_count=10,
        )
        out = build_raw_result(res, row_cap=3)
        assert out is not None
        assert len(out["rows"]) == 3
        assert out["total_rows"] == 10


class TestBuildSqlResultsPayload:
    def test_single_block_returns_none(self):
        blk = SimpleNamespace(
            query="SELECT 1",
            query_explanation="",
            results=None,
            viz_type="table",
            viz_config=None,
            insights=None,
        )
        assert (
            build_sql_results_payload([blk], row_cap=100, answer="hi") is None
        )

    def test_multiple_blocks_no_rows_skip_viz(self):
        blk = SimpleNamespace(
            query="SELECT 1",
            query_explanation="e",
            results=None,
            viz_type="table",
            viz_config=None,
            insights=[],
        )
        out = build_sql_results_payload([blk, blk], row_cap=100, answer="")
        assert out is not None
        assert len(out) == 2
        assert out[0]["visualization"] is None


class TestBuildSearchSnippet:
    def test_query_not_found_truncates(self):
        long_text = "abc" * 200
        snippet = build_search_snippet(long_text, "xyz", max_len=30)
        assert snippet.endswith("...")
        assert len(snippet) <= 33

    def test_query_found_centers(self):
        text = "x" * 100 + "needle" + "y" * 100
        snippet = build_search_snippet(text, "needle", max_len=60)
        assert "needle" in snippet
