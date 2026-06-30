"""SQLAgent → query-failure diagnostics capture wiring (spec §3.4 / plan T6).

Drives the real ``SQLAgent._handle_execute_query`` with the heavy deps stubbed
and ``app.agents.sql_agent.ValidationLoop`` patched so ``.execute`` returns a
crafted :class:`ValidationLoopResult`. Asserts that the recorder
(``maybe_record_query_failure``) is invoked with the loop's attempts + success
flag right after ``_extract_learnings``. The recorder itself decides to no-op
(disabled / clean success) — SQLAgent always calls it unconditionally, so we
assert the call happens for both a failed and a clean-success loop result.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import AgentContext
from app.agents.sql_agent import SQLAgent
from app.connectors.base import ConnectionConfig, QueryResult, SchemaInfo
from app.core.query_validation import (
    QueryAttempt,
    QueryError,
    QueryErrorType,
    ValidationLoopResult,
)
from app.core.workflow_tracker import WorkflowTracker

# ---------------------------------------------------------------------------
# Fixtures (mirror tests/unit/test_sql_agent.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_tracker():
    t = MagicMock(spec=WorkflowTracker)
    t.begin = AsyncMock(return_value="wf-1")
    t.end = AsyncMock()
    t.emit = AsyncMock()

    @asynccontextmanager
    async def fake_step(wf_id, step, detail="", **kwargs):
        yield

    t.step = MagicMock(side_effect=fake_step)
    return t


@pytest.fixture
def mock_llm():
    router = MagicMock()
    router.complete = AsyncMock()
    return router


@pytest.fixture
def mock_vector_store():
    vs = MagicMock()
    vs.query = MagicMock(return_value=[])
    return vs


@pytest.fixture
def mock_custom_rules():
    cr = MagicMock()
    cr.load_rules = MagicMock(return_value=[])
    cr.load_db_rules = AsyncMock(return_value=[])
    cr.rules_to_context = MagicMock(return_value="")
    return cr


@pytest.fixture
def config():
    return ConnectionConfig(
        db_type="postgres",
        db_host="localhost",
        db_port=5432,
        db_name="testdb",
        db_user="user",
        connection_id="conn-1",
    )


@pytest.fixture
def agent(mock_llm, mock_vector_store, mock_custom_rules):
    return SQLAgent(
        llm_router=mock_llm,
        vector_store=mock_vector_store,
        rules_engine=mock_custom_rules,
    )


@pytest.fixture
def context(config, mock_llm, mock_tracker):
    return AgentContext(
        project_id="proj-1",
        connection_config=config,
        user_question="Show me all users",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-1",
    )


def _stub_heavy_deps(agent):
    """Patch every heavy helper ``_handle_execute_query`` calls before/around
    the validation loop so the real method runs without touching a DB."""
    agent._get_or_create_connector = AsyncMock(return_value=MagicMock())
    agent._get_cached_schema = AsyncMock(
        return_value=SchemaInfo(db_type="postgres", db_name="testdb")
    )
    agent._load_db_index_hints = AsyncMock(return_value="")
    agent._load_sync_for_repair = AsyncMock(return_value=("", ""))
    agent._load_rules_for_repair = AsyncMock(return_value="")
    agent._load_distinct_values = AsyncMock(return_value={})
    agent._load_learnings_for_repair = AsyncMock(return_value="")
    agent._load_required_filters_by_table = AsyncMock(return_value={})
    agent._extract_learnings = AsyncMock()


def _failed_loop_result() -> ValidationLoopResult:
    err = QueryError(
        error_type=QueryErrorType.SYNTAX_ERROR,
        message="syntax error near GROUP",
        raw_error='ERROR: syntax error at or near "GROUP"',
    )
    attempts = [
        QueryAttempt(
            attempt_number=1,
            query="SELECT id GROUP BY 1",
            explanation="first try",
            error=err,
            elapsed_ms=12.0,
        ),
    ]
    return ValidationLoopResult(
        success=False,
        query="SELECT id GROUP BY 1",
        explanation="first try",
        results=None,
        attempts=attempts,
        total_attempts=1,
        final_error=err,
    )


def _success_loop_result() -> ValidationLoopResult:
    qr = QueryResult(columns=["id"], rows=[[1]], row_count=1)
    attempts = [
        QueryAttempt(
            attempt_number=1,
            query="SELECT id FROM users",
            explanation="ok",
            error=None,
            results=qr,
            elapsed_ms=5.0,
        ),
    ]
    return ValidationLoopResult(
        success=True,
        query="SELECT id FROM users",
        explanation="ok",
        results=qr,
        attempts=attempts,
        total_attempts=1,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_loop_invokes_recorder(agent, context):
    """A failed validation loop → recorder awaited once with loop_success=False
    and the loop's exact attempts list."""
    _stub_heavy_deps(agent)
    loop_result = _failed_loop_result()

    with (
        patch("app.agents.sql_agent.ValidationLoop") as mock_vl,
        patch(
            "app.agents.sql_agent.maybe_record_query_failure",
            new_callable=AsyncMock,
        ) as mock_record,
    ):
        mock_vl.return_value.execute = AsyncMock(return_value=loop_result)

        out = await agent._handle_execute_query(
            {"query": "SELECT id GROUP BY 1", "explanation": "first try"},
            context,
            "wf-1",
            run_state={},
        )

    # Failure path returns the failure message (not a formatted result table).
    assert "Query failed" in out

    mock_record.assert_awaited_once()
    kwargs = mock_record.call_args.kwargs
    assert kwargs["loop_success"] is False
    assert kwargs["attempts"] is loop_result.attempts
    assert kwargs["context"] is context
    assert kwargs["question"] == context.user_question


@pytest.mark.asyncio
async def test_clean_success_still_invokes_recorder(agent, context):
    """A clean-success loop still calls the recorder — the helper (not SQLAgent)
    owns the no-op decision. Asserts loop_success=True and the same attempts."""
    _stub_heavy_deps(agent)
    loop_result = _success_loop_result()

    with (
        patch("app.agents.sql_agent.ValidationLoop") as mock_vl,
        patch(
            "app.agents.sql_agent.maybe_record_query_failure",
            new_callable=AsyncMock,
        ) as mock_record,
    ):
        mock_vl.return_value.execute = AsyncMock(return_value=loop_result)

        await agent._handle_execute_query(
            {"query": "SELECT id FROM users", "explanation": "ok"},
            context,
            "wf-1",
            run_state={},
        )

    mock_record.assert_awaited_once()
    kwargs = mock_record.call_args.kwargs
    assert kwargs["loop_success"] is True
    assert kwargs["attempts"] is loop_result.attempts


@pytest.mark.asyncio
async def test_recorder_called_after_extract_learnings(agent, context):
    """Ordering contract: capture fires AFTER _extract_learnings so a captured
    failure reflects the same attempts the learning extractor saw."""
    _stub_heavy_deps(agent)
    loop_result = _failed_loop_result()
    order: list[str] = []

    agent._extract_learnings = AsyncMock(side_effect=lambda *a, **k: order.append("extract"))

    async def _record(*a, **k):
        order.append("record")

    with (
        patch("app.agents.sql_agent.ValidationLoop") as mock_vl,
        patch(
            "app.agents.sql_agent.maybe_record_query_failure",
            new=AsyncMock(side_effect=_record),
        ),
    ):
        mock_vl.return_value.execute = AsyncMock(return_value=loop_result)

        await agent._handle_execute_query(
            {"query": "SELECT id GROUP BY 1", "explanation": "first try"},
            context,
            "wf-1",
            run_state={},
        )

    assert order == ["extract", "record"]
