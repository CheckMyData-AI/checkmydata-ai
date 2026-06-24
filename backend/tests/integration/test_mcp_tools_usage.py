"""Usage-accounting + concurrency tests for MCP agent tools (R2 / C5).

Confirms that ``query_database`` and ``search_codebase`` now:

* build the inner :class:`LLMRouter` with a :class:`DbUsageSink` bound to the
  authenticated principal, so every nested LLM call records a ``TokenUsage``
  row (F-MCP-01);
* acquire and release the shared :data:`agent_limiter` slot around the
  orchestrator run, mirroring the chat route (F-MCP-02);
* surface the limiter's deny reason as a ``ToolError`` without leaking a slot.

These are integration-shaped (real tool function exercising the full guard
prologue) but the orchestrator + DB session are mocked at the service layer to
keep the test hermetic and fast.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from app.llm.router import LLMRouter
from app.llm.usage_sink import DbUsageSink
from app.mcp_server import tools

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _fake_agent_response() -> MagicMock:
    return MagicMock(
        answer="ok",
        response_type="text",
        query=None,
        query_explanation=None,
        results=None,
        viz_type="text",
        knowledge_sources=None,
        error=None,
    )


def _query_database_patches(make_orch_target: MagicMock):
    """Common patch stack for the happy/limited paths of ``query_database``."""
    project = MagicMock(id="p1", name="Proj")
    mock_conn = MagicMock(id="c1", project_id="p1")
    mock_config = MagicMock()
    return [
        patch.object(tools._project_svc, "get", new=AsyncMock(return_value=project)),
        patch.object(tools, "_require_project_access", new=AsyncMock(return_value=None)),
        patch.object(
            tools._connection_svc,
            "list_by_project",
            new=AsyncMock(return_value=[mock_conn]),
        ),
        patch.object(tools._connection_svc, "to_config", new=AsyncMock(return_value=mock_config)),
        patch.object(tools._usage_svc, "check_token_budget", new=AsyncMock(return_value=None)),
        patch.object(tools, "_make_orchestrator", new=make_orch_target),
        patch.object(tools._singleton_tracker, "begin", new=AsyncMock(return_value="wf-1")),
        patch.object(tools, "_get_trace_svc", return_value=None),
    ]


def _search_codebase_patches(make_orch_target: MagicMock):
    """Common patch stack for the happy/limited paths of ``search_codebase``."""
    project = MagicMock(id="p1", name="Proj")
    return [
        patch.object(tools._project_svc, "get", new=AsyncMock(return_value=project)),
        patch.object(tools, "_require_project_access", new=AsyncMock(return_value=None)),
        patch.object(tools._usage_svc, "check_token_budget", new=AsyncMock(return_value=None)),
        patch.object(tools, "_make_orchestrator", new=make_orch_target),
        patch.object(tools._singleton_tracker, "begin", new=AsyncMock(return_value="wf-1")),
        patch.object(tools, "_get_trace_svc", return_value=None),
    ]


@contextmanager
def _stacked(patches):
    """Apply a list of ``patch`` context managers as a single block.

    Using a generator-based contextmanager guarantees that every entered patch
    is torn down even if a later one raises, which the manual ``ExitStack``
    pattern would only achieve if the caller re-entered it via ``with``.
    """
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield


# --------------------------------------------------------------------------- #
# query_database
# --------------------------------------------------------------------------- #


async def test_query_database_acquires_and_releases_limiter():
    principal = {"user_id": "user-q-ok", "email": ""}
    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(return_value=_fake_agent_response())
    make_orch = MagicMock(return_value=mock_orch)

    with (
        _stacked(_query_database_patches(make_orch)),
        patch.object(tools.agent_limiter, "acquire", new=AsyncMock(return_value=None)) as acq,
        patch.object(tools.agent_limiter, "release", new=AsyncMock(return_value=None)) as rel,
    ):
        out = await tools.query_database(principal, "p1", "how many users?")

    assert isinstance(out, dict)
    acq.assert_awaited_once_with("user-q-ok")
    rel.assert_awaited_once_with("user-q-ok")
    mock_orch.run.assert_awaited_once()


async def test_query_database_limiter_denied_raises_tool_error():
    principal = {"user_id": "user-q-denied", "email": ""}
    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(return_value=_fake_agent_response())
    make_orch = MagicMock(return_value=mock_orch)

    deny_msg = "Too many concurrent requests"

    with (
        _stacked(_query_database_patches(make_orch)),
        patch.object(tools.agent_limiter, "acquire", new=AsyncMock(return_value=deny_msg)) as acq,
        patch.object(tools.agent_limiter, "release", new=AsyncMock(return_value=None)) as rel,
    ):
        with pytest.raises(ToolError, match="Too many concurrent"):
            await tools.query_database(principal, "p1", "how many users?")

    acq.assert_awaited_once_with("user-q-denied")
    # Denied acquire means nothing to release.
    rel.assert_not_called()
    mock_orch.run.assert_not_called()


async def test_query_database_builds_router_with_db_usage_sink():
    principal = {"user_id": "user-q-sink", "email": ""}
    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(return_value=_fake_agent_response())

    captured: dict[str, LLMRouter | None] = {"router": None}

    def _capture_make_orch(router: LLMRouter | None = None) -> MagicMock:
        captured["router"] = router
        return mock_orch

    make_orch = MagicMock(side_effect=_capture_make_orch)

    with (
        _stacked(_query_database_patches(make_orch)),
        patch.object(tools.agent_limiter, "acquire", new=AsyncMock(return_value=None)),
        patch.object(tools.agent_limiter, "release", new=AsyncMock(return_value=None)),
    ):
        await tools.query_database(principal, "p1", "how many users?")

    router = captured["router"]
    assert router is not None, "tool must pass its router into _make_orchestrator"
    assert isinstance(router, LLMRouter)
    sink = router._sink
    assert isinstance(sink, DbUsageSink), f"expected DbUsageSink, got {type(sink).__name__}"
    assert sink._user_id == "user-q-sink"
    assert sink._project_id == "p1"


# --------------------------------------------------------------------------- #
# search_codebase
# --------------------------------------------------------------------------- #


async def test_search_codebase_acquires_and_releases_limiter():
    principal = {"user_id": "user-s-ok", "email": ""}
    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(return_value=_fake_agent_response())
    make_orch = MagicMock(return_value=mock_orch)

    with (
        _stacked(_search_codebase_patches(make_orch)),
        patch.object(tools.agent_limiter, "acquire", new=AsyncMock(return_value=None)) as acq,
        patch.object(tools.agent_limiter, "release", new=AsyncMock(return_value=None)) as rel,
    ):
        out = await tools.search_codebase(principal, "p1", "where is auth?")

    assert isinstance(out, dict)
    acq.assert_awaited_once_with("user-s-ok")
    rel.assert_awaited_once_with("user-s-ok")
    mock_orch.run.assert_awaited_once()


async def test_search_codebase_limiter_denied_raises_tool_error():
    principal = {"user_id": "user-s-denied", "email": ""}
    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(return_value=_fake_agent_response())
    make_orch = MagicMock(return_value=mock_orch)

    deny_msg = "Hourly cap reached"

    with (
        _stacked(_search_codebase_patches(make_orch)),
        patch.object(tools.agent_limiter, "acquire", new=AsyncMock(return_value=deny_msg)) as acq,
        patch.object(tools.agent_limiter, "release", new=AsyncMock(return_value=None)) as rel,
    ):
        with pytest.raises(ToolError, match="Hourly cap"):
            await tools.search_codebase(principal, "p1", "where is auth?")

    acq.assert_awaited_once_with("user-s-denied")
    rel.assert_not_called()
    mock_orch.run.assert_not_called()


async def test_search_codebase_builds_router_with_db_usage_sink():
    principal = {"user_id": "user-s-sink", "email": ""}
    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(return_value=_fake_agent_response())

    captured: dict[str, LLMRouter | None] = {"router": None}

    def _capture_make_orch(router: LLMRouter | None = None) -> MagicMock:
        captured["router"] = router
        return mock_orch

    make_orch = MagicMock(side_effect=_capture_make_orch)

    with (
        _stacked(_search_codebase_patches(make_orch)),
        patch.object(tools.agent_limiter, "acquire", new=AsyncMock(return_value=None)),
        patch.object(tools.agent_limiter, "release", new=AsyncMock(return_value=None)),
    ):
        await tools.search_codebase(principal, "p1", "where is auth?")

    router = captured["router"]
    assert router is not None, "tool must pass its router into _make_orchestrator"
    assert isinstance(router, LLMRouter)
    sink = router._sink
    assert isinstance(sink, DbUsageSink), f"expected DbUsageSink, got {type(sink).__name__}"
    assert sink._user_id == "user-s-sink"
    assert sink._project_id == "p1"
