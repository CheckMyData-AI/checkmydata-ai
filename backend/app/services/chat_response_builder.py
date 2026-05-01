"""Payload builders used by the chat endpoints (T23).

These were previously private helpers in ``app/api/routes/chat.py``. They
are extracted here so (a) the router stays focused on HTTP glue and (b)
we can unit-test the payload shapes without spinning up FastAPI.
"""

from __future__ import annotations

from typing import Any

from app.llm.errors import LLMError
from app.viz.renderer import render


def has_rules_changed(tool_call_log: list[dict] | None) -> bool:
    """Return True if any tool call in the log modified rules."""
    if not tool_call_log:
        return False
    return any(
        tc.get("tool") in ("manage_custom_rules", "manage_rules")
        for tc in tool_call_log
    )


def build_structured_error(exc: Exception) -> dict[str, Any]:
    """Build a structured error payload for SSE error events.

    Preserves the extra fields (``is_retryable``, ``user_message``) for
    :class:`LLMError` subclasses so the UI can render a targeted message.
    """
    if isinstance(exc, LLMError):
        return {
            "error": str(exc),
            "error_type": type(exc).__name__,
            "is_retryable": exc.is_retryable,
            "user_message": exc.user_message,
        }
    return {
        "error": str(exc),
        "error_type": "internal",
        "is_retryable": True,
        "user_message": "An unexpected error occurred. Please try again.",
    }


def build_raw_result(results, *, row_cap: int) -> dict[str, Any] | None:
    """Extract raw tabular data from query results, capped at ``row_cap`` rows."""
    if not results:
        return None
    cols = getattr(results, "columns", None)
    rows = getattr(results, "rows", None)
    if not cols:
        return None
    from app.viz.utils import serialize_value

    capped = (rows or [])[:row_cap]
    return {
        "columns": list(cols),
        "rows": [[serialize_value(v) for v in row] for row in capped],
        "total_rows": getattr(results, "row_count", len(rows or [])),
    }


def build_sql_results_payload(
    sql_result_blocks: list,
    *,
    row_cap: int,
    answer: str = "",
) -> list[dict[str, Any]] | None:
    """Serialize a list of SQLResultBlock objects for the API response.

    Returns ``None`` when there are fewer than 2 blocks (single-result
    case is handled by the legacy top-level fields for backward
    compatibility).
    """
    if len(sql_result_blocks) < 2:
        return None
    payload: list[dict[str, Any]] = []
    for blk in sql_result_blocks:
        blk_viz = None
        if blk.results and blk.results.rows:
            blk_viz = render(
                result=blk.results,
                viz_type=blk.viz_type,
                config=blk.viz_config,
                summary=answer,
            )
        payload.append(
            {
                "query": blk.query,
                "query_explanation": blk.query_explanation,
                "visualization": blk_viz,
                "raw_result": build_raw_result(blk.results, row_cap=row_cap),
                "insights": blk.insights or [],
            }
        )
    return payload


def build_search_snippet(text: str, query: str, *, max_len: int = 200) -> str:
    """Render a highlight-worthy snippet around ``query`` within ``text``.

    Falls back to a truncation when the query is not present in the text.
    """
    lower = text.lower()
    idx = lower.find(query.lower())
    if idx == -1:
        return text[:max_len] + ("..." if len(text) > max_len else "")
    start = max(0, idx - max_len // 3)
    end = min(len(text), idx + len(query) + max_len * 2 // 3)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet
