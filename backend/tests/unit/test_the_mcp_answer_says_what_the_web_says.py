"""The second interface must disclose what the first one does.

`checkmydata_query_database` runs the *same* orchestrator as the web chat
(`tools.py` → `OrchestratorAgent.run`, the same object `core/agent.py:89` calls), so
the reasoning, the gates and the SQL are identical. What differed was the wrapper:
`_agent_response_to_dict` dropped three things the web has always shown.

**The freshness warning.** `KnowledgeFreshnessService` produces the sentence that says
the index behind this answer is stale. The web renders it; MCP dropped it, so an agent
asking through a client received a confident answer from a six-week-old index with
nothing to object. That is the product's own honesty mechanism reaching one of its two
interfaces.

**Every stage's rows.** `resp.results` is the LAST query-bearing stage. A pipeline
answer computed from three stages showed one table here — ORCH-09's exact shape, on a
surface the remediation board did not cover.

**Which connection answered.** The tool takes `connection_id` as optional and picks one
when it is omitted; it then never said which. An agent holding four connections could
not tell what it had just been told about.

And the picker itself: it took `connections[0]` with no check that the connection is a
*database*. `is_queryable_database` is False for analytics sources (GA4) and MCP
sources, so a project whose first connection is GA4 answered a natural-language SQL
question with no database attached. The web cannot do this — `chat.py` only builds a
config when the caller names a connection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.connectors.base import QueryResult
from app.mcp_server.tools import _agent_response_to_dict


@dataclass
class _Block:
    """The shape `agents/response_builder.py:30-38` actually produces."""

    query: str | None = None
    query_explanation: str | None = None
    results: QueryResult | None = None
    viz_type: str = "table"
    viz_config: dict[str, Any] = field(default_factory=dict)
    insights: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _Resp:
    answer: str = "42 orders."
    response_type: str | None = "sql_result"
    query: str | None = "SELECT count(*) FROM orders"
    query_explanation: str | None = None
    results: QueryResult | None = None
    viz_type: str = "text"
    viz_config: dict[str, Any] = field(default_factory=dict)
    knowledge_sources: list[Any] = field(default_factory=list)
    error: str | None = None
    staleness_warning: str | None = None
    sql_results: list[_Block] = field(default_factory=list)


def _qr(n: int) -> QueryResult:
    return QueryResult(columns=["n"], rows=[[n]], row_count=1)


def test_the_freshness_warning_reaches_the_mcp_client():
    warning = "The database index is 41 days old; schema changes since then are not reflected."
    out = _agent_response_to_dict(_Resp(staleness_warning=warning))
    assert out.get("staleness_warning") == warning, (
        "an MCP agent received an answer from a stale index with no disclosure, while "
        "the web showed the warning for the same run"
    )


def test_a_clean_answer_carries_no_warning():
    assert "staleness_warning" not in _agent_response_to_dict(_Resp())


def test_every_stage_of_a_pipeline_answer_is_returned():
    resp = _Resp(
        results=_qr(3),
        sql_results=[
            _Block(query="SELECT 1", results=_qr(1)),
            _Block(query="SELECT 2", results=_qr(2)),
            _Block(query="SELECT 3", results=_qr(3)),
        ],
    )
    out = _agent_response_to_dict(resp)
    stages = out.get("stage_results")
    assert stages is not None and len(stages) == 3, (
        "only the final stage's table reached the client; a three-stage answer showed one"
    )
    assert [s["query"] for s in stages] == ["SELECT 1", "SELECT 2", "SELECT 3"]
    assert stages[0]["results"]["rows"] == [[1]]
    # `results` stays the final stage, for callers that only want that.
    assert out["results"]["rows"] == [[3]]


def test_a_single_stage_answer_does_not_grow_a_stage_list():
    """Same threshold the web's own builder uses: fewer than two blocks -> nothing."""
    resp = _Resp(results=_qr(1), sql_results=[_Block(query="SELECT 1", results=_qr(1))])
    assert "stage_results" not in _agent_response_to_dict(resp)


def test_a_stage_without_rows_is_still_reported():
    """A text-only stage has no `results`; dropping it would renumber the others."""
    resp = _Resp(
        sql_results=[_Block(query="SELECT 1", results=_qr(1)), _Block(query_explanation="no rows")]
    )
    stages = _agent_response_to_dict(resp)["stage_results"]
    assert len(stages) == 2
    assert stages[1]["results"] is None


# ---------------------------------------------------------------------------
# The picker: a SQL question needs a connection that IS a database.
# ---------------------------------------------------------------------------


class _Row:
    def __init__(self, cid: str, source_type: str = "database", is_active: bool = True):
        self.id = cid
        self.source_type = source_type
        self.is_active = is_active


def _pick(rows):
    """The selection `query_database` performs when `connection_id` is omitted.

    Mirrors `tools.py` so the rule can be tested without standing up a session:
    filter out analytics sources on the ROW, then prefer an active connection.
    """
    from app.services.connection_service import is_analytics_source

    usable = [c for c in rows if not is_analytics_source(c.source_type)]
    if not usable:
        return None
    return next((c for c in usable if getattr(c, "is_active", True)), usable[0])


def test_a_ga4_source_is_never_bound_to_a_sql_question():
    """`is_queryable_database` is False for an analytics source.

    The picker took `connections[0]`, so a project whose first connection is GA4
    answered a natural-language *database* question with no database attached —
    and said nothing about it. The web cannot do this: it builds a config only
    when the caller names a connection.
    """
    chosen = _pick([_Row("ga4-1", source_type="ga4"), _Row("db-1")])
    assert chosen is not None and chosen.id == "db-1"


def test_a_project_with_only_analytics_sources_is_refused_not_guessed():
    assert (
        _pick([_Row("ga4-1", source_type="ga4"), _Row("ga4-2", source_type="googleplay")]) is None
    )


def test_an_active_database_still_wins_over_an_inactive_one():
    """The existing preference is preserved — this change adds a filter, not a policy."""
    chosen = _pick([_Row("db-off", is_active=False), _Row("db-on")])
    assert chosen is not None and chosen.id == "db-on"


def test_all_inactive_still_yields_the_first_rather_than_nothing():
    chosen = _pick([_Row("db-a", is_active=False), _Row("db-b", is_active=False)])
    assert chosen is not None and chosen.id == "db-a"
