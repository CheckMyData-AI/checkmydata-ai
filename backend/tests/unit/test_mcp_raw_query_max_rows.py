"""`max_rows` on the raw-query tool: default stays 100, caller may raise it to the
connector ceiling, never past it, and `truncated` follows the cap that was applied."""

from app.connectors.base import MAX_RESULT_ROWS as CONNECTOR_CAP
from app.connectors.base import QueryResult
from app.mcp_server.tools import MAX_RESULT_ROWS, _format_query_result, clamp_max_rows


def _qr(n: int) -> QueryResult:
    return QueryResult(
        columns=["x"],
        rows=[[i] for i in range(n)],
        row_count=n,
        execution_time_ms=1.0,
        truncated=False,
        error=None,
    )


def test_default_cap_is_unchanged_at_100():
    assert clamp_max_rows(None) == MAX_RESULT_ROWS == 100
    out = _format_query_result(_qr(250))
    assert out["returned_rows"] == 100 and out["truncated"] is True


def test_caller_can_raise_the_cap_and_truncation_follows_it():
    out = _format_query_result(_qr(250), max_rows=500)
    assert out["returned_rows"] == 250 and out["truncated"] is False
    out = _format_query_result(_qr(250), max_rows=200)
    assert out["returned_rows"] == 200 and out["truncated"] is True


def test_cap_never_exceeds_the_connector_ceiling_or_drops_below_one():
    assert clamp_max_rows(10**9) == CONNECTOR_CAP == 10_000
    assert clamp_max_rows(0) == 1 and clamp_max_rows(-5) == 1
