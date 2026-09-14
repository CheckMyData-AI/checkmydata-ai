"""`request_traces.total_duration_ms` must be the request, not its last query.

PRJ-01 R3. `QueryResult.execution_time_ms` is a `float` defaulting to **0.0**, never
`None` (`app/connectors/base.py:312`). All three chat transports passed it as the
request's duration:

    total_duration_ms=result.results.execution_time_ms if result.results else None

and `finalize_trace` writes any value that `is not None` over the row the buffer flush
already wrote with the real elapsed time (`trace_persistence_service.py:275-286`) — so
`0.0` qualifies, and so does a 12 ms query on a 59 s request. Every completed SQL answer
therefore recorded a duration that was not the request's.

That matters beyond tidiness: the duration is the measurement ADR-0005 D4 is graded on
(p95 ≤ 60 s, ceiling 180 s). A metric computed from the wrong quantity cannot fail.

This test locks the call sites. The *mechanism* is asserted first, so a reader who
changes `execution_time_ms` to `None`-able learns why the guard exists.
"""

import ast
import pathlib

from app.connectors.base import QueryResult

CHAT = pathlib.Path(__file__).resolve().parents[3] / "app" / "api" / "routes" / "chat.py"


def test_a_query_result_always_carries_a_number_so_it_can_never_mean_absent():
    """The premise: there is no `None` to fall back to, only a misleading 0.0."""
    qr = QueryResult(columns=[], rows=[], row_count=0)
    assert qr.execution_time_ms == 0.0
    assert qr.execution_time_ms is not None


def _duration_arguments(tree: ast.AST) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "total_duration_ms":
                found.append((kw.value.lineno, ast.unparse(kw.value)))
    return found


def test_no_chat_transport_passes_a_query_time_as_the_request_duration():
    tree = ast.parse(CHAT.read_text())
    passed = _duration_arguments(tree)
    assert passed, "no call passes total_duration_ms — has the trace call moved?"
    offenders = [(line, src) for line, src in passed if "execution_time_ms" in src]
    assert not offenders, (
        "a per-query time is being written as the request's duration at "
        + "; ".join(f"chat.py:{line} -> {src}" for line, src in offenders)
        + ". Pass None and let the buffer flush's measured elapsed time stand."
    )
